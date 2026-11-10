## Approval guidance fix — November 9, 2026

Human approval on HP uses the separate bundled foreground `operator_console.py`.
At its prompt enter ONE line `approve ID:DIGEST`, inspect the exact uncommitted
preview, then personally type `confirm REVIEW_CODE` in that same session if desired.
Gateway `/decisions approve` and `/decisions confirm` are refused by the source
identity guard. Model tools draft/read only. Never ask an agent to launch the
operator or enter confirmation. `/decisions list` and `/decisions show` remain
readback commands. No source guard relaxation is part of this fix.

Model prompt/tool descriptions, receipt cards, generic preview and refusal/help text now explain the working approval surface. Latest candidate paste fix and malformed-input PTY regression preserved.

## 0.3.1 catalog packaging candidate — November 9, 2026

- Bundled standalone `operator_console.py` for real local foreground terminal
  approval after the gateway CLI transport proved incompatible with the narrow
  v0.3.1 source guard. No widening of gateway approval identity checks.
- Corrected README, manifest and release evidence: no longer claim working
  `/decisions approve` in a real Hermes 0.22.4 gateway-backed CLI.
- The new console dynamically locates installed plugin/profile data and checks
  current user ownership, foreground TTY and exact installed source hashes;
  same-UID code access remains outside the security boundary.
- Isolated packaged-console real-PTY test, 60 previous unit tests: PASS;
  real HP human confirmation and final catalog CI remain unverified.

# Changes

## 0.3.1 candidate — November 9, 2026

- V1: every untrusted scope, condition and source preview line is explicitly
  prefixed as data; Unicode Cc/Cf formatting characters are escaped on display.
  Stored decision text is unchanged.
- V2: CLI `approve/reject/revoke/satisfy` only creates a full authoritative
  preview; a separate `/decisions confirm REVIEW_CODE` bound to the original
  CLI session, action, receipt, replacement, rendered source warning and event
  revision commits atomically. Codes expire after 15 minutes; cancel is safe.
- Native `/decisions review` continues to use the optional supported choice API,
  built on the same preview/confirmation path. Hermes 0.22.4 does not need it.
- Model drafts above the review limit fail BEFORE persistence; legacy oversized
  drafts fail closed instead of forcing a blind exact-token approval.
- Added isolated V1/V2 regressions. The original 43 suite tests were adapted to
  the explicit two-step operator workflow, not deleted.
- Original v0.3.1 native validation passed in an offline disposable Hermes 0.22.4
  image. The metadata-portable runner and this cleaned package still need their
  final native check. No production replacement or public submission occurred.
- Release preparation removes bytecode caches and historical binary/demo artifacts;
  runtime source is unchanged. See VALIDATION.md for evidence provenance and limits.

## 0.3.0 — November 9, 2026

- Native choice review is optional. Ordinary exact-token confirmation works on the
  official 0.22.4 release without a Hermes upgrade.
- Tested loader, registry, source retrieval and confirmation lifecycle on both 0.22.4
  and the recorded newer source baseline. Old commands without session context still
  cannot approve. The v0.2 hard choice-API gate is superseded.
- Decision cards advertise choice review only when available.

## 0.2.0 — November 9, 2026

- Added `/decisions review ID` using Hermes's public native choice panel, so users can
  inspect exact scope/conditions and choose without copying the long digest token.
- Cancellation, timeout, unknown choice and unavailable panel leave state unchanged.
  Conflicts are checked before opening a panel and again transactionally after its answer.
- Cancelled review reports a fresh recorded status, including an approval or revocation
  made concurrently in another session; it does not falsely claim the draft is still proposed.
- Corrected compatibility: actual v0.22.2 lacks command session context and is unsupported.
  The old unverified `>=0.22.2` manifest claim was removed; a public feature gate now rejects
  the tested old release before creating ledger data. Supported baseline is the recorded
  Nov 9 source commit. No internal Hermes runtime API import is needed in plugin code.
- Fixed the source-window limit to count UTF-8 bytes, rather than characters.
- Clarified that receipts are optional recordkeeping and never an extra permission gate.

v0.1 remains a preserved historical package; these corrections supersede its compatibility
instructions. Database schema is unchanged. No production deployment or publication.
