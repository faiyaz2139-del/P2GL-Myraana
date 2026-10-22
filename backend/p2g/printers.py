"""Separate discovered Windows printers from virtual document printers."""
import re


# Names and drivers that do not mark a press or office printer.
_MARKERS = (
    "microsoft print to pdf",
    "microsoft xps document writer",
    "xps document writer",
    "onenote",
    "one note",
    "adobe pdf",
    "adobe acrobat",
    "foxit",
    "cutepdf",
    "pdfcreator",
    "bullzip",
    "dopdf",
    "nitro pdf",
    "clawpdf",
    "pdf24",
    "primopdf",
    "pdf-xchange",
    "microsoft print to onenote",
)
_PORTS = {"portprompt:", "nul:", "shrfax:", "file:"}


def is_virtual_printer(item):
    if not isinstance(item, dict):
        return True
    name = str(item.get("name") or "")
    driver = str(item.get("driver") or "")
    port = str(item.get("port") or "")
    blob = f"{name} {driver} {port}".lower()
    if any(marker in blob for marker in _MARKERS):
        return True
    if port.strip().lower() in _PORTS:
        return True
    if re.search(r"\bfax\b", blob):
        return True
    return False


def filter_printers(items):
    if not isinstance(items, list):
        return []
    kept = []
    for item in items:
        if isinstance(item, dict) and not is_virtual_printer(item):
            kept.append(item)
    return kept


def printer_status(item, verified_names, device_status):
    """Connection of the computer is not the same thing as a verified press."""
    name = str((item or {}).get("name") or "")
    verified = name in set(verified_names or [])
    return {
        "name": name,
        "driver": (item or {}).get("driver") or "",
        "port": (item or {}).get("port") or "",
        "deviceStatus": device_status or "Offline",
        "productionStatus": "Verified" if verified else "Not verified",
    }
