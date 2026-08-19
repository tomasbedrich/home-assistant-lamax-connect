"""Fixtures for the LAMAX Connect tests."""

from __future__ import annotations

from collections.abc import Generator
import json
from unittest.mock import AsyncMock, patch

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lamax_connect.const import DOMAIN
from custom_components.lamax_connect.lamax import (
    Device,
    DeviceSnapshot,
    Health,
    Location,
    Message,
)

pytest_plugins = "pytest_homeassistant_custom_component"

TEST_USERNAME = "parent@example.com"
TEST_PASSWORD = "hunter2"
TEST_IMEI = "860000000000001"
TEST_D_ID = 1000000000000001


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading of the custom integration in every test."""


@pytest.fixture
def device() -> Device:
    """Return a watch as the backend reports it."""
    return Device.from_json(
        {
            "imei": TEST_IMEI,
            "name": "Junior",
            "d_id": TEST_D_ID,
            "device_type": 27,
            "dv": "L36W_A_S90_WC_VE_V001_250801#newoss01#0",
        }
    )


@pytest.fixture
def location() -> Location:
    """Return a position report as the backend reports it."""
    return Location.from_json(
        {
            "lat": "50.07553",
            "lng": "14.437800",
            "Electricity": 100,
            "accuracy": 10,
            "locationType": 0,
            "desc": "",
            "uploadtime": 1786950041000,
        }
    )


@pytest.fixture
def health() -> Health:
    """Return health readings as the backend reports them."""
    return Health.from_json(
        {
            "devicestep": "9474",
            "step_time": 1787145590236,
            "calories": 387,
            "km": "6.78",
            "heart_rate": 93,
            "heart_rate_system_time": "1785747669000",
            "blood_oxygen": 99,
            "blood_oxygen_system_time": "1784733205000",
            "body_temperature": "0",
            "blood_pressure": "0,0",
        }
    )


@pytest.fixture
def messages() -> tuple[Message, ...]:
    """Return one already-delivered message from the watch."""
    parsed = Message.from_json({"msg_content": "260819143000_555_1_ahoj tati", "msg_type": 1})
    assert parsed is not None
    return (parsed,)


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured LAMAX Connect entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=TEST_USERNAME,
        unique_id=TEST_USERNAME,
        data={CONF_USERNAME: TEST_USERNAME, CONF_PASSWORD: TEST_PASSWORD},
    )


@pytest.fixture
def mock_client(
    device: Device,
    location: Location,
    health: Health,
    messages: tuple[Message, ...],
) -> Generator[AsyncMock]:
    """Patch LamaxClient everywhere the integration constructs one."""
    with (
        patch("custom_components.lamax_connect.LamaxClient", autospec=True) as mock_in_init,
        patch("custom_components.lamax_connect.config_flow.LamaxClient", new=mock_in_init),
    ):
        client = mock_in_init.return_value
        client.host = "elem6.wisskys.com"
        client.token = "test-token"
        client.u_id = 2000000000000002
        client.login = AsyncMock(return_value=None)
        client.async_get_snapshots = AsyncMock(
            return_value={device.imei: DeviceSnapshot(device, location, health, messages)}
        )
        client.async_send_message = AsyncMock(return_value="ok")
        client.async_send_group_message = AsyncMock(return_value="ok")
        client.async_find_device = AsyncMock(return_value=None)
        client.async_request_location_update = AsyncMock(return_value=None)
        yield client


def load_json_fixture(name: str) -> dict:
    """Load a JSON fixture from the fixtures directory."""
    from pathlib import Path

    path = Path(__file__).parent / "fixtures" / name
    return json.loads(path.read_text(encoding="utf-8"))
