"""Tests for the LAMAX Connect API client."""

from __future__ import annotations

from datetime import UTC, datetime
import json

import aiohttp
from aioresponses import aioresponses
import pytest

from custom_components.lamax_connect.lamax import (
    LamaxAuthError,
    LamaxClient,
    LamaxConnectionError,
    LamaxError,
)
from custom_components.lamax_connect.lamax.crypto import decrypt, encrypt

BASE = "https://elem6.wisskys.com/watchxr"


def encrypted(payload: dict) -> str:
    """Encrypt a response body the way the backend does."""
    return encrypt(json.dumps(payload))


@pytest.fixture
async def client():
    """Yield a client backed by a real aiohttp session."""
    async with aiohttp.ClientSession() as session:
        yield LamaxClient(session)


async def test_login_stores_session(client: LamaxClient) -> None:
    """A successful login remembers the token and user id."""
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            body=encrypted({"code": 0, "token": "TOK", "u_id": 42}),
        )
        await client.login("user@example.com", "pw")

    assert client.token == "TOK"
    assert client.u_id == 42


async def test_login_sends_expected_fields(client: LamaxClient) -> None:
    """The login body carries the fields the backend expects."""
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/user/login",
            body=encrypted({"code": 0, "token": "TOK", "u_id": 42}),
        )
        await client.login("user@example.com", "pw", "2", country="420")

        request = next(iter(mocked.requests.values()))[0]
        sent = json.loads(decrypt(request.kwargs["data"]))

    assert sent["username"] == "user@example.com"
    assert sent["pwd"] == "pw"
    assert sent["type"] == "2"
    assert sent["country"] == "420"
    assert sent["version"] == "YkMG%4#^4LUIunhg"


@pytest.mark.parametrize("code", [24, 25])
async def test_auth_errors(client: LamaxClient, code: int) -> None:
    """Bad credentials and expired sessions raise LamaxAuthError."""
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": code}))
        with pytest.raises(LamaxAuthError):
            await client.login("user@example.com", "pw")


async def test_generic_error_code(client: LamaxClient) -> None:
    """An unexpected code raises LamaxError carrying that code."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 557, "msg": "nope"}),
        )
        with pytest.raises(LamaxError) as err:
            await client.async_get_devices()

    assert err.value.code == 557


async def test_undecodable_response(client: LamaxClient) -> None:
    """A response that is not a valid envelope raises a connection error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body="garbage")
        with pytest.raises(LamaxConnectionError):
            await client.async_get_devices()


async def test_network_error(client: LamaxClient) -> None:
    """A transport failure raises a connection error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            exception=aiohttp.ClientError("boom"),
        )
        with pytest.raises(LamaxConnectionError):
            await client.async_get_devices()


async def test_get_devices(client: LamaxClient) -> None:
    """Devices are parsed, including the firmware suffix being stripped."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "deviceList": [
                        {
                            "imei": "860000000000001",
                            "name": "Junior",
                            "d_id": 1000000000000001,
                            "device_type": 27,
                            "dv": "L36W_A_S90_WC_VE_V001_250801#newoss01#0",
                        }
                    ],
                }
            ),
        )
        devices = await client.async_get_devices()

    assert len(devices) == 1
    assert devices[0].imei == "860000000000001"
    assert devices[0].name == "Junior"
    assert devices[0].firmware == "L36W_A_S90_WC_VE_V001_250801"


async def test_get_location(client: LamaxClient) -> None:
    """A position is parsed from the top-level response fields."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            body=encrypted(
                {
                    "code": 0,
                    "lat": "50.07553",
                    "lng": "14.437800",
                    "Electricity": 100,
                    "accuracy": 10,
                    "step": "1234",
                    "uploadtime": 1786950041000,
                }
            ),
        )
        location = await client.async_get_location(1)

    assert location.latitude == pytest.approx(50.07553)
    assert location.longitude == pytest.approx(14.437800)
    assert location.battery == 100
    assert location.steps == 1234
    assert location.updated_at == datetime.fromtimestamp(1786950041, tz=UTC)


async def test_get_geofences_accepts_no_data_code(client: LamaxClient) -> None:
    """Code 2 means 'no geofences configured', not an error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/security/getwatchfencePost",
            body=encrypted({"code": 2, "GeoFenceList": []}),
        )
        assert await client.async_get_geofences(1) == []


async def test_send_message_format(client: LamaxClient) -> None:
    """The message payload uses the app's '<time>_<uid>_FFF<imei>_<text>' format."""
    client.token = "TOK"
    client.u_id = 42
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendDevice", body=encrypted({"code": 0}))
        await client.async_send_message("869123456789012", 7, "hi there")

        request = next(iter(mocked.requests.values()))[0]
        sent = json.loads(decrypt(request.kwargs["data"]))

    stamp, uid, receiver, text = sent["msg_content"].split("_", 3)
    assert len(stamp) == 12
    assert uid == "42"
    assert receiver == "FFF869123456789012"
    assert text == "hi there"
    assert sent["msg_type"] == 1
    assert sent["token"] == "TOK"


async def test_send_message_requires_login(client: LamaxClient) -> None:
    """Sending without a session raises rather than building a bogus payload."""
    with pytest.raises(LamaxAuthError):
        await client.async_send_message("869123456789012", 7, "hi")


async def test_devices_with_location_survives_location_failure(
    client: LamaxClient,
) -> None:
    """A watch whose position lookup fails is still returned, without a location."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "deviceList": [
                        {"imei": "111", "name": "A", "d_id": 1},
                        {"imei": "222", "name": "B", "d_id": 2},
                    ],
                }
            ),
        )
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            body=encrypted({"code": 0, "lat": "1.0", "lng": "2.0"}),
        )
        mocked.post(f"{BASE}/location/getlast/searchPost", body=encrypted({"code": 557}))
        result = await client.async_get_devices_with_location()

    assert set(result) == {"111", "222"}
    assert sum(location is None for _, location in result.values()) == 1


async def test_devices_with_location_propagates_auth_error(
    client: LamaxClient,
) -> None:
    """An expired session during a position lookup is not swallowed."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "111", "name": "A", "d_id": 1}]}),
        )
        mocked.post(f"{BASE}/location/getlast/searchPost", body=encrypted({"code": 25}))
        with pytest.raises(LamaxAuthError):
            await client.async_get_devices_with_location()


async def test_timeout_raises_connection_error(client: LamaxClient) -> None:
    """A request timeout is reported as a connection error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", exception=TimeoutError())
        with pytest.raises(LamaxConnectionError):
            await client.async_get_devices()


async def test_malformed_json_raises_connection_error(client: LamaxClient) -> None:
    """A well-encrypted but non-JSON body is reported as a connection error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body=encrypt("not json"))
        with pytest.raises(LamaxConnectionError):
            await client.async_get_devices()


async def test_http_error_raises_connection_error(client: LamaxClient) -> None:
    """A non-2xx status is reported as a connection error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", status=502)
        with pytest.raises(LamaxConnectionError):
            await client.async_get_devices()


async def test_no_devices_skips_location_lookups(client: LamaxClient) -> None:
    """An account with no watches returns an empty mapping."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": []}),
        )
        assert await client.async_get_devices_with_location() == {}


async def test_find_and_locate_commands(client: LamaxClient) -> None:
    """The one-shot device commands post to their endpoints."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/controllerDevice/findPost", body=encrypted({"code": 0}))
        mocked.post(f"{BASE}/controllerDevice/ask/localtionPost", body=encrypted({"code": 0}))
        await client.async_find_device("869123456789012")
        await client.async_request_location_update("869123456789012")

    assert len(mocked.requests) == 2


async def test_track_history(client: LamaxClient) -> None:
    """Track points are parsed from the List field."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/location/watchtrackPost",
            body=encrypted(
                {
                    "code": 0,
                    "List": [
                        {
                            "lat": "49.1",
                            "lng": "13.4",
                            "locationType": 1,
                            "uploadtime": 1786950041000,
                        }
                    ],
                }
            ),
        )
        points = await client.async_get_track_history(
            1, datetime(2026, 8, 17, tzinfo=UTC), datetime(2026, 8, 19, tzinfo=UTC)
        )

    assert len(points) == 1
    assert points[0].latitude == pytest.approx(49.1)
    assert points[0].recorded_at == datetime.fromtimestamp(1786950041, tz=UTC)


async def test_geofences_parsed(client: LamaxClient) -> None:
    """Geofence entries are parsed including the capitalised Radius field."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/security/getwatchfencePost",
            body=encrypted(
                {
                    "code": 0,
                    "GeoFenceList": [
                        {
                            "id": 5,
                            "fenceName": "Home",
                            "lat": "49.1",
                            "lng": "13.4",
                            "Radius": 300,
                            "entry": 1,
                            "exit": 0,
                            "enable": 1,
                        }
                    ],
                }
            ),
        )
        fences = await client.async_get_geofences(1)

    assert fences[0].name == "Home"
    assert fences[0].radius == 300
    assert fences[0].notify_on_entry is True
    assert fences[0].notify_on_exit is False


async def test_host_property(client: LamaxClient) -> None:
    """The client exposes the backend host it talks to."""
    assert client.host == "elem6.wisskys.com"
