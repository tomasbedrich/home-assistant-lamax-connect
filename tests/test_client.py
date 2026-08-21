"""Tests for the LAMAX Connect API client."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json

import aiohttp
from aioresponses import CallbackResult, aioresponses
import pytest
from yarl import URL

from custom_components.lamax_connect.lamax import (
    LamaxAuthError,
    LamaxClient,
    LamaxConnectionError,
    LamaxError,
    message_width,
    truncate_message,
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
                    "uploadtime": 1786950041000,
                }
            ),
        )
        location = await client.async_get_location(1, "860000000000001")

    assert location.latitude == pytest.approx(50.07553)
    assert location.longitude == pytest.approx(14.437800)
    assert location.battery == 100
    assert location.updated_at == datetime.fromtimestamp(1786950041, tz=UTC)


async def test_get_location_sends_did_and_imei(client: LamaxClient) -> None:
    """With did alone the backend answers with a days-old record."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/location/getlast/searchPost", body=encrypted({"code": 0}))
        await client.async_get_location(1, "860000000000001")
        request = next(iter(mocked.requests.values()))[0]
        sent = json.loads(decrypt(request.kwargs["data"]))

    assert sent["did"] == 1
    assert sent["imei"] == "860000000000001"


async def test_get_geofences_accepts_no_data_code(client: LamaxClient) -> None:
    """Code 2 means 'no geofences configured', not an error."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/security/getwatchfencePost",
            body=encrypted({"code": 2, "GeoFenceList": []}),
        )
        assert await client.async_get_geofences(1) == []


async def test_get_track_history_accepts_no_data_code(client: LamaxClient) -> None:
    """Code 2 means the watch reported no position in the window."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/location/watchtrackPost",
            body=encrypted({"code": 2}),
        )
        assert await client.async_get_track_history(1, datetime.now(UTC), datetime.now(UTC)) == []


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


async def test_snapshots_survive_location_failure(
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
        result = await client.async_get_snapshots()

    assert set(result) == {"111", "222"}
    assert sum(snap.location is None for snap in result.values()) == 1


async def test_snapshots_propagate_auth_error(
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
            await client.async_get_snapshots()


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
        assert await client.async_get_snapshots() == {}


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


async def test_health_readings_parsed(client: LamaxClient) -> None:
    """Steps come from devicestep, not the always-zero location step field."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            body=encrypted(
                {
                    "code": 0,
                    "devicestep": "9474",
                    "step_time": 1787145590236,
                    "calories": 387,
                    "km": "6.78",
                    "heart_rate": 93,
                    "heart_rate_system_time": "1785747669000",
                    "blood_oxygen": 99,
                    "blood_oxygen_system_time": "1784733205000",
                }
            ),
        )
        health = await client.async_get_health(1, "860000000000001")

    assert health.steps == 9474
    assert health.calories == 387
    assert health.distance_km == pytest.approx(6.78)
    assert health.heart_rate == 93
    assert health.blood_oxygen == 99
    assert health.heart_rate_at == datetime.fromtimestamp(1785747669, tz=UTC)
    assert health.blood_oxygen_at == datetime.fromtimestamp(1784733205, tz=UTC)


async def test_health_absent(client: LamaxClient) -> None:
    """A watch that reports nothing yields None values rather than zeroes.

    The tested hardware reports 0 for unsupported metrics, which must not be
    shown as a real reading of 0 bpm or 0%.
    """
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            body=encrypted(
                {
                    "code": 0,
                    "heart_rate": 0,
                    "blood_oxygen": 0,
                    "body_temperature": "0",
                    "blood_pressure": "0,0",
                    "heart_rate_system_time": "0",
                }
            ),
        )
        health = await client.async_get_health(1, "860000000000001")

    assert health.steps is None
    assert health.calories is None
    assert health.heart_rate is None
    assert health.blood_oxygen is None
    assert health.heart_rate_at is None


async def test_expired_session_is_recovered_transparently(client: LamaxClient) -> None:
    """Code 25 triggers a re-login and a retry, invisibly to the caller.

    The backend only allows one session per account, so the phone app logging
    in silently invalidates our token. That must self-heal.
    """
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T1", "u_id": 42}))
        await client.login("user@example.com", "pw")

        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body=encrypted({"code": 25}))
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T2", "u_id": 42}))
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "1", "name": "A"}]}),
        )
        devices = await client.async_get_devices()

    assert len(devices) == 1
    assert client.token == "T2"


async def test_expired_session_retries_only_once(client: LamaxClient) -> None:
    """A persistently rejected session surfaces instead of looping forever."""
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T1", "u_id": 42}))
        await client.login("user@example.com", "pw")

        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body=encrypted({"code": 25}))
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T2", "u_id": 42}))
        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body=encrypted({"code": 25}))
        with pytest.raises(LamaxAuthError):
            await client.async_get_devices()


async def test_relogin_with_bad_credentials_surfaces(client: LamaxClient) -> None:
    """If the password itself is now wrong, escalate instead of retrying."""
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T1", "u_id": 42}))
        await client.login("user@example.com", "pw")

        mocked.post(f"{BASE}/watchAppUser/getbindDeviceListPost", body=encrypted({"code": 25}))
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 24}))
        with pytest.raises(LamaxAuthError) as err:
            await client.async_get_devices()

    assert err.value.code == 24


async def test_concurrent_expiry_relogins_once(client: LamaxClient) -> None:
    """Parallel requests hitting an expired session share a single re-login.

    Without the shared lock each in-flight request would re-authenticate, and
    since the backend allows one session per account they would invalidate each
    other in a loop.
    """
    logins = 0

    def login_cb(url: URL, **kwargs: object) -> CallbackResult:
        nonlocal logins
        logins += 1
        return CallbackResult(body=encrypted({"code": 0, "token": "T2", "u_id": 42}))

    def location_cb(url: URL, **kwargs: object) -> CallbackResult:
        sent = json.loads(decrypt(kwargs["data"]))  # type: ignore[arg-type]
        if sent["token"] == "T1":  # stale session
            return CallbackResult(body=encrypted({"code": 25}))
        return CallbackResult(body=encrypted({"code": 0, "lat": "1.0", "lng": "2.0"}))

    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T1", "u_id": 42}))
        await client.login("user@example.com", "pw")

        mocked.post(f"{BASE}/user/login", callback=login_cb, repeat=True)
        mocked.post(f"{BASE}/location/getlast/searchPost", callback=location_cb, repeat=True)
        results = await asyncio.gather(
            *(client.async_get_location(i, "860000000000001") for i in range(5))
        )

    assert len(results) == 5
    assert all(r.latitude == pytest.approx(1.0) for r in results)
    assert logins == 1
    assert client.token == "T2"


async def test_send_message_rejects_non_zero_code(client: LamaxClient) -> None:
    """Only code 0 counts as sent, so a queued/rejected send is not silent."""
    client.token = "TOK"
    client.u_id = 42
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendDevice", body=encrypted({"code": 4}))
        with pytest.raises(LamaxError) as err:
            await client.async_send_message("860000000000001", 7, "hi")

    assert err.value.code == 4


async def test_snapshot_survives_health_failure(client: LamaxClient) -> None:
    """A watch whose health lookup fails still reports its position."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "111", "name": "A", "d_id": 1}]}),
        )
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            body=encrypted({"code": 0, "lat": "1.0", "lng": "2.0"}),
        )
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            body=encrypted({"code": 557}),
        )
        result = await client.async_get_snapshots()

    assert result["111"].health is None
    assert result["111"].location is not None


async def test_snapshot_survives_whole_device_failure(client: LamaxClient) -> None:
    """If every per-watch lookup fails, the watch is still listed."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "111", "name": "A", "d_id": 1}]}),
        )
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            exception=aiohttp.ClientError("down"),
        )
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            exception=aiohttp.ClientError("down"),
        )
        result = await client.async_get_snapshots()

    assert result["111"].location is None
    assert result["111"].health is None


async def test_relogin_skipped_when_another_task_refreshed(
    client: LamaxClient,
) -> None:
    """The generation guard stops a second re-login for the same expiry."""
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/user/login", body=encrypted({"code": 0, "token": "T1", "u_id": 42}))
        await client.login("user@example.com", "pw")

        # Pretend another task already re-authenticated after this generation.
        stale_generation = client._session_generation - 1
        await client._async_relogin(stale_generation)

    assert client.token == "T1"


async def test_snapshot_gathers_location_and_health(client: LamaxClient) -> None:
    """A healthy poll returns both the position and the health readings."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "111", "name": "A", "d_id": 1}]}),
        )
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            body=encrypted({"code": 0, "lat": "1.0", "lng": "2.0", "Electricity": 55}),
        )
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            body=encrypted({"code": 0, "devicestep": "9474", "heart_rate": 93}),
        )
        mocked.post(
            f"{BASE}/rtosWechat/getVoiceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "chaMsgList": [{"msg_content": "260819143000_555_1_ahoj", "msg_type": 1}],
                }
            ),
        )
        result = await client.async_get_snapshots()

    snapshot = result["111"]
    assert [m.content for m in snapshot.messages] == ["ahoj"]
    assert snapshot.health is not None
    assert snapshot.health.steps == 9474
    assert snapshot.health.heart_rate == 93
    assert snapshot.location is not None
    assert snapshot.location.battery == 55


async def test_group_message_addresses_the_family_conversation(
    client: LamaxClient,
) -> None:
    """A family-chat message uses receiver "1", not the watch's IMEI."""
    client.token = "TOK"
    client.u_id = 42
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendGroupMsg", body=encrypted({"code": 0}))
        await client.async_send_group_message("860000000000001", 7, "dinner time")

        sent = json.loads(decrypt(next(iter(mocked.requests.values()))[0].kwargs["data"]))

    _, uid, receiver, text = sent["msg_content"].split("_", 3)
    assert uid == "42"
    assert receiver == "1"
    assert text == "dinner time"


@pytest.mark.parametrize(
    "send",
    ["async_send_message", "async_send_group_message"],
)
async def test_long_messages_are_truncated(client: LamaxClient, send: str) -> None:
    """The watch trims past 30 characters, so do it up front for both targets."""
    client.token = "TOK"
    client.u_id = 42
    long_message = "x" * 45
    path = "appSendDevice" if send == "async_send_message" else "appSendGroupMsg"
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/{path}", body=encrypted({"code": 0}))
        actually_sent = await getattr(client, send)("860000000000001", 7, long_message)

        sent = json.loads(decrypt(next(iter(mocked.requests.values()))[0].kwargs["data"]))

    assert actually_sent == "x" * 30
    assert sent["msg_content"].split("_", 3)[3] == "x" * 30


async def test_czech_diacritics_get_the_full_30_characters(
    client: LamaxClient,
) -> None:
    """Latin text counts one per character, so accents are not charged double."""
    client.token = "TOK"
    client.u_id = 42
    czech = "Sváča je připravená, přijď!!"  # 28 characters
    assert len(czech) == 28
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendDevice", body=encrypted({"code": 0}))
        assert await client.async_send_message("860000000000001", 7, czech) == czech


async def test_wide_characters_count_double(client: LamaxClient) -> None:
    """CJK is charged two units each, matching the app's input filter."""
    client.token = "TOK"
    client.u_id = 42
    wide = "中" * 20  # 40 units, so only 15 characters fit
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendDevice", body=encrypted({"code": 0}))
        sent = await client.async_send_message("860000000000001", 7, wide)

    assert sent == "中" * 15
    assert message_width(sent) == 30


def test_message_width_counts_punctuation_as_wide() -> None:
    """Curly quotes and dashes live in General Punctuation, charged double."""
    assert message_width("abc") == 3
    assert message_width("\u2014") == 2  # em dash
    assert message_width("\u2019") == 2  # right single quote
    assert truncate_message("a" * 40) == "a" * 30


async def test_message_at_the_limit_is_untouched(client: LamaxClient) -> None:
    """Exactly 30 characters must not be trimmed."""
    client.token = "TOK"
    client.u_id = 42
    exact = "y" * 30
    with aioresponses() as mocked:
        mocked.post(f"{BASE}/rtosWechat/appSendDevice", body=encrypted({"code": 0}))
        assert await client.async_send_message("860000000000001", 7, exact) == exact


async def test_group_message_requires_login(client: LamaxClient) -> None:
    """Sending to the family chat without a session raises."""
    with pytest.raises(LamaxAuthError):
        await client.async_send_group_message("860000000000001", 7, "hi")


async def test_get_messages_parses_the_envelope(client: LamaxClient) -> None:
    """Incoming messages are split into sender, receiver and body."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/rtosWechat/getVoiceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "chaMsgList": [
                        {"msg_content": "260819143000_555_1_ahoj tati", "msg_type": 1},
                        {
                            "msg_content": "260819143100_555_FFF860000000000001_12",
                            "msg_type": 3,
                        },
                    ],
                }
            ),
        )
        messages = await client.async_get_messages(1)

    group, voice = messages
    assert group.content == "ahoj tati"
    assert group.sender_id == "555"
    assert group.kind == "text"
    assert group.is_group is True
    assert group.sent_at == datetime(2026, 8, 19, 14, 30)

    assert voice.kind == "voice"
    assert voice.duration == 12
    assert voice.content == ""
    assert voice.is_group is False


async def test_get_messages_keeps_underscores_in_body(client: LamaxClient) -> None:
    """Only the first three underscores are separators."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/rtosWechat/getVoiceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "chaMsgList": [{"msg_content": "260819143000_555_1_a_b_c", "msg_type": 1}],
                }
            ),
        )
        assert (await client.async_get_messages(1))[0].content == "a_b_c"


async def test_get_messages_skips_malformed_and_empty(client: LamaxClient) -> None:
    """Entries without the expected envelope are dropped, code 2 means none."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/rtosWechat/getVoiceListPost",
            body=encrypted(
                {
                    "code": 0,
                    "chaMsgList": [
                        {"msg_content": "garbage", "msg_type": 1},
                        {"msg_content": "notatimestamp_5_1_hi", "msg_type": 1},
                    ],
                }
            ),
        )
        messages = await client.async_get_messages(1)
    assert len(messages) == 1
    assert messages[0].sent_at is None

    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/rtosWechat/getVoiceListPost",
            body=encrypted({"code": 2, "chaMsgList": []}),
        )
        assert await client.async_get_messages(1) == []


async def test_snapshot_survives_message_failure(client: LamaxClient) -> None:
    """A failed chat poll leaves the rest of the snapshot intact."""
    client.token = "TOK"
    with aioresponses() as mocked:
        mocked.post(
            f"{BASE}/watchAppUser/getbindDeviceListPost",
            body=encrypted({"code": 0, "deviceList": [{"imei": "111", "name": "A", "d_id": 1}]}),
        )
        mocked.post(
            f"{BASE}/location/getlast/searchPost",
            body=encrypted({"code": 0, "lat": "1.0", "lng": "2.0"}),
        )
        mocked.post(
            f"{BASE}/heath/getLastAllByDeviceLocalTimePost",
            body=encrypted({"code": 0, "devicestep": "5"}),
        )
        mocked.post(f"{BASE}/rtosWechat/getVoiceListPost", exception=aiohttp.ClientError("down"))
        result = await client.async_get_snapshots()

    assert result["111"].messages == ()
    assert result["111"].health is not None


def test_sending_is_text_only() -> None:
    """Neither send method exposes a message kind.

    Voice needs the audio uploaded to object storage first, so offering the
    parameter would let a caller emit a message the watch cannot render.
    """
    import inspect

    for name in ("async_send_message", "async_send_group_message"):
        params = inspect.signature(getattr(LamaxClient, name)).parameters
        assert "msg_type" not in params, name


async def test_sends_always_declare_text(client: LamaxClient) -> None:
    """Every outgoing message goes out as msg_type 1."""
    client.token = "TOK"
    client.u_id = 42
    for path, send in (
        ("appSendDevice", client.async_send_message),
        ("appSendGroupMsg", client.async_send_group_message),
    ):
        with aioresponses() as mocked:
            mocked.post(f"{BASE}/rtosWechat/{path}", body=encrypted({"code": 0}))
            await send("860000000000001", 7, "hi")
            sent = json.loads(decrypt(next(iter(mocked.requests.values()))[0].kwargs["data"]))
        assert sent["msg_type"] == 1, path
