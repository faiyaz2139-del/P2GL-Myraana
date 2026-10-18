"""Route selection from saved shop configuration and connector discovery.

Discovery is not capability verification. Compatibility is an explicit,
attributed operator confirmation; staging readiness remains a separate gate.
"""
import hashlib


def route_options(job, settings, devices):
    options = []
    for device in devices:
        for printer in device.get("inventory", {}).get("printers", []):
            name = printer.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            name = name.strip()
            identity = f"{device['id']}\0{name}"
            option_id = hashlib.sha256(identity.encode()).hexdigest()
            if any(item["id"] == option_id for item in options):
                continue
            blockers = []
            if device.get("status") != "Connected":
                blockers.append("Connector is offline. Start it and refresh the printer list.")
            if name != settings.get("printer"):
                blockers.append("An administrator must select this printer in Shop settings.")
            if job.get("stock") not in settings.get("stocks", []):
                blockers.append(f"Shop settings do not list support for {job.get('stock')}.")
            if job.get("sides") not in settings.get("sides", []):
                blockers.append("Shop settings do not list support for the requested number of sides.")
            options.append({
                "id": option_id, "printer": name, "deviceId": device["id"],
                "hostname": device.get("inventory", {}).get("hostname", ""),
                "status": device.get("status", "Offline"),
                "blockers": blockers, "eligible": not blockers,
                "capabilitySource": "Administrator configuration; operator verification required",
            })
    return {"settingsVersion": settings["version"], "options": options,
            "message": "Select a discovered printer and verify compatibility for this job."
            if options else "No printers discovered. Check the existing connector and refresh; do not repeat pairing if it is already connected."}


def select_route(job, settings, devices, payload, actor, timestamp):
    """Return a validated route or a specific error; never mutate input records."""
    if payload.get("settingsVersion") != settings["version"]:
        raise ValueError("Shop settings changed. Refresh the printer list before selecting a route.")
    option = next((item for item in route_options(job, settings, devices)["options"]
                   if item["id"] == payload.get("routeId")), None)
    if not option:
        raise ValueError("Select a printer from the current discovered-printer list.")
    if option["blockers"]:
        raise ValueError(" ".join(option["blockers"]))
    note = payload.get("verificationNote")
    if payload.get("compatibilityConfirmed") is not True or not isinstance(note, str) or not 5 <= len(note.strip()) <= 1000:
        raise ValueError("Verify stock and side support from printer specifications or a validated shop setup, then record the evidence and confirm compatibility.")
    return {"settingsVersion": settings["version"], "printer": option["printer"],
            "deviceId": option["deviceId"], "routeId": option["id"],
            "compatibility": {"source": "operator-confirmed", "actor": actor,
                              "at": timestamp, "stock": job["stock"],
                              "sides": job["sides"], "evidence": note.strip()},
            "stagingVerified": False}
