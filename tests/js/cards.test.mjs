// Rendering tests of the Lovelace cards, with a minimal DOM stub (node --test, no dependency).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const registry = new Map();
globalThis.window = globalThis;
globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c) };
globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = { innerHTML: "", querySelectorAll: () => [] };
    return this.shadowRoot;
  }
};
const source = readFileSync(new URL("../../custom_components/skolengo/frontend/skolengo-cards.js", import.meta.url), "utf8");
console.info = () => {};
new Function(source)();

const today = new Date();
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const day = iso(today);
const tomorrow = iso(new Date(today.getTime() + 86400000));

function hass(states) {
  return { states, locale: { language: "fr" }, language: "fr", entities: {} };
}

function render(type, config, state) {
  const card = new (registry.get(type))();
  card.setConfig(config);
  card.hass = hass({ [config.entity]: state });
  return card.shadowRoot.innerHTML;
}

test("the three cards are registered for the card picker", () => {
  for (const type of ["skolengo-homework-card", "skolengo-timetable-card", "skolengo-messages-card"]) {
    assert.ok(registry.get(type), type);
    assert.ok(window.customCards.some((c) => c.type === type));
  }
});

test("homework card groups by day and escapes the ENT texts", () => {
  const html = render("skolengo-homework-card", { entity: "sensor.lou_homework" }, {
    state: "1",
    attributes: {
      student: "Lou MARTIN",
      homework: [
        { id: "hw-1", date: day, subject: "MATHS", title: "p 41", description: "p 41", done: true, background_color: "#185abc" },
        { id: "hw-2", date: tomorrow, subject: "<b>ES</b>", title: "Ex", description: "Ex\n<img src=x onerror=alert(1)>", done: false, background_color: "red;}" },
      ],
    },
  });
  assert.match(html, /Devoirs Lou MARTIN/);
  assert.equal((html.match(/class="day"/g) || []).length, 2);
  assert.ok(!html.includes("<img"), "no HTML from the ENT");
  assert.match(html, /&lt;b&gt;ES&lt;\/b&gt;/);
  assert.match(html, /background:var\(--primary-color\)/, "invalid colours are replaced");
  assert.match(html, /data-id="hw-2" data-done="0"/);
});

test("homework card hides done homework when asked", () => {
  const html = render("skolengo-homework-card", { entity: "sensor.h", display_done_homework: false }, {
    state: "0",
    attributes: { homework: [{ id: "hw-1", date: day, subject: "MATHS", title: "p 41", done: true }] },
  });
  assert.match(html, /Aucun devoir/);
});

test("timetable card shows rooms, cancelled lessons and the lunch break", () => {
  const lesson = (id, start, end, extra = {}) => ({
    id, start_at: `${day}T${start}:00+01:00`, end_at: `${day}T${end}:00+01:00`, start_time: start, end_time: end,
    lesson: id.toUpperCase(), classroom: "B21", teacher_name: "M. ROUX", canceled: false, status: "upcoming",
    background_color: "#ffed00", is_morning: start < "12:00", is_afternoon: start >= "12:00", ...extra,
  });
  const html = render("skolengo-timetable-card", { entity: "sensor.t" }, {
    state: "2",
    attributes: {
      day,
      lessons: [lesson("hg", "08:05", "09:05"), lesson("ma", "09:05", "10:00", { canceled: true, status: "canceled" }), lesson("fr", "13:30", "14:25")],
    },
  });
  assert.match(html, /B21 · M\. ROUX/);
  assert.match(html, /row canceled strike dim/);
  assert.match(html, /Annulé/);
  assert.match(html, /Pause déjeuner/);
  assert.match(html, /De 08:05 à 14:25/);
});

test("messages card: unread first-class, limit and ENT link", () => {
  const messages = Array.from({ length: 8 }, (_, i) => ({
    id: `c-${i}`, subject: `Sujet ${i}`, sender: "Mme DURAND", date: today.toISOString(), read: i > 0, preview: "Bonjour",
  }));
  const html = render("skolengo-messages-card", { entity: "sensor.m", max_messages: 3, ent_url: "https://ent.example" }, {
    state: "1", attributes: { messages },
  });
  assert.equal((html.match(/class="row /g) || []).length, 3);
  assert.match(html, /row unread/);
  assert.match(html, /1 non lu/);
  assert.match(html, /href="https:\/\/ent.example"/);
  const unsafe = render("skolengo-messages-card", { entity: "sensor.m", ent_url: "javascript:alert(1)" }, {
    state: "0", attributes: { messages: [] },
  });
  assert.ok(!unsafe.includes("javascript:"));
});

test("an unavailable entity shows a warning", () => {
  const html = render("skolengo-messages-card", { entity: "sensor.m" }, { state: "unavailable", attributes: {} });
  assert.match(html, /Entité indisponible/);
});
