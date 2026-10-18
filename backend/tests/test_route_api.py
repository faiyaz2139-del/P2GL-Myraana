"""Isolated ASGI tests. No Mongo connection, live account, AI or printer calls."""
import os
from copy import deepcopy
from unittest.mock import AsyncMock, patch

os.environ.update(MONGO_URL="mongodb://127.0.0.1:9", DB_NAME="isolated_route_unit_test",
                  CORS_ORIGINS="http://testserver")

from fastapi.testclient import TestClient
import server
from p2g.workflow import tasks
from test_routing import route_fixture


def fixture():
    spec, settings, devices, payload = route_fixture()
    job = {**spec, "id": "route-test", "generation": 2, "state": "active", "revision": 1,
           "tasks": tasks(), "files": [], "events": [],
           "approval": {"sha": "test-proof", "generation": 2}}
    for task in job["tasks"][:8]:
        task["status"] = "Completed"
    job["tasks"][8]["status"] = "Waiting for operator"
    return job, settings, devices, {**payload, "action": "route", "generation": 2}


def test_route_api_saves_then_reloads_without_authorization_or_dispatch():
    job, settings, devices, payload = fixture()
    saved = {}
    async def save(value):
        saved.update(deepcopy(value))
    async def get(_):
        return deepcopy(saved or job)
    with patch.object(server, "current_user", AsyncMock(return_value={"id": "operator-1", "name": "Operator", "role": "operator"})), \
         patch.object(server, "get_job", side_effect=get), \
         patch.object(server, "shop_settings", AsyncMock(return_value=settings)), \
         patch.object(server, "paired_devices", AsyncMock(return_value=devices)), \
         patch.object(server, "save_job", side_effect=save), \
         patch.object(server, "readiness", AsyncMock()) as readiness:
        client = TestClient(server.app)
        options = client.get('/api/jobs/route-test/route-options')
        assert options.status_code == 200
        assert len(options.json()['options']) == 2
        response = client.post('/api/jobs/route-test/action', json=payload)
        assert response.status_code == 200, response.text
        reloaded = client.get('/api/jobs/route-test').json()
        assert reloaded['route']['printer'] == 'Shop Press'
        assert reloaded['route']['compatibility']['actor'] == 'Operator'
        assert reloaded['route']['compatibility']['actorId'] == 'operator-1'
        assert reloaded['tasks'][8]['status'] == 'Completed'
        assert reloaded['tasks'][9]['status'] == 'Waiting for operator'
        assert reloaded['tasks'][10]['status'] == 'Pending'
        assert reloaded['approval'] == job['approval']
        assert 'authorization' not in reloaded
        assert 'readiness' not in reloaded
        readiness.assert_not_awaited()


def test_route_api_exposes_blockers_and_rejects_stale_or_unverified_requests():
    job, settings, devices, payload = fixture()
    with patch.object(server, "current_user", AsyncMock(return_value={"id": "operator-1", "name": "Operator", "role": "operator"})), \
         patch.object(server, "get_job", AsyncMock(side_effect=lambda _: deepcopy(job))), \
         patch.object(server, "shop_settings", AsyncMock(return_value=settings)), \
         patch.object(server, "paired_devices", AsyncMock(return_value=devices)), \
         patch.object(server, "save_job", AsyncMock()) as save:
        client = TestClient(server.app)
        for invalid, text in [({**payload, 'compatibilityConfirmed': False}, 'Verify stock'),
                              ({**payload, 'generation': 1}, 'Job version changed'),
                              ({**payload, 'settingsVersion': 1}, 'Shop settings changed'),
                              ({'action': 'route', 'generation': 2}, 'Shop settings changed')]:
            response = client.post('/api/jobs/route-test/action', json=invalid)
            assert response.status_code == 409
            assert text in response.json()['error']
        settings['sides'] = [1]
        options = client.get('/api/jobs/route-test/route-options').json()
        assert 'requested number of sides' in options['options'][0]['blockers'][0]
        response = client.post('/api/jobs/route-test/action', json=payload)
        assert response.status_code == 409
        assert 'requested number of sides' in response.json()['error']
        save.assert_not_awaited()
