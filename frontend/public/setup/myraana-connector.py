"""Windows connector: printer discovery, pairing, and HTTPS heartbeats.

The pairing code is created in one shop's settings and only joins that shop.
This program does not use CONNECTOR_SECRET. It never prints or releases jobs.
When Myraana asks, it can place a PRINT_READY file on a Fiery HOLD queue.
Build on Windows with the adjacent PowerShell script.
"""
import argparse
import importlib.util
import json
import queue
import sys
import threading
import urllib.parse
import os
import platform
import secrets
import socket
import urllib.error
import urllib.request
import uuid

try:
    import keyring
except ImportError:
    keyring = None


STATE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Myraana", "connector.json")
SERVICE = "MyraanaConnector"
DEFAULT_WEBSITE = "https://myraana.com"
REPAIR_MESSAGE = (
    "This computer needs to be paired again. Create a pairing code in "
    "Myraana Shop settings and enter it here."
)
POLL_MISMATCH_MESSAGE = (
    "This pairing no longer matches. Create a new pairing code in "
    "Myraana Shop settings and enter it here."
)
CODE_FORMAT_MESSAGE = "The pairing code must be 8 characters."
CODE_EXPIRED_MESSAGE = (
    "That pairing code is invalid or expired. Create a new one in Myraana Shop settings."
)
WEBSITE_MESSAGE = "That website was not found. Check the Myraana website address."
HOLD_FOOTER = (
    "This connector finds your printers and can place approved PRINT_READY files "
    "on your Fiery HOLD queue. It never prints or releases jobs."
)


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


def forget_secret(name):
    """Drop one saved credential. A missing entry is already forgotten."""
    if not keyring:
        return
    try:
        keyring.delete_password(SERVICE, name)
    except Exception:
        return


def normalize_code(value):
    """Pairing codes are shown in groups. Spaces and dashes are not part of the code."""
    return str(value or "").upper().replace(" ", "").replace("-", "").strip()


def module_candidates(filename):
    """Frozen bundle first (_MEIPASS, then the exe directory), then the script directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, filename))
        candidates.append(os.path.join(os.path.dirname(sys.executable), filename))
    candidates.append(os.path.join(here, filename))
    backend = os.path.join("backend", "p2g", filename)
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", "..", backend)))
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", backend)))
    return candidates


def load_python_module(filename, module_name):
    for candidate in module_candidates(filename):
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location(module_name, candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


_DISCOVERY = None
_FIERY = None


def load_discovery():
    """The discovery module ships beside this script and in the frozen bundle."""
    global _DISCOVERY
    if _DISCOVERY is not None:
        return _DISCOVERY
    module = load_python_module("printer_discovery.py", "myraana_printer_discovery")
    if module is None:
        raise RuntimeError("Printer discovery is unavailable.")
    _DISCOVERY = module
    return module


def printers():
    """Windows spooler queues. Get-Printer and Bonjour run in discover_printers."""
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


def discover_printers():
    """Bonjour plus the OS queues. Failures become an empty list so the heartbeat still runs."""
    try:
        discovery = load_discovery()

        def queues():
            found = []
            try:
                found.extend(discovery.os_queues() or [])
            except Exception:
                pass
            found.extend(printers())
            return found

        return discovery.discover(
            browse=lambda: discovery.browse_mdns(timeout=1.0),
            list_queues=queues,
            probe=lambda address: discovery.probe_fiery(address, timeout=1.0),
        ) or []
    except Exception:
        return []


def inventory():
    found = discover_printers()
    fiery = [item for item in found if item.get("isFiery")]
    return {"hostname": socket.gethostname(), "printers": found,
            "fiery_rip": fiery, "hot_folders": []}


def request(api_url, path, payload, credential=None):
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    body = json.dumps(payload).encode("utf-8")
    call = urllib.request.Request(api_url + path, data=body, headers=headers)
    with urllib.request.urlopen(call, timeout=20) as response:
        return json.load(response)


def request_bytes(api_url, path, credential):
    headers = {"Authorization": f"Bearer {credential}"}
    call = urllib.request.Request(api_url + path, headers=headers)
    with urllib.request.urlopen(call, timeout=60) as response:
        return response.read()


def load_fiery_hold():
    """Same lookup as discovery: frozen bundle, exe directory, then this script."""
    global _FIERY
    if _FIERY is not None:
        return _FIERY
    module = load_python_module("fiery_hold.py", "myraana_fiery_hold")
    if module is None:
        raise RuntimeError("Fiery hold support is unavailable.")
    _FIERY = module
    return module


def exercise_bundled_modules():
    """Import discovery and Fiery HOLD. The packaged exe must be able to do both."""
    discovery = load_discovery()
    fiery = load_fiery_hold()
    if not hasattr(discovery, "discover") or not hasattr(fiery, "submit_hold"):
        raise RuntimeError("Connector bundle is missing discovery or Fiery hold support.")
    return discovery, fiery


def perform_holds(api_url, credential, result, opener=None):
    """Submit queued PRINT_READY files to HOLD. A failure is reported, never printed."""
    holds = result.get("holds") if isinstance(result, dict) else None
    if not holds:
        return None
    fiery = load_fiery_hold()
    reports = []
    for item in holds:
        if not isinstance(item, dict) or not item.get("jobId"):
            continue
        try:
            pdf = request_bytes(api_url, f"/connector-devices/holds/{item['jobId']}", credential)
            outcome = fiery.submit_hold(
                address=item.get("address") or "",
                filename=item.get("filename") or "artwork_PRINT_READY.pdf",
                preset=item.get("preset") or "London BC",
                stock=item.get("stock") or "",
                pdf=pdf,
                opener=opener or fiery.fiery_opener,
                hot_folder=item.get("hotFolder") or None,
            )
        except Exception:
            outcome = {
                "ok": False,
                "held": False,
                "printed": False,
                "method": "api",
                "error": "The hold could not be submitted.",
            }
        if outcome.get("printed") or outcome.get("release") or outcome.get("released"):
            outcome = {
                "ok": False,
                "held": False,
                "printed": False,
                "method": "api",
                "error": "Refused a print or release. The job stays on HOLD.",
            }
        reports.append({"jobId": item["jobId"], **outcome})
    return reports or None


def website_url(value):
    value = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("A valid HTTPS Myraana website URL is required.")
    return value


def run(url=None, code=None, report=print, stop=None):
    stop = stop or threading.Event()
    state = load_state()
    state.setdefault("deviceId", str(uuid.uuid4()))
    url = website_url(url or os.environ.get("MYRAANA_URL", "")
                      or state.get("websiteUrl", "")
                      or input("Enter your Myraana HTTPS website URL: "))
    if state.get("websiteUrl") and state["websiteUrl"] != url:
        raise ValueError("This connector is already linked to a different website.")
    api_url = url + "/api"
    claim_secret = secret("claimSecret") or secret("claimSecret", secrets.token_urlsafe(48))
    credential = secret("credential")
    # Older installations do not record their host. Require a new pairing rather
    # than transmitting an existing bearer token to an unconfirmed website.
    if credential and not state.get("websiteUrl"):
        raise ValueError("Existing connection needs migration before using this setup window.")
    state["websiteUrl"] = url
    state.pop("claimSecret", None)
    state.pop("credential", None)
    save_state(state)
    code = normalize_code(code or os.environ.get("MYRAANA_PAIRING_CODE", ""))
    if code and len(code) != 8:
        raise ValueError(CODE_FORMAT_MESSAGE)
    # A typed code replaces a saved credential. The old token may belong to a
    # device the shop removed, or to a database that was reset.
    if code and credential:
        forget_secret("credential")
        credential = None
        state.pop("pairingId", None)
        save_state(state)
    while not stop.is_set():
        try:
            if credential:
                found = inventory()
                result = request(api_url, "/connector-devices/heartbeat",
                                 {"inventory": found}, credential)
                report(f"Connected. {len(found.get('printers') or [])} printer(s) found.")
                if isinstance(result, dict) and result.get("scan"):
                    found = inventory()
                    result = request(api_url, "/connector-devices/heartbeat",
                            {"inventory": found, "scanned": True}, credential)
                    report("Scanned again for printers.")
                reports = perform_holds(api_url, credential, result)
                if reports:
                    request(api_url, "/connector-devices/heartbeat",
                            {"inventory": found, "holds": reports}, credential)
                    report("Sent the PRINT_READY file to the Fiery hold queue. It was not printed.")
            else:
                if not state.get("pairingId"):
                    if not code:
                        raise ValueError("Enter the pairing code shown in Myraana.")
                    claimed = request(api_url, "/connector-pairings/claim", {
                        "code": code, "deviceId": state["deviceId"],
                        "claimSecret": claim_secret, "inventory": inventory(),
                    })
                    state["pairingId"] = claimed["id"]
                    save_state(state)
                    report("Printer found. Approve this computer in Myraana.")
                result = request(api_url,
                    f"/connector-pairings/{state['pairingId']}/poll",
                    {"claimSecret": claim_secret},
                )
                if result.get("credential"):
                    credential = secret("credential", result["credential"])
                    state.pop("pairingId", None)
                    save_state(state)
                    report("Approved. Checking connection...")
            stop.wait(8)
        except urllib.error.HTTPError as error:
            if error.code == 401 and credential:
                forget_secret("credential")
                credential = None
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(REPAIR_MESSAGE)
            if error.code == 401:
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(POLL_MISMATCH_MESSAGE)
            if error.code == 400:
                raise ValueError(CODE_FORMAT_MESSAGE)
            if error.code == 409:
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(CODE_EXPIRED_MESSAGE)
            if error.code == 404:
                raise ValueError(WEBSITE_MESSAGE)
            if error.code == 403:
                raise ValueError("Myraana refused this connection. Check the website and try again.")
            report(f"Service unavailable (HTTP {error.code}). Retrying automatically.")
            stop.wait(8)
        except (urllib.error.URLError, KeyError, OSError) as error:
            report(f"Offline or waiting for service ({type(error).__name__}). Retrying automatically.")
            stop.wait(8)


def setup_window(self_test=False):
    if self_test:
        exercise_bundled_modules()
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Myraana Connector")
    root.geometry("560x430")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Connect your Windows computer",
              font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Use your Myraana website and its pairing code.").pack(anchor="w", pady=(8, 18))
    state = load_state()
    ttk.Label(frame, text="Myraana website").pack(anchor="w")
    url = tk.StringVar(value=os.environ.get("MYRAANA_URL") or state.get("websiteUrl") or DEFAULT_WEBSITE)
    url_entry = ttk.Entry(frame, textvariable=url, width=64)
    url_entry.pack(fill="x", pady=(4, 12))
    ttk.Label(frame, text="Pairing code (leave blank when reconnecting)").pack(anchor="w")
    code = tk.StringVar(value=os.environ.get("MYRAANA_PAIRING_CODE", ""))
    code_entry = ttk.Entry(frame, textvariable=code, width=64)
    code_entry.pack(fill="x", pady=(4, 12))
    status = tk.StringVar(value="Ready to connect.")
    events = queue.Queue()
    stop = threading.Event()
    worker = None

    def work(address, pairing_code):
        try:
            run(address, pairing_code, lambda message: events.put(("status", message)), stop)
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Setup could not complete. Check your connection and try again."
            events.put(("error", message))
        finally:
            events.put(("done", ""))

    def connect():
        nonlocal worker
        try:
            address = website_url(url.get())
        except ValueError as error:
            status.set(str(error))
            return
        stop.clear()
        button.configure(state="disabled")
        url_entry.configure(state="disabled")
        code_entry.configure(state="disabled")
        status.set("Connecting...")
        pairing_code = code.get()
        code.set("")
        worker = threading.Thread(target=work, args=(address, pairing_code), daemon=True)
        worker.start()

    button = ttk.Button(frame, text="Connect", command=connect)
    button.pack(anchor="w", pady=(0, 12))
    ttk.Label(frame, textvariable=status, wraplength=500).pack(anchor="w")
    ttk.Label(frame, text=HOLD_FOOTER, wraplength=500).pack(anchor="w", pady=(16, 0))

    def poll():
        try:
            while True:
                kind, message = events.get_nowait()
                if kind in ("status", "error"):
                    status.set(message)
                if kind == "done":
                    button.configure(state="normal")
                    url_entry.configure(state="normal")
                    code_entry.configure(state="normal")
        except queue.Empty:
            pass
        root.after(200, poll)

    def close():
        stop.set()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    if self_test:
        # Discovery and Fiery HOLD were loaded above. Close the window without connecting.
        root.update()
        root.after(100, close)
    else:
        poll()
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true", help="Use console setup")
    parser.add_argument("--self-test", action="store_true", help="Check setup window without connecting")
    args = parser.parse_args()
    if args.console:
        run()
    else:
        setup_window(self_test=args.self_test)
