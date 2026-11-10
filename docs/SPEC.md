## Updated release integration boundary — Nov 9, 2026

Live Hermes 0.22.4 routes local CLI plugin slash commands through gateway `slash.exec`
using non-null LOCAL sources. The plugin's existing authenticated-CLI parameter guard
therefore refuses `/decisions approve`, and direct-dispatch native tests were too
narrow. We will NOT broaden that guard to all LOCAL origins. The supported mutation
surface for competition is the separate foreground-only `operator_console.py` bundled
with the plugin. It calls existing verified `_prepare` and `_confirm` methods, refuses
sourced proposals without verifiable native history, and requires a two-step terminal
preview/confirm. 60 existing unit tests and isolated PTY test passed; a live HP
operator confirmation remains a release gate. Previous CLI-mutating claims in this
archived spec are superseded by this note and the current README.

# v0.3.1 candidate specification and acceptance contract

This document specifies plugin behavior. It does not authorize installation,
deployment, publication, spending or account access.

User job: identify what is actually confirmed for a project without silently treating an
assistant suggestion, quotation or conditional response as unconditional approval.

The durable unit is one immutable exact scope, conditions and optional native-source
snapshot. Each has a random ID and content digest; confirmation binds both. Updating
scope means creating a new unit. Rejected/revoked/superseded scopes can be proposed again
with a new ID; an old command remains terminal.

Model tool: `draft`, `list`, `show`. No status-setting parameter or mutation action.
Local user command: approve, reject, revoke, satisfy, explicit replacement.
Quick local review uses the public native choice panel when supported.
On Hermes 0.22.4 and other CLI surfaces without an optional choice API,
`approve TOKEN` previews exact source/scope/conditions/replacement/warnings and
issues a 15-minute random challenge; ONLY a separate `confirm CODE` in the same
CLI session commits after event-revision and preview-digest revalidation.
The first command is never an approval. Oversized drafts cannot be blind-approved.
`cancel CODE` never changes a receipt. Repeated preview invalidates prior code. The model cannot invoke that
review action through the dedicated tool. Keep/cancel/timeout mean no mutation; confirmation
binds the exact displayed token and rechecks conflicts transactionally.
Storage: one profile-local SQLite DB. No cloud, hook interception, external memory
replacement, model inference call, parser that infers approval from “yes”, or recurring task.

| Input / event | Required outcome |
|---|---|
| User confirms research; assistant later suggests implementation | Research receipt unchanged; implementation proposed |
| Historical “yes”, relayed approval, quoted stale decision | Source candidate only; no automatic approval |
| Conditional decision confirmed | Conditional with exact conditions |
| Assistant says conditions passed | No state change |
| Local operator satisfies with evidence note | Approved, preserving conditions and attestation history |
| Explicit local revocation | Revoked now, old approval retained in history |
| Stale/wrong digest | Refuse without write |
| Replayed command | No duplicate event; old approval cannot undo revocation |
| Conflicting same-topic approval | Refuse unless exact current token explicitly replaced |
| Conditional replacement | Old retires immediately, new remains conditional; disclosed on card |
| Concurrent conflicting approvals | Exactly one approved; others proposed |
| Missing/changed source | Visible verification warning; no invented original |
| Unknown/gateway/Desktop context | Reads only; mutation refused |
| Native quick review cancelled, timed out or unavailable | No mutation; strict two-step local CLI preview/confirm alternative remains |
| Competitor approval arrives while review panel is open | Requested new approval refuses; existing receipt preserved |
| Empty or partially paged ledger | Coverage/continuation disclosed, not global absence of approval |
| Cross-key semantic overlap | Not automatically resolved; disclose exact-key matching |

Quality criteria: ordinary exact approvals must work, while the dangerous cases above
must not silently approve. Zero false approvals on synthetic cases is necessary but not
evidence of general natural-language accuracy. A conservative ledger can pass by requiring
new explicit receipts; that is a product tradeoff, not a discovery that historical recall is solved.

Independent review found and reproduced a reauthorization defect; implementation and
regressions fixed it. Review also narrowed identity claims to local CLI and required explicit
conditional-replacement semantics. See validation for the tested boundary.

Bookkeeping is not permission: routine work already authorized by the user does not need
another ledger confirmation. The ledger never makes missing receipt evidence into a denial.
