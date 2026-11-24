import time
from pathlib import Path
import pytest
import yaml
import anyio
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from longlive.app import create_app
from longlive.manager import RoomManager
from longlive.schemas import CreateRoom
from tests.test_rooms import FakeSource, settings


def wait_state(client, room_id, target):
    deadline = time.monotonic()+2
    while time.monotonic()<deadline:
        data=client.get(f"/api/v1/rooms/{room_id}").json()
        if data["state"]==target:
            return data
        time.sleep(.01)
    raise AssertionError(data)


def test_http_contract_and_async_recovery():
    config=settings(1)
    with TestClient(create_app(config, RoomManager(config, FakeSource))) as client:
        payload={"name":"demo","initial_prompt":"forest"}
        response=client.post('/api/v1/rooms',json=payload,headers={'Idempotency-Key':'one'})
        assert response.status_code==201 and response.headers['X-Request-ID']
        room_id=response.json()['id']
        assert client.post('/api/v1/rooms',json=payload,headers={'Idempotency-Key':'one'}).status_code==200
        wait_state(client,room_id,'LIVE')
        assert client.get('/api/v1/rooms').json()['items'][0]['name']=='demo'
        assert client.get('/api/v1/rooms?limit=0').status_code==400
        assert client.get('/api/v1/rooms?cursor=-1').status_code==400
        assert client.post('/api/v1/rooms',json=payload,headers={'Idempotency-Key':'two'}).status_code==429
        assert client.post(f'/api/v1/rooms/{room_id}/prompts',json={'text':'missing IDs'}).status_code==400
        assert client.post(f'/api/v1/rooms/{room_id}/stop').status_code==202
        wait_state(client,room_id,'STOPPED')
        assert client.get('/api/v1/capacity').json()['available_slots']==1
        assert client.post(f'/api/v1/rooms/{room_id}/stop').json()['state']=='STOPPED'
        assert client.post(f'/api/v1/rooms/{room_id}/start').status_code==202
        wait_state(client,room_id,'LIVE')


def test_websocket_snapshot_shared_lease_and_origin():
    config=settings(1)
    with TestClient(create_app(config, RoomManager(config,FakeSource))) as client:
        room_id=client.post('/api/v1/rooms',json={'name':'demo','initial_prompt':'test'},headers={'Idempotency-Key':'one'}).json()['id']
        wait_state(client,room_id,'LIVE')
        path=f'/api/v1/rooms/{room_id}/stream'
        with client.websocket_connect(path) as first:
            assert first.receive_json()['type']=='snapshot'
            with client.websocket_connect(path) as second:
                assert second.receive_json()['room']['viewers']==2
                assert client.get('/api/v1/capacity').json()['active_sessions']==1
            assert client.get(f'/api/v1/rooms/{room_id}').json()['state']=='LIVE'
            assert client.get(f'/api/v1/rooms/{room_id}').json()['viewers']==1
        assert client.get(f'/api/v1/rooms/{room_id}').json()['state']=='LIVE'
        assert client.get(f'/api/v1/rooms/{room_id}').json()['viewers']==0
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path,headers={'origin':'https://unrelated.example'}):
                pass


@pytest.mark.asyncio
async def test_cancelled_stream_releases_viewer():
    config=settings(1)
    manager=RoomManager(config,FakeSource)
    app=create_app(config,manager)
    snapshot=anyio.Event()

    class Socket:
        headers={}

        async def accept(self):
            pass

        async def send_json(self, event):
            if event['type']=='snapshot':
                snapshot.set()

        async def send_bytes(self, packet):
            pass

        async def receive_text(self):
            await anyio.sleep_forever()

        async def close(self):
            pass

    async with app.router.lifespan_context(app):
        room,_=await manager.create(CreateRoom(name='demo',initial_prompt='forest'),'cancel-test')
        endpoint=next(route.endpoint for route in app.routes if route.path.endswith('/stream'))
        async with anyio.create_task_group() as group:
            group.start_soon(endpoint,Socket(),room.id)
            await snapshot.wait()
            assert len(manager.room(room.id).viewers)==1
            group.cancel_scope.cancel()
        assert not manager.room(room.id).viewers


def test_exported_openapi_matches_service():
    assert yaml.safe_load(Path('api/openapi.yaml').read_text())==create_app().openapi()
