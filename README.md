# Print2Go Production Studio

Print2Go is a guarded production workspace for business-card jobs. It preserves
PDF lineage in MongoDB GridFS and never sends a physical print command.

## Runtime

- Frontend: React, using `REACT_APP_BACKEND_URL` for all API requests.
- Backend: FastAPI, with every route under `/api`.
- Data and durable PDFs: MongoDB plus the `pdf_files` GridFS bucket.
- PDF workflow: PyMuPDF and pypdf inspect, prepare, generate, reopen, and verify
  the stored production PDF.

## MongoDB and GridFS

Set only these existing server environment variables; do not commit their values:

```text
MONGO_URL=<mongodb connection string>
DB_NAME=<dedicated Print2Go database name>
```

The backend creates its collections and GridFS indexes during startup. Originals
and derived PDFs are stored in GridFS, not in local or temporary folders. Use a
dedicated database name for each isolated QA run and delete that database after
the run completes.

## Startup and recovery

The supervised backend runs the startup recovery hook automatically. Durable
processing executions receive an atomic Mongo lease before PDF files are written.
An expired execution is marked interrupted and any running task becomes safely
retryable; existing immutable evidence remains attached to the job. Do not start
an additional Uvicorn process beside the supervised backend.

## First administrator

On a fresh database, open the Studio and use the first-run setup screen to choose
the owner name, email, and a password of at least 12 characters. There is no
public signup and no seeded production account. Administrators can create
operators; operators can run jobs but cannot change recipes or shop settings.

## Assistant providers

Direct provider credentials are server-only environment variables:

```text
ANTHROPIC_API_KEY=<server secret>
OPENAI_API_KEY=<server secret>
AI_PRIMARY_PROVIDER=anthropic
AI_FALLBACK_ENABLED=true
CLAUDE_MODEL=claude-sonnet-4-5-20250929
OPENAI_MODEL=gpt-4.1
```

Claude is primary unless `AI_PRIMARY_PROVIDER=openai`. OpenAI is only used as a
fallback before visible provider output or a tool result. Do not put keys, model
secrets, or provider calls in the browser. If neither direct key is configured,
the Studio persists an honest recovery message and guarded job controls continue
to work. Assistant tools are read-only and cannot approve, authorize, print, or
confirm physical work.

## CORS and deployment origin

Set `CORS_ORIGINS` to comma-separated HTTPS browser origins that are allowed to
send credentialed requests. The backend also validates the deployed forwarded
HTTPS host so preview traffic remains protected behind the platform proxy. Do not
use a wildcard origin with credentialed production traffic.

## Local shop connector

Set a random server-side `CONNECTOR_SECRET` through deployment secrets. Do not
place it in source control or browser code. Download the local connector from
Studio Shop settings, then configure its local environment with:

```text
PRINT2GO_URL=https://your-studio-host
CONNECTOR_SECRET=<same server secret>
PRINT2GO_FOLDER=/safe/non-printing-staging-folder
```

The staging folder must not auto-print. The connector reports freshness and
writability, accepts only exact authorized checksum handoffs, and never sends a
physical print command.

## Production safety

Approval is tied to the exact verified production PDF. Changing artwork invalidates
downstream work. Changing shop settings preserves the unchanged proof approval but
revokes the route, readiness evidence, and authorization until an operator chooses
a route again. Physical print, cutting, QC, and packing all require explicit human
confirmation.
