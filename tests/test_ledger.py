import concurrent.futures
import json
import os
import re
import threading
import sqlite3
import tempfile
import unittest
from pathlib import Path

from decision_ledger.core import Ledger, LedgerError
from decision_ledger.plugin import Service


class Fixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = Ledger(self.path)
        self.service = Service(self.ledger)

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, scope="Research deployment options only", topic="deployment", conditions=None):
        return self.ledger.draft("demo", topic, scope, conditions)

    def command(self, action, item, extra=""):
        # Existing state-machine tests now execute the real v0.3.1 CLI
        # two-step sequence. Separate tests assert a preview NEVER mutates.
        session = "operator-test-" + str(threading.get_ident())
        output = self.service.command(f"{action} {item['token']}" + (" " + extra if extra else ""),
                                      platform="cli", session_id=session)
        m = re.search(r"^/decisions confirm (\S+)$", output, re.M)
        if not m:
            return output
        return self.service.command("confirm " + m.group(1), platform="cli", session_id=session)

    def approve(self, item):
        self.command("approve", item)
        return self.ledger.get(item["id"])


class LedgerTests(Fixture, unittest.TestCase):
    def test_later_suggestion_cannot_expand_approved_scope(self):
        research = self.approve(self.draft())
        implementation = self.draft("Implement and deploy to production")
        self.assertEqual("approved", self.ledger.get(research["id"])["status"])
        self.assertEqual("proposed", implementation["status"])
        self.assertIn("Research deployment options only", self.service.command("list demo"))

    def test_conditions_survive_and_model_cannot_resolve_them(self):
        item = self.approve(self.draft(conditions=["All tests pass", "User reviews the diff"]))
        self.assertEqual("conditional", item["status"])
        result = json.loads(self.service.tool({"action": "satisfy", "id": item["id"]}))
        self.assertFalse(result["ok"])
        self.assertEqual("conditional", self.ledger.get(item["id"])["status"])
        self.command("satisfy", item, "I checked all tests and reviewed the diff")
        ready = self.ledger.get(item["id"])
        self.assertEqual("approved", ready["status"])
        self.assertEqual(item["conditions"], ready["conditions"])
        self.assertEqual("local_operator", ready["events"][-1]["data"]["actor"])

    def test_condition_requires_attestation_note(self):
        item = self.approve(self.draft(conditions=["tests pass"]))
        self.assertIn("requires", self.command("satisfy", item))
        self.assertEqual("conditional", self.ledger.get(item["id"])["status"])

    def test_unknown_yes_does_not_approve(self):
        item = self.draft()
        self.assertIn("/decisions approve", self.service.command("yes", platform="cli", session_id="s"))
        self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_model_status_escalation_rejected(self):
        for action in ("approve", "revoke", "satisfy", "supersede"):
            self.assertFalse(json.loads(self.service.tool({"action": action}))["ok"])
        self.assertFalse(json.loads(self.service.tool({"action": "draft", "project": "demo", "topic": "x",
                         "scope": "x", "status": "approved"}))["ok"])
        self.assertEqual(0, self.ledger.list()["total"])

    def test_gateway_desktop_and_unknown_mutations_refused(self):
        item = self.draft()
        for platform, source, sid in [("telegram", {"sender_id": "owner"}, "s"), ("desktop", None, "s"),
                                       ("", None, "s"), ("cli", {}, "s"), ("cli", None, "")]:
            result = self.service.command("approve " + item["token"], platform=platform, source=source, session_id=sid)
            self.assertIn("require the local", result)
            self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_revoke_preserves_history_and_replay_cannot_reapprove(self):
        item = self.approve(self.draft())
        self.command("revoke", item)
        self.assertIn("cannot approve", self.command("approve", item))
        current = self.ledger.get(item["id"])
        self.assertEqual("revoked", current["status"])
        self.assertEqual(["approve", "revoke"], [e["action"] for e in current["events"]])

    def test_identical_command_replay_is_idempotent(self):
        item = self.draft()
        self.command("approve", item)
        self.command("approve", item)
        self.assertEqual(1, len(self.ledger.get(item["id"])["events"]))

    def test_stale_token_refused(self):
        item = self.draft()
        self.assertIn("incorrect", self.service.command("approve " + item["id"] + ":0000000000000000",
                     platform="cli", session_id="s"))
        self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_duplicate_draft_dedup_and_edit_is_new_immutable_proposal(self):
        item = self.draft()
        self.assertEqual(item["token"], self.draft()["token"])
        edited = self.draft("A different scope")
        self.assertNotEqual(item["token"], edited["token"])
        self.command("approve", item)
        self.assertEqual("proposed", self.ledger.get(edited["id"])["status"])

    def test_replacement_must_be_explicit_and_atomic(self):
        old = self.approve(self.draft())
        new = self.draft("Research and implement locally, no publication")
        self.assertIn("approved decision exists", self.command("approve", new))
        self.assertEqual("proposed", self.ledger.get(new["id"])["status"])
        self.command("approve", new, "replace " + old["token"])
        self.assertEqual("superseded", self.ledger.get(old["id"])["status"])
        self.assertEqual("approved", self.ledger.get(new["id"])["status"])

    def test_cross_project_or_wrong_replacement_refused(self):
        old = self.approve(self.draft())
        other = self.draft(topic="other")
        self.assertIn("replacement must", self.command("approve", other, "replace " + old["token"]))
        self.assertEqual("approved", self.ledger.get(old["id"])["status"])
        self.assertEqual("proposed", self.ledger.get(other["id"])["status"])

    def test_concurrent_approval_conflict(self):
        items = [self.draft("option " + str(i)) for i in range(5)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            list(ex.map(lambda x: self.command("approve", x), items))
        statuses = [self.ledger.get(i["id"])["status"] for i in items]
        self.assertEqual(1, statuses.count("approved"))
        self.assertEqual(4, statuses.count("proposed"))

    def test_rejected_decision_never_reapproved_by_replay(self):
        item = self.draft()
        self.command("reject", item)
        self.assertIn("cannot approve", self.command("approve", item))
        self.assertEqual("rejected", self.ledger.get(item["id"])["status"])

    def test_empty_history_means_unknown_not_denied(self):
        result = json.loads(self.service.tool({"action": "list", "project": "missing"}))
        self.assertEqual([], result["decisions"])
        self.assertIn("completeness unknown", result["coverage"])

    def test_pagination_reports_partial_results(self):
        for i in range(4):
            self.draft(topic="t" + str(i))
        result = self.ledger.list(limit=2)
        self.assertEqual(4, result["total"])
        self.assertEqual(2, result["next_offset"])
        self.assertEqual(2, len(self.ledger.list(offset=2, limit=2)["decisions"]))

    def test_semantic_overlap_not_silently_resolved(self):
        self.approve(self.draft(topic="deploy"))
        self.approve(self.draft(topic="deployment"))
        result = self.ledger.list("demo")
        self.assertEqual(2, len(result["decisions"]))
        self.assertIn("semantic overlap", result["scope_matching"])

    def test_persistence_after_restart(self):
        item = self.approve(self.draft())
        self.assertEqual("approved", Ledger(self.path).get(item["id"])["status"])

    def test_legitimate_reauthorization_gets_new_receipt(self):
        for terminal in ("revoke", "reject"):
            old = self.draft(topic=terminal)
            if terminal == "revoke":
                self.approve(old)
            self.command(terminal, old)
            fresh = self.draft(topic=terminal)
            self.assertNotEqual(old["id"], fresh["id"])
            self.assertEqual("proposed", fresh["status"])
            self.assertEqual("approved", self.approve(fresh)["status"])
            self.assertEqual("revoked" if terminal == "revoke" else "rejected", self.ledger.get(old["id"])["status"])

    def test_return_to_previously_superseded_exact_scope(self):
        old = self.approve(self.draft())
        alternative = self.draft("Use an alternative")
        self.command("approve", alternative, "replace " + old["token"])
        fresh = self.draft()
        self.assertNotEqual(old["id"], fresh["id"])
        self.command("approve", fresh, "replace " + alternative["token"])
        self.assertEqual("approved", self.ledger.get(fresh["id"])["status"])
        self.assertEqual("superseded", self.ledger.get(old["id"])["status"])

    def test_conditional_replacement_retires_old_immediately(self):
        old = self.approve(self.draft())
        new = self.draft("Deploy only when conditions met", conditions=["tests pass"])
        self.assertIn("retires OLD immediately", self.service.view(new)["card"])
        self.command("approve", new, "replace " + old["token"])
        self.assertEqual("superseded", self.ledger.get(old["id"])["status"])
        self.assertEqual("conditional", self.ledger.get(new["id"])["status"])

    def test_integrity_change_rejected(self):
        item = self.draft()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE proposals SET payload=? WHERE id=?", ('{}', item["id"]))
        with self.assertRaisesRegex(LedgerError, "integrity"):
            self.ledger.get(item["id"])

    def test_private_file_permissions(self):
        if os.name == "posix":
            self.assertEqual(0o600, self.path.stat().st_mode & 0o777)

    def test_invalid_inputs(self):
        for project in (None, "", "bad project", "../other", "démø"):
            with self.assertRaises(LedgerError):
                self.ledger.draft(project, "topic", "scope")
        with self.assertRaises(LedgerError):
            self.ledger.draft("demo", "topic", "scope", "tests pass")


class SourceTests(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.messages = [
            {"id": 1, "role": "assistant", "content": "May I research options?", "timestamp": 1},
            {"id": 2, "role": "user", "content": "Yes, research only. Implementation needs approval.", "timestamp": 2},
            {"id": 3, "role": "assistant", "content": "I suggest deploying everything now.", "timestamp": 3},
        ]
        self.service = Service(self.ledger, self.dispatch)

    def dispatch(self, name, args):
        self.assertEqual("session_search", name)
        return json.dumps({"mode": "scroll", "session_id": "past-session", "messages": self.messages})

    def sourced_draft(self):
        return json.loads(self.service.tool({"action": "draft", "project": "demo", "topic": "deployment",
                            "scope": "Research only", "source_session": "past-session", "source_message": 2}))["decision"]

    def test_native_snapshot_is_context_not_inferred_approval(self):
        item = self.sourced_draft()
        self.assertEqual("proposed", item["status"])
        self.assertEqual("unchanged", item["source_check"])
        self.assertEqual(3, len(item["evidence"]["messages"]))
        self.assertEqual("assistant", item["evidence"]["messages"][0]["role"])

    def test_quote_relay_question_conditional_remain_unconfirmed(self):
        for body in ["Yes", "Alice approved deploying the site.", "Should we deploy?",
                     "I approve deployment only if the tests pass.", 'The assistant said "user approved deployment".']:
            self.messages[1]["content"] = body
            item = self.sourced_draft()
            self.assertEqual("proposed", item["status"])
            self.assertEqual("not established", item["approval_basis"])

    def test_changed_missing_source_warns(self):
        item = self.sourced_draft()
        self.messages[1]["content"] = "different"
        changed = self.service.view(self.ledger.get(item["id"]))
        self.assertEqual("changed_or_missing", changed["source_check"])
        self.assertIn("cannot currently be verified", changed["warning"])

    def test_more_context_is_not_source_tampering(self):
        item = self.sourced_draft()
        self.messages.append({"id": 4, "role": "assistant", "content": "A new suggestion", "timestamp": 4})
        self.assertEqual("unchanged", self.service.view(self.ledger.get(item["id"]))["source_check"])

    def test_missing_or_failed_native_reader_never_invents_evidence(self):
        self.service.dispatch = lambda *_: json.dumps({"success": False, "error": "not found"})
        result = json.loads(self.service.tool({"action": "draft", "project": "demo", "topic": "x", "scope": "x",
                                 "source_session": "past-session", "source_message": 2}))
        self.assertFalse(result["ok"])
        self.assertEqual(0, self.ledger.list()["total"])

    def test_source_read_unavailable_warns_after_receipt(self):
        item = self.sourced_draft()
        self.approve(item)
        self.service.dispatch = lambda *_: json.dumps({"error": "source gone"})
        view = self.service.view(self.ledger.get(item["id"]))
        self.assertEqual("unavailable", view["source_check"])
        self.assertIn("cannot currently be verified", view["warning"])

    def test_cross_profile_read_refused(self):
        with self.assertRaises(LedgerError):
            self.service.source("other/profile", 2)

    def test_source_size_is_bounded_in_bytes_not_characters(self):
        self.messages[1]["content"] = "界" * 22000
        with self.assertRaisesRegex(LedgerError, "64 KB"):
            self.service.source("past-session", 2)


class ReviewTests(Fixture, unittest.TestCase):
    def review(self, item, platform="cli"):
        return self.service.command("review " + item["id"], platform=platform, session_id="operator")

    def test_native_review_binds_exact_scope_and_condition(self):
        item = self.draft(conditions=["tests pass"])
        shown = []
        def pick(question, choices):
            shown.append((question, choices))
            return "approve"
        self.service.ask_choice = pick
        out = self.review(item)
        self.assertIn("[CONDITIONAL]", out)
        self.assertIn(item["scope"], shown[0][0])
        self.assertIn("tests pass", shown[0][0])
        self.assertEqual("leave", shown[0][1][0]["value"])
        current = self.ledger.get(item["id"])
        self.assertIn("-> confirmed ", current["events"][0]["data"]["command"])

    def test_cancel_timeout_unknown_and_keep_have_no_effect(self):
        for value in (None, "leave", "yes", "", "another-id"):
            item = self.draft(topic="leave" + str(len(str(value))))
            self.service.ask_choice = lambda *_: value
            self.assertIn("This review made no change", self.review(item))
            self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_native_rejection_is_retained(self):
        item = self.draft()
        self.service.ask_choice = lambda *_: "reject"
        self.assertIn("[REJECTED]", self.review(item))

    def test_cancel_reports_fresh_state_after_another_session_changes_it(self):
        for revoked in (False, True):
            item = self.draft(topic="race" + str(revoked).lower())
            def race(*_):
                self.approve(item)
                if revoked:
                    self.command("revoke", item)
                return None
            self.service.ask_choice = race
            out = self.review(item)
            self.assertIn("This review made no change", out)
            self.assertIn("[REVOKED]" if revoked else "[APPROVED]", out)
            self.assertNotIn("remains proposed", out)

    def test_missing_choice_panel_leaves_draft(self):
        item = self.draft()
        self.assertIn("No native choice panel", self.review(item))
        self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_gateway_never_opens_confirmation(self):
        item = self.draft()
        def should_not_run(*_):
            self.fail("gateway opened the choice panel")
        self.service.ask_choice = should_not_run
        self.assertIn("require the local", self.review(item, platform="telegram"))
        self.assertEqual("proposed", self.ledger.get(item["id"])["status"])

    def test_review_rejects_stale_explicit_token(self):
        item = self.draft()
        out = self.service.command("review " + item["id"] + ":wrong", platform="cli", session_id="operator")
        self.assertIn("incorrect decision token", out)

    def test_conflict_during_review_cannot_overwrite_other_approval(self):
        item = self.draft()
        competing = self.draft("Another exact scope")
        def race(*_):
            self.approve(competing)
            return "approve"
        self.service.ask_choice = race
        self.assertIn("ledger changed after preview", self.review(item))
        self.assertEqual("proposed", self.ledger.get(item["id"])["status"])
        self.assertEqual("approved", self.ledger.get(competing["id"])["status"])

    def test_known_conflict_does_not_prompt_again(self):
        self.approve(self.draft())
        item = self.draft("Another exact scope")
        self.service.ask_choice = lambda *_: self.fail("unnecessary confirmation")
        self.assertIn("an approved decision exists", self.review(item))

    def test_model_review_action_refused(self):
        item = self.draft()
        self.service.ask_choice = lambda *_: self.fail("model opened operator panel")
        self.assertFalse(json.loads(self.service.tool({"action": "review", "id": item["id"]}))["ok"])

    def test_review_cannot_revive_old_receipt(self):
        item = self.approve(self.draft())
        self.command("revoke", item)
        self.service.ask_choice = lambda *_: self.fail("revoked proposal offered approval")
        self.assertIn("review only confirms proposed", self.review(item))


if __name__ == "__main__":
    unittest.main()
