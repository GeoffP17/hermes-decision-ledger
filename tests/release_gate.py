"""Negative integration: legacy commands without context cannot record approval."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    plugin = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ledger-old-release-") as directory:
        home = Path(directory)
        os.environ["HERMES_HOME"] = str(home)
        shutil.copytree(plugin, home / "plugins" / "decision-ledger",
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "artifacts"))
        (home / "config.yaml").write_text("plugins:\n  enabled:\n    - decision-ledger\n")
        from hermes_cli.plugins import PluginManager
        manager = PluginManager()
        manager.discover_and_load()
        state = manager._plugins.get("decision-ledger")
        assert state, "plugin not discovered"
        if state.enabled:  # Unversioned source checkouts can bypass version ranges.
            from tools.registry import registry
            raw = registry.dispatch("decision_ledger", dict(action="draft", project="legacy", topic="test", scope="Research only"), scope=manager.scope_key)
            item = json.loads(raw)["decision"]
            out = manager._plugin_commands["decisions"]["handler"]("approve " + item["token"])
            assert "require the local" in out, out
            current = json.loads(registry.dispatch("decision_ledger", dict(action="show", id=item["id"]), scope=manager.scope_key))["decision"]
            assert current["status"] == "proposed" and current["events"] == []
        else:
            assert "requires" in state.error.lower(), state.error
        print(json.dumps({"release_gate": "passed", "unsupported_release": "v0.22.2",
                          "approval_without_context_refused": True}, indent=2))


if __name__ == "__main__":
    main()
