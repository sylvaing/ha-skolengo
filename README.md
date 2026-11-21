# Skolengo (ENT) for Home Assistant

> **Unofficial project.** Not affiliated with, endorsed by or supported by Kosmos.
> "Skolengo" is a trademark of its owner.

🇫🇷 [Version française](README.fr.md)

Home Assistant custom integration for **Skolengo**, the school ENT (digital workspace) by Kosmos used by
many French regions (e.g. *Mon ENT Occitanie*). It uses the same API as the Skolengo mobile app.

## Status

**v0.1.0 — first release.** Tested with a parent account of *Mon ENT Occitanie*. Other Skolengo ENTs
should work but are untested: reports are welcome in the
[issues](https://github.com/sylvaing/ha-skolengo/issues). Changes are listed in the [changelog](CHANGELOG.md).

## Features

Per student, only for the services their school enables:

- **Homework** (cahier de textes): a sensor and a to-do list; ticking an item marks the homework as done
  in the ENT.
- **Timetable**: a sensor and a calendar (subjects, rooms, teachers, cancelled lessons).
- **Messages**: unread-messages sensor with the latest messages.
- **Lovelace cards** shipped with the integration: `skolengo-homework-card`, `skolengo-timetable-card`,
  `skolengo-messages-card`.

Sign-in: pick your school and your identity provider, then type your **EduConnect** login and password.
The integration signs in itself, without a browser; the password is not stored, only the refresh token.

Grades and absences are out of scope for v0.1.0: on schools that run Pronote, Skolengo only proxies them
and the API often fails. The [Pronote integration](https://github.com/delphiki/hass-pronote) covers them.

## Entities

| Entity | Per | State | For |
| --- | --- | --- | --- |
| `sensor.<student>_homework` | student (homework enabled) | homework not done | homework card |
| `todo.<student>_homework` | student (homework enabled) | homework not done | tick = done in the ENT |
| `sensor.<student>_timetable` | student (timetable enabled) | lessons of the current school day | timetable card |
| `sensor.<student>_next_lesson` | student (timetable enabled) | start of the next lesson | automations |
| `calendar.<student>_timetable` | student (timetable enabled) | current / next lesson | calendar |
| `sensor.<account>_unread_messages` | account (messaging enabled) | unread conversations | messages card |

The event `skolengo_new_message` is fired for each new unread message (`subject`, `sender`, `date`,
`preview`), to build notifications.

## Cards

The cards are shipped with the integration and loaded automatically: no resource to add. Add them from
the card picker (search "Skolengo") or in YAML. Their look and options follow the Pronote cards of
[lovelace-pronote](https://github.com/delphiki/lovelace-pronote) (independent code).

```yaml
type: custom:skolengo-homework-card
entity: sensor.lou_martin_homework
display_header: true
current_week_only: false
display_done_homework: true
reduce_done_homework: true   # done items: subject only
enable_slider: false         # one day at a time, with arrows
```

Click the circle of a homework to mark it done or not done (through the student's to-do list; set
`todo_entity` if it is not found automatically). Only a **student** account may do this: the ENT lets a
parent account read the homework only, so the list and the card are then read-only.

```yaml
type: custom:skolengo-timetable-card
entity: sensor.lou_martin_timetable
display_header: true
display_lunch_break: true
display_classroom: true
display_teacher: true
display_day_hours: true
dim_ended_lessons: true
display_free_time_slots: true
max_days: 5
current_week_only: false
enable_slider: false
switch_to_next_day: true     # once today's lessons are over, start at the next school day
```

```yaml
type: custom:skolengo-messages-card
entity: sensor.alex_martin_unread_messages
display_header: true
max_messages: 5
unread_only: false
ent_url: https://your-ent.example   # optional "Open the ENT" link
```

## Documentation

- [Skolengo mobile API — unofficial reference](docs/skolengo-api.md)

## Installation

Through [HACS](https://hacs.xyz):

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/sylvaing/ha-skolengo`, type **Integration**.
2. Install **Skolengo (ENT)**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Skolengo (ENT)**: find your school, choose how you
   sign in, then type your EduConnect login and password.

The cards are available right away (refresh the browser once after the restart).

## Privacy

Your EduConnect password is sent only to EduConnect (`educonnect.education.gouv.fr`) during sign-in and
is not stored. The session tokens are stored in Home Assistant only and sent only to your ENT and to the
Skolengo API (`api.skolengo.com`), like the mobile app does. The integration reads your children's school
data: keep your Home Assistant access restricted accordingly.

## License

[MIT](LICENSE)
