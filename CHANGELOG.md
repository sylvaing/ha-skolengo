# Changelog

## Unreleased

- **README**: list of the Skolengo ENTs, by region and département, with their sign-in choice (#21).

## 0.2.0 — 2026-11-21

- **README**: screenshots of the cards made from invented data (`docs/screenshots/demo.html`).
- **Blueprints**: notify new messages; evening reminder of the homework due on the next school day (#20).

## 0.1.0 — 2026-11-21

First release.

- **Sign-in**: find the school, choose the identity provider, then type the EduConnect login and
  password; the integration signs in itself, without a browser. The password is not stored, only the
  session (refreshed and persisted automatically). Browser fallback (paste the `skoapp-prod://` address)
  for FranceConnect or a captcha. Reauthentication when the session dies.
- **Updates**: every 30 minutes by default (option), at most every 3 hours at night; only the services
  each school grants are read; one failing service keeps its last data and never hides the others.
- **Homework**: sensor and to-do list per student; ticking an item marks the homework done in the ENT
  when the account may do so (student accounts). Parent accounts only get read access from the ENT:
  the list and the card are then read-only.
- **Timetable**: lessons-of-the-day sensor, next-lesson sensor and calendar per student; cancelled
  lessons marked.
- **Messages**: unread sensor with the latest conversations and a preview of their last message, and the
  `skolengo_new_message` event.
- **Cards** shipped and registered by the integration: `skolengo-homework-card`,
  `skolengo-timetable-card`, `skolengo-messages-card` (visual editors, French and English).
- **Diagnostics** without personal data; own icon and logo.
