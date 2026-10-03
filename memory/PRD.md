# Print2Go Production Studio

## Purpose

Standalone Print2Go London production workspace. It must remain independent of
Myraana and never send a print command or claim physical production completed.

## Architecture

- React Studio frontend using `REACT_APP_BACKEND_URL`.
- FastAPI backend under `/api`.
- MongoDB job records and Mongo GridFS immutable PDF storage.
- Server-side bcrypt passwords and expiring HttpOnly sessions.
- PDF inspection uses PyMuPDF and pypdf.

## Implemented — 2026-10-03

- First-run owner-created administrator bootstrap, sign-in/sign-out, role checks,
  operator creation API, and no seeded production user.
- Versioned business-card recipes, shop settings, jobs, 16 protected workflow
  tasks, immutable PDF lineage, checksum re-read, proof PNG rendering, and
  approval/authorization identity records.
- Connector heartbeat, nonce replay rejection, writable-capability gate, exact
  authorized PDF download, and staged-file-only behavior. No physical print API.
- Adapted source Studio UI with Jobs, Recipes, and Shop settings plus responsive
  desktop/mobile entry screens and data test IDs.

## Verification

- PASS: isolated temporary Mongo database workflow with source valid PDF:
  ORIGINAL → WORKING_COPY → PRINT_READY, GridFS read-back, checksum, and reopened
  PDF verification. The temporary database was deleted after the run.
- PASS: backend health endpoint and first-run state on the preview URL.
- PASS: production frontend build plus desktop and mobile browser entry proof.
- PASS: 16-criterion isolated acceptance run. It covered browser job/proof flow,
  approval persistence, GridFS lineage/checksum, PDF proof rendering, artwork
  replacement invalidation, bleed/blocking/DPI behavior, duplicate requests,
  connector replay/readiness/handoff, and human production gates.
- PASS: independent regression test confirmed preview-proxy authentication returns
  200 while a deliberately unrelated origin returns 403. The QA database was
  dropped immediately after verification and the original backend environment was
  restored.
- PASS: sanitized source archive excludes `.env`, QA credentials, databases, and
  credential literals. QA report and desktop/mobile proof screenshots are in
  `/app/artifacts/`.
- NOT VERIFIED: live connector/hardware, direct Anthropic/OpenAI credentials, and
  live custom-domain routing.
- FAIL (honestly blocked): managed LLM tool-call probe returned a provider-side
  request-format error. The assistant remains unconfigured rather than claiming AI.

## Prioritized Backlog

### P0

- Owner completes first-run administrator setup in the new preview only.
- Configure and verify direct Anthropic/OpenAI credentials or resolve the managed
  provider tool-call failure before enabling assistant conversations.
- Configure `CONNECTOR_SECRET` outside source control and verify a shop computer
  connector against a non-printing staging folder.

### P1

- Perform owner-led physical proof, RIP, and production-gate validation.
- Connect the final custom domain only after the preview acceptance checklist passes.

### P2

- Add additional validated product adapters and production reporting after the
  business-card workflow is accepted.