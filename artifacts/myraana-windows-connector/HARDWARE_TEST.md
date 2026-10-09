# Read-only Windows Hardware Acceptance

Run this only on an authorized preview Windows computer with locally installed
printers. Do not use a production shop, customer job, or physical printer action.

1. Record the installed-printer list and current printer configuration.
2. Build and start the connector following `README.md`.
3. Confirm its console first reports **Found** or **Needs Attention**; it must not
   show a print action, create a test page, or modify printer configuration.
4. In Myraana preview, create a one-time pairing code, start the connector with it,
   and confirm the discovered printer name matches the Windows-installed printer.
5. Approve only the displayed device in Connect Shop. Confirm its status becomes
   **Connected** after an outbound heartbeat.
6. Close the connector, restart it, and confirm it reconnects without a new pairing
   code. Temporarily remove network access and restore it; confirm it recovers.
7. Compare printer configuration, spooler queues, and default-printer choice with
   the values recorded in step 1. They must be unchanged.

Expected results: discovery, pairing, and heartbeat are visible; no printer queue
entry, test page, hot-folder write, job release, or production workflow change occurs.

Real Windows hardware validation is required. Linux or browser-only testing cannot
prove Windows spooler discovery, Credential Manager storage, executable startup, or
automatic reconnection.