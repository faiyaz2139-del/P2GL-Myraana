"""Preview Windows connector: read-only discovery, pairing, and HTTPS heartbeats.

This program never prints, creates test pages, changes printer settings, or writes
to hot folders. Build on Windows with the adjacent PowerShell script.
"""
import json
import os
import platform
import secrets
import socket
import time
import urllib.error
import urllib.request
import uuid

try:
    import keyring
except ImportError:
    keyring = None


API_URL = os.environ.get("MYRAANA_URL", "").rstrip("/") + "/api"
STATE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Myraana", "connector.json")
SERVICE = "MyraanaConnector"


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def secret(name, value=None):
    if not keyring:
        raise RuntimeError("Windows Credential Manager support is required.")
    if value is not None:
        keyring.set_password(SERVICE, name, value)
        return value
    return keyring.get_password(SERVICE, name)


def printers():
    if platform.system() != "Windows":
        return []
    try:
        import win32print
    except ImportError:
        return []
    found = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for item in win32print.EnumPrinters(flags):
        name = item[2]
        handle = win32print.OpenPrinter(name)
        try:
            details = win32print.GetPrinter(handle, 2)
            found.append({"source": "windows_spooler", "name": name,
                          "driver": details.get("pDriverName", ""),
                          "port": details.get("pPortName", ""),
                          "status": str(details.get("Status", ""))})
        finally:
            win32print.ClosePrinter(handle)
    return found


def inventory():
    return {"hostname": socket.gethostname(), "printers": printers(),
            "fiery_rip": [], "hot_folders": []}


def request(path, payload, credential=None):
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    body = json.dumps(payload).encode("utf-8")
    call = urllib.request.Request(API_URL + path, data=body, headers=headers)
    with urllib.request.urlopen(call, timeout=20) as response:
        return json.load(response)


def run():
    state = load_state()
    state.setdefault("deviceId", str(uuid.uuid4()))
    claim_secret = secret("claimSecret") or secret("claimSecret", secrets.token_urlsafe(48))
    credential = secret("credential")
    state.pop("claimSecret", None)
    state.pop("credential", None)
    save_state(state)
    while True:
        try:
            if not credential:
                code = os.environ.get("MYRAANA_PAIRING_CODE", "").strip().upper()
                if not code:
                    print("Needs Attention: enter the one-time code shown in Myraana.")
                    time.sleep(15)
                    continue
                claimed = request("/connector-pairings/claim", {
                    "code": code, "deviceId": state["deviceId"],
                    "claimSecret": claim_secret, "inventory": inventory(),
                })
                state["pairingId"] = claimed["id"]
                save_state(state)
                print("Found: awaiting Myraana administrator approval.")
            result = request(
                f"/connector-pairings/{state['pairingId']}/poll",
                {"claimSecret": claim_secret},
            )
            if result.get("credential"):
                credential = secret("credential", result["credential"])
            if credential:
                request("/connector-devices/heartbeat", {"inventory": inventory()}, credential)
                print("Connected: discovery and health check complete. No print actions are available.")
            time.sleep(30)
        except (urllib.error.URLError, urllib.error.HTTPError, KeyError):
            print("Offline: retrying automatically. No print actions are available.")
            time.sleep(30)


if __name__ == "__main__":
    run()