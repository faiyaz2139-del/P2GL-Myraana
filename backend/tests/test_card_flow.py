"""Business-card flow: defaults, queue pages, and a Fiery hold that never prints."""
import socket
import threading
from pathlib import Path

from p2g.card_flow import (
    AUTO_ACTOR,
    RECIPE_STEPS,
    apply_card_defaults,
    apply_known_stock,
    auto_bleed,
    duplo_line,
    keep_production_route,
    known_finish,
    manual_press_message,
    mark_sent_to_fiery,
    operator_touches,
    print_order,
    page_jobs,
    queue_bucket,
    queue_page_query,
    record_successful_hold,
    shop_cardstock,
    specs_known,
)
from p2g.fiery_hold import (
    assert_pinned_peer,
    build_ipp_print_job,
    discovered_fiery_ips,
    fiery_credentials,
    hold_ipp_paths,
    hold_payload,
    hold_queue_name,
    hold_target,
    interpret_hold_report,
    ipp_confirmed,
    job_label,
    private_ipv4,
    send_lpr,
    send_smb,
    smb_hold_unc,
    submit_hold,
)
from p2g.london_card import STOP_PRESET, london_business_card_recipe


ROOT = Path(__file__).resolve().parents[2]


def _task(status="Pending", title="Step"):
    return {"status": status, "title": title}


def _job(**extra):
    tasks = [_task("Completed" if index == 0 else "Pending") for index in range(16)]
    job = {
        "id": "job-1",
        "state": "active",
        "tasks": tasks,
        "files": [],
        "updated": "2026-10-22T00:00:00",
        "spec": {"width": 3.5, "height": 2, "stock": "14pt matte"},
        "quantity": 100,
        "stock": "14pt matte",
        "finish": "Matte",
    }
    job.update(extra)
    return job


def test_card_defaults_use_the_shop_recipe_and_keep_an_order():
    settings = {
        "stocks": ["100lb Gloss Text", "14pt matte", "Gloss Cover"],
        "jobDefaults": {"product": "business-card", "quantity": 250, "finish": "Gloss"},
    }
    filled = apply_card_defaults({"product": "business-card"}, settings)
    assert (filled["width"], filled["height"], filled["unit"]) == (3.5, 2.0, "in")
    assert filled["quantity"] == 250
    assert filled["stock"] == "14pt matte"
    assert filled["finish"] == "Glossy"
    assert shop_cardstock(settings) == "14pt matte"
    explicit = apply_card_defaults(
        {"product": "business-card", "width": 2, "height": 3.5, "quantity": 40, "stock": "16pt", "finish": "Matte"},
        settings,
    )
    assert explicit["width"] == 2 and explicit["height"] == 3.5
    assert explicit["quantity"] == 40 and explicit["stock"] == "16pt" and explicit["finish"] == "Matte"
    assert known_finish("Soft touch") is None
    assert known_finish("gloss") == "Glossy"


def test_missing_bleed_still_pauses_and_a_real_bleed_is_automatic():
    paused = _job(inspection={"bleed": "missing"})
    assert auto_bleed(paused, "orig", "2026-10-22T00:00:00") is None
    ready = _job(inspection={"bleed": "present"})
    confirmation = auto_bleed(ready, "orig", "2026-10-22T00:00:00")
    assert confirmation["actor_name"] == AUTO_ACTOR
    assert confirmation["decision"] == "bleed-present"
    assert specs_known(_job()) is True
    assert specs_known(_job(spec={})) is False


def test_queue_groups_and_pages_two_thousand_jobs():
    waiting = _job(id="wait")
    needs = _job(id="proof", files=[{"stage": "ORIGINAL"}])
    needs["tasks"][7]["status"] = "Waiting for approval"
    for index in range(1, 7):
        needs["tasks"][index]["status"] = "Completed"
    held = _job(id="held", files=[{"stage": "ORIGINAL"}], fieryHold={"status": "held"}, route={"mode": "production"})
    for index in range(1, 10):
        held["tasks"][index]["status"] = "Completed"
    printing = _job(id="press", files=[{"stage": "ORIGINAL"}])
    for index in range(1, 12):
        printing["tasks"][index]["status"] = "Completed"
    done = _job(id="done", state="complete")
    stopped = _job(id="stop", files=[{"stage": "ORIGINAL"}], productionStop="STOP")
    stopped["tasks"][2]["status"] = "Needs attention"
    assert queue_bucket(waiting) == "waiting-customer"
    assert queue_bucket(needs) == "needs-you"
    assert queue_bucket(stopped) == "needs-you"
    assert queue_bucket(held) == "ready-to-print"
    assert queue_bucket(printing) == "printing-cutting"
    assert queue_bucket(done) == "done"
    rows = []
    for index in range(2000):
        rows.append(_job(id=f"job-{index:04d}", updated=f"2026-10-22T00:{index // 60:02d}:{index % 60:02d}", state="complete"))
    rows.append(needs)
    page = page_jobs(rows, "done", limit=50)
    assert page["counts"]["done"] == 2000
    assert page["counts"]["needs-you"] == 1
    assert len(page["jobs"]) == 50
    assert page["nextCursor"]
    second = page_jobs(rows, "done", cursor=page["nextCursor"], limit=50)
    assert len(second["jobs"]) == 50
    assert {item["id"] for item in page["jobs"]}.isdisjoint({item["id"] for item in second["jobs"]})
    query, ordering = queue_page_query("ready-to-print")
    assert query["queue"] == "ready-to-print"
    assert ordering[0] == ("updated", -1)


def test_print_order_stays_on_production_and_a_proof_switch_keeps_the_proof():
    recipe = london_business_card_recipe()
    job = _job(
        recipe=recipe,
        product="business-card",
        spec={"product": "business-card", "width": 3.5, "height": 2, "stock": "14pt matte"},
        stock="14pt matte",
        finish="Matte",
        generation=3,
        approval={"sha": "proof-sha", "fileId": "file-1"},
        files=[{"id": "file-1", "stage": "PRINT_READY", "sha": "proof-sha", "name": "RA_PRINT_READY.pdf"}],
        route={"mode": "proof-only", "printer": None},
    )
    for index in range(8):
        job["tasks"][index]["status"] = "Completed"
        job["tasks"][index]["result"] = f"done-{index}"
    job["tasks"][8]["status"] = "Completed"
    job["tasks"][8]["result"] = "Proof-only route selected. No press is assigned and nothing will print."
    job["tasks"][9]["status"] = "Waiting for operator"
    job["tasks"][9]["result"] = "Proof only: nothing is sent to a press."
    assert print_order(job) is True
    assert print_order(_job(spec={"product": "flyer"}, product="flyer")) is True
    keep_production_route(job, {"version": 4, "stocks": ["14pt matte"], "printer": "", "discoveredPrinters": []})
    assert job["route"]["mode"] == "production"
    assert job["route"]["manual"] is True
    assert job["approval"] == {"sha": "proof-sha", "fileId": "file-1"}
    assert job["generation"] == 3
    assert job["files"][0]["sha"] == "proof-sha"
    for index in range(8):
        assert job["tasks"][index]["status"] == "Completed"
        assert job["tasks"][index]["result"] == f"done-{index}"
    assert job["tasks"][9]["result"] == manual_press_message(job)
    assert job["tasks"][9]["result"] == (
        "Print it yourself: download the PRINT_READY PDF, import it to Fiery, "
        "hold it, impose with London BC, set 14pt matte"
    )
    assert "Proof only" not in job["tasks"][9]["result"]
    paired = {
        "version": 4,
        "discoveredPrinters": [
            {"name": "Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)", "address": "192.168.0.200", "isFiery": True},
            {"name": "Color Printer", "address": "192.168.0.200", "isFiery": True},
        ],
    }
    keep_production_route(job, paired)
    assert job["route"]["mode"] == "production"
    assert job["route"]["manual"] is False
    assert job["route"]["printer"] == "Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)"
    assert "Fiery HOLD" in job["tasks"][9]["result"]
    assert job["approval"]["sha"] == "proof-sha"
    keep_production_route(job, {"version": 4, "printer": "", "discoveredPrinters": []})
    assert mark_sent_to_fiery(job) == "Cut on Duplo DC-618, job 2"
    assert duplo_line(job) == "Cut on Duplo DC-618, job 2"
    assert queue_bucket(job) == "printing-cutting"
    assert job["tasks"][12]["status"] == "Waiting for operator"
    assert job["tasks"][9]["status"] == "Completed"
    assert job["approval"]["sha"] == "proof-sha"
    assert job["generation"] == 3
    flyer = _job(spec={"product": "flyer"}, product="flyer", stock="100lb Gloss Text")
    assert "impose this flyer" in manual_press_message(flyer)
    assert "100lb Gloss Text" in manual_press_message(flyer)


def test_known_finish_answers_stock_and_a_hold_leaves_duplo_without_printing():
    recipe = london_business_card_recipe()
    job = _job(recipe=recipe, finish="Matte", cardRoute={"outputName": "card_PRINT_READY.pdf"})
    outcome = record_successful_hold(job, ["14pt matte", "Gloss Cover"])
    assert outcome["stop"] is None
    statuses = {step["id"]: step["status"] for step in job["productionChecklist"]}
    assert statuses["import"] == "done"
    assert statuses["save"] == "done"
    assert statuses["stock"] == "done"
    assert statuses["cutter"] == "pending"
    assert job["productionChecklist"][-1]["id"] == "cutter"
    broken = _job(recipe=london_business_card_recipe(), finish="Matte")
    broken["recipe"]["production"]["imposition"]["name"] = "Other"
    stopped = record_successful_hold(broken, ["14pt matte"])
    assert stopped["stop"] == STOP_PRESET
    stock_job = _job(recipe=recipe, finish="Glossy", productionChecklist=[{"id": "stock", "status": "pending"}])
    answered = apply_known_stock(stock_job, ["Gloss Cover"])
    assert answered["stop"] is None
    assert stock_job["productionChecklist"][0]["status"] == "done"


def _down(*_args, **_kwargs):
    raise RuntimeError("down")


def _serve_lpr(acks):
    """A one-connection RFC 1179 server. acks are the five acknowledgement bytes."""
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
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
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
                    received["control_zero"] = marker
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
    assert ready.wait(5)
    return port[0], received, thread


def _lpr_on(port):
    def send(address, pdf, job_name, filename, timeout, queue="hold"):
        return send_lpr(address, pdf, job_name, filename, timeout, queue, port)

    return send


def test_print_and_direct_queues_are_refused_before_any_connection():
    calls = []

    def connect(address, pdf, job_name, filename, timeout, queue="hold"):
        calls.append(queue)
        raise AssertionError(queue)

    for queue in ("print", "direct", "PRINT", "Direct", "hold\nprint", "print_hold"):
        outcome = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF",
            queue=queue,
            lpr=connect,
            ipp=connect,
            smb=connect,
            api=connect,
        )
        assert outcome["ok"] is False
        assert outcome["held"] is False
        assert outcome["printed"] is False
        assert "Refusing to print" in outcome["error"]
        assert "Nothing was printed" in outcome["error"]
    assert calls == []
    for queue in ("print", "direct"):
        try:
            hold_queue_name(queue)
        except RuntimeError as error:
            assert "Only the hold queue" in str(error)
        else:
            raise AssertionError(queue)
    assert hold_ipp_paths() == ("/ipp/hold", "/hold")
    assert smb_hold_unc(
        "192.168.0.200", "card_PRINT_READY.pdf", allowed=["192.168.0.200"]
    ) == "\\\\192.168.0.200\\hold\\card_PRINT_READY.pdf"
    try:
        smb_hold_unc("192.168.0.200", "card_PRINT_READY.pdf", queue="direct", allowed=["192.168.0.200"])
    except RuntimeError as error:
        assert "Refusing to print" in str(error)
    else:
        raise AssertionError("direct share")


def test_lpr_hold_queue_confirms_the_job_name_and_a_refused_ack_does_not():
    pdf = b"%PDF-1.4 hold-me"
    port, received, thread = _serve_lpr((0, 0, 0, 0, 0))
    used = {"ipp": 0}

    def ipp(*_args, **_kwargs):
        used["ipp"] += 1
        raise RuntimeError("ipp should not run")

    outcome = submit_hold(
        "127.0.0.1",
        "card_PRINT_READY.pdf",
        "London BC",
        "Matte",
        pdf,
        job_name="RA",
        job_id="job-42",
        timeout=3,
        lpr=_lpr_on(port),
        ipp=ipp,
        smb=_down,
    )
    thread.join(5)
    assert outcome == {"ok": True, "held": True, "printed": False, "method": "lpr", "error": ""}
    assert used["ipp"] == 0
    assert received["commands"][0] == b"\x02hold"
    assert all(not command.startswith(b"\x02print") and not command.startswith(b"\x02direct") for command in received["commands"])
    control = received["control"].decode("utf-8")
    assert "JRA job-42\n" in control
    assert "NRA job-42.pdf\n" in control
    assert "\nldfA" in control or control.startswith("ldfA") or "\nl" in control
    assert received["control_zero"] == b"\x00"
    assert received["data"] == pdf
    assert received["data_zero"] == b"\x00"
    assert job_label("RA", "job-42", "card_PRINT_READY.pdf") == "RA job-42"

    port, refused, thread = _serve_lpr((0, 0, 0, 0, 1))
    failed = submit_hold(
        "127.0.0.1",
        "card_PRINT_READY.pdf",
        "London BC",
        "Matte",
        pdf,
        job_name="RA",
        job_id="job-42",
        timeout=3,
        lpr=_lpr_on(port),
        ipp=_down,
        smb=_down,
    )
    thread.join(5)
    assert failed["ok"] is False
    assert failed["held"] is False
    assert failed["printed"] is False
    assert "Nothing was printed" in failed["error"]
    assert interpret_hold_report(failed)["ok"] is False
    assert refused.get("data") == pdf


def test_ipp_and_smb_stay_on_hold_and_api_waits_for_a_pinned_login():
    body = build_ipp_print_job("ipp://192.168.0.200/ipp/hold", "RA job-42", b"%PDF")
    assert b"ipp://192.168.0.200/ipp/hold" in body
    assert b"/print" not in body
    assert b"/direct" not in body
    assert b"RA job-42" in body
    assert b"job-hold-until" in body
    assert b"indefinite" in body
    assert body.endswith(b"%PDF")
    assert ipp_confirmed(200, bytes([1, 1, 0, 0, 0, 0, 0, 1])) is True
    assert ipp_confirmed(200, bytes([1, 1, 0x04, 0x00, 0, 0, 0, 1])) is False
    assert ipp_confirmed(500, bytes([1, 1, 0, 0, 0, 0, 0, 1])) is False
    assert ipp_confirmed(200, b"") is False
    try:
        build_ipp_print_job("ipp://192.168.0.200/ipp/print", "RA", b"%PDF")
    except RuntimeError as error:
        assert "Refusing to print" in str(error)
    else:
        raise AssertionError("print uri")

    seen = {}

    def copy(path, data):
        seen["path"] = path
        seen["data"] = data

    saved = send_smb(
        "192.168.0.200", b"%PDF-smb", "card_PRINT_READY.pdf", 3, copy=copy, allowed=["192.168.0.200"]
    )
    assert saved["method"] == "smb" and saved["printed"] is False
    assert seen == {"path": "\\\\192.168.0.200\\hold\\card_PRINT_READY.pdf", "data": b"%PDF-smb"}

    calls = []

    def api(address, pdf, payload, credentials, timeout):
        calls.append((address, credentials["username"], payload["queue"], payload["print"], pdf))
        return {"ok": True, "held": True, "printed": False, "method": "api", "error": ""}

    missing = submit_hold(
        "192.168.0.200",
        "card_PRINT_READY.pdf",
        "London BC",
        "Matte",
        b"%PDF",
        lpr=_down,
        ipp=_down,
        smb=_down,
        api=api,
        opener=lambda *args: calls.append("opener"),
    )
    assert missing["ok"] is False and calls == []
    assert fiery_credentials({"apiKey": "key", "username": "user"}) is None
    ready = submit_hold(
        "192.168.0.200",
        "card_PRINT_READY.pdf",
        "London BC",
        "Matte",
        b"%PDF",
        lpr=_down,
        ipp=_down,
        smb=_down,
        api=api,
        credentials={"apiKey": "key", "username": "admin", "password": "secret"},
    )
    assert ready["ok"] is True and ready["method"] == "api" and ready["printed"] is False
    assert calls == [("192.168.0.200", "admin", "hold", False, b"%PDF")]
    assert_pinned_peer("192.168.0.200", "192.168.0.200")
    try:
        assert_pinned_peer("192.168.0.200", "10.0.0.8")
    except RuntimeError as error:
        assert "not pinned" in str(error)
    else:
        raise AssertionError("pin")


def _shop_fiery(address="192.168.0.200", name="Xerox EX-Li PX300 Server 1.0 US(6B:72:F0)"):
    return {"name": name, "address": address, "isFiery": True}


def test_hold_uses_only_a_discovered_private_fiery():
    printers = [
        _shop_fiery(),
        {"name": "Color Printer", "address": "192.168.0.200", "isFiery": True},
        {"name": "Roland DG BY-20", "address": "192.168.0.3", "isFiery": False},
    ]
    assert discovered_fiery_ips(printers) == ["192.168.0.200"]
    assert private_ipv4("10.1.2.3") == "10.1.2.3"
    assert private_ipv4("10.255.255.255") == "10.255.255.255"
    assert private_ipv4("172.16.0.1") == "172.16.0.1"
    assert private_ipv4("172.31.255.254") == "172.31.255.254"
    assert private_ipv4("192.168.0.200") == "192.168.0.200"
    for refused in (
        "8.8.8.8", "172.32.0.1", "172.15.5.5", "192.168.000.200", "127.0.0.1",
        "169.254.1.1", "fiery.local", "192.168.0.200.1", "", "0.0.0.0",
    ):
        assert private_ipv4(refused) is None
    assert discovered_fiery_ips([{"isFiery": True, "address": "8.8.8.8"}]) == []
    assert hold_target("", printers) == "192.168.0.200"
    assert hold_target("192.168.0.200", printers) == "192.168.0.200"
    assert hold_target(r"\\192.168.0.200\hold", printers) == "192.168.0.200"
    assert hold_target("//192.168.0.200/hold", printers) == "192.168.0.200"

    calls = []

    def transport(*_args, **_kwargs):
        calls.append("network")
        raise AssertionError("network")

    for supplied in (
        "8.8.8.8",
        "evil.example",
        r"\\8.8.8.8\share",
        r"\\192.168.0.200\print",
        r"\\192.168.0.200\hold\extra",
        r"\\192.168.0.200\hold\card.pdf",
        "172.32.0.1",
        "192.168.000.200",
        "10.1.2.3",
        "192.168.0.3",
    ):
        outcome = submit_hold(
            supplied,
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF",
            printers=printers,
            lpr=transport,
            ipp=transport,
            smb=transport,
            api=transport,
            hot_folder=r"\\attacker\share",
        )
        assert outcome["ok"] is False and outcome["held"] is False and outcome["printed"] is False
        assert "Nothing was printed" in outcome["error"]
        assert "did not discover" in outcome["error"]
    assert calls == []
    try:
        hold_target("", [{"isFiery": True, "address": "8.8.8.8"}])
    except RuntimeError as error:
        assert "No Fiery was found" in str(error)
    else:
        raise AssertionError("public fiery")
    two = [_shop_fiery("10.0.0.8", "EX-Li"), _shop_fiery("10.1.0.8", "EX-P")]
    try:
        hold_target("", two)
    except RuntimeError as error:
        assert "did not discover" in str(error)
    else:
        raise AssertionError("two fieries")

    for bad_unc in (
        r"\\192.168.0.200\hold",
        r"\\192.168.0.200\print",
        r"\\8.8.8.8\share",
        r"\\192.168.0.200\hold\extra",
        "8.8.8.8",
        "fiery.local",
    ):
        try:
            smb_hold_unc(bad_unc, "card_PRINT_READY.pdf", allowed=["192.168.0.200"])
        except RuntimeError as error:
            assert "Nothing was printed" in str(error)
        else:
            raise AssertionError(bad_unc)
    try:
        send_smb("192.168.0.200", b"%PDF", "card_PRINT_READY.pdf", 3, copy=transport)
    except RuntimeError as error:
        assert "did not discover" in str(error)
    else:
        raise AssertionError("smb without allow list")
    assert calls == []

    folder = ROOT / "backend" / "tests" / "_hold_tmp"
    folder.mkdir(exist_ok=True)
    try:
        ignored = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-hold",
            lpr=_down,
            ipp=_down,
            smb=_down,
            hot_folder=str(folder),
        )
        assert ignored["ok"] is False
        assert ignored["held"] is False
        assert not (folder / "Hold").exists()
        local = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-hold",
            lpr=_down,
            ipp=_down,
            smb=_down,
            operator_folder=str(folder),
        )
        assert local == {"ok": True, "held": True, "printed": False, "method": "hot-folder", "error": ""}
        assert (folder / "Hold" / "card_PRINT_READY.pdf").read_bytes() == b"%PDF-hold"
        remote = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-hold",
            lpr=_down,
            ipp=_down,
            smb=_down,
            operator_folder=r"\\192.168.0.200\hold",
        )
        assert remote["ok"] is False
        assert "folder on this computer" in remote["error"]
    finally:
        target = folder / "Hold" / "card_PRINT_READY.pdf"
        if target.exists():
            target.unlink()
        hold_dir = folder / "Hold"
        if hold_dir.exists():
            hold_dir.rmdir()
        if folder.exists():
            folder.rmdir()


def test_unconfirmed_hold_is_not_delivered_and_a_folder_still_requires_the_bytes():
    assert interpret_hold_report({"ok": True, "held": True, "printed": True})["ok"] is False
    assert interpret_hold_report({"ok": True, "held": True, "method": "lpr"})["method"] == "lpr"
    assert interpret_hold_report({"ok": True, "held": True})["ok"] is False
    assert interpret_hold_report({"ok": True, "held": True, "method": "print"})["ok"] is False
    assert hold_payload("x.pdf", "London BC", "Matte")["release"] is False
    assert hold_payload("x.pdf", "London BC", "Matte")["queue"] == "hold"
    folder = ROOT / "backend" / "tests" / "_hold_tmp"
    folder.mkdir(exist_ok=True)
    try:
        refused = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-server",
            lpr=_down,
            ipp=_down,
            smb=_down,
            hot_folder=str(folder),
        )
        assert refused["ok"] is False and refused["held"] is False
        assert not (folder / "Hold").exists()
        saved = submit_hold(
            "192.168.0.200",
            "card_PRINT_READY.pdf",
            "London BC",
            "Matte",
            b"%PDF-hold",
            lpr=_down,
            ipp=_down,
            smb=_down,
            operator_folder=str(folder),
        )
        assert saved == {"ok": True, "held": True, "printed": False, "method": "hot-folder", "error": ""}
        assert (folder / "Hold" / "card_PRINT_READY.pdf").read_bytes() == b"%PDF-hold"
        assert not (folder / "card_PRINT_READY.pdf").exists()
    finally:
        target = folder / "Hold" / "card_PRINT_READY.pdf"
        if target.exists():
            target.unlink()
        hold_dir = folder / "Hold"
        if hold_dir.exists():
            hold_dir.rmdir()
        if folder.exists():
            folder.rmdir()
    original = (ROOT / "backend" / "p2g" / "fiery_hold.py").read_bytes()
    shipped = (ROOT / "frontend" / "public" / "setup" / "fiery_hold.py").read_bytes()
    mirror = (ROOT / "artifacts" / "myraana-windows-connector" / "fiery_hold.py").read_bytes()
    assert original == shipped == mirror
    pairing = (ROOT / "backend" / "p2g" / "connector_pairing.py").read_text(encoding="utf-8")
    assert '"jobName": job_label(' in pairing
    assert "hold_method_label" in pairing
    assert "hotFolder" not in pairing
    connector = (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_text(encoding="utf-8")
    holds = connector.split("def perform_holds", 1)[1].split("\nRUN_KEY", 1)[0]
    assert "hotFolder" not in holds
    assert "hot_folder=" not in holds
    assert "printers=printers" in holds
    assert "hold_target" in holds
    ui = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    assert 'data-testid="fiery-hold-error"' in ui


def test_operator_clicks_drop_when_the_proof_path_is_automatic():
    assert RECIPE_STEPS == 16
    assert operator_touches(finish_known=True, auto_send=True) == 2
    assert operator_touches(finish_known=False, auto_send=True) == 3
    assert operator_touches(finish_known=True, auto_send=False) < RECIPE_STEPS
    workflow = (ROOT / "backend" / "p2g" / "workflow.py").read_text(encoding="utf-8")
    pipeline = workflow.split("async def run_pdf_workflow", 1)[1].split("async def process_with_lease", 1)[0]
    assert "actor = AUTO_ACTOR" in pipeline
    assert "Proof is ready to send" in pipeline
    assert 'name="shop_queue_updated"' in workflow
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    assert "fieryAutoSend" in server
    assert "process_with_lease(job[\"id\"], job[\"generation\"], AUTO_ACTOR)" in server
    original = (ROOT / "backend" / "p2g" / "fiery_hold.py").read_text(encoding="utf-8")
    shipped = (ROOT / "frontend" / "public" / "setup" / "fiery_hold.py").read_text(encoding="utf-8")
    assert original == shipped
    connector = (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_text(encoding="utf-8")
    assert "perform_holds" in connector
    assert "It was not printed" in connector


def test_queue_index_page_does_not_request_every_job():
    query, _ordering = queue_page_query("needs-you", "2026-10-22T00:00:00|job-9")
    assert query["archived"] == {"$ne": True}
    assert "$or" in query
    assert "limit" not in query
