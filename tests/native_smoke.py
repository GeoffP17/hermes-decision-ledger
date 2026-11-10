"""Offline integration using REAL Hermes discovery, registry, commands and session DB.

Run in a dependency-equipped interpreter:
  python tests/native_smoke.py /path/to/hermes-agent
Creates and deletes its own HERMES_HOME. Never uses the production profile.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    plugin = Path(__file__).resolve().parents[1]
    demo = "--demo" in sys.argv[2:]
    sys.path.insert(0, str(root))
    with tempfile.TemporaryDirectory(prefix="decision-ledger-native-") as directory:
        home = Path(directory)
        os.environ["HERMES_HOME"] = str(home)
        os.environ["HERMES_DISABLE_TELEMETRY"] = "1"
        shutil.copytree(plugin, home / "plugins" / "decision-ledger",
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "artifacts"))
        (home / "config.yaml").write_text("plugins:\n  enabled:\n    - decision-ledger\n", encoding="utf-8")
        from hermes_cli.plugins import PluginManager, PluginContext
        from hermes_cli.plugin_command_dispatch import invoke_plugin_command
        choice_available = callable(getattr(PluginContext, "ask_choice", None))
        if choice_available:
            from hermes_cli.plugin_choices import bind_asker, clarify_asker
        from tools.registry import registry
        from hermes_state import SessionDB
        from tools import session_search_tool  # noqa: F401 — registers native tool

        db = SessionDB(home / "state.db")
        sid = "ledger-history-fixture"
        db.create_session(sid, source="cli")
        db.append_message(sid, "assistant", "May I research the deployment choices?")
        anchor = db.append_message(sid, "user", "Yes, research only. Implementation requires another approval.")
        db.append_message(sid, "assistant", "I suggest implementing and publishing now.")
        db.close()

        manager = PluginManager()
        manager.discover_and_load()
        state = manager._plugins.get("decision-ledger")
        assert state and state.enabled, {"decision_ledger": state.error if state else "not discovered"}
        entry = registry.get_entry("decision_ledger", scope=manager.scope_key)
        assert entry, "native tool not registered"
        handler = manager._plugin_commands["decisions"]["handler"]

        def operator(command, session="operator"):
            """Native Hermes slash dispatcher; first preview, then actual CLI confirm."""
            preview = invoke_plugin_command(handler, command, source=None,
                         session_id=session, session_key=session, platform="cli")
            match = re.search(r"^/decisions confirm (\S+)$", preview, re.M)
            assert match, "expected preview challenge: " + preview
            # No approval should exist before this second local-operator step.
            return invoke_plugin_command(handler, "confirm " + match.group(1), source=None,
                         session_id=session, session_key=session, platform="cli")

        def tool(**args):
            raw = registry.dispatch("decision_ledger", args, scope=manager.scope_key)
            result = json.loads(raw)
            assert result["ok"], result
            return result

        research = tool(action="draft", project="demo", topic="deployment", scope="Research deployment options only",
                        source_session=sid, source_message=anchor)["decision"]
        assert research["source_check"] == "unchanged", research
        assert research["status"] == "proposed"
        if demo:
            print("DECISION LEDGER — synthetic conversation; scripted operator commands; no live model\n")
            print("1. Retrieved conversation stays an unconfirmed interpretation\n" + research["card"] + "\n")
        # Native PluginContext.ask_choice + native clarify binding; the response
        # is scripted operator input, not a real person or a model response.
        shown = []
        def panel(questions):
            shown.extend(questions)
            q = questions[0]
            return {"answers": {q["qid"]: "Confirm this exact scope"}, "outcome": "submitted"}
        if choice_available:
          with bind_asker(clarify_asker(panel)):
            response = invoke_plugin_command(handler, "review " + research["id"], source=None,
                                              session_id="operator", session_key="operator", platform="cli")
        else:
            response = operator("approve " + research["token"])
        assert "[APPROVED]" in response, response
        if choice_available:
            assert research["scope"] in shown[0]["question"]
            assert "Keep proposed" == shown[0]["choices"][0]
        if demo:
            print("2. Operator confirms the exact research scope\n" + response + "\n")
        implementation = tool(action="draft", project="demo", topic="deployment", scope="Implement and publish")
        assert implementation["decision"]["status"] == "proposed"
        recalled = tool(action="show", id=research["id"])["decision"]
        assert recalled["status"] == "approved"
        assert len(recalled["evidence"]["messages"]) == 3
        assert recalled["events"][0]["data"]["command"].startswith("/decisions review " if choice_available else "/decisions approve ")
        if demo:
            print("3. Later implementation proposal cannot expand approval\n" + implementation["decision"]["card"])
            print("Existing receipt: " + recalled["status"] + " — " + recalled["scope"] + "\n")
        denied = invoke_plugin_command(handler, "approve " + implementation["decision"]["token"], source=None,
                                         session_id="desktop", session_key="desktop", platform="desktop")
        assert "require the local" in denied, denied
        raw = json.loads(registry.dispatch("decision_ledger", {"action": "approve", "id": research["id"]},
                                          scope=manager.scope_key))
        assert not raw["ok"]
        conditional = tool(action="draft", project="demo", topic="release", scope="Release staging build",
                           conditions=["All tests pass and operator reviews the diff"])["decision"]
        out = operator("approve " + conditional["token"])
        assert "[CONDITIONAL]" in out
        attempt = json.loads(registry.dispatch("decision_ledger", {"action": "satisfy", "id": conditional["id"]},
                                              scope=manager.scope_key))
        assert not attempt["ok"]
        if demo:
            print("4. An assistant cannot satisfy a condition\n" + out + "\n")
        revoked = operator("revoke " + research["token"], session="operator-next-session")
        assert "[REVOKED]" in revoked
        after = tool(action="show", id=research["id"])["decision"]
        assert [e["action"] for e in after["events"]] == ["approve", "revoke"]
        if demo:
            print("5. Revocation changes current status, preserving the original receipt\n" + revoked + "\n")
        print(json.dumps({"native_smoke": "passed", "hermes_commit": (subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
            capture_output=True, check=False).stdout.strip()
            if (root / ".git").exists() else "unavailable-in-packaged-image"),
            "choice_panel_available": choice_available,
            "confirmation_path": "native choice binding" if choice_available else "persisted preview then separate CLI confirm",
            "checks": ["real discovery and manifest", "real registry dispatch", "real SessionDB source window",
                       "real slash dispatcher",
                       "research remains approved after later implementation proposal",
                       "desktop mutation refused", "model approval refused", "conditions preserved",
                       "model cannot satisfy conditions", "revocation retains approval history"],
            "model_calls": 0, "network_calls_by_plugin": 0}, indent=2))


if __name__ == "__main__":
    main()
