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
- Release evidence is published as static preview downloads under
  `/setup/releases/`. Criterion 16 records the credential-like build-transcript
  incident as unresolved; its real/sample classification and any rotation action
  require platform security investigation.
- Static release-link regression passed: all seven published preview artifacts
  returned HTTP 200, the published source ZIP checksum matched, and the ZIP had
  no `.env` or `test_credentials.md` entries.
- Audit update: restored the source-style job assistant workspace, server-only
  direct-provider adapters, durable processing execution leases, pause/resume/
  cancel controls, step execution references, and settings-route invalidation.
- PASS: focused isolated lease/pause/unconfigured-assistant assertion and an
  independent 4/4 desktop/mobile assistant+proof regression. The QA database was
  deleted and the production preview was restored empty after the checks.
- PASS: independent settings-mutation regression (8/8) plus stale-readiness
  cleanup verification (5/5). Changing shop settings preserves the unchanged
  verified proof approval while revoking route, readiness, authorization, and
  downstream route tasks. The isolated QA database was deleted afterward.
- PASS: focused operator recovery regression (6/6). Rejected final QC exposes
  protected rework and returns to human reauthorization; readiness recovery
  exposes Connect shop and retry readiness without artwork-upload drift.
- PASS: deterministic multi-agent integration runner completed 24/24 isolated
  endpoint checks and the supplied agent suite completed 10/10. The test backend
  was stopped, `p2g_integration_test` was dropped, and the live preview stayed in
  first-run state. The independent regression review reported no issues.
- PASS: corrected connector ordering in the isolated agent runner completed
  26 PASS / 0 FAIL. It proves a Production-agent STOP with the exact
  `Disconnected or stale connector.` reason before artwork replacement. Positive
  QC completion remains explicitly NOT TESTED because no physical operator stages
  were fabricated.
- Feature added: a minimal job-detail advisory Production Review panel invokes the
  existing no-body agent evaluation endpoint and displays persisted PASS/WARN/STOP
  evidence without mutating workflow state. Targeted static verification passed.
- NOT VERIFIED: live connector/hardware, direct Anthropic/OpenAI credentials, and
  live custom-domain routing.
- FAIL (honestly blocked): managed LLM tool-call probe returned a provider-side
  request-format error. The assistant remains unconfigured rather than claiming AI.
- Deployment status check: live run `bf94d950` completed successfully for
  `myraana.com` and `www.myraana.com`. Read-only checks found root, `/api/`, and
  `/api/auth` healthy, active Cloudflare SSL, no destructive migration/reset log
  activity, and no recent 5xx errors. The requested git commit cannot be matched
  byte-for-byte because `/api/build-info` reports `commit:unavailable`; production
  data integrity remains unverified within the read-only check scope.
- Final live browser check: `https://myraana.com` served the expected sign-in page,
  but the available browser context had no authorized session. No protected job UI,
  review panel, workflow, or build metadata was accessed; no production mutation
  was attempted. Build-to-commit identity remains unverified.
- Read-only deployed-bundle inspection: `main.506517f0.js` contains deployed
  implementation markers for all six targeted UI fixes and the `Run AI Production
  Review` control. This proves bundle presence only; protected interaction remains
  blocked without an authorized session. `build-info` obtains its commit using
  `git rev-parse --short HEAD` and returns `unavailable` on lookup failure, so the
  actual deployed commit cannot be evidenced from the available metadata.
- Deployment-agent confirmation: production package intentionally has no `.git`,
  and the platform build injects neither `GIT_COMMIT` nor `BUILD_TIMESTAMP`.
  Therefore the runtime `git rev-parse` call fails and the endpoint correctly
  returns `commit: unavailable` and `builtAt: runtime`. Deployment logs and image
  metadata also contain no commit SHA, so the deployed commit is definitively
  unknown from available metadata. Full bundle inspection confirmed all six fixes
  and the Production Review UI as positive literals in `main.506517f0.js`.
- Preview build-identity fix: `craco.config.js` now runs
  `backend/scripts/stamp_build_metadata.py` for production builds. The script
  writes commit and UTC build time to `backend/build_metadata.json`, and the
  read-only `/api/build-info` endpoint returns only validated fields through
  `p2g.build_metadata.read_build_metadata`; it no longer shells out to Git at
  runtime. Preview evidence: commit
  `df14ac2758c22257208decd93908b99f1c5395f2`, built at
  `2026-10-09T02:07:17+00:00`.
- Preview acceptance update: iteration 12 independently passed authenticated
  desktop/mobile navigation, all six targeted UI fixes, 16 task summaries,
  build display, and render-only advisory-review UI. A disposable valid-PDF job
  additionally passed upload, preflight, PRINT_READY creation/verification,
  proof approval, routing, and RIP staging. It was cancelled and settings were
  restored. Connector readiness correctly blocked with the disconnected-agent
  message; authorization, physical print, cut, QC, and pack were not attempted.
- Windows Connector handoff: source, unsigned preview PyInstaller build script,
  pinned Windows-only dependencies, pairing instructions, and a read-only hardware
  acceptance checklist were packaged in
  `/app/artifacts/Myraana_Windows_Connector_Preview.zip`. The archive was checked
  to exclude `.env`, local state, credentials, and pairing secrets. Real Windows
  executable and printer validation remain intentionally untested.
- GitHub Actions handoff: `.github/workflows/build-windows-connector.yml` uses a
  GitHub-hosted Windows runner to install pinned connector dependencies, invoke the
  existing unsigned PyInstaller script, validate `.exe` output, and upload a
  five-day preview artifact. It contains no secrets, signing, release, deployment,
  or printing action. GitHub repository access was unavailable in this environment,
  so the workflow has not been run.

## Prioritized Backlog

### P0

- Configure a non-printing preview Edge Agent heartbeat with a writable staging
  folder and `CONNECTOR_SECRET` before validating positive readiness.
- Configure and verify direct Anthropic/OpenAI credentials or resolve the managed
  provider tool-call failure before enabling assistant conversations.

### P1

- Perform owner-led physical proof, RIP, and production-gate validation.
- Connect the final custom domain only after the preview acceptance checklist passes.

### P2

- Add additional validated product adapters and production reporting after the
  business-card workflow is accepted.