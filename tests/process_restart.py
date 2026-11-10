"""Real Hermes plugin in separate Python processes; synthetic, disposable data only."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def worker(root, mode, pid=None):
    sys.path.insert(0, root)
    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugin_command_dispatch import invoke_plugin_command
    from hermes_state import SessionDB
    from tools import session_search_tool  # noqa: F401
    from tools.registry import registry
    if mode == "seed":
        db = SessionDB(Path(os.environ["HERMES_HOME"]) / "state.db")
        db.create_session("prior", source="cli")
        db.append_message("prior", "assistant", "Research only?")
        anchor = db.append_message("prior", "user", "Research only. Do not implement.")
        db.close()
    manager = PluginManager()
    manager.discover_and_load()
    state = manager._plugins["decision-ledger"]
    assert state.enabled, state.error
    def call(args):
        result = json.loads(registry.dispatch("decision_ledger", args, scope=manager.scope_key))
        assert result["ok"], result
        return result["decision"]
    if mode == "seed":
        item = call(dict(action="draft", project="restart", topic="scope", scope="Research only; no implementation",
                         source_session="prior", source_message=anchor))
        output = invoke_plugin_command(manager._plugin_commands["decisions"]["handler"],
                     "approve " + item["token"], source=None, platform="cli", session_id="operator-one")
        match = re.search(r"^/decisions confirm (\S+)$", output, re.M)
        assert match, output
        # Crucially, seed worker exits with no mutation. A NEW process confirms.
        assert call(dict(action="show", id=item["id"]))["status"] == "proposed"
        print("RESULT:" + json.dumps({"id": item["id"], "challenge": match.group(1)}))
        return
    if mode == "confirm":
        output = invoke_plugin_command(manager._plugin_commands["decisions"]["handler"],
                  "confirm " + pid, source=None, platform="cli", session_id="operator-one")
        assert "[APPROVED]" in output, output
    else:
        item = call(dict(action="show", id=pid))
        print("RESULT:" + json.dumps(item))
        return
    # A later third process reads the confirmed record separately.
    print("RESULT:" + json.dumps({"confirmed": True}))


def main():
    if sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
        return
    root = str(Path(sys.argv[1]).resolve())
    plugin = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ledger-process-test-") as directory:
        home = Path(directory)
        shutil.copytree(plugin, home / "plugins" / "decision-ledger",
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "artifacts"))
        (home / "config.yaml").write_text("plugins:\n  enabled:\n    - decision-ledger\n")
        env = {**os.environ, "HERMES_HOME": str(home)}
        def run(mode, pid=None):
            cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", root, mode]
            if pid:
                cmd.append(pid)
            r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
            assert r.returncode == 0, r.stderr + r.stdout
            return json.loads(next(l[7:] for l in r.stdout.splitlines() if l.startswith("RESULT:")))
        initial = run("seed")
        assert run("confirm", initial["challenge"])["confirmed"]
        first = run("read", initial["id"])
        second = run("read", initial["id"])
        assert first["status"] == second["status"] == "approved"
        assert first["events"] == second["events"]
        assert second["source_check"] == "unchanged"
        (home / "state.db").rename(home / "removed-source.db")
        third = run("read", first["id"])
        assert third["status"] == "approved"  # receipt survives; missing source is disclosed
        assert third["events"] == first["events"]
        assert third["source_check"] == "unavailable", third
        assert "cannot currently be verified" in third["warning"]
        assert not (home / "state.db").exists(), "reader must not manufacture missing history"
        print(json.dumps({"process_restart": "passed", "distinct_processes": 5,
              "receipt_and_history_preserved": True, "missing_source_warned": True,
              "missing_history_not_recreated": True, "model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
