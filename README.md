# Skolengo (ENT) for Home Assistant

> **Unofficial project.** Not affiliated with, endorsed by or supported by Kosmos.
> "Skolengo" is a trademark of its owner.

🇫🇷 [Version française](README.fr.md)

Home Assistant custom integration for **Skolengo**, the school ENT (digital workspace) by Kosmos used by
many French regions (e.g. *Mon ENT Occitanie*). It uses the same API as the Skolengo mobile app.

## Status

🚧 **In development — not usable yet.** Progress is tracked in the
[issues](https://github.com/sylvaing/ha-skolengo/issues) and
[milestones](https://github.com/sylvaing/ha-skolengo/milestones).

## Planned features (v0.1.0)

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

## Documentation

- [Skolengo mobile API — unofficial reference](docs/skolengo-api.md)

## Installation

Not available yet. Once v0.1.0 is released it will be installable through [HACS](https://hacs.xyz) as a
custom repository.

## Privacy

Your EduConnect password is sent only to EduConnect (`educonnect.education.gouv.fr`) during sign-in and
is not stored. The session tokens are stored in Home Assistant only and sent only to your ENT and to the
Skolengo API (`api.skolengo.com`), like the mobile app does. The integration reads your children's school
data: keep your Home Assistant access restricted accordingly.

## License

[MIT](LICENSE)
