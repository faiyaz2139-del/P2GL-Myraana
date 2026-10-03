# Acceptance report — Print2Go Production Studio

Tested 2 October 2026. This report distinguishes verified backend behavior from unverified browser/hardware behavior. Test accounts, files, connector responses and physical confirmations were confined to an isolated Miniflare D1/R2 instance; no physical printing occurred and no test data was added to the published database.

## Acceptance criteria

| # | Result | Evidence and scope |
|---|---|---|
| 1 | PASS — API; UI interaction unverified | Order created with validated customer, quantity, stock, sides, finish and due date. A Start a job form is implemented; no chat is required. |
| 2 | PASS | A 23,221-byte real production PDF was generated, stored, reopened and validated. SHA-256: `889f9b1469f2d61a3d6944e1eb61b383bd8a2f0b5cd19ab3b8bc94ddf84a8137`. Poppler confirmed two pages; both were rendered and visually inspected. |
| 3 | PASS | Trim-only artwork stopped at Needs attention, with no PRINT_READY output until an explicit blank-border decision. |
| 4 | PASS | Incorrect dimensions and detectable unsafe text stopped Check artwork with Blocked and revised-upload recovery. |
| 5 | PASS | A 60×30-pixel image placed at 1.667×0.556 inches measured 36 DPI and generated a measured warning. Supported checks have clearly stated limits. |
| 6 | FAIL — browser verification pending | The authenticated endpoint serves the actual two-page generated PDF; the PDF.js canvas viewer is implemented. The generated front/back pages were independently rendered and inspected. In-browser display was not tested because browser-control capability was unavailable. |
| 7 | PASS | Approval stores exact file ID, checksum, job generation, approver and time. Repeated approval preserves the original evidence. |
| 8 | PASS | Replacing artwork incremented the generation, preserved originals and revoked downstream verification, approval and authorization. Production-setting changes reset the route and revoked authorization. |
| 9 | PASS — persisted API state | Fresh requests preserved job/task state, file lineage and generations in D1/R2. Job URL selection is restored on refresh. Full browser refresh interaction is unverified. |
| 10 | PASS — tested failure paths | Missing Claude credentials returned an honest 503. Corrupt PDF became Failed with recovery guidance. A live Anthropic streaming failure needs credentialed verification. |
| 11 | PASS — blocking behavior | With no heartbeat, readiness became Blocked and authorization could not proceed. A live shop connection is still unverified. |
| 12 | PASS | Concurrent processing requests started one execution and produced one PRINT_READY file. Repeated processing and approvals retained existing evidence. |
| 13 | PASS — server gate | Print confirmation before readiness/authorization was rejected. Authorization is an explicit human API action tied to the approved checksum and job generation. No Claude tool can grant it. |
| 14 | PASS — confirmation/state gates | Print, cut, QC and pack required operator confirmation. QC rejection revoked authorization and required rework. A connector handoff did not mark Print completed. Physical hardware results were not tested. |
| 15 | FAIL — browser verification pending | Responsive light/dark layouts and desktop/tablet/mobile breakpoints are implemented. Clipping, touch interaction, keyboard behavior, browser errors and visual quality require browser QA. |
| 16 | PASS — source and response checks | Settings responses expose only configuration flags, never the Anthropic or connector secrets. Credential access is server-only; session cookies are HttpOnly, SameSite=Strict and Secure on HTTPS. Source/client-bundle review found no real credentials. |

Fourteen criteria have verified backend evidence within the stated scope; two have not passed browser verification. This is not a claim that all end-to-end acceptance criteria passed.

## Additional checks

- Anonymous access to job APIs was denied.
- Operator accounts could not modify administrator settings.
- Pause prevented further actions; resume restored active work.
- Expired execution lease became recoverable Failed; retry generated a verified PDF from saved state.
- A valid isolated connector heartbeat enabled readiness; authorized PDF bytes matched the recorded checksum.
- Connector acknowledgment created a PRODUCTION_OUTPUT lineage record and did not claim printing.
- Production-setting changes revoked unprinted authorization, while preserving approval of the unchanged proof file.
- TypeScript checking and the production build passed.

Machine-readable assertions are in `tests/results/acceptance.json`. Test-only generated PDF and rendered pages are in `tests/results/`.

## Exact remaining setup and checks

1. Create your administrator account on first opening. No live account or password was pre-seeded.
2. Set the server secret `ANTHROPIC_API_KEY`; optionally set `CLAUDE_MODEL`. Verify an actual Claude message, streamed update, successful allowed tool call, API error and recovery. The current key-present flag is not proof of connection.
3. Enter the shop's actual printer and supported stocks in Shop settings. RIP/imposition remains operator-assisted; there is no verified Fiery submission integration.
4. Configure the server `CONNECTOR_SECRET`, install Python 3.10+ on the shop computer, and set `PRINT2GO_URL`, `PRINT2GO_FOLDER` and the matching local secret. Resolve owner-private-site machine access through an appropriate deployment access policy or supported private tunnel. Verify a real heartbeat, destination writability and checksum acknowledgment.
5. Run a real desktop and phone review of the job form, actual front/back proof, approval flow, light/dark theme and essential actions. Browser-control skill was unavailable; no screenshot or browser-console pass is claimed.
6. Perform a supervised test on the configured print equipment. Printing, cutting, QC and packing remain human-confirmed; no physical production was triggered during development.

## Limitations

Four-MB, at-most-two-page PDF upload limit. Preflight is measured but not certified PDF/X. Nested forms, unusual text operators, angled text, images in complex transforms, transparency, logos and colour fidelity need expert/visual review. No missing artwork is invented. No font substitution or colour conversion policy is applied. Automated preparation sets page boxes and optionally adds an explicitly approved blank border. Background worker termination requires explicit safe retry after lease recovery; no guaranteed external queue is provided in this release. Flyer, sticker and banner adapters are extension points rather than implemented products.

## Backend AI update — 2 October 2026

Claude and ChatGPT models are now server-side providers for one Print2Go Assistant. There is no operator model selector or model/provider name in the interface. Model settings are omitted from the settings API. Both adapters use the same persisted job and constrained production tools. The backend defaults to Claude primary/OpenAI backup, configurable only through server environment values.

PASS — provider protocol fixture tests verified routing, OpenAI strict-tool payloads, Anthropic/OpenAI SSE parsing, tool-result call identity, initial-request fallback, refusal to fallback after partial output, hidden-reasoning suppression and truncated-stream errors. These fixtures verify protocol handling; they are not claims of successful live provider calls.

PASS — production build, TypeScript checks and the isolated production acceptance suite still pass. No new schema migration or live data cleanup was required.

NOT VERIFIED — real Anthropic and OpenAI credentials have not been supplied. Both live API connections and account/model access require setup and real requests. The original browser/hardware limitations still apply.
