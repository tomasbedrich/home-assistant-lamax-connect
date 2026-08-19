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
- `POST /location/getlast/searchPost {did}` → top level: `{lat, lng,
  Electricity (battery %), accuracy, locationType, step, desc, uploadtime}`. This is
  the "give me what you've got" call and is what the Home Assistant
  device_tracker polls.
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

## Deliverables

- `custom_components/lamax_connect/lamax/` - the API client: crypto layer,
  typed models (`Device`, `Location`, `GeoFence`, `TrackPoint`) and
  `LamaxClient`. It has no Home Assistant imports, so it can be extracted into
  a standalone PyPI package later without changes.
- `custom_components/lamax_connect/` - the Home Assistant integration built on
  that client: config flow with reauth and reconfigure, a
  `DataUpdateCoordinator`, and `device_tracker` / `sensor` / `binary_sensor` /
  `button` / `notify` platforms, plus redacted diagnostics.
- `tests/` - 75 tests at 100% statement coverage, including crypto vectors
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
