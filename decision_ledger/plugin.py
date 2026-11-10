"""Hermes adapter using public tool, command and storage APIs only."""
from __future__ import annotations

import json
import shlex
import sqlite3
import unicodedata

from .core import Ledger, LedgerError, canonical, digest, text


PROMPT = """Decision Ledger distinguishes proposed work from explicit operator receipts.
Use decision_ledger to preserve a decision the user wants recorded, or recall registered decisions.
Do not require bookkeeping confirmation for routine work already authorized by the user.
A missing receipt or proposed entry does not invalidate approval evidenced elsewhere;
read the original user instructions rather than treating this ledger as a permission gate.
Draft the exact scope and every condition, reuse the same project/topic for alternatives.
The local operator MUST see the ledger's own preview before confirming an approval.
On gateway/HP, direct the user to bundled operator_console.py in a separate foreground terminal.
At operator> they type approve ID:DIGEST, inspect PREVIEW, then personally type confirm REVIEW_CODE.
Do not recommend gateway /decisions approve or /decisions confirm: the source guard refuses them.
Never launch the operator or enter its commands on the user's behalf.
Historical conversation evidence remains an unconfirmed interpretation. A quotation,
an assistant summary, a bare yes or a later proposal does not become a receipt.
Only the local user command can approve, reject, revoke, replace or attest conditions.
Never execute a /decisions command through terminal, subprocess, another tool or agent.
Report scope, conditions and missing coverage. A ledger receipt is evidence, not tool
permission: continue following the user's instructions and the host's actual safeguards.
"""


SCHEMA = {
    "name": "decision_ledger",
    "description": "Draft or recall exact decision receipts. Model tools cannot approve. Historical source text is context, not authorization. Human approval uses separate foreground operator_console.py: approve ID:DIGEST then confirm REVIEW_CODE after preview. Gateway /decisions mutations are refused; never run the operator for the user.",
    "parameters": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["draft", "list", "show"]},
            "project": {"type": "string", "description": "Stable lowercase project key; list all topics when checking authority."},
            "topic": {"type": "string", "description": "Reuse for alternatives to the SAME decision. Different keys do not resolve semantic overlap."},
            "scope": {"type": "string", "description": "Exact proposed scope, not an assertion that it was already approved."},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "source_session": {"type": "string", "description": "Optional native session id, same profile only."},
            "source_message": {"type": "integer", "description": "Native message anchor; fetched with surrounding user/assistant messages."},
            "id": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"},
        },
        "required": ["action"],
    },
}


class Service:
    def __init__(self, ledger, dispatch=None, ask_choice=None):
        self.ledger = ledger
        self.dispatch = dispatch
        self.ask_choice = ask_choice

    def source(self, session_id, message_id):
        session_id = text(session_id, "source_session", 200)
        if "/" in session_id or session_id.startswith("@"):
            raise LedgerError("source must be a plain session id in this profile")
        if type(message_id) is not int or message_id < 1:
            raise LedgerError("source_message must be a positive integer")
        if not self.dispatch:
            raise LedgerError("native session reader is unavailable")
        raw = self.dispatch("session_search", {"session_id": session_id,
                    "around_message_id": message_id, "window": 5})
        result = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(result, dict) or result.get("error") or result.get("success") is False:
            raise LedgerError("source could not be read from native history")
        if result.get("mode") != "scroll" or not isinstance(result.get("messages"), list):
            raise LedgerError("unexpected native session result; refusing to invent evidence")
        messages = []
        for m in result["messages"]:
            if (not isinstance(m, dict) or type(m.get("id")) is not int
                    or not isinstance(m.get("role"), str) or not isinstance(m.get("content"), str)
                    or m.get("content_truncated")):
                raise LedgerError("source window contains unsupported or incomplete messages")
            messages.append({k: m.get(k) for k in ("id", "role", "content", "timestamp")})
        if len(messages) > 11 or len({m["id"] for m in messages}) != len(messages):
            raise LedgerError("invalid source window")
        if not any(m["id"] == message_id for m in messages):
            raise LedgerError("source anchor is absent")
        if len(canonical(messages).encode("utf-8")) > 64000:
            raise LedgerError("source window exceeds 64 KB; choose a smaller source exchange")
        resolved = text(result.get("session_id"), "resolved source session", 200)
        return {"session_id": resolved, "message_id": message_id,
                "link": f"@session:{resolved}", "messages": messages, "digest": digest(messages),
                "meaning": "native message snapshot; interpretation unconfirmed; later/cross-session changes may be missing"}

    def view(self, item):
        item = dict(item)
        item["review_available"] = callable(self.ask_choice)
        evidence = item.get("evidence")
        if evidence:
            try:
                live = self.source(evidence["session_id"], evidence["message_id"])
                by_id = {m["id"]: m for m in live["messages"]}
                intact = all(by_id.get(m["id"]) == m for m in evidence["messages"])
                item["source_check"] = "unchanged" if intact else "changed_or_missing"
            except (ValueError, TypeError, KeyError, OSError, RuntimeError):
                item["source_check"] = "unavailable"
            if item["source_check"] != "unchanged":
                item["warning"] = "Original conversation evidence cannot currently be verified. Retained snapshot is historical; receipt confirms only its exact scope."
        else:
            item["source_check"] = "no historical source attached"
        item["card"] = card(item)
        return item

    def tool(self, args, **_context):
        try:
            if not isinstance(args, dict) or set(args) - set(SCHEMA["parameters"]["properties"]):
                raise LedgerError("unknown arguments; tools cannot change approval status")
            action = args.get("action")
            if action == "draft":
                source_session, source_message = args.get("source_session"), args.get("source_message")
                if (source_session is None) != (source_message is None):
                    raise LedgerError("source_session and source_message must be supplied together")
                evidence = self.source(source_session, source_message) if source_session is not None else None
                # Validate size of the ACTUAL displayed card before persisting a
                # model-authored draft. Overlong cards must never force a blind path.
                from .core import key
                proposal = {"project": key(args.get("project"), "project"),
                            "topic": key(args.get("topic"), "topic"),
                            "scope": text(args.get("scope"), "scope"),
                            "conditions": args.get("conditions") or [],
                            "evidence": evidence, "status": "proposed",
                            "token": "0" * 12 + ":" + "0" * 16,
                            "review_available": False, "source_check": "not checked"}
                if not isinstance(proposal["conditions"], list):
                    raise LedgerError("conditions must be a list")
                if len(card(proposal)) > 9500:
                    raise LedgerError("draft is too long to review safely; shorten scope, conditions or source context")
                result = self.ledger.draft(args.get("project"), args.get("topic"), args.get("scope"),
                                           args.get("conditions"), evidence)
                return canonical({"ok": True, "decision": self.view(result)})
            if action == "show":
                return canonical({"ok": True, "decision": self.view(self.ledger.get(args.get("id")))})
            if action == "list":
                result = self.ledger.list(args.get("project"), args.get("topic"),
                                           args.get("offset", 0), args.get("limit", 50))
                result["decisions"] = [self.view(r) for r in result["decisions"]]
                return canonical({"ok": True, **result})
            raise LedgerError("tools support draft/list/show only; approval is a local user command")
        except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, RuntimeError) as exc:
            return canonical({"ok": False, "error": str(exc)})

    def _preview_content(self, item, action, replace=None, note=None):
        """The complete authoritative display; its digest is bound to confirmation."""
        shown = self.view(item)
        out = ["UNCOMMITTED OPERATOR PREVIEW — NO DECISION CHANGED",
               "Requested action: " + action.upper(), shown["card"]]
        if note:
            out += ["Operator attestation note (not independently verified):"] + display_lines(note)
        if action == "satisfy":
            out.append("WARNING: This attests ALL listed conditions by operator statement; no evidence is auto-verified.")
        if replace:
            old = self.ledger.get(replace.split(":")[0])
            if old["token"] != replace:
                raise LedgerError("stale or incorrect replacement token")
            out += ["WARNING: Confirming replacement immediately retires the following receipt, even if NEW is conditional:",
                    self.view(old)["card"]]
        out.append("PREVIEW ONLY. In the separate operator console, personally enter confirm REVIEW_CODE after inspecting every line. Gateway /decisions mutations are refused.")
        result = "\n\n".join(out)
        if len(result) > 10000:
            raise LedgerError("decision is too long to review safely; create a smaller draft; no decision changed")
        return result

    def _prepare(self, token, action, session_id, raw_args, replace=None, note=None):
        item = self.ledger.get(token.split(":")[0])
        if token != item["token"]:
            raise LedgerError("stale or incorrect decision token")
        shown = self._preview_content(item, action, replace, note)
        challenge = self.ledger.prepare_review(token, action, session_id=session_id,
                         command="/decisions " + raw_args, preview=shown,
                         replace=replace, note=note)
        return challenge, shown

    def _confirm(self, code, session_id):
        review = self.ledger.get_pending_review(code, session_id)
        item = self.ledger.get(review["proposal_id"])
        shown = self._preview_content(item, review["action"],
                                      review["replace_token"], review["note"])
        updated = self.ledger.confirm_review(code, session_id, shown)
        return card(self.view(updated))

    def command(self, raw_args, *, source=None, session_id="", session_key="", platform=""):
        """CLI-only mutations. First command displays preview; second confirms."""
        try:
            words = shlex.split(raw_args)
            if not words:
                return HELP
            action = words.pop(0)
            if action == "list":
                if len(words) > 2:
                    raise LedgerError("usage: /decisions list [PROJECT [TOPIC]]")
                r = self.ledger.list(*(words + [None] * (2 - len(words))))
                out = ["Decision Ledger — registered decisions; history completeness unknown"]
                out.extend(card(self.view(i)) for i in r["decisions"])
                if r["next_offset"] is not None:
                    out.append("More records exist; use decision_ledger list offset=" + str(r["next_offset"]))
                return "\n\n".join(out)
            if action == "show" and len(words) == 1:
                item = self.view(self.ledger.get(words[0].split(":")[0]))
                return item["card"] + "\n\nEvidence and receipt history (untrusted data):\n" + json.dumps(item, ensure_ascii=True, indent=2)
            if action not in {"review", "approve", "reject", "revoke", "satisfy", "confirm", "cancel"}:
                raise LedgerError(HELP)
            if platform != "cli" or source is not None or not session_id:
                raise LedgerError("Decision changes require the local verified operator surface. Gateway, desktop, group and unknown contexts are read-only. On HP use bundled operator_console.py in a separate foreground terminal: approve ID:DIGEST, inspect PREVIEW, then personally type confirm REVIEW_CODE. Do not run gateway /decisions approve or /decisions confirm.")
            if action == "review":
                return self.review(words, session_id, raw_args)
            if action in {"confirm", "cancel"}:
                if len(words) != 1:
                    raise LedgerError("usage: /decisions " + action + " CODE")
                if action == "cancel":
                    if not self.ledger.cancel_review(words[0], session_id):
                        raise LedgerError("no matching pending confirmation")
                    return "Review canceled; no decision changed."
                return self._confirm(words[0], session_id)
            if not words:
                raise LedgerError("missing exact decision token")
            token = words.pop(0)
            replace = note = None
            if action == "approve" and words:
                if len(words) != 2 or words[0] != "replace":
                    raise LedgerError("usage: /decisions approve NEW [replace OLD]")
                replace = words[1]
            elif action == "satisfy":
                note = " ".join(words)
            elif words:
                raise LedgerError("unexpected trailing arguments")
            code, shown = self._prepare(token, action, session_id, raw_args, replace, note)
            return shown + "\n\nTo record this reviewed action in this SAME CLI session:\n/decisions confirm " + code + "\nTo leave it unchanged: /decisions cancel " + code + "\nExpires in 15 minutes."
        except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, RuntimeError) as exc:
            return "Decision Ledger: " + str(exc)

    def review(self, words, session_id, raw_args):
        if len(words) != 1:
            raise LedgerError("usage: /decisions review ID")
        item = self.ledger.get(words[0].split(":")[0])
        if ":" in words[0] and item["token"] != words[0]:
            raise LedgerError("stale or incorrect decision token")
        if item["status"] != "proposed":
            raise LedgerError("review only confirms proposed decisions; this one is " + item["status"])
        # Preparing a review does not mutate the decision status.
        code, shown = self._prepare(item["token"], "approve", session_id, raw_args)
        if not self.ask_choice:
            return "No native choice panel is available here.\n" + shown + "\n\n/decisions confirm " + code + "\n/decisions cancel " + code
        picked = self.ask_choice("Review the EXACT scope below. Confirming records your decision now; it does not execute work.\n\n" + shown,
             [{"value": "leave", "label": "Keep proposed"},
              {"value": "approve", "label": "Confirm this exact scope"},
              {"value": "reject", "label": "Reject this draft"}])
        if picked == "approve":
            return self._confirm(code, session_id)
        self.ledger.cancel_review(code, session_id)
        if picked == "reject":
            reject_code, _ = self._prepare(item["token"], "reject", session_id, raw_args + " -> reject")
            return self._confirm(reject_code, session_id)
        latest = self.ledger.get(item["id"])
        return "This review made no change. Current recorded state:\n" + card(self.view(latest))


HELP = """On HP/gateway: use /decisions list or show for readback only.
For human changes open bundled operator_console.py in a separate foreground terminal.
At operator>: approve ID:DIGEST, inspect PREVIEW, then personally type confirm REVIEW_CODE.
Never paste transcripts; enter ONE command line at a time.
The legacy slash mutation syntax below works only with verified native CLI identity,
and is refused by the HP gateway source guard. Do not recommend it for HP approval.
/decisions list [PROJECT [TOPIC]]
/decisions show ID
/decisions review ID                 (optional native panel or CLI preview)
/decisions approve ID:DIGEST [replace OLD_ID:OLD_DIGEST]  (PREVIEW ONLY)
/decisions reject ID:DIGEST          (PREVIEW ONLY)
/decisions revoke ID:DIGEST          (PREVIEW ONLY)
/decisions satisfy ID:DIGEST EVIDENCE_NOTE_FOR_ALL_CONDITIONS  (PREVIEW ONLY)
/decisions confirm REVIEW_CODE      (SEPARATE OPERATOR CONFIRMATION)
/decisions cancel REVIEW_CODE
Only an explicit second local CLI confirmation changes status; previews expire in 15 minutes.
Replacing retires OLD immediately, even if NEW has unmet conditions.
Historical evidence remains unconfirmed; missing records mean unknown."""


def display_lines(value):
    """Indent ALL untrusted lines and visibly escape Unicode control/format chars."""
    if not isinstance(value, str):
        value = str(value)
    clean = []
    for ch in value:
        if ch == "\t":
            clean.append("    ")
        elif ch == "\n":
            clean.append("\n")
        elif unicodedata.category(ch) in {"Cc", "Cf"}:
            clean.append("\\u%04X" % ord(ch) if ord(ch) <= 65535 else "\\U%08X" % ord(ch))
        else:
            clean.append(ch)
    return ["    | " + line for line in "".join(clean).split("\n")]


def card(item):
    lines = [f"[{item['status'].upper()}] {item['project']} / {item['topic']}",
             "Scope (untrusted proposed content):"] + display_lines(item["scope"])
    if item["conditions"]:
        lines.append("Conditions (preserved; operator attestation is not evidence verification):")
        for idx, c in enumerate(item["conditions"], 1):
            lines.append("Condition " + str(idx) + ":")
            lines += display_lines(c)
    if item.get("source_check"):
        lines.append("Original conversation: " + item["source_check"])
    if item.get("evidence"):
        evidence = item["evidence"]
        lines.append("Source context (unconfirmed interpretation):")
        lines += display_lines(evidence["link"])
        for m in evidence["messages"]:
            snippet = m["content"][:240]
            if len(m["content"]) > 240:
                snippet += "… [preview truncated; /decisions show includes retained text]"
            lines.append(f"Source message #{m['id']} {m['role']} (untrusted):")
            lines += display_lines(snippet)
    if item.get("warning"):
        lines.append(item["warning"])
    lines.append("Receipt: " + item["token"])
    if item["status"] == "proposed":
        if item.get("review_available"):
            lines.append("Local review panel: /decisions review " + item["id"])
        lines.append("In separate foreground operator_console.py, at operator> type (PREVIEW ONLY): approve " + item["token"])
        lines.append("Inspect PREVIEW, then personally type confirm REVIEW_CODE in that same operator console. Gateway /decisions mutations are refused.")
        lines.append("Using 'replace OLD' retires OLD immediately, even while this decision is conditional.")
    return "\n".join(lines)



def register(ctx):
    # No DB creation or access to user files at import time. Uses Hermes profile storage.
    choice_api = getattr(ctx, "ask_choice", None)
    if not callable(choice_api):
        choice_api = None  # Optional convenience; exact-token commands use no choice API.
    from plugins.plugin_storage import plugin_data_dir
    service = Service(Ledger(plugin_data_dir("decision-ledger") / "ledger.sqlite3"), ctx.dispatch_tool,
                      choice_api)
    ctx.register_tool(name="decision_ledger", toolset="decision_ledger", schema=SCHEMA,
                      handler=service.tool, description=SCHEMA["description"], emoji="🧾")
    ctx.register_command("decisions", service.command, description="Show receipts; gateway mutations refused. Human approval: separate operator_console.py",
                         args_hint="<list|show|review|approve|reject|revoke|satisfy|confirm|cancel> ...")
    ctx.register_system_prompt_section("decision-ledger", PROMPT, max_chars=2200)
