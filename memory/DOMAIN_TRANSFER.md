# Safe custom-domain migration: myraana.com

Do this only after the new Print2Go preview has been owner-tested. Do not modify
the old Myraana deployment, data, or domain configuration before that point.

1. Open the Print2Go preview and create the first administrator account yourself.
2. Verify a normal job lifecycle with non-customer test artwork: upload, inspect,
   generated proof, explicit approval, route selection, and blocked connector state.
3. Configure the connector only on a non-printing staging folder. Confirm a real
   heartbeat and exact checksum handoff without authorizing physical production.
4. Resolve assistant credentials only if needed; do not treat a key-present state
   as a successful AI connection.
5. Record an owner acceptance decision for the new preview. Keep Myraana running.
6. In the domain manager for `myraana.com`, change the app target to the new
   Print2Go deployment using the platform-provided custom-domain target. Do not
   change unrelated DNS records such as mail records.
7. Wait for DNS and TLS status to become active, then test `https://myraana.com`
   and a direct deep link from a separate signed-out browser session.
8. Confirm the old Myraana application is still recoverable before formally
   retiring it. Roll back the domain target if the new app fails acceptance.

The domain transfer is intentionally not performed by this build process.