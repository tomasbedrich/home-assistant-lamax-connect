# LAMAX Connect for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/tomasbedrich/home-assistant-lamax-connect/actions/workflows/validate.yml/badge.svg)](https://github.com/tomasbedrich/home-assistant-lamax-connect/actions/workflows/validate.yml)

Track and message LAMAX kids' GPS watches from Home Assistant.

This is an **unofficial** integration, reverse engineered from the LAMAX Connect
Android app. It is not affiliated with or endorsed by LAMAX Electronics.

## Features

- **Location tracking** - each watch appears as a `device_tracker` with GPS
  coordinates and accuracy, so it works with zones, maps and presence
  automations.
- **Messaging** - each watch gets a `notify` entity, so you can send it a text
  message from any automation or script.
- **Activity and health sensors** - battery, steps, calories, distance, heart
  rate and blood oxygen.
- **Buttons** to ask the watch for a fresh GPS fix, or to make it ring so it can
  be found.
- **Multiple watches** on one account are supported, including watches bound
  after the integration was set up.

## Supported devices

Any watch that pairs with the **LAMAX Connect** mobile app and is bound to your
account. Developed and tested against a LAMAX watch reporting device type 27
(firmware `L36W_A_S90_WC_VE_V001_*`).

Watches sold under the same white-label platform in other regions (elem6,
Kinder Handee) talk to the same backend and are likely to work, but are
untested.

**Not supported:** LAMAX action cameras and dashcams - those use a completely
different, local protocol.

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/tomasbedrich/home-assistant-lamax-connect` with
   category **Integration**.
3. Search for **LAMAX Connect**, download it, and restart Home Assistant.

### Manual

Copy `custom_components/lamax_connect/` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Configuration

Go to **Settings → Devices & Services → Add Integration** and search for
**LAMAX Connect**.

| Field | Description |
| --- | --- |
| Email | The email address registered in the LAMAX Connect app |
| Password | The password for that account |

Sign in with the **same account you use in the app**. The LAMAX backend does not
offer app passwords or API tokens, so the integration signs in exactly as the
app does. Only one Home Assistant config entry per LAMAX account is allowed.

> [!NOTE]
> Only email sign-in is supported. If your LAMAX account is registered to a
> phone number, add an email address to it in the app first.

> [!IMPORTANT]
> **The LAMAX backend allows only one active session per account.** Signing in
> from Home Assistant logs you out of the LAMAX mobile app, and signing back in
> on the phone invalidates Home Assistant's session. See
> [One session per account](#one-session-per-account) below.

### Removing the integration

Go to **Settings → Devices & Services → LAMAX Connect**, open the three-dot menu
on the entry and choose **Delete**. Nothing is left behind on the LAMAX side;
the integration only reads from and sends commands to the account.

## One session per account

This is the most important thing to know before using this integration.

The LAMAX backend keeps **one session per account**. Whichever client logged in
most recently owns the session; the other one is silently logged out and its
next request fails with `code 25`.

In practice:

- When Home Assistant polls, the LAMAX app on your phone gets logged out.
- When you sign back in on your phone, Home Assistant's session dies.

The integration handles its own side automatically: on `code 25` it
re-authenticates and retries the request transparently, so you should not see
errors or gaps in history. It only asks you to re-authenticate if the password
itself stops working. **But it cannot stop this from logging your phone out** -
that is the backend's behaviour, not something a client can work around.

**If you want to keep using the phone app normally, create a second LAMAX
account and invite it to the watch, then use that account for Home Assistant.**
One account per client is the only real fix.

A side effect worth understanding: because Home Assistant re-authenticates
whenever it finds itself logged out, the two clients will keep taking the
session from each other for as long as both are active. Home Assistant will
keep working; your phone app will keep needing to log back in.

## Entities

For each watch (`<watch>` is the watch name from the app):

| Entity | Description |
| --- | --- |
| `device_tracker.<watch>` | GPS position and accuracy |
| `notify.<watch>_message` | Send a text message to the watch |
| `sensor.<watch>_battery` | Battery percentage |
| `sensor.<watch>_steps` | Today's step count as reported by the watch |
| `sensor.<watch>_calories` | Calories burned today |
| `sensor.<watch>_distance` | Distance covered today |
| `sensor.<watch>_heart_rate` | Last heart rate measurement |
| `sensor.<watch>_blood_oxygen` | Last blood oxygen (SpO₂) measurement |
| `sensor.<watch>_last_seen` | When the watch last reported a position |

### About the health readings

Heart rate and blood oxygen are **not** measured continuously - the watch only
records them when a measurement is taken on the device. A reading can therefore
be hours, days or weeks old. Every health sensor carries a `measured_at`
attribute with the time the reading was actually captured; use it rather than
the entity's `last_changed` if the age matters:

```yaml
{{ state_attr('sensor.junior_heart_rate', 'measured_at') }}
```

Steps, calories and distance reset daily on the watch.
| `binary_sensor.<watch>_location_fix` | Whether a position is currently known |
| `button.<watch>_request_location` | Ask the watch for a fresh GPS fix |
| `button.<watch>_find_watch` | Make the watch ring so it can be found |

## How data is updated

The integration polls the LAMAX cloud every **5 minutes** and reads the last
position the watch reported on its own schedule. The watch itself decides how
often it uploads a fix (configurable in the LAMAX app), so a position can be
older than the polling interval - check `sensor.<watch>_last_seen`.

To force an immediate fix, press `button.<watch>_request_location`. This asks
the watch to report right away; the new position appears at the next poll,
usually within a minute. This is a silent background request - it does not alert
the child.

## Examples

Send a message when the watch arrives at school:

```yaml
automation:
  - alias: "Notify when Junior arrives at school"
    triggers:
      - trigger: zone
        entity_id: device_tracker.junior
        zone: zone.school
        event: enter
    actions:
      - action: notify.send_message
        target:
          entity_id: notify.junior_message
        data:
          message: "Have a nice day at school!"
```

Warn when the watch battery gets low:

```yaml
automation:
  - alias: "Watch battery low"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.junior_battery
        below: 20
    actions:
      - action: notify.persistent_notification
        data:
          message: "Junior's watch battery is below 20%."
```

Ask for a fresh position before leaving to pick them up:

```yaml
script:
  locate_junior:
    sequence:
      - action: button.press
        target:
          entity_id: button.junior_request_location
      - delay: "00:01:00"
```

## Known limitations

- **One session per account.** Home Assistant and the LAMAX phone app log each
  other out. See [One session per account](#one-session-per-account).
- **Polling only.** The LAMAX app receives live push over RongCloud IM; this
  integration does not implement that protocol, so positions and incoming
  messages are only as fresh as the 5-minute poll.
- **Sending only.** Messages sent *from* the watch are not exposed as entities.
- **No voice messages.** Only text is supported; voice notes go through Alibaba
  Cloud OSS and are not implemented.
- **No geofence management.** The watch's own geofences can be read from the API
  but are not exposed - use Home Assistant zones with the `device_tracker`
  instead, which is more flexible.
- **Body temperature and blood pressure are not exposed.** The API returns them
  but the tested watch reports `0` for both, so they appear to be unsupported
  on this hardware. Open an issue if your watch measures them.
- **Health readings are on-demand, not continuous.** See
  [About the health readings](#about-the-health-readings).
- **Unofficial API.** LAMAX can change or break the backend at any time.

## Troubleshooting

**"Invalid credentials" when setting up** - confirm the email and password work
in the LAMAX Connect app. Accounts registered to a phone number rather than an
email address are not supported; add an email address in the app first.

**My phone keeps getting logged out of the LAMAX app** - expected; only one
session per account exists. Use a separate LAMAX account for Home Assistant.
See [One session per account](#one-session-per-account).

**The integration asks me to re-authenticate** - this now only happens when the
password itself is rejected (`code 24`); ordinary session loss (`code 25`) is
recovered automatically. Check whether the password was changed in the app.

**A message reported success but never arrived** - the integration treats only
`code 0` as sent, so a silent failure should now surface as an error. If you
still see this, enable debug logging and open an issue with the logged result
code for `/rtosWechat/appSendDevice`.

**Position is stale or missing** - the watch reports on its own schedule and
needs signal. Check `sensor.<watch>_last_seen`, press
`button.<watch>_request_location`, and confirm the watch shows a recent position
in the LAMAX app. If the app is also stale, the watch is offline, not the
integration.

**Heart rate or blood oxygen is empty or looks old** - expected; the watch only
records these when a measurement is taken on the device. Check the sensor's
`measured_at` attribute.

**Entity names are wrong** - entity names come from the watch names set in the
LAMAX app. Rename the watch there, then reload the integration.

### Debug logging

```yaml
logger:
  default: info
  logs:
    custom_components.lamax_connect: debug
```

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.test.txt
pytest            # tests with coverage
ruff check .      # lint
ruff format .     # format
mypy custom_components/lamax_connect
```

The API client lives in `custom_components/lamax_connect/lamax/` and has no
Home Assistant imports, so it can be split into a standalone PyPI package later
without changes. Until then it ships inside the integration so that changes
only need one version bump.

Releases are cut by publishing a GitHub release; the workflow stamps the tag
into `manifest.json` and attaches the ZIP that HACS downloads. The `version` in
git is a `0.0.0` placeholder on purpose.

## Credits

See [ANALYSIS.md](ANALYSIS.md) for how the API was reverse engineered.

## License

[MIT](LICENSE)
