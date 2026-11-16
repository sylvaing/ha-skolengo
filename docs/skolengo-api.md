# Skolengo mobile API — unofficial reference

A practical, implementation-oriented reference for the **Skolengo** mobile API (the "BFF"
backend of the official Skolengo app by Kosmos, used by many French ENTs such as *Mon ENT
Occitanie*, *Mon Bureau Numérique*, *l'Éducation de l'Académie*, etc.).

This document is **neutral and self-contained**: it describes the whole API, not a specific
integration. It is meant to be reused by other projects (Home Assistant, scripts, bots, …).

> **Status:** unofficial. Kosmos does not publish this API. It was pieced together from the
> open-source clients [`maelgangloff/scolengo-api`](https://github.com/maelgangloff/scolengo-api)
> (Node.js) and `scolengo-api` (Python), from decompiling the official Android app (v5.3.1,
> Flutter), and from live calls against a real account. Endpoints may change without notice.
>
> **Scope of use:** you can only ever access **your own** data (or, with a parent account, your
> children's). Tokens are personal and grant full account access (including sending messages).
> Treat them as secrets, respect the ENT's terms, and mind GDPR when storing minors' data.

---

## 1. Transport & conventions

- **Base URL:** `https://api.skolengo.com/api/v1/bff-sko-app`
- **Format:** [JSON:API](https://jsonapi.org/) (resources with `type`/`id`/`attributes`/
  `relationships`, and an `included` array for side-loaded resources).
- **Auth:** OAuth 2.0 / OpenID Connect bearer token (see §2).
- **Current app config** (public, no auth): `GET /sko-app-configs/current` returns
  `latestDeployedSkoAppVersion`, `latestSupportedSkoAppVersion`, `apiCallRetryDelay` (ms),
  `apiCallMaxRetries`. Use the retry hints to be a good citizen.

### Required request headers (authenticated calls)

| Header | Value | Notes |
|---|---|---|
| `Authorization` | `Bearer <access_token>` | |
| `X-Skolengo-School-Id` | the establishment id (`SKO-E-…`) | **Of the student the request is about** — a parent's children can be in different schools (see §4). |
| `X-Skolengo-Ems-Code` | the ENT code, e.g. `entmip` | From the school record (`emsCode`). |
| `X-Skolengo-Date-Format` | `utc` | |
| `x-skolengo-bff-api-key` | *(app secret)* | **Added in app v5, but NOT required** in practice — authenticated calls succeed without it. Public endpoints (`/schools`, `/sko-app-configs`) also work without it. |
| `Accept` | `application/json` | |

### Common JSON:API query parameters

- `include=rel1,rel2.sub` — side-load related resources into `included`.
- `filter[field]=value`, and range filters `filter[field][GE]=…` / `filter[field][LE]=…`.
- `fields[type]=attr1,attr2` — sparse fieldsets.
- `page[limit]=N` & `page[offset]=M` — pagination.

### Error format

Errors come back as `{ "errors": [ { "code": "...", "title": "...", ... } ] }`. A notable one is
`PRONOTE_RESOURCES_NOT_READY` — some ENTs proxy Pronote behind Skolengo and the data is not ready
yet; retry after a short delay. (A plain HTML `401` from the token endpoint instead means a
**client-authentication** problem — see §2.)

---

## 2. Authentication (OIDC + PKCE)

Skolengo delegates login to each ENT's identity provider (often **EduConnect**/CAS). The flow is
standard OpenID Connect **authorization code + PKCE**, with a **confidential** client.

### Public mobile client

These credentials ship in the app and are shared by all users (not personal):

```
client_id     = SkoApp.Prod.0d349217-9a4e-41ec-9af9-df9e69e09494
client_secret = 7cb4d9a8-2580-4041-9ae8-d5803869183f
redirect_uri  = skoapp-prod://sign-in-callback
scope         = openid
```

### Step by step

1. **Find the school** and its OIDC discovery URL (§3). Each school record carries
   `emsOIDCWellKnownUrl`, e.g. `https://sso.mon-ent-occitanie.fr/oidc/.well-known`.
2. **Fetch the discovery document** to get `authorization_endpoint`, `token_endpoint`,
   `revocation_endpoint`, `end_session_endpoint`.
3. **Generate PKCE**: `code_verifier` (random) and
   `code_challenge = BASE64URL(SHA256(code_verifier))`.
4. **Open the authorization URL** in a browser:
   ```
   {authorization_endpoint}
     ?client_id=SkoApp.Prod.0d349217-9a4e-41ec-9af9-df9e69e09494
     &redirect_uri=skoapp-prod://sign-in-callback
     &response_type=code
     &scope=openid
     &state=<random>
     &code_challenge=<challenge>
     &code_challenge_method=S256
   ```
   The user authenticates (EduConnect: "élève ou parent", etc.).
5. **Capture the authorization code.** The provider redirects to
   `skoapp-prod://sign-in-callback?code=…`. This is a **custom URL scheme**: a normal browser
   cannot follow it (it shows "information not secure" / does nothing). On a real device the app
   handles it. For a non-app client, intercept the code — the most robust way is to **read it from
   the page** right before the redirect (the code appears in a form `action`, a link, or the raw
   HTML as `skoapp-prod://…?code=…`) rather than relying on navigation.
6. **Exchange the code for tokens** at the `token_endpoint`. **Client authentication MUST be HTTP
   Basic** (`Authorization: Basic base64(client_id:client_secret)`); sending the secret in the
   body returns an HTML `401`.
   ```
   POST {token_endpoint}
   Authorization: Basic base64(client_id:client_secret)
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code
   &code=<code>
   &redirect_uri=skoapp-prod://sign-in-callback
   &code_verifier=<verifier>
   ```
   Response: `access_token`, `id_token`, `refresh_token`, `token_type=bearer`, `expires_in`,
   `scope`. The user id is the `sub` claim of the `id_token`.

### Non-interactive login (no browser)

Because the final redirect is just a `Location: skoapp-prod://sign-in-callback?code=…` header,
an HTTP client can run the whole login itself with the user's credentials and read the code
from that header, without following it. Verified on *Mon ENT Occitanie* with EduConnect:

1. `GET` the authorization URL, following redirects → the ENT's CAS page asks for the identity
   provider (a GET form with a `selection` radio, e.g. `TOULO-EDU_parent_eleve`, and a hidden
   `service`). Submit it.
2. Auto-post the `SAMLRequest` form to EduConnect (Shibboleth).
3. Shibboleth's local-storage page: post it with `shib_idp_ls_supported=true` and every
   `shib_idp_ls_success.*=true`, or it loops.
4. EduConnect login form: post `csrf_token`, `j_username`, `j_password`, `_eventId_proceed`.
5. Auto-post the `SAMLResponse` form back to CAS, then follow redirects **manually** and stop at
   the `skoapp-prod://` location. Check `state`, then exchange the code (§2 step 6).

EduConnect may add a CaptchEtat captcha to the login form (`#captchetat`), apparently after
failed attempts; a non-interactive client should detect it and ask the user to log in once in
a browser. FranceConnect sign-in cannot be scripted this way.

### Token lifetime & refresh

- `access_token` lives **~24 h** (`expires_in = 86400`).
- Refresh with the same Basic auth:
  ```
  POST {token_endpoint}      (Authorization: Basic …)
  grant_type=refresh_token&refresh_token=<refresh_token>
  ```
- The **refresh token rotates**: each refresh returns a *new* `refresh_token` that replaces the
  old one. **Persist the new value every time**, or you will lose the session.
- No re-login via EduConnect is needed as long as refreshing succeeds.
- Revoke with `revocation_endpoint`; end the SSO session with `end_session_endpoint`.

---

## 3. Finding a school

```
GET /schools?filter[text]=<query>&page[limit]=20
GET /schools?filter[lat]=<lat>&filter[lon]=<lon>
```

Each result (`type: "school"`) has attributes incl. `name`, `addressLine1`, `city`, `emsCode`
and `emsOIDCWellKnownUrl`, and an `id` like `SKO-E-<uuid>`. Keep `id` (→ `X-Skolengo-School-Id`),
`emsCode` (→ `X-Skolengo-Ems-Code`) and `emsOIDCWellKnownUrl` (→ §2).

`GET /schools-info` / `GET /schools-info/{id}` return school news/announcements.

---

## 4. Current user & students

```
GET /users-info/{userId}?include=students,students.school,school,schools,prioritySchool
```

- `{userId}` defaults to the token `sub`.
- Send `X-Skolengo-Ems-Code` here too: without it the call returns `500`. The school id header
  is not needed for this call.
- A **student** account's own info is at the root; a **parent** account has
  `type: legalRepresentativeUserInfo` and lists children under the `students` relationship
  (each `student`/`studentUserInfo` has `firstName`, `lastName`, `className`, and a `school`
  relationship).
- **Important:** a parent's children can be in **different establishments**. Use each student's
  own `school.id` in `X-Skolengo-School-Id` for requests about that student, not a single fixed
  school. (Requesting a student at a school that doesn't expose a feature can return `403`.)

---

## 5. Endpoint reference

All paths are relative to the base URL. `{studentId}` is a student resource id (`ESKO-P-…` or the
`sub`). Dates are `YYYY-MM-DD`.

### Homework (cahier de textes)

```
GET /homework-assignments
    ?filter[student.id]={studentId}
    &filter[dueDate][GE]={start}&filter[dueDate][LE]={end}
    &include=subject,teacher,teacher.person
    &fields[homework]=title,done,dueDateTime,html
    &fields[subject]=label,color
    &page[limit]=50
GET   /homework-assignments/{id}
PATCH /homework-assignments/{id}        # body: set "done" true/false
```
Homework attributes: `title`, `html` (full content), `dueDateTime`, `done`. Side-loaded `subject`
gives `label` + `color`. The sparse fieldsets are **required**: the same request without
`fields[homework]`/`fields[subject]` returns `500`. In practice the text often lives in `title`
while `html` is an empty document. `include=attachments` is rejected (`405`).

### Timetable / agenda

```
GET /agendas?filter[student.id]={studentId}&filter[date][GE]=…&filter[date][LE]=…
GET /agendas-definitions
GET /lessons/{lessonId}
GET /teachers-agendas
GET /users-calendars , /users-calendars-daily-views
```
With `include=lessons,lessons.subject,lessons.teachers`, each `agenda` is one day and the
`lesson` resources carry `startDateTime`, `endDateTime`, `title`, `location`, `canceled`,
`anyHomeworkToDoForTheLesson`; `subject` gives `label` + `color`, `teacher` gives `title`,
`firstName`, `lastName`. Lessons carry subject, room, teachers, times, cancellation flags. `scolengo-api` exposes a helper
to turn an agenda into iCalendar.

### Evaluations / grades / reports

```
GET /evaluations-settings?filter[student.id]={studentId}      # periods, skill colors
GET /evaluation-services?filter[student.id]={studentId}&filter[period.id]=…   # per-subject
GET /evaluations/{evaluationId}
GET /evaluations-results
GET /periodic-reports-files?filter[student.id]={studentId}    # term report PDFs (attachments)
```
When the school runs Pronote, `evaluations-settings` returns a single period labelled
"Période Pronote" and Skolengo proxies Pronote. On some schools `/evaluation-services` and
`/absence-files` then fail with a server-side `500` whatever the parameters.

### Messaging — classic ("Messagerie" / communications)

Parent/student ↔ school & teachers, threaded.

```
GET  /users-mail-settings/{userId}?include=folders,folders.parent,signature,contacts,contacts.person
GET  /communications?filter[folders.id]={folderId}
         &include=lastParticipation,lastParticipation.sender,lastParticipation.sender.person
         &page[limit]=10
GET  /communications/{id}
GET  /communications/{id}/participations          # messages in a thread
GET  /communications/{id}/participants
PATCH /communications/{id}/relationships/folders  # move thread between folders
POST /communications                              # start a thread
POST /participations                              # reply in a thread
GET  /contacts , /contacts-folders                # address book
```
`users-mail-settings` returns the folders (each with `name`, `position` and `type`: `INBOX`,
`SENT`, `TRASH`, `PERSONAL`). A communication has `subject`, `read`, `participationsNumber`,
`recipientsSummary` (HTML) and a `lastParticipation` (`dateTime`, `contentWithoutHtml`,
`sender`); `meta.totalResourceCount` gives the folder size. The participations' `content` and
`contentWithoutHtml` come back `null` unless the list asks for them with sparse fieldsets:
`fields[communication]=subject,read,participationsNumber,lastParticipation` and
`fields[participation]=dateTime,contentWithoutHtml,content,sender` (verified: this does not change the
`read` flags). Count `read: false` in the inbox
folder for an "unread messages" indicator.

### Messaging — "La Bulle" (instant messaging, Matrix-based)

Newer real-time chat, built on **Matrix** (the Element protocol). Not JSON:API.

```
GET /users-la-bulle-settings?fields[userLaBulleSetting]=homeserverUrl,pushGatewayUrl
GET /users-la-bulle-access-tokens?...
```
`homeserverUrl` + the access token let a Matrix client sync rooms/messages
(`/send/m.room.message/`, rooms, members). Requires the `ACCESS_LA_BULLE` capability. For a
read-only need, an unread-count is the realistic target; a full chat client is a separate project.

### School life

```
GET  /absence-files?filter[student.id]={studentId}
GET  /absence-files/{id}
POST /absence-files-states            # justify/complete an absence (COMPLETE_ABSENCE_FILES)
GET  /absence-reasons
GET  /punishments , /observations
GET  /attendance-registers-settings
GET  /schooling-events-wrappers
```

### Finance / catering

```
GET /invoices , /payments , /payments-due-dates
GET /wallets , /wallet-transactions      # canteen / e-wallet balance & history
```

### Attachments & notifications

```
GET  {attachment.url}                    # download; sends your bearer token — only follow URLs
                                         # returned by the API itself
POST /push-mobile-tokens                 # register an FCM token for push (app-only)
```

---

## 6. Capabilities (permissions)

`users-info` returns `attributes.permissions` as a list of
`{schoolId, service, permittedOperations}`; services seen include `TAF` (homework),
`CDT` (lessons), `MSG`, `EVAL`, `ABS`, `PUN`, `OBS`. A parent's children in different schools
get different services. The account advertises what it may do. Check these before calling a feature (and to explain a
`403`). Observed values include:

```
READ_HOMEWORK_ASSIGNMENTS, MARK_HOMEWORK_ASSIGNMENT_AS_DONE,
READ_MESSAGES, WRITE_MESSAGES, READ_EXTERNAL_MESSAGES, WRITE_EXTERNAL_MESSAGES, ACCESS_LA_BULLE,
READ_LESSONS, READ_LESSONS_DETAILS,
READ_EVALUATIONS,
READ_ABSENCE_FILES, READ_ABSENCE_FILES_DETAILS, COMPLETE_ABSENCE_FILES, READ_ATTENDANCE_REGISTERS,
READ_PUNISHMENTS, READ_PUNISHMENTS_DETAILS, READ_OBSERVATIONS, READ_OBSERVATIONS_DETAILS,
READ_CATERING_SERVICES, FILE_READ_WRITE
```

Not every ENT/school enables every feature (e.g. a lycée may not use the Skolengo *cahier de
textes* even if the collège in the same account does).

---

## 7. Practical notes

- **Reuse one HTTP client/connection** and close it cleanly. Poll at a reasonable cadence
  (e.g. every 15–30 min, not at night). Honour `apiCallRetryDelay`/`apiCallMaxRetries`.
- **Persist the rotating refresh token** on every refresh.
- **Per-student headers**: set `X-Skolengo-School-Id` to the relevant student's school.
- **Capturing the auth code** without a device: read the `skoapp-prod://…code=…` string from the
  final page's DOM; browsers block the custom-scheme navigation and show a benign
  "not secure" prompt.
- **Secrets**: the client_id/secret above are public; **user tokens are not** — never log, print,
  or commit them.

---

## 8. Credits & references

- [`maelgangloff/scolengo-api`](https://github.com/maelgangloff/scolengo-api) — Node.js client
  (GPL-3.0); the original source of endpoint shapes and the OIDC client.
- [`maelgangloff/scolengo-token`](https://github.com/maelgangloff/scolengo-token) — token helper.
- `scolengo-api` on PyPI — Python port.
- Official **Skolengo** app (Kosmos), Android v5.3.1 — decompiled (Flutter/Dart) to confirm the
  v5 auth flow, headers, endpoints and the Matrix-based "La Bulle".

*Compiled 2026-11-15. Unofficial; no affiliation with Kosmos/Skolengo. Endpoints may change.*
