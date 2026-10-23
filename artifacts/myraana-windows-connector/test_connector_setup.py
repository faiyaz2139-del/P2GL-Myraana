import importlib.util
import os
import pathlib
import socket
import threading
import unittest
import urllib.error
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "frontend/public/setup/myraana-connector.py"
if not SOURCE.exists():
    SOURCE = pathlib.Path(__file__).with_name("myraana-connector.py")
spec = importlib.util.spec_from_file_location("connector", SOURCE)
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

class ConnectorSetupTests(unittest.TestCase):
    def test_rejects_invalid_websites(self):
        for url in ("http://example.com", "https://", "https://u:p@example.com",
                    "https://example.com/path", "https://example.com?q=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                connector.website_url(url)

    def test_pairing_then_heartbeat_and_no_secret_in_state(self):
        state = {}
        credentials = {}
        stop = threading.Event()
        calls = []
        saved = []
        def secret(name, value=None):
            if value is not None:
                credentials[name] = value
            return credentials.get(name)
        def request(url, path, payload, credential=None):
            calls.append((url, path, payload, credential))
            if path.endswith("/claim"):
                return {"id": "pair-1"}
            if path.endswith("/poll"):
                return {"credential": "test-token"}
            stop.set()
            return {}
        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state", side_effect=lambda s: saved.append(dict(s))), \
             patch.object(connector, "secret", side_effect=secret), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(connector, "inventory", return_value={"printers": []}), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://preview.example.com", "ABCDEFGH", lambda m: None, stop)
        self.assertEqual([c[1] for c in calls], [
            "/connector-pairings/claim", "/connector-pairings/pair-1/poll",
            "/connector-devices/heartbeat"])
        self.assertEqual(calls[1][2]["claimSecret"], credentials["claimSecret"])
        self.assertEqual(calls[2][3], "test-token")
        for entry in saved:
            self.assertNotIn("credential", entry)
            self.assertNotIn("claimSecret", entry)
        self.assertEqual(state["websiteUrl"], "https://preview.example.com")

    def test_reconnect_without_pairing_code(self):
        stop = threading.Event()
        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://preview.example.com"}), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "inventory", return_value={}), \
             patch.object(connector, "request", side_effect=lambda *a, **kw: stop.set()) as request:
            connector.run("https://preview.example.com", report=lambda m: None, stop=stop)
        self.assertEqual(request.call_args.args[1], "/connector-devices/heartbeat")

    def test_host_change_never_reads_or_transmits_credentials(self):
        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://old.example.com"}), \
             patch.object(connector, "secret") as secret, \
             patch.object(connector, "request") as request:
            with self.assertRaises(ValueError):
                connector.run("https://new.example.com")
        secret.assert_not_called()
        request.assert_not_called()

    def test_scan_request_discovers_again_and_marks_it_done(self):
        stop = threading.Event()
        calls = []
        scans = {"n": 0}

        def inventory():
            scans["n"] += 1
            return {"hostname": "press", "printers": [
                {"name": "Fiery EX", "model": "EFI Fiery", "address": "10.0.0.8",
                 "protocol": "ipps", "isFiery": True},
            ], "fiery_rip": [], "hot_folders": []}

        def request(url, path, payload, credential=None):
            calls.append(payload)
            if len(calls) == 1:
                return {"ok": True, "status": "Connected", "scan": True}
            stop.set()
            return {"ok": True, "scan": False}

        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://preview.example.com"}), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "inventory", side_effect=inventory), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://preview.example.com", report=lambda message: None, stop=stop)
        self.assertEqual(scans["n"], 2)
        self.assertNotIn("scanned", calls[0])
        self.assertIs(calls[1]["scanned"], True)
        self.assertEqual(calls[1]["inventory"]["printers"][0]["name"], "Fiery EX")
        self.assertEqual(calls[1]["inventory"]["printers"][0]["protocol"], "ipps")
        self.assertIs(calls[1]["inventory"]["printers"][0]["isFiery"], True)

    def test_discovery_module_merges_mocked_bonjour_and_queues(self):
        discovery = connector.load_discovery()
        rows = discovery.discover(
            browse=lambda: [{
                "name": "Fiery EX", "model": "EFI Fiery", "address": "10.4.4.5",
                "protocol": "ipps", "service": "_ipps._tcp",
            }],
            list_queues=lambda: [{
                "name": "Press", "model": "Ricoh", "address": "10.4.4.4", "protocol": "socket",
            }],
            probe=lambda address: address == "10.4.4.4",
        )
        found = {row["name"]: row for row in rows}
        for row in found.values():
            self.assertEqual(set(row) >= {"name", "model", "address", "protocol", "isFiery"}, True)
        self.assertIs(found["Fiery EX"]["isFiery"], True)
        self.assertEqual(found["Fiery EX"]["protocol"], "ipps")
        self.assertIs(found["Press"]["isFiery"], True)
        self.assertEqual(found["Press"]["address"], "10.4.4.4")
        self.assertEqual(discovery.SERVICE_TYPES, (
            "_ipp._tcp", "_ipps._tcp", "_printer._tcp", "_pdl-datastream._tcp",
        ))

    def test_unbound_legacy_token_is_not_transmitted(self):
        with patch.object(connector, "load_state", return_value={}), \
             patch.object(connector, "secret", return_value="old-token"), \
             patch.object(connector, "request") as request:
            with self.assertRaisesRegex(ValueError, "migration"):
                connector.run("https://preview.example.com")
        request.assert_not_called()

    def test_heartbeat_401_forgets_the_saved_credential(self):
        state = {"websiteUrl": "https://myraana.com", "pairingId": "old-pair", "deviceId": "dev-1"}
        forgotten = []

        def request(url, path, payload, credential=None):
            raise urllib.error.HTTPError(url + path, 401, "unauthorized", {}, None)

        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "forget_secret", side_effect=forgotten.append), \
             patch.object(connector, "inventory", return_value={"printers": []}), \
             patch.object(connector, "request", side_effect=request):
            with self.assertRaises(ValueError) as caught:
                connector.run("https://myraana.com", report=lambda message: None, stop=threading.Event())
        self.assertEqual(str(caught.exception), connector.REPAIR_MESSAGE)
        self.assertEqual(forgotten, ["credential"])
        self.assertNotIn("pairingId", state)

    def test_poll_401_clears_pairing_and_asks_for_a_new_code(self):
        state = {"websiteUrl": "https://myraana.com", "pairingId": "pair-1", "deviceId": "dev-1"}
        forgotten = []

        def secret(name, value=None):
            return None if name == "credential" else "claim-secret"

        def request(url, path, payload, credential=None):
            self.assertTrue(path.endswith("/poll"))
            raise urllib.error.HTTPError(url + path, 401, "unauthorized", {}, None)

        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=secret), \
             patch.object(connector, "forget_secret", side_effect=forgotten.append), \
             patch.object(connector, "inventory", return_value={"printers": []}), \
             patch.object(connector, "request", side_effect=request):
            with self.assertRaises(ValueError) as caught:
                connector.run("https://myraana.com", report=lambda message: None, stop=threading.Event())
        self.assertEqual(str(caught.exception), connector.POLL_MISMATCH_MESSAGE)
        self.assertIn("new pairing code", str(caught.exception))
        self.assertNotIn("pairingId", state)
        self.assertEqual(forgotten, [])

    def test_typed_code_pairs_fresh_when_a_credential_exists(self):
        state = {"websiteUrl": "https://myraana.com", "pairingId": "old-pair", "deviceId": "dev-1"}
        forgotten = []
        calls = []
        stop = threading.Event()
        credentials = {"credential": "old-token", "claimSecret": "claim-secret"}

        def secret(name, value=None):
            if value is not None:
                credentials[name] = value
            return credentials.get(name)

        def forget(name):
            forgotten.append(name)
            credentials.pop(name, None)

        def request(url, path, payload, credential=None):
            calls.append((path, payload, credential))
            if path.endswith("/claim"):
                return {"id": "pair-new"}
            if path.endswith("/poll"):
                return {"credential": "new-token"}
            stop.set()
            return {}

        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=secret), \
             patch.object(connector, "forget_secret", side_effect=forget), \
             patch.object(connector, "inventory", return_value={"printers": []}), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://myraana.com", "ab-cd 2345", lambda message: None, stop=stop)
        self.assertEqual(forgotten, ["credential"])
        self.assertTrue(calls[0][0].endswith("/claim"))
        self.assertEqual(calls[0][1]["code"], "ABCD2345")
        self.assertIsNone(calls[0][2])
        self.assertEqual(calls[-1][0], "/connector-devices/heartbeat")
        self.assertEqual(calls[-1][2], "new-token")
        self.assertNotIn("old-token", [item[2] for item in calls])

    def test_http_errors_name_the_problem(self):
        cases = (
            (400, connector.CODE_FORMAT_MESSAGE),
            (409, connector.CODE_EXPIRED_MESSAGE),
            (404, connector.WEBSITE_MESSAGE),
        )
        for status, message in cases:
            state = {"websiteUrl": "https://myraana.com", "deviceId": "dev-1", "pairingId": "pair-1"}

            def request(url, path, payload, credential=None, status=status):
                raise urllib.error.HTTPError(url + path, status, "err", {}, None)

            with self.subTest(status=status), \
                 patch.object(connector, "load_state", return_value=state), \
                 patch.object(connector, "save_state"), \
                 patch.object(connector, "secret", side_effect=lambda name, value=None: None if name == "credential" else "claim"), \
                 patch.object(connector, "inventory", return_value={"printers": []}), \
                 patch.object(connector, "request", side_effect=request):
                with self.assertRaises(ValueError) as caught:
                    connector.run("https://myraana.com", "ABCDEFGH", report=lambda m: None, stop=threading.Event())
            self.assertEqual(str(caught.exception), message)
            if status == 409:
                self.assertNotIn("pairingId", state)

    def test_short_code_is_rejected_before_the_network(self):
        state = {"websiteUrl": "https://myraana.com", "deviceId": "dev-1"}
        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "forget_secret") as forget, \
             patch.object(connector, "request") as request:
            with self.assertRaises(ValueError) as caught:
                connector.run("https://myraana.com", "ab-cd", report=lambda m: None, stop=threading.Event())
        self.assertEqual(str(caught.exception), connector.CODE_FORMAT_MESSAGE)
        request.assert_not_called()
        forget.assert_not_called()

    def test_fiery_hold_loads_with_discovery(self):
        discovery, fiery = connector.exercise_bundled_modules()
        self.assertTrue(callable(discovery.discover))
        self.assertTrue(callable(fiery.submit_hold))
        self.assertIn("print", fiery.hold_payload("job_PRINT_READY.pdf", "London BC", "14pt matte"))
        self.assertIs(fiery.hold_payload("job_PRINT_READY.pdf", "London BC", "14pt matte")["print"], False)

    def test_frozen_lookup_checks_the_bundle_then_the_exe_then_the_script(self):
        with patch.object(connector.sys, "frozen", True, create=True), \
             patch.object(connector.sys, "_MEIPASS", os.path.join("bundle"), create=True), \
             patch.object(connector.sys, "executable", os.path.join("app", "MyraanaConnector.exe")):
            found = connector.module_candidates("fiery_hold.py")
        self.assertEqual(found[0], os.path.join("bundle", "fiery_hold.py"))
        self.assertEqual(found[1], os.path.join("app", "fiery_hold.py"))
        self.assertTrue(found[2].endswith(os.path.join("setup", "fiery_hold.py")) or found[2].endswith("fiery_hold.py"))

    def test_windows_build_bundles_fiery_hold_and_sources_match(self):
        frontend = pathlib.Path(__file__).resolve().parents[2] / "frontend/public/setup/myraana-connector.py"
        mirror = pathlib.Path(__file__).with_name("myraana-connector.py")
        if frontend.exists() and frontend.resolve() != mirror.resolve():
            self.assertEqual(frontend.read_bytes(), mirror.read_bytes())
        script = frontend.with_name("build-myraana-connector.ps1") if frontend.exists() else mirror.with_name("build-myraana-connector.ps1")
        text = script.read_text(encoding="utf-8")
        self.assertIn('printer_discovery.py', text)
        self.assertIn('fiery_hold.py', text)
        mirror_script = pathlib.Path(__file__).with_name("build-myraana-connector.ps1")
        if script.resolve() != mirror_script.resolve():
            self.assertEqual(script.read_text(encoding="utf-8"), mirror_script.read_text(encoding="utf-8"))
        source = frontend.read_text(encoding="utf-8") if frontend.exists() else mirror.read_text(encoding="utf-8")
        self.assertNotIn('show="*"', source)
        self.assertNotIn("Myraana Connector — Preview", source)
        self.assertNotIn("Myraana preview website", source)
        self.assertIn("text=HOLD_FOOTER", source)
        self.assertIn("on your Fiery HOLD queue. It never prints or releases jobs.", source)
        self.assertIn("https://myraana.com", source)
        self.assertIn("exercise_bundled_modules()", source)
        self.assertIn("exercise_tray_support()", source)
        self.assertIn("pystray._win32", text)
        self.assertEqual(connector.TRAY_MENU, ("Open", "Scan again", "Start with Windows", "Quit"))
        self.assertIn("handle_window_close", source)
        self.assertIn("should_reconnect", source)
        self.assertIn('"capabilities": reported_capabilities()', source)
        self.assertEqual(connector.reported_capabilities(), ["fiery_hold"])
        fiery_frontend = frontend.with_name("fiery_hold.py")
        fiery_mirror = pathlib.Path(__file__).with_name("fiery_hold.py")
        if fiery_frontend.exists() and fiery_frontend.resolve() != fiery_mirror.resolve():
            self.assertEqual(fiery_frontend.read_bytes(), fiery_mirror.read_bytes())
        self.assertIn("load_fiery_credentials", source)
        self.assertIn("job_name=item.get(\"jobName\")", source)
        self.assertNotIn("opener=opener or fiery.fiery_opener", source)

    def test_closing_the_window_keeps_the_heartbeat(self):
        class Root:
            def __init__(self):
                self.hidden = False
                self.destroyed = False
            def withdraw(self):
                self.hidden = True
            def destroy(self):
                self.destroyed = True

        root = Root()
        stop = threading.Event()
        self.assertEqual(connector.handle_window_close(root, stop), "hide")
        self.assertTrue(root.hidden)
        self.assertFalse(root.destroyed)
        self.assertFalse(stop.is_set())
        connector.quit_connector(root, stop, icon=None)
        self.assertTrue(stop.is_set())
        self.assertTrue(root.destroyed)

        root = Root()
        stop = threading.Event()
        self.assertEqual(connector.handle_window_close(root, stop, self_test=True), "quit")
        self.assertTrue(stop.is_set())
        self.assertTrue(root.destroyed)
        self.assertFalse(root.hidden)

    def test_start_with_windows_uses_the_current_user_run_key(self):
        class MemoryRegistry:
            HKEY_CURRENT_USER = "HKCU"
            REG_SZ = 1
            def __init__(self):
                self.values = {}
                self.path = None
            def CreateKey(self, root, path):
                self.path = path
                return self
            def OpenKey(self, root, path):
                self.path = path
                return self
            def SetValueEx(self, key, name, reserved, typ, value):
                self.values[name] = value
            def QueryValueEx(self, key, name):
                if name not in self.values:
                    raise OSError(name)
                return self.values[name], self.REG_SZ
            def DeleteValue(self, key, name):
                try:
                    del self.values[name]
                except KeyError as error:
                    raise OSError(name) from error
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        registry = MemoryRegistry()
        self.assertTrue(connector.set_startup(True, registry=registry))
        self.assertEqual(registry.path, connector.RUN_KEY)
        self.assertIn("MyraanaConnector", registry.values)
        self.assertTrue(connector.startup_enabled(registry=registry))
        self.assertTrue(connector.set_startup(False, registry=registry))
        self.assertFalse(connector.startup_enabled(registry=registry))
        state = {"websiteUrl": "https://myraana.com"}
        with patch.object(connector, "save_state"):
            self.assertTrue(connector.ensure_default_startup(state, registry=registry))
        self.assertIs(state["startWithWindows"], True)
        self.assertIn("MyraanaConnector", registry.values)
        state["startWithWindows"] = False
        registry.values.clear()
        with patch.object(connector, "save_state"):
            self.assertFalse(connector.ensure_default_startup(state, registry=registry))
        self.assertNotIn("MyraanaConnector", registry.values)

    def test_launch_reconnects_when_already_paired(self):
        self.assertTrue(connector.should_reconnect({"websiteUrl": "https://myraana.com"}, "token", ""))
        self.assertFalse(connector.should_reconnect({"websiteUrl": "https://myraana.com"}, "token", "ABCDEFGH"))
        self.assertFalse(connector.should_reconnect({"websiteUrl": "https://myraana.com"}, None, ""))
        self.assertFalse(connector.should_reconnect({}, "token", ""))

    def test_scan_again_marks_the_next_heartbeat(self):
        stop = threading.Event()
        scan = threading.Event()
        scan.set()
        calls = []

        def request(url, path, payload, credential=None):
            calls.append(payload)
            stop.set()
            return {"ok": True, "scan": False}

        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://myraana.com"}), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "inventory", return_value={"printers": [{"name": "Press"}]}), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(connector, "ensure_default_startup", return_value=True), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://myraana.com", report=lambda message: None, stop=stop, scan_now=scan)
        self.assertIs(calls[0]["scanned"], True)

    def test_tray_menu_offers_open_scan_startup_and_quit(self):
        class Item:
            def __init__(self, text, action, default=False, checked=None):
                self.text = text
                self.default = default
                self.checked = checked

        class Menu:
            def __init__(self, *items):
                self.items = items

        class FakePystray:
            pass
        FakePystray.MenuItem = Item
        FakePystray.Menu = Menu

        menu = connector.build_tray_menu(FakePystray, {
            "open": lambda *args: None,
            "scan": lambda *args: None,
            "toggle_startup": lambda *args: None,
            "quit": lambda *args: None,
            "startup_checked": lambda: True,
        })
        self.assertEqual([item.text for item in menu.items], ["Open", "Scan again", "Start with Windows", "Quit"])
        self.assertTrue(menu.items[0].default)
        self.assertTrue(menu.items[2].checked(None))

    def test_lpr_hold_queue_names_the_job_and_refuses_print(self):
        fiery = connector.load_fiery_hold()
        pdf = b"%PDF-1.4 p2gl-hold"
        port, received, thread = _serve_lpr((0, 0, 0, 0, 0))

        def send(address, data, job_name, filename, timeout, queue="hold"):
            return fiery.send_lpr(address, data, job_name, filename, timeout, queue, port)

        outcome = fiery.submit_hold(
            "127.0.0.1",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            pdf,
            job_name="RA",
            job_id="job-42",
            timeout=3,
            lpr=send,
            ipp=_transport_down,
            smb=_transport_down,
        )
        thread.join(5)
        self.assertEqual(outcome["ok"], True)
        self.assertEqual(outcome["method"], "lpr")
        self.assertIs(outcome["printed"], False)
        self.assertIs(outcome["held"], True)
        self.assertEqual(received["commands"][0], b"\x02hold")
        self.assertNotIn(b"\x02print", b" ".join(received["commands"]))
        self.assertNotIn(b"\x02direct", b" ".join(received["commands"]))
        self.assertIn(b"JRA job-42\n", received["control"])
        self.assertEqual(received["data"], pdf)
        self.assertEqual(received["data_zero"], b"\x00")
        for queue in ("print", "direct"):
            refused = fiery.submit_hold(
                "192.168.0.200", "card_PRINT_READY.pdf", "London BC", "Matte", pdf,
                queue=queue, lpr=_transport_down, ipp=_transport_down, smb=_transport_down, api=_transport_down,
            )
            self.assertIs(refused["ok"], False)
            self.assertIs(refused["printed"], False)
            self.assertIn("Refusing to print", refused["error"])
        self.assertIsNone(fiery.fiery_credentials({"apiKey": "k", "username": "u"}))
        self.assertEqual(
            fiery.smb_hold_unc("192.168.0.200", "card_PRINT_READY.pdf", allowed=["192.168.0.200"]),
            "\\\\192.168.0.200\\hold\\card_PRINT_READY.pdf",
        )
        for bad in (r"\\8.8.8.8\share", r"\\192.168.0.200\print", r"\\192.168.0.200\hold\extra", "8.8.8.8"):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                fiery.smb_hold_unc(bad, "card_PRINT_READY.pdf", allowed=["192.168.0.200"])

    def test_server_address_is_refused_unless_this_computer_found_that_fiery(self):
        printers = [
            {"name": "Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)", "address": "192.168.0.200", "isFiery": True},
            {"name": "Color Printer", "address": "192.168.0.200", "isFiery": True},
        ]
        fiery = connector.load_fiery_hold()
        self.assertEqual(fiery.discovered_fiery_ips(printers), ["192.168.0.200"])
        downloaded = []

        def request_bytes(*_args, **_kwargs):
            downloaded.append("pdf")
            raise AssertionError("pdf")

        result = {"holds": [{
            "jobId": "job-42",
            "address": r"\\8.8.8.8\share",
            "hotFolder": r"\\attacker\share",
            "filename": "card_PRINT_READY.pdf",
        }]}
        with patch.object(connector, "request_bytes", side_effect=request_bytes), \
             patch.object(connector, "load_fiery_credentials", return_value={}):
            reports = connector.perform_holds("https://preview.example.com", "token", result, printers=printers)
        self.assertEqual(downloaded, [])
        self.assertEqual(len(reports), 1)
        self.assertIs(reports[0]["ok"], False)
        self.assertIs(reports[0]["held"], False)
        self.assertIs(reports[0]["printed"], False)
        self.assertIn("did not discover", reports[0]["error"])
        self.assertIn("Nothing was printed", reports[0]["error"])

        submitted = {}

        def submit_hold(**kwargs):
            submitted.update(kwargs)
            return {"ok": True, "held": True, "printed": False, "method": "lpr", "error": ""}

        fiery.submit_hold = submit_hold
        matched = {"holds": [{
            "jobId": "job-42",
            "address": r"\\192.168.0.200\hold",
            "hotFolder": r"\\attacker\share",
            "filename": "card_PRINT_READY.pdf",
            "jobName": "RA",
        }]}
        with patch.object(connector, "request_bytes", return_value=b"%PDF"), \
             patch.object(connector, "load_fiery_hold", return_value=fiery), \
             patch.object(connector, "load_fiery_credentials", return_value={}):
            accepted = connector.perform_holds("https://preview.example.com", "token", matched, printers=printers)
        self.assertEqual(accepted[0]["method"], "lpr")
        self.assertEqual(submitted["address"], "192.168.0.200")
        self.assertEqual(submitted["printers"], printers)
        self.assertNotIn("hot_folder", submitted)
        self.assertNotIn("operator_folder", submitted)


def _transport_down(*_args, **_kwargs):
    raise RuntimeError("down")


def _serve_lpr(acks):
    received = {}
    ready = threading.Event()
    port = []

    def run():
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        port.append(server.getsockname()[1])
        ready.set()
        try:
            conn, _addr = server.accept()
        except socket.timeout:
            server.close()
            return
        conn.settimeout(5)
        buffer = bytearray()

        def read(count):
            while len(buffer) < count:
                chunk = conn.recv(max(1, count - len(buffer)))
                if not chunk:
                    raise RuntimeError("closed")
                buffer.extend(chunk)
            out = bytes(buffer[:count])
            del buffer[:count]
            return out

        def read_line():
            while b"\n" not in buffer:
                chunk = conn.recv(4096)
                if not chunk:
                    raise RuntimeError("closed")
                buffer.extend(chunk)
            index = buffer.index(b"\n")
            line = bytes(buffer[:index])
            del buffer[: index + 1]
            return line

        try:
            commands = []
            for step, take_body in ((0, False), (1, True), (3, True)):
                line = read_line()
                commands.append(line)
                conn.sendall(bytes([acks[step]]))
                if acks[step] != 0:
                    break
                if not take_body:
                    continue
                count = int(line[1:].split(b" ", 1)[0])
                body = read(count)
                marker = read(1)
                if step == 1:
                    received["control"] = body
                    conn.sendall(bytes([acks[2]]))
                    if acks[2] != 0:
                        break
                else:
                    received["data"] = body
                    received["data_zero"] = marker
                    conn.sendall(bytes([acks[4]]))
            received["commands"] = commands
        finally:
            conn.close()
            server.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not ready.wait(5):
        raise RuntimeError("LPR test server did not start")
    return port[0], received, thread


if __name__ == "__main__":
    unittest.main()
