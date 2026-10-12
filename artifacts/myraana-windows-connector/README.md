# Myraana Windows Connector — Preview

1. Download and extract the Windows build ZIP.
2. Open `MyraanaConnector/MyraanaConnector.exe`.
3. Paste your Myraana preview website and its pairing code into the setup window.
4. Click **Connect**, then approve the displayed computer in Myraana.
5. Wait for **Connected**. Keep the window open while using the connection.

The website is remembered. On subsequent launches, click **Connect** with the code
blank to reconnect. If the connection is interrupted, it retries automatically.
Closing the window stops the connector.

This unsigned preview discovers installed Windows printers and sends health
checks. It cannot print, change printer settings, release jobs or write to hot
folders. Use an authorized preview environment for testing.

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
