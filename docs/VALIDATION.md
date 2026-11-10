# Decision Ledger v0.3.1 — verified-source UX candidate

Source ZIP verified: 50,609 bytes; SHA256 3e887949d68e93be8d384f662e43ccf192eb00973e8d91e43794de0647990e5f. This supersedes the older-byte recovery candidate. Latest README, operator paste handling, author attribution and malformed-input regression retained.

Completed: model prompt/tool description, proposed cards, generic preview wording, gateway refusal and help point HP users to separate operator_console.py. Source identity guard condition and ledger core unchanged. Expected plugin hash synchronized. Two guidance/refusal tests added; PTY prompt matching waits for trailing prompt rather than embedded help text.

Validation: 63 tests passed from the prior final extracted ZIP; runtime source and tests are unchanged in this documentation-only finalization. Source manifest regenerated. Official Hermes upstream 396fe52bccfb1b60907ed8716cfd12f4d0d95bee full CLI `python -m hermes_cli.main plugins validate PATH --install-deps --json` ran in the officially prepared, workspace-isolated runtime: exit 0, all 15 checks PASS, no warnings or dependency/import errors. This resolves the earlier dependency-preparation blocker. Security scan safe; capability probe and declarations match; no core override; host-ready isolation. No live install or data/config changes. Revalidate final public pinned commit in catalog CI after publication approval.

Live operator approval, fresh CLI recall, WebUI readback and natural-use/conflict refusal are carried-forward user-observed evidence in Master Brief; not rerun. Corrected source is NOT installed on HP. No new portability claim.

Remaining gates: revalidate the final public pinned commit in catalog CI after publication approval; optional separately authorized HP source upgrade; owner-authorized public repo/catalog PR, real under-90-second X video tagging @NousResearch and form submission. No public actions performed. Deadline November 11, 2026 2 PM PST; internal target 12:30 PM.

Official admission source: https://hermes-agent.nousresearch.com/docs/developer-guide/plugins/catalog-submission
