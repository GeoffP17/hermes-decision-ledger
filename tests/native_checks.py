"""Official validator + doctor in a disposable profile; no model calls."""
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root))
    # Older official validators launch a fresh capability-probe interpreter;
    # an uninstalled source checkout needs its import root passed explicitly.
    os.environ["PYTHONPATH"] = str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")
    plugin = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ledger-official-checks-") as directory:
        os.environ["HERMES_HOME"] = directory
        os.environ["HERMES_DISABLE_TELEMETRY"] = "1"
        from hermes_cli.plugin_validate import validate_plugin_dir
        from hermes_cli.plugin_dev import doctor_plugin
        validation = validate_plugin_dir(plugin)
        doctor = doctor_plugin(str(plugin))
        result = {"validation": validation.to_dict(), "doctor": {
            "ok": doctor.ok, "text": doctor.format_text(),
            "tools": doctor.registered_tools, "hooks": doctor.registered_hooks}}
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if validation.ok and doctor.ok else 1)


if __name__ == "__main__":
    main()
