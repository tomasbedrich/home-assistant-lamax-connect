# LAMAX Connect — reverse engineering analysis

Target: `LAMAX+Connect_1.0.17_APKPure.xapk` (package `com.ztc.lamax`, version 1.0.17,
targetSdk 35). This is the companion app for LAMAX's kids' GPS smartwatches
(marketed in some regions under the "elem6" / "Kinder Handee" white-label).

## Methodology

1. Unpacked the `.xapk` (a zip of split APKs) and extracted the base APK.
2. Decompiled `classes.dex`..`classes4.dex` to Java with `jadx` (installed via
   Homebrew). ~14,000 source files recovered, mostly de-obfuscated at the
   package/method-name level but with R8-mangled member names (`m12801e`,
   `f13230b`, etc.) — still fully readable logic.
3. Grepped decompiled sources and raw `strings` output from the dex/resources
   for hostnames, endpoint paths, and crypto constants.
4. Cross-referenced findings against three focused passes over
   `com/ztc/lamax/utils/CWRequestUtils.java` (2,416 lines, ~100 endpoint
   methods) and the `bean`/`dbflow` model classes.
5. **Independently validated the encryption scheme**: extracted
   `AesUtil.java`, stripped its one Guava dependency, compiled it with a
   real JDK (`openjdk` via Homebrew), and round-tripped ciphertext between
   the compiled Java code and a from-scratch Python reimplementation in both
   directions (Java-encrypt → Python-decrypt and vice versa). Both directions
   matched byte-for-byte — the Python crypto implementation is a confirmed,
   not just plausible, match.

6. **Verified against the live backend** with a real account and a real bound
   watch. This corrected two things static analysis got wrong - see
   "Live verification" below. Endpoints that would alert a child or mutate
   account state were deliberately not exercised.

## Backend architecture

- **Base URL**: `https://elem6.wisskys.com/watchxr<path>` (fallback host
  `elem6.lagenio.com`, selected by a local settings flag — likely a China/
  international split). Confirmed at `ServerUtils.java`.
- **Transport**: plain HTTPS POST, JSON body, via the `Ion` HTTP client.
  No custom headers of any kind — auth token and everything else travels
  as a JSON field inside the (encrypted) body.
- **~100 REST-ish endpoints** under a handful of namespaces: `/user`,
  `/code` (SMS/email verification), `/watchAppUser` (device binding),
  `/controllerDevice` (locate/find/wake/reset), `/location`, `/security`
  (geofences), `/heath` [sic] (heart rate/steps/temperature), `/notify`,
  `/rtosWechat` + `/wechatvoice` (device messaging), `/agora` (call
  signaling — name is legacy, see below), `/phonebook`, `/app` (misc
  settings: alarms, wifi, dialpad, sedentary reminders...).
- **Real-time chat/voice does not go through this REST API.** It's handled
  by **RongCloud IM** (`io.rong.*`), with tokens fetched directly from
  `api-sg01.ronghub.com` (not from the LAMAX backend), and voice/video
  calls via **RongCloud RTC** (`cn.rongcloud.rtc.*`) — despite endpoint
  names like `/agora/appCallDevice`, the Agora SDK is imported but never
  actually instantiated anywhere in the app. The `/rtosWechat/*` REST
  endpoints are a store-and-forward sync/backfill layer on top of the live
  RongCloud push channel (used e.g. after reinstall, or to poll for
  messages missed while the app was closed).
- **File storage**: photos/voice notes go through Alibaba Cloud OSS
  (`oss.aliyuncs.com`), with the LAMAX backend issuing pre-signed
  credentials.

## Encryption scheme (`AesUtil.java`)

Every request body and response body is wrapped in a custom envelope —
not TLS-adjacent, this sits *on top of* HTTPS:

```
"3c3c" + key_index(1 digit, "1".."5") + iv(16 alphanumeric chars)
       + HMAC-SHA256(key = iv + hmac_key[i], msg = ciphertext_hex).hexdigest()
       + ciphertext_hex
       + "2f2f"
```

- Plaintext is AES-256-**CTR** encrypted (`AES/CTR/NoPadding`) with a
  **random 16-byte alphanumeric IV** generated per message, used directly as
  the initial CTR counter block (matches `IvParameterSpec` semantics 1:1
  with `cryptography`'s `modes.CTR(iv)` in Python).
- The AES key and the HMAC salt are each picked from a **fixed table of 5
  hardcoded strings** baked into the APK (`AesUtil.f13227a` /
  `f13228b`), indexed by a value derived from `plaintext.length() % 6`
  (falling back to `% 3`, then `% 2`) — a cheap key-rotation scheme, not a
  secret negotiation; anyone with the APK has all 5 keys.
- Integrity: HMAC-SHA256 over the **ciphertext hex string** (not the raw
  bytes), keyed by `IV + hmac_key[i]`. This authenticates ciphertext+IV but
  is checked with `String.equals`, not constant-time comparison, in the
  original app (not a practical concern for a read-mostly client).

This is security-by-obscurity glued on top of HTTPS — it does not add real
confidentiality against anyone who has the APK (which is exactly the
threat model of building a compatible client), but the server presumably
*requires* it, so any client must implement it to be accepted. Fully
implemented and independently verified in
[`custom_components/lamax_connect/lamax/crypto.py`](custom_components/lamax_connect/lamax/crypto.py).

## Authentication

`POST /user/login`: `{username, pwd, type ("1"=email,"2"=phone), languageType, "app-version": "Android-LAMAX-<ver>", country? }`, plus the "version" field described below.
Every request, authenticated or not, also carries a **static constant**
`"version": "YkMG%4#^4LUIunhg"` — not a real version number, more likely an
app-signature/anti-tamper check.

Response (top level, *not* nested under `resultBean` - see "Live
verification"): `{token, u_id, name, head, rongyun_token}`. There is
no separate header or cookie — `token` is simply echoed back as a JSON
field (`"token": "<token>"`) on every subsequent authenticated request.
`code == 25` on any response means the token is invalid/expired and the
official app force-logs-out; the Python client raises `LamaxAuthError` for
this so a Home Assistant config entry can trigger reauth.

## Geolocation

- `POST /controllerDevice/ask/localtionPost {imei}` — asks the *watch* to
  push a fresh GPS fix upstream. The HTTP response itself is just an ack;
  the actual fix has to be picked up afterwards.
- `POST /location/getlast/searchPost {did, imei}` → top level: `{lat, lng,
  Electricity (battery %), accuracy, locationType, step, desc, uploadtime,
  update_time}`. This is the "give me what you've got" call and is what the Home
  Assistant device_tracker polls. **Both identifiers are required** - see the
  production notes; `did` alone returns a stale record.
- `POST /location/watchtrackPost {did, starttime, endtime}` → `List`: array
  of `{imei, lat, lng, locationType, date, uploadtime}` — track history.
- `POST /security/{add,update,delete,get}watchfence*` — full CRUD on
  geofences: `{fenceName, lat, lng, Radius, entry, exit, enable}`.
- `POST /controllerDevice/findPost {imei}` — ring/vibrate the watch so it
  can be found physically (distinct from GPS location).

## Messaging

- `POST /rtosWechat/appSendDevice {d_id, imei, msg_type, msg_content}` —
  send app→device. `msg_type`: 1=text, 2=emoji, 3=voice (voice content is
  a filename key; the audio itself is uploaded to OSS first).
  `msg_content` is a manually built pipe of fields:
  `"<yyMMddHHmmss>_<sender_uid>_FFF<imei>_<text>"`.
- `POST /rtosWechat/appSendGroupMsg` — same shape, group-addressed.
- `POST /rtosWechat/getVoiceListPost {did, d_id, imei, u_id}` →
  `chaMsgList`: backlog of messages sent *from* the device, same
  `msg_content` encoding. This is the sync/backfill path; live delivery
  while both sides are connected happens over RongCloud IM push and is
  **not implemented** in the Python client (would require embedding the
  RongCloud IM protocol/SDK, out of scope for a REST wrapper).
- `/watchAppUser/getAppMsgPost` and `/watchAppUser/getWatchMsgPost` are
  **not** chat — they're admin/system notification feeds (binding
  requests, SOS, geofence alerts, firmware updates).

## Backend behaviours learned in production

Things that only surfaced once the integration ran against a real account:

- **One session per account.** The backend invalidates the previous token on
  every login, so Home Assistant and the phone app log each other out. The
  stale client gets `code 25` on its next request. The client now stores its
  credentials and transparently re-logins + retries once on `code 25`,
  serialising concurrent re-logins behind a lock and a generation counter so a
  burst of parallel requests triggers exactly one login.
- **Result codes are per-endpoint, not global.** An earlier version accepted
  `code 4` as success everywhere, generalised from the Android message-send
  handler. That was wrong and could mask failures, so the default is now
  strictly `code 0`, with `code 2` additionally allowed for geofence listing
  ("none configured"). `code 24` is bad credentials, `code 25` is an expired
  session.
- **Step counts do not come from the location response.** The `step` field of
  `/location/getlast/searchPost` is always `"0"`. Steps, calories, distance,
  heart rate and blood oxygen all come from one call,
  `POST /heath/getLastAllByDeviceLocalTimePost {did, imei}`:

  ```json
  {"code": 0, "devicestep": "9684", "step_time": 1787145590236,
   "calories": 387, "km": "6.78",
   "heart_rate": 93, "heart_rate_system_time": "1785747669000",
   "blood_oxygen": 99, "blood_oxygen_system_time": "1784733205000",
   "body_temperature": "0", "blood_pressure": "0,0"}
  ```

  Heart rate and blood oxygen are only captured when a measurement is taken on
  the watch, so they are frequently stale - the `*_system_time` fields (epoch
  ms, sometimes as strings) say when. `body_temperature` and `blood_pressure`
  read `0` on the tested hardware and appear unsupported, so `0` is treated as
  "never measured" rather than a real reading. `/app/getTodayStepPost` and
  `/app/getStepPost` also return `devicestep`; the latter adds the configured
  daily goal as `step`.
- **Battery lives in the location response and shares its staleness.**
  `Electricity` comes back from `/location/getlast/searchPost`, so it is only
  as fresh as the last position report - which can lag by days even while
  steps keep updating. The app keeps its figure current by calling
  `/controllerDevice/ask/localtionPost` whenever the map screen opens
  (`LocationFragment` issues it twice), then re-reading `getlast`.
- **`Electricity == 255` means charging, not 255%.** `LocationFragment`
  branches on 255 to show a charging icon before any percentage comparison.
  Reporting it verbatim would give Home Assistant a 255% battery.
- **Login is email-only in practice.** The API accepts `type: "2"` with a
  `country` dial code for phone accounts, but the integration only offers email
  sign-in to keep the config flow to two fields. Submitting empty credentials
  returns `code 23`.
- **Two chat targets, distinguished only by a segment of `msg_content`.**
  Both `/rtosWechat/appSendDevice` (private) and `/rtosWechat/appSendGroupMsg`
  (family) take the same body `{token, d_id, imei, msg_type, msg_content}`.
  The receiver segment is `FFF<imei>` for private and the literal `1` for the
  family conversation:
  `"<yyMMddHHmmss>_<sender_u_id>_<receiver>_<text>"`.
- **Outgoing text is capped at 30 weighted units**, trimmed silently. The app's
  own filter (`ui.inputfilter.ChineseInputFiler`, wired up in
  `wechat.widget.ChatBottomView` with a limit of 30) charges 2 for
  `CJK_UNIFIED_IDEOGRAPHS`, `CJK_COMPATIBILITY_IDEOGRAPHS`,
  `CJK_UNIFIED_IDEOGRAPHS_EXTENSION_A`, `GENERAL_PUNCTUATION`,
  `CJK_SYMBOLS_AND_PUNCTUATION` and `HALFWIDTH_AND_FULLWIDTH_FORMS`, and 1 for
  everything else - so it is neither a character nor a byte count, and Latin
  text with diacritics gets the full 30.
- **Receiving is `POST /rtosWechat/getVoiceListPost {token, did}`** returning
  `chaMsgList` of `{msg_content, msg_type}` with the same envelope. `msg_type`
  here is the content kind (1 text, 2 emoji, 3 voice); for voice the trailing
  segment is a duration in seconds and the audio sits in Alibaba OSS. The
  backend never deletes delivered messages and the app de-duplicates locally on
  the exact `msg_content` string, so any client must do the same.
- **One inbox, two conversations.** `getVoiceListPost` takes only
  `{token, did}` and is not filtered by thread - private and family messages
  arrive together and the app separates them client-side on `receive_id`.
  `WechatGroupActivity` queries `receive_id = "1"`; `WechatPrivateActivity`
  queries the pair `(receive_id = <my u_id> AND send_id = "FFF<imei>")` or its
  mirror. Messages from `getVoiceListPost` are always inbound - the handler
  stamps direction unconditionally.
- **The endpoint only applies to some hardware.** `ChatDeviceFragment` calls
  `getVoiceListPost` only when the mapped `device_type` setting is 2, 3, 4 or
  5, and uses RongCloud history otherwise. Raw `device_type` 26-30 (the tested
  watch reports 27) map to 4, so polling is the correct path here.
- **Only text is sent.** `msg_type` is fixed to 1 on the wire. Emoji (2) is
  merely unused, but voice (3) is actively unsafe to expose: the app uploads
  the `.amr` to Alibaba OSS *first* and only then posts `msg_type: 3`
  referencing it, so sending 3 without that upload produces a message the
  watch cannot render. The client therefore takes no message-kind parameter at
  all rather than guarding one.
- **Message sends are acknowledged, not confirmed.** The REST response only
  says the backend accepted the request; there is no delivery receipt, and the
  live delivery path is RongCloud IM. Treat a successful send as "queued".
- **`/location/getlast/searchPost` needs both `did` and `imei`.** With `did`
  alone the backend answers `code 0` with a *stale* record - verified live: the
  same second, `{did}` returned a four-day-old fix at home while `{did, imei}`
  returned a ten-minute-old fix at the child's actual location. The app always
  sends `{token, imei, did}` (`CWRequestUtils.W`). Adding a surplus identifier
  such as `d_id` fails with `code 555`, and `{imei}` alone does too, so the
  pair is exact. This one omission looked exactly like a watch that had stopped
  reporting: `ask/localtionPost` returned `code 0` and nothing ever changed,
  while steps and health - whose endpoint already sent `imei` - kept updating.
- **Asking is still not answering.** `ask/localtionPost` only queues the
  request; the fix appears in `getlast` once the watch has woken, fixed and
  uploaded. The app keeps its refresh button disabled for 60 s and re-reads
  afterwards, so a client should poll for a few minutes rather than once.
- **`code 3` and `4` on a `controllerDevice/*` command are about the watch, not
  the request**: `RequestToastUtils` maps 3 to `device_ont_online_prompt`
  ("device is not online") and 4 to `wait_online_update_prompt` ("will be
  updated once it is online"). Verified live on a watch that had not reported
  since the previous afternoon:
  `{"code": 3, "service_ip": "172.31.46.42", "last_online_ip": "172.31.46.42"}`.
  The two commands then part ways, and the integration follows each:
  - **locate treats both as queued.** `LocationFragment` toasts
    `location_no_net_prompt` - the request has been sent and the position will
    follow once the watch is online - and re-reads `getlast` a minute later
    regardless, giving up quietly if nothing changed. So a locate is never
    reported as failed; the watch simply may not answer.
  - **ring reports the failure.** `MoreFragment` sends code 3 straight to
    `RequestToastUtils`, so the user is told the watch is not online. Nothing
    rings later, so this one surfaces as an error.
- **Device commands are node-routed.** Every `controllerDevice/*` call in the
  app takes the host as a parameter (`CWRequestUtils.A0`, `.r`, ...) and each
  response carries `service_ip` and `last_online_ip`. When they differ, the app
  stores `last_online_ip` and re-sends the same command there - the watch's
  session lives on one backend node and only that node can reach it. The
  integration always posts to the public host and does not follow the
  redirect; that is fine while the pair matches, which is all that has been
  observed live.
- **`Electricity: "0"` is not a battery reading.** A watch flat enough to
  report 0% is off and reports nothing at all; 0 comes back on records the
  backend stored without a battery sample - seen live alongside `accuracy: 10`,
  `locationType: 0` and `step: "0"`, the same defaults `LocationFragment`
  fills in for push-delivered positions. The app renders 0 and "missing"
  identically (`ic_electric_zero`), so the integration reports both as unknown.
- **`locationType` says how the position was obtained**: 1 = LBS (cell tower),
  2 = WiFi, anything else = GPS. `LocationFragment.c1()` picks the `ic_lbs`,
  `ic_wifi` or `ic_gps` icon on exactly that, and for 1 and 2 it makes the map
  marker draggable with "update_latlng_prompt" - the app itself treats coarse
  fixes as guesses the user may need to correct. In practice WiFi (2) came back
  accurate to 25 m on the tested watch and is perfectly usable, so only the bare
  cell tower estimate (1) is ignored for the tracker: Home Assistant matches
  zones against the accuracy circle (`zone_dist - accuracy < zone_radius`) and
  would report the watch as home from kilometres away.
- **`Electricity == 255` means charging**, and like the battery percentage it is
  only as fresh as the position report it rides on - read it together with that
  timestamp.
- **Timestamps: the epoch fields are the truth, the strings are decoration.**
  `getlast` also returns `update_time`, which is `uploadtime` rendered in
  GMT+8 (`TimeUtils.g/c` set that zone explicitly), and the health response
  adds `heart_rate_upload_time`, `blood_oxygen_upload_time`,
  `device_upload_time` and `sys_time` as preformatted strings - the app prints
  them verbatim. On a live account `heart_rate_system_time` and
  `blood_oxygen_system_time` matched their `*_upload_time` strings exactly once
  rendered in the account's timezone, so the epoch-milliseconds fields are
  correct instants and are what the integration parses.
- **The health call needs no time window.** The app sends
  `{token, did, starttime, endtime}` (today 00:00 to now) to
  `/heath/getLastAllByDeviceLocalTimePost`; sending the window without `imei`
  returns `code 555`, and sending `{did, imei}` with no window returns the last
  known reading for every metric, which is what the integration wants anyway.
- **`watchtrackPost` returns `code 2` when there is no history** in the
  requested window, exactly like the geofence listing.
- **The device list has no liveness field.** `status` on a `deviceList` entry
  is the binder's role (1 = manager, 0 = member, per `BindMemberFragment`), not
  an online flag, and there is no last-online endpoint anywhere in
  `CWRequestUtils`. The only "last seen" the API can offer is the timestamp of
  the last position report.

## Deliverables

- `custom_components/lamax_connect/lamax/` - the API client: crypto layer,
  typed models (`Device`, `Location`, `GeoFence`, `TrackPoint`) and
  `LamaxClient`. It has no Home Assistant imports, so it can be extracted into
  a standalone PyPI package later without changes.
- `custom_components/lamax_connect/` - the Home Assistant integration built on
  that client: config flow with reauth and reconfigure, a
  `DataUpdateCoordinator`, and `device_tracker` / `sensor` / `button` /
  `event` / `notify` platforms, plus redacted diagnostics.
- `tests/` - 127 tests at 100% statement coverage, including crypto vectors
  captured from the real compiled Android class.

## Caveats / what's not covered

- **Real-time messaging is out of scope** - only the REST backfill path
  (`getVoiceListPost`) exists in the API notes; true push requires the
  RongCloud IM protocol, which the integration does not implement.
- **Health metrics (heart rate, steps, temperature, sleep) and phonebook/
  dialpad/wifi settings endpoints** were catalogued (see the full path list
  above) but are not implemented - out of scope for the geolocation and
  messaging focus.
- This is unofficial, reverse-engineered, and unaffiliated with LAMAX; the
  backend can change or start rejecting requests at any time.
