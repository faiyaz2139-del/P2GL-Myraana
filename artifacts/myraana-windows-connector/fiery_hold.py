"""Submit a PRINT_READY PDF to a Fiery hold queue. This never prints or releases."""
import json
from pathlib import Path


HOLD_STATUSES = {200, 201, 202, 204}


def hold_payload(filename, preset, stock):
    """Attributes for a hold submission. print and release stay false."""
    payload = {
        "filename": Path(str(filename or "artwork_PRINT_READY.pdf")).name[:180] or "artwork_PRINT_READY.pdf",
        "queue": "hold",
        "preset": str(preset or "London BC")[:80],
        "stock": str(stock or "")[:120],
        "print": False,
        "release": False,
    }
    if payload["print"] or payload["release"] or payload["queue"] != "hold":
        raise RuntimeError("Refusing to print.")
    return payload


def submit_hold(address, filename, preset, stock, pdf, opener=None, hot_folder=None, timeout=8.0):
    """Put the file on HOLD via the Fiery API, or a Hold hot folder if the API fails.

    opener(url, payload, pdf_bytes, timeout) returns an HTTP status. It must not be asked to print.
    """
    payload = hold_payload(filename, preset, stock)
    api_error = "No Fiery address."
    if address and opener is not None:
        url = f"https://{address}:443/live/api/v5/jobs"
        try:
            status = int(opener(url, payload, pdf or b"", timeout))
        except Exception:
            status = 0
            api_error = "Fiery did not answer."
        else:
            api_error = f"Fiery answered {status}."
        if status in HOLD_STATUSES:
            return {"ok": True, "held": True, "printed": False, "method": "api", "error": ""}
    if hot_folder:
        try:
            _write_hold_folder(hot_folder, payload["filename"], pdf or b"")
        except Exception:
            return {
                "ok": False,
                "held": False,
                "printed": False,
                "method": "hot-folder",
                "error": "The hot folder could not be written. Nothing was printed.",
            }
        return {"ok": True, "held": True, "printed": False, "method": "hot-folder", "error": ""}
    return {"ok": False, "held": False, "printed": False, "method": "api", "error": api_error}


def interpret_hold_report(report):
    """A connector report may confirm a hold. A print or release is refused."""
    if not isinstance(report, dict):
        return {"ok": False, "held": False, "printed": False, "method": "", "error": "The connector report was empty."}
    if report.get("printed") is True or report.get("released") is True or report.get("release") is True:
        return {
            "ok": False,
            "held": False,
            "printed": False,
            "method": "",
            "error": "Refused a print or release. The job stays on HOLD.",
        }
    if report.get("ok") is True and report.get("held") is True:
        method = report.get("method") if report.get("method") in {"api", "hot-folder"} else "api"
        return {"ok": True, "held": True, "printed": False, "method": method, "error": ""}
    error = str(report.get("error") or "Fiery did not accept the hold.")[:300]
    return {"ok": False, "held": False, "printed": False, "method": str(report.get("method") or "api")[:40], "error": error}


def _write_hold_folder(folder, filename, pdf):
    root = Path(folder).resolve()
    hold = root / "Hold"
    hold.mkdir(parents=True, exist_ok=True)
    safe = Path(str(filename or "")).name
    if not safe or safe in {".", ".."} or not safe.lower().endswith(".pdf"):
        raise ValueError("filename")
    target = (hold / safe).resolve()
    if hold.resolve() not in target.parents:
        raise ValueError("path")
    target.write_bytes(pdf)


def fiery_opener(url, payload, pdf, timeout):
    """POST the hold attributes and the PDF. There is no print or release call."""
    import urllib.error
    import urllib.request

    if payload.get("print") or payload.get("release") or payload.get("queue") != "hold":
        raise RuntimeError("Refusing to print.")
    boundary = "----myraana-hold"
    meta = json.dumps(payload).encode("utf-8")
    filename = payload["filename"]
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"attributes\"\r\nContent-Type: application/json\r\n\r\n".encode(),
            meta,
            b"\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n".encode(),
            pdf or b"",
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    call = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
