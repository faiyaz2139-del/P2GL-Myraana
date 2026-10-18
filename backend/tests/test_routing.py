from copy import deepcopy

from run_tests import cases
from p2g.routing import route_options, select_route


def route_fixture():
    job = {"stock": "14pt matte", "sides": 2}
    settings = {"version": 3, "printer": "Shop Press", "stocks": ["14pt matte"], "sides": [1, 2]}
    devices = [{"id": "device-1", "status": "Connected", "inventory": {
        "hostname": "P2GL-2", "printers": [{"name": "Shop Press"}, {"name": "Office Printer"}]}}]
    option = route_options(job, settings, devices)["options"][0]
    payload = {"routeId": option["id"], "settingsVersion": 3,
               "compatibilityConfirmed": True, "verificationNote": "Checked the stock/duplex specification sheet."}
    return job, settings, devices, payload


def test_discovery_does_not_make_every_printer_eligible():
    job, settings, devices, _ = route_fixture()
    options = route_options(job, settings, devices)["options"]
    assert len(options) == 2
    assert options[0]["eligible"] is True
    assert options[1]["eligible"] is False
    assert "administrator" in options[1]["blockers"][0].lower()
    assert "operator verification required" in options[0]["capabilitySource"]


def test_selected_route_records_human_evidence_without_changing_inputs():
    job, settings, devices, payload = route_fixture()
    before = deepcopy((job, settings, devices))
    route = select_route(job, settings, devices, payload, "Operator", "2026-10-18T00:00:00Z")
    assert route["printer"] == "Shop Press"
    assert route["compatibility"]["actor"] == "Operator"
    assert route["compatibility"]["source"] == "operator-confirmed"
    assert route["compatibility"]["stock"] == job["stock"]
    assert route["stagingVerified"] is False
    assert (job, settings, devices) == before


@cases('kind', ['offline', 'stock', 'duplex', 'printer', 'unknown-id', 'stale-settings', 'no-confirmation', 'numeric-confirmation', 'no-evidence'])
def test_invalid_routes_reject_without_mutation(kind):
    job, settings, devices, payload = route_fixture()
    if kind == 'offline': devices[0]['status'] = 'Offline'
    if kind == 'stock': settings['stocks'] = []
    if kind == 'duplex': settings['sides'] = [1]
    if kind == 'printer': settings['printer'] = ''
    if kind == 'unknown-id': payload['routeId'] = 'forged'
    if kind == 'stale-settings': settings['version'] = 4
    if kind == 'no-confirmation': payload['compatibilityConfirmed'] = False
    if kind == 'numeric-confirmation': payload['compatibilityConfirmed'] = 1
    if kind == 'no-evidence': payload['verificationNote'] = ' '
    before = deepcopy((job, settings, devices))
    try:
        select_route(job, settings, devices, payload, "Operator", "now")
    except ValueError as error:
        assert str(error)
    else:
        raise AssertionError('Invalid route accepted: ' + kind)
    assert (job, settings, devices) == before


def test_empty_inventory_gives_actionable_message():
    job, settings, _, _ = route_fixture()
    result = route_options(job, settings, [])
    assert result['options'] == []
    assert 'do not repeat pairing' in result['message']


def test_same_printer_name_on_two_computers_has_distinct_identity():
    job, settings, devices, _ = route_fixture()
    other = deepcopy(devices[0]); other['id'] = 'device-2'; devices.append(other)
    ids = [option['id'] for option in route_options(job, settings, devices)['options']]
    assert len(set(ids)) == 4
