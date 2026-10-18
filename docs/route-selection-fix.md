# Step 9 route selection patch

## Repository findings

At base commit `737f9d1`, the route action sends only an action and job generation.
It reads the printer name from shop settings and never uses discovered printers.
Its only compatibility checks are a configured name and membership in a stock
list; it does not validate the requested number of sides. Errors appear at the
top of the job view, above the review panel, rather than beside the route button.
The button also has no saving label or request timeout.

The optimization advisory reads `machine_capabilities`, a separate collection.
An empty collection explains the advisory's STOP message; it does not prove that
the route endpoint rejected a particular live click. The live network response
was not captured, so this patch does not claim to have proven that runtime cause.

## Changed behavior

- Step 9 lists printers reported by paired connectors and explains individual
  offline, configured-printer, stock and side-count blockers.
- Settings offers discovered printer names and an explicit side-support choice.
- Discovery is never labeled capability verification. For a route to be saved,
  the operator must provide compatibility evidence and confirm stock/side support.
  This is attributed human evidence, not automatic machine certification.
- The backend revalidates against current discovery and settings. Unknown IDs,
  stale settings, unsupported stock/sides and missing evidence fail with 409.
- Route save shows progress, has a timeout, validates the server's success
  response and shows errors beside the control. Unknown save outcomes offer a
  job refresh rather than automatic resubmission.
- The selected printer, connector identity, settings version and compatibility
  evidence persist on the job. Proof approval remains unchanged. RIP handoff,
  readiness and authorization are still separate gates; no PDF is dispatched.
- Optimization and monetary cost claims remain unchanged. The route picker does
  not fabricate measured capability/resource profiles for the advisory.

## Integration and test limits

The base repository is older than the build shown in the user's October 17
screenshots. Integrate these focused changes into the latest Emergent source;
do not overwrite that source with this older repository wholesale. Deploy the
frontend and backend together because the route action now requires explicit
printer selection, a settings version and human compatibility evidence.

Backend unit tests cover eligible and blocked routes; isolated ASGI endpoint tests
cover save/reload, errors, stale requests and preservation of approvals with all
database operations mocked. Frontend tests cover selection, evidence, inline
errors, timeouts and busy feedback. No live shop records, credentials, settings,
pairings, AI calls or printer operations are used. Mocked persistence does not
prove live MongoDB or Windows/Fiery acceptance.

The separate database-backed `integration_agents_e2e.py` fixture is updated for
the new route payload but was not executed here; it requires its isolated MongoDB
environment and external PDF fixtures.

No deployment is included. No Emergent agent run was started.
