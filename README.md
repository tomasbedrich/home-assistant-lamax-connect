# LAMAX Connect for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/tomasbedrich/home-assistant-lamax-connect/actions/workflows/validate.yml/badge.svg)](https://github.com/tomasbedrich/home-assistant-lamax-connect/actions/workflows/validate.yml)

Track and message LAMAX kids' GPS watches from Home Assistant.

This is an **unofficial** integration, reverse engineered from the LAMAX Connect
Android app. It is not affiliated with or endorsed by LAMAX Electronics.

## Features

- **Location tracking** - each watch appears as a `device_tracker` with GPS
  coordinates and accuracy, so it works with zones, maps and presence
  automations, plus a sensor saying how old the fix is.
- **Messaging** - send a private message to the watch or post to the shared
  family chat, and get an event in Home Assistant when the watch replies.
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
| `notify.<watch>_message` | Send a private message to the watch |
| `notify.<watch>_family_chat` | Post to the shared family conversation |
| `event.<watch>_message_received` | Fires when the watch sends a message |
| `sensor.<watch>_battery` | Battery percentage as of the last position report |
| `sensor.<watch>_steps` | Today's step count as reported by the watch |
| `sensor.<watch>_calories` | Calories burned today |
| `sensor.<watch>_distance` | Distance covered today |
| `sensor.<watch>_heart_rate` | Last heart rate measurement |
| `sensor.<watch>_heart_rate_measured` | When that heart rate was measured |
| `sensor.<watch>_blood_oxygen` | Last blood oxygen (SpO₂) measurement |
| `sensor.<watch>_blood_oxygen_measured` | When that SpO₂ reading was measured |
| `sensor.<watch>_location_updated` | When the position and battery were reported |

### Family chat

The watch has two conversations, and each gets its own entity:

- `notify.<watch>_message` - a private thread between your account and the
  watch.
- `notify.<watch>_family_chat` - the shared conversation every family member
  bound to the watch can see.

> [!IMPORTANT]
> **Messages are limited to 30 characters.** The watch silently trims anything
> longer, so the integration truncates up front and logs a warning telling you
> exactly what was sent.

The limit is 30 *weighted* units rather than characters or bytes: Chinese,
Japanese and Korean characters, and typographic punctuation such as curly
quotes, en/em dashes and `…`, each cost 2. Everything else costs 1, so plain
Latin text - **including Czech diacritics** - gets the full 30 characters.

#### Receiving messages

`event.<watch>_message_received` fires for messages the watch sends to **either
conversation** - there is one event entity per watch, not one per thread. Use
the `is_group` attribute to tell them apart:

- `is_group: true` - the watch posted to the family chat
- `is_group: false` - the watch sent you a private message

The event carries type `text`, `emoji` or `voice`, and these attributes:

| Attribute | Meaning |
| --- | --- |
| `sender_id` | LAMAX user id of the sender |
| `is_group` | `true` if it went to the family chat |
| `sent_at` | Watch-local time the message was written |
| `content` | Message text — **text and emoji only** |
| `duration` | Voice note length in seconds — **voice only** |

`content` and `duration` are mutually exclusive: a voice event carries only
`duration`, a text or emoji event carries only `content`.

Filter on `is_group` when an automation should only react to one thread:

```yaml
      - condition: template
        value_template: "{{ trigger.to_state.attributes.is_group }}"
```

```yaml
automation:
  - alias: "Announce messages from the watch"
    triggers:
      - trigger: state
        entity_id: event.junior_message_received
    conditions:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.event_type == 'text' }}"
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            Junior: {{ trigger.to_state.attributes.content }}
```

Two things to know about receiving:

- **Messages arrive on the 5 minute poll**, not instantly. The official app
  gets them pushed over RongCloud IM, which this integration does not
  implement.
- **Messages already waiting when Home Assistant starts do not fire events.**
  They are recorded as history, so a restart never replays old conversation
  into your automations.

#### Voice messages are not supported

To be unambiguous about what "voice" means here:

- **You cannot send voice.** Both notify entities send text only.
- **You cannot listen to voice.** When the watch sends a voice note, the event
  fires with type `voice` and its `duration` in seconds, and that is all. The
  audio file lives in Alibaba Cloud object storage that this integration never
  fetches, so there is nothing to play.

Treat a `voice` event as "a voice note arrived, this many seconds long" - a
cue to open the LAMAX app, not a replacement for it.

### About the health readings

Heart rate and blood oxygen are **not** measured continuously - the watch only
records them when a measurement is taken on the device. A reading can therefore
be hours, days or weeks old, while Home Assistant's own "last changed" resets
on every restart. Each reading therefore has its own timestamp sensor next to
it - prefer that:

| Reading | Its age |
| --- | --- |
| `sensor.junior_heart_rate` | `sensor.junior_heart_rate_measured` |
| `sensor.junior_blood_oxygen` | `sensor.junior_blood_oxygen_measured` |
| `sensor.junior_battery` | `sensor.junior_location_updated` |

Steps, calories and distance reset daily on the watch.
| `binary_sensor.<watch>_charging` | Whether the watch was on the charger at the last position report |
| `button.<watch>_request_location` | Ask the watch for a fresh GPS fix |
| `button.<watch>_find_watch` | Make the watch ring so it can be found |

### Why the battery can disagree with the app

**The battery reading is only as fresh as the last position report.** The
backend sends the battery level inside the location response, so if the watch
has not reported its position for a day, the battery figure is a day old too -
even though steps and health keep updating.

`sensor.<watch>_location_updated` is the age of both the position and the
battery - they arrive in the same response. If the battery disagrees with the
LAMAX app, read that timestamp first.

The app refreshes it by asking the watch for a fresh position whenever you open
the map. Home Assistant deliberately does not do that on every poll, because it
wakes the watch's radio and costs the very battery you are measuring. To force
an update, press `button.<watch>_request_location`.

While the watch is on its charger the backend reports a sentinel instead of a
percentage, so `sensor.<watch>_battery` becomes unknown and
`binary_sensor.<watch>_charging` turns on. That flag is as old as the position
report it arrived with, so read it next to `sensor.<watch>_location_updated`.

## How data is updated

The integration polls the LAMAX cloud every **5 minutes**, but polling only
reads what the watch has already uploaded. The watch reports on its own
schedule (configurable in the LAMAX app) and needs signal to do it, so a fix can
be older than the polling interval - and a watch that is asleep or out of
coverage can leave it much older than that.

The tracker deliberately does **not** re-write its state when a poll brings
the same position, so its own "last changed" stays put instead of resetting
every five minutes. (Home Assistant normally forces that write for trackers,
assuming they are push-based.) It still resets when Home Assistant restarts or
when a failed poll makes the entity unavailable, which is why
`sensor.<watch>_location_updated` exists: it is the exact age of the fix, taken
from the watch's own report, and it survives restarts.

The tracker uses GPS and WiFi fixes (this hardware reports WiFi accurate to
tens of metres) but ignores a bare cell tower estimate, which can be kilometres
off and would still drag zone matching with it.

To force a fresh fix, press `button.<watch>_request_location`. Like the map
screen in the app, this asks the watch to report and then keeps re-reading the
position every 20 seconds for up to 3 minutes, stopping as soon as the fix
changes - so the position appears on its own once the watch answers, with no
second button press. If nothing has changed after 3 minutes, the watch did not
answer; the polling costs cloud requests, not watch battery. This is a silent background request - it does not alert
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
- **Messages are capped at 30 weighted characters** by the watch (CJK and
  typographic punctuation count double).
- **Voice is not supported.** Sending voice is not possible, and incoming voice
  notes only report their duration - the audio is never downloaded or played.
- **Sending is text only.** Emoji messages exist in the protocol but are not
  offered.
- **Chat is polled, not pushed.** Expect up to a 5 minute delay on incoming
  messages.
- **No geofence management.** The watch's own geofences can be read from the API
  but are not exposed - use Home Assistant zones with the `device_tracker`
  instead, which is more flexible.
- **Body temperature and blood pressure are not exposed.** The API returns them
  but the tested watch reports `0` for both, so they appear to be unsupported
  on this hardware. Open an issue if your watch measures them.
- **Health readings are on-demand, not continuous.** See
  [About the health readings](#about-the-health-readings).
- **Battery is tied to the position report**, not polled independently. See
  [Why the battery can disagree with the app](#why-the-battery-can-disagree-with-the-app).
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

**Position is stale or missing** - check `sensor.<watch>_location_updated`
first, then press `button.<watch>_request_location` and wait: the watch has to
wake, get a fix and upload it. If the timestamp still does not move, compare
with the LAMAX app - if the app is stale too, the watch is not reporting (off,
no signal, no data, or location disabled in its settings) rather than the
integration being wrong.

**The tracker says "home" but nobody is there** - it is showing the last GPS
fix, not a current one; `sensor.<watch>_location_updated` says when that was.

**Battery does not match the LAMAX app** - the reading is as old as the last
position report; check `sensor.<watch>_location_updated`. See
[Why the battery can disagree with the app](#why-the-battery-can-disagree-with-the-app).

**Heart rate or blood oxygen is empty or looks old** - expected; the watch only
records these when a measurement is taken on the device. Check
`sensor.<watch>_heart_rate_measured` and `sensor.<watch>_blood_oxygen_measured`.

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
