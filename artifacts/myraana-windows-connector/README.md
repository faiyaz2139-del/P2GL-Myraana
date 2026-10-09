# Myraana Windows Connector — Preview Handoff

This preview connector performs read-only Windows printer discovery, secure pairing,
and outbound HTTPS heartbeats. It never prints, creates test pages, changes printer
settings, releases jobs, or writes to hot folders.

## Package contents

- `myraana-connector.py` — connector source.
- `build-myraana-connector.ps1` — unsigned preview PyInstaller build script.
- `requirements.txt` — pinned build dependencies.
- `HARDWARE_TEST.md` — read-only acceptance procedure.

## Build on an authorized Windows 10/11 x64 computer

1. Install Python 3.11 or 3.12 for the current Windows user.
2. Open PowerShell in this extracted folder.
3. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
python -m pip install -r requirements.txt
.\build-myraana-connector.ps1
```

The unsigned preview executable is created at
`dist\MyraanaConnector\MyraanaConnector.exe`. Do not distribute it beyond preview
testing. Production distribution requires an Authenticode-signed installer.

## Pair with Myraana preview

1. Sign in to the authorized Myraana **preview** shop administrator account.
2. Open **Shop settings → Connect Windows Connector** and select **Pair connector**.
3. Download the connector and start it with these process-only variables:

```powershell
$env:MYRAANA_URL = "https://YOUR-PREVIEW-HOST"
$env:MYRAANA_PAIRING_CODE = "CODE-SHOWN-IN-MYRAANA"
.\dist\MyraanaConnector\MyraanaConnector.exe
```

4. Review the discovered Windows printer name in Myraana and approve the pairing.
5. The connector stores its device credential in Windows Credential Manager, then
   sends outbound HTTPS heartbeats every 30 seconds. It retries automatically after
   restart or network loss.

Never place pairing codes, credentials, or server secrets in scripts, source files,
shared documents, or command history.