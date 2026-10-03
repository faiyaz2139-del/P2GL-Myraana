# Print2Go Production Studio

A new, standalone application for Print2Go London. It has no Myraana dependency.

## Start using it

1. Open the published site and create the first administrator account. Use a unique password of at least 12 characters.
2. Select **Start a job**, enter the order and upload a one- or two-page PDF (front first, back second), up to 4 MB.
3. Choose **Check artwork**. Real checks run on the server and save evidence. Blocking issues require a revised file.
4. For trim-only artwork, upload corrected artwork or explicitly accept a blank border outside trim. No content is stretched or invented.
5. Review the actual generated pages and all warnings, then approve that exact file.
6. Configure a compatible printer in **Shop settings**, select the route, and stage imposition in the RIP. The RIP step is operator-assisted.
7. Connect the shop computer, verify readiness and explicitly authorize production. Confirm printing only after sheets physically print. Confirm cutting, QC and packing separately.

Existing jobs pin the recipe version. **Recipes** creates new versions for future jobs.

## Stack and source

React/Vinext + TypeScript on Cloudflare Workers. D1 holds users, sessions, job state and execution records. R2 holds immutable PDF versions. PDF.js parses PDF contents; pdf-lib creates and verifies production page boxes. The UI renders actual PDF pages with PDF.js. One Print2Go Assistant uses Claude (Anthropic Messages API) and ChatGPT models (OpenAI Responses API) behind the scenes, with streaming and the same constrained tools.

Source layout:

- `app/Studio.tsx` — responsive jobs, recipe and shop settings interface.
- `app/api/[...path]/route.ts` — authenticated, validated APIs and human-action gates.
- `lib/production/engine.ts` — task sequencing, file lineage, evidence and authorization.
- `lib/production/pdf.ts` — measured inspection, preparation and reopened verification.
- `lib/production/products.ts` — product adapter boundary. Business cards are implemented; future products need their own validated adapters and order forms.
- `lib/production/ai.ts`, `providers.ts` — server-only dual-provider routing, streaming adapters and shared tool orchestration.
- `db/schema.ts`, `drizzle/` — persistent schema and migrations.
- `public/setup/print2go-connector.py` — local file staging agent, never a print agent.
- `tests/` — isolated acceptance harness and clearly labelled test artwork.

## Backend AI setup

Operators see one **Print2Go Assistant**. They do not see model names, provider names or a model selector. Provider configuration is managed entirely through server environment values, not job forms or browser settings.

Configure these secrets on the server:

- `ANTHROPIC_API_KEY`: Claude API key.
- `OPENAI_API_KEY`: OpenAI API key for ChatGPT models.

Optional server configuration:

- `AI_PRIMARY_PROVIDER`: `claude` (default) or `openai`.
- `CLAUDE_MODEL`: Claude model ID; default `claude-sonnet-4-5`.
- `OPENAI_MODEL`: OpenAI model ID; default `gpt-4.1`.
- `AI_FALLBACK_ENABLED`: `true` (default) or `false`.

With both keys configured, Claude is primary and OpenAI is the backup by default. If the primary has no configured key, the configured backup is used when fallback is enabled. A failed initial request can fall back only before any text is streamed or any tool is executed. After a conversation starts using a provider, that provider keeps the tool loop for that request; errors ask for a safe retry instead of replaying work through another model. Both providers use the same saved job, recipe and tool evidence. This is primary/backup orchestration, not two simultaneous execution engines or two mandatory billable calls per message.

API keys are never returned to the browser, stored in job records or passed to either model as prompt data. Never put keys in a public file, chat, source control or a `NEXT_PUBLIC_*` variable. Model IDs and provider selection are also omitted from browser settings responses. A key-present status is not a successful live API request.

The Anthropic Messages and OpenAI Responses streaming/tool contracts are implemented following official documentation:
https://platform.claude.com/docs/en/build-with-claude/streaming
https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
https://developers.openai.com/api/docs/guides/function-calling
https://developers.openai.com/api/docs/guides/streaming-responses

Each provider receives the pinned recipe, current persisted tasks and verified tool results. Human approval, authorization and physical confirmations are not exposed as tools. Inputs are checked outside the model; no arbitrary paths or executable code are allowed. Hidden reasoning events are not forwarded or persisted. A separate per-job assistant lease prevents simultaneous conversations from starting independent execution loops.

If using the OpenAI Developers plugin to configure an API key, enable that plugin and use its API-key setup flow. Both real credentialed connections remain unverified until their first live calls succeed.

## Shop connector setup

Requires Python 3.10+, an HTTPS application URL and a writable staging folder. Configure a strong random `CONNECTOR_SECRET` in the server environment and, separately, in the shop computer's environment. The server does not return this secret in browser responses. Use local environment settings or a protected process configuration; do not paste secrets into application chat or commit them.

Set these values on the shop computer:

- `PRINT2GO_URL`: the published HTTPS site address.
- `PRINT2GO_FOLDER`: an absolute path to a writable staging folder.
- `CONNECTOR_SECRET`: the same server-side connector secret.

Then run `python print2go-connector.py`. It tests folder writability, sends authenticated heartbeats and writes only explicitly authorized PDF versions. It verifies the downloaded and written SHA-256 checksum, renames atomically and acknowledges the handoff. A handoff creates a PRODUCTION_OUTPUT lineage record; it never marks Print completed.

**Use a staging folder that does not automatically trigger a printer.** Imposition and Fiery/RIP staging are operator-assisted. This release has no verified direct Fiery API integration, machine print command or automatic cutter control.

A private Sites publication can reject machine requests before they reach the application. A machine-access policy or supported private tunnel must be configured for the shop computer. This is a deployment access requirement, separate from the connector bearer token. Live connectivity is not claimed until a real heartbeat reaches the published application. Keep the application private while that access is resolved.

## Permissions and records

Administrators manage recipes, shop settings and operator accounts. Operators can create jobs, perform permitted checks and explicitly approve/confirm their work. Passwords use salted PBKDF2; session tokens are hashed in D1 and sent only in HttpOnly, SameSite=Strict cookies, Secure on HTTPS. Sessions expire after 12 hours. First-run administrator setup is available only before the first account exists; the published site is also owner-private.

ORIGINAL → WORKING_COPY → PRINT_READY → PRODUCTION_OUTPUT.

Files are never overwritten or deleted by the workflow. Replacement artwork increments the generation and revokes downstream verification, approval and authorization. Approval/authorization history records preserve exact checksums and actors. Production-setting changes reset affected unprinted routes and revoke authorization. A quality rejection requires rework and a new human authorization.

Processing uses background `waitUntil` with D1 execution records and per-job leases. Repeated clicks cannot run simultaneous work on the same job. Tasks save after each validated stage. Refresh uses persisted state and a real-event SSE feed with polling fallback. An interrupted lease is recovered after two minutes and exposes a safe retry; this release does not provide an external queue that guarantees unattended retry if the worker is terminated. Pause stops between automated stages; it cannot stop an already-running physical machine. Cancel preserves saved records and closes further work.

## PDF checks and practical limits

Measured: page count, page dimensions, Media/Crop/Trim/Bleed boxes, detected top-level text-font embedding, approximate axis-aligned text bounds, direct image placements and DPI, basic colour operators. Invalid dimensions, page count, rotated pages, interactive forms/annotations, detected unsafe text and detected unembedded used fonts block the flow.

Manual proof review remains required for nested forms, unusual text operators, angled text, transparency, masks, logos, vector content, exact safe-area interpretation, actual bleed coverage, colour fidelity and output profiles. This is not a certified PDF/X preflight engine. No colour conversion, font substitution or design edits are applied. RGB/CMYK rendering operator information alone cannot certify a document's colour-management suitability.

Generated verification reopens the stored file and rechecks the recipe dimensions, page boxes and content issues, while independently checking its recorded checksum. It does not certify colour separations, overprint or every RIP-specific property.

## Development and verification

Install dependencies using the project lockfile. Commands:

```
pnpm install
pnpm exec tsc --noEmit
pnpm build
python3 tests/fixtures.py
node tests/acceptance.mjs
node tests/providers.mjs
```

The acceptance harness loads the built Worker in an isolated Miniflare instance with its own temporary D1/R2. It creates QA-only accounts and synthetic jobs. It never contacts a physical printer or seeds the production database. Fixture passwords and connector tokens are explicitly test-only values; production secrets are not present in this repository.

`docs/ACCEPTANCE.md` documents results and exact remaining checks. No simulated task outcomes are used for the live application. Isolated connector/physical-action tests validate gates and state transitions, not real machine completion.

## Remaining release limitations

- Real Claude and OpenAI calls require their respective API keys and account/model access.
- Live shop readiness/handoff require shop hardware, connector secret and a machine-access policy.
- Browser screenshot/interaction QA was unavailable in this environment. Responsive layout and actual canvas proof display must receive a live desktop/mobile review.
- One business-card product is executable. Other product adapters are extension points, not implemented production routes.
- Four-MB, at-most-two-page PDF limit; no certified PDF/X, imposition engine or direct Fiery submission.
- No password reset, account removal or automated backup/export scheduling in this first release.
