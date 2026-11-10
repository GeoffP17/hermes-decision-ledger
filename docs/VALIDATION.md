# v0.3.2 validation — November 10, 2026

- 67 isolated unit/regression tests pass, including console PTY checks and read-only reader lifecycle/pagination/tamper checks.
- Official prepared-runtime `hermes plugins validate PATH --install-deps --json`: all 15 checks pass, zero warnings, host_ready=true. Validator source: 396fe52bccfb1b60907ed8716cfd12f4d0d95bee.
- Independent API import and temporary-database checks pass: missing storage not created, POST refused, invalid pagination rejected, existing scope matches, database bytes unchanged.
- Official `hermes dashboard` was built and launched on loopback in an isolated test profile with the installed plugin. The real Decision Ledger tab loaded successfully. No host code was patched.
- Created one explicitly labeled TEST RECORD ONLY proposal through the real model-tool Service API, without making a model call. The board read its exact scope/token/status. It stayed proposed and was absent from the Confirmed filter.
- Search, no-match filtering, Refresh and proposal-review guidance inspected in the real dashboard. A 390px view rendered legibly without horizontal overflow. Browser viewport restored afterward.
- An unauthenticated HTTP receipt request returned 401. Dashboard viewing/search/filtering left SQLite database SHA256 unchanged.

These are local author-run checks, not independent maintainer validation. No user approval was created. No live HP install, profile SQLite/config, paid provider or model setting was changed. Native Hermes Desktop uses a different frontend SDK and is not claimed compatible. Full human approval/fresh-chat conflict demonstration has not been re-recorded for v0.3.2.
