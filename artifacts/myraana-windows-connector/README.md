# Myraana Windows Connector

1. Download and extract the Windows build ZIP.
2. Open `MyraanaConnector/MyraanaConnector.exe`.
3. The website is filled in as `https://myraana.com`. Paste the pairing code from Myraana Shop settings. The code is visible; it is a one-time code, not a password.
4. Click **Connect**, then approve the displayed computer in Myraana.
5. Wait for **Connected**. Keep the window open while using the connection.

The website is remembered. On subsequent launches, click **Connect** with the code
blank to reconnect. If the saved connection is no longer accepted, the window asks
for a new pairing code instead of staying on the old error. If the connection is
interrupted, it retries automatically. Closing the window stops the connector.

This connector finds the shop printers and can place approved PRINT_READY files
on the Fiery HOLD queue. It never prints or releases jobs.

Pairing codes are cleared from the setup form when connection starts. Credentials
are stored in Windows Credential Manager. Do not save codes or credentials in files.

A connection is bound to its saved website. Changing the website requires a
separate installation profile. Older credentials without a recorded website need
migration; they are never automatically sent to an unconfirmed host.

## Build from source

On Windows with Python 3.12, run `build-myraana-connector.ps1` from the source
folder. The output is `dist/MyraanaConnector/MyraanaConnector.exe`.

The CI build runs mocked pairing and reconnection tests and opens/closes the
packaged setup window without network or printer access. Actual shop printer
discovery, pairing approval and restart recovery still require the hardware
acceptance procedure in `HARDWARE_TEST.md`.
