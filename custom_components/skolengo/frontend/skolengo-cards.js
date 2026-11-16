/*
 * Skolengo cards for Home Assistant: homework, timetable and messages.
 *
 * Shipped and registered by the Skolengo integration (no resource to add by hand).
 * The look and options follow the Pronote cards of lovelace-pronote
 * (https://github.com/delphiki/lovelace-pronote, MIT); this is independent code.
 *
 * Plain custom elements, no build step and no external library. Every text coming from the ENT
 * is inserted as text (escaped), never as HTML.
 */

const VERSION = "0.1.0";

const I18N = {
  en: {
    homework: "Homework",
    timetable: "Timetable",
    messages: "Messages",
    no_homework: "No homework",
    no_lessons: "No lessons",
    no_messages: "No messages",
    done: "Done",
    todo: "To do",
    done_count: "{n} done",
    canceled: "Cancelled",
    lunch_break: "Lunch break",
    free_time: "Free time",
    homework_due: "Homework due",
    unread: "{n} unread",
    open_ent: "Open the ENT",
    previous: "Previous day",
    next: "Next day",
    unavailable: "Entity unavailable",
    no_todo: "No to-do list found for this student",
    from: "From {a} to {b}",
  },
  fr: {
    homework: "Devoirs",
    timetable: "Emploi du temps",
    messages: "Messages",
    no_homework: "Aucun devoir",
    no_lessons: "Aucun cours",
    no_messages: "Aucun message",
    done: "Fait",
    todo: "À faire",
    done_count: "{n} fait(s)",
    canceled: "Annulé",
    lunch_break: "Pause déjeuner",
    free_time: "Temps libre",
    homework_due: "Devoir à rendre",
    unread: "{n} non lu(s)",
    open_ent: "Ouvrir l'ENT",
    previous: "Jour précédent",
    next: "Jour suivant",
    unavailable: "Entité indisponible",
    no_todo: "Aucune liste de devoirs trouvée pour cet élève",
    from: "De {a} à {b}",
  },
};

function t(hass, key, vars = {}) {
  const lang = (hass?.locale?.language || hass?.language || "en").split("-")[0];
  let text = (I18N[lang] || I18N.en)[key] || I18N.en[key] || key;
  for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, v);
  return text;
}

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

function safeColor(value) {
  return /^#[0-9a-fA-F]{3,8}$/.test(value || "") ? value : "var(--primary-color)";
}

function locale(hass) {
  return hass?.locale?.language || hass?.language || navigator.language;
}

function dayLabel(hass, isoDate) {
  const d = new Date(`${isoDate}T12:00:00`);
  const text = d.toLocaleDateString(locale(hass), { weekday: "long", day: "numeric", month: "long" });
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function shortDate(hass, iso) {
  const d = new Date(iso);
  const today = new Date();
  if (d.toDateString() === today.toDateString()) {
    return d.toLocaleTimeString(locale(hass), { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(locale(hass), { day: "numeric", month: "short" });
}

function localIsoDate(date) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

function endOfWeek() {
  const d = new Date();
  d.setDate(d.getDate() + ((7 - d.getDay()) % 7));
  return localIsoDate(d);
}

function groupBy(items, key) {
  const groups = new Map();
  for (const item of items) {
    const k = key(item);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(item);
  }
  return groups;
}

const BASE_STYLE = `
  ha-card { overflow: hidden; }
  .header { display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 12px 16px 4px; font-size: 1.15em; font-weight: 500; }
  .header .sub { font-size: 0.8em; font-weight: 400; color: var(--secondary-text-color); }
  .content { padding: 4px 16px 12px; }
  .day { margin-top: 10px; font-weight: 500; color: var(--primary-text-color);
    display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .day .hours { font-weight: 400; font-size: 0.85em; color: var(--secondary-text-color); }
  .row { display: flex; align-items: stretch; gap: 10px; padding: 6px 0; }
  .bar { width: 4px; border-radius: 2px; flex: none; }
  .main { flex: 1; min-width: 0; }
  .title { font-weight: 500; }
  .meta { font-size: 0.85em; color: var(--secondary-text-color); }
  .text { font-size: 0.9em; white-space: pre-line; overflow-wrap: anywhere; }
  .empty { padding: 8px 0; color: var(--secondary-text-color); }
  .dim { opacity: 0.5; }
  .strike .title, .strike .time { text-decoration: line-through; }
  .badge { display: inline-block; font-size: 0.75em; padding: 0 6px; border-radius: 8px;
    background: var(--error-color); color: var(--text-primary-color, #fff); margin-left: 6px;
    vertical-align: middle; }
  .badge.info { background: var(--warning-color); }
  .nav { display: flex; gap: 4px; }
  .nav button, .icon-button { background: none; border: none; cursor: pointer; padding: 4px;
    color: var(--secondary-text-color); border-radius: 50%; line-height: 0; }
  .nav button[disabled] { opacity: 0.3; cursor: default; }
  .warning { padding: 16px; color: var(--error-color); }
`;

class SkolengoBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._offset = 0;
  }

  setConfig(config) {
    if (!config || !config.entity) throw new Error("entity is required");
    this._config = { ...this.constructor.defaults, ...config };
    this._lastState = undefined;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const state = hass.states[this._config?.entity];
    // Re-render only when the entity changed (the hass object changes for every state in HA).
    if (state !== this._lastState || hass.locale !== this._lastLocale) {
      this._lastState = state;
      this._lastLocale = hass.locale;
      this._render();
    }
  }

  get hass() {
    return this._hass;
  }

  getCardSize() {
    return 4;
  }

  _render() {
    if (!this._config || !this._hass) return;
    const state = this._hass.states[this._config.entity];
    let body;
    if (!state || state.state === "unavailable") {
      body = `<div class="warning">${esc(t(this._hass, "unavailable"))}: ${esc(this._config.entity)}</div>`;
    } else {
      body = this._body(state);
    }
    this.shadowRoot.innerHTML = `<style>${BASE_STYLE}${this.constructor.style || ""}</style><ha-card>${body}</ha-card>`;
    this._bind();
  }

  _header(title, sub = "", nav = "") {
    if (!this._config.display_header) return nav ? `<div class="header"><span></span>${nav}</div>` : "";
    return `<div class="header"><span>${esc(title)}${sub ? ` <span class="sub">${esc(sub)}</span>` : ""}</span>${nav}</div>`;
  }

  _nav(count) {
    if (!this._config.enable_slider || count === 0) return "";
    this._offset = Math.max(0, Math.min(this._offset, count - 1));
    return `<div class="nav">
      <button data-nav="-1" title="${esc(t(this._hass, "previous"))}" ${this._offset === 0 ? "disabled" : ""}>
        <ha-icon icon="mdi:chevron-left"></ha-icon></button>
      <button data-nav="1" title="${esc(t(this._hass, "next"))}" ${this._offset >= count - 1 ? "disabled" : ""}>
        <ha-icon icon="mdi:chevron-right"></ha-icon></button></div>`;
  }

  _bind() {
    this.shadowRoot.querySelectorAll("[data-nav]").forEach((button) =>
      button.addEventListener("click", () => {
        this._offset += Number(button.dataset.nav);
        this._render();
      }),
    );
  }

  _student(state) {
    return state.attributes.student || "";
  }
}

/* ---------------------------------------------------------------------------------------------- */

class SkolengoHomeworkCard extends SkolengoBaseCard {
  static defaults = {
    display_header: true,
    current_week_only: false,
    reduce_done_homework: true,
    display_done_homework: true,
    enable_slider: false,
  };

  static style = `
    .check { flex: none; align-self: center; cursor: pointer; color: var(--secondary-text-color); }
    .check.done { color: var(--success-color, #4caf50); }
    .row.done .title { color: var(--secondary-text-color); }
  `;

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && Array.isArray(hass.states[id].attributes.homework),
    );
    return { entity: entity || "" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "skolengo" } } },
        { name: "title", selector: { text: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "display_header", selector: { boolean: {} } },
            { name: "current_week_only", selector: { boolean: {} } },
            { name: "display_done_homework", selector: { boolean: {} } },
            { name: "reduce_done_homework", selector: { boolean: {} } },
            { name: "enable_slider", selector: { boolean: {} } },
          ],
        },
      ],
    };
  }

  _body(state) {
    const c = this._config;
    let items = state.attributes.homework || [];
    if (c.current_week_only) {
      const end = endOfWeek();
      items = items.filter((h) => h.date <= end);
    }
    if (!c.display_done_homework) items = items.filter((h) => !h.done);
    const days = [...groupBy(items, (h) => h.date).entries()];
    const nav = this._nav(days.length);
    const shown = c.enable_slider ? days.slice(this._offset, this._offset + 1) : days;
    const title = c.title || `${t(this._hass, "homework")} ${this._student(state)}`.trim();
    let html = this._header(title, "", nav);
    html += `<div class="content">`;
    if (!shown.length) html += `<div class="empty">${esc(t(this._hass, "no_homework"))}</div>`;
    for (const [date, list] of shown) {
      html += `<div class="day">${esc(dayLabel(this._hass, date))}</div>`;
      for (const h of list) html += this._row(h);
    }
    return `${html}</div>`;
  }

  _row(h) {
    const c = this._config;
    const reduced = h.done && c.reduce_done_homework;
    const icon = h.done ? "mdi:check-circle" : "mdi:checkbox-blank-circle-outline";
    const label = t(this._hass, h.done ? "done" : "todo");
    const text = h.description && h.description !== h.title ? h.description : h.title;
    return `<div class="row ${h.done ? "done" : ""}">
      <div class="bar" style="background:${safeColor(h.background_color)}"></div>
      <div class="main">
        <div class="title">${esc(h.subject || h.title)}</div>
        ${reduced ? "" : `<div class="text">${esc(text)}</div>`}
        ${!reduced && h.teacher ? `<div class="meta">${esc(h.teacher)}</div>` : ""}
      </div>
      <ha-icon class="check ${h.done ? "done" : ""}" icon="${icon}" title="${esc(label)}"
        data-id="${esc(h.id)}" data-done="${h.done ? 1 : 0}"></ha-icon>
    </div>`;
  }

  _bind() {
    super._bind();
    this.shadowRoot.querySelectorAll(".check[data-id]").forEach((el) =>
      el.addEventListener("click", () => this._toggle(el.dataset.id, el.dataset.done !== "1")),
    );
  }

  _todoEntity() {
    if (this._config.todo_entity) return this._config.todo_entity;
    const entities = this._hass.entities || {};
    const device = entities[this._config.entity]?.device_id;
    if (!device) return undefined;
    return Object.keys(entities).find(
      (id) => id.startsWith("todo.") && entities[id].device_id === device && entities[id].platform === "skolengo",
    );
  }

  async _toggle(id, done) {
    const todo = this._todoEntity();
    if (!todo) {
      alert(t(this._hass, "no_todo"));
      return;
    }
    try {
      await this._hass.callService(
        "todo",
        "update_item",
        { item: id, status: done ? "completed" : "needs_action" },
        { entity_id: todo },
      );
    } catch (err) {
      alert(err?.message || String(err));
    }
  }
}

/* ---------------------------------------------------------------------------------------------- */

class SkolengoTimetableCard extends SkolengoBaseCard {
  static defaults = {
    display_header: true,
    display_lunch_break: true,
    display_classroom: true,
    display_teacher: true,
    display_day_hours: true,
    dim_ended_lessons: true,
    max_days: null,
    current_week_only: false,
    enable_slider: false,
    display_free_time_slots: true,
    switch_to_next_day: false,
  };

  static style = `
    .time { flex: none; width: 3.2em; font-size: 0.85em; text-align: right; color: var(--secondary-text-color); }
    .time div:first-child { color: var(--primary-text-color); }
    .separator { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 0.8em;
      color: var(--secondary-text-color); }
    .separator::before, .separator::after { content: ""; flex: 1; border-top: 1px dashed var(--divider-color); }
    .row.ongoing .bar { width: 6px; }
  `;

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && Array.isArray(hass.states[id].attributes.lessons),
    );
    return { entity: entity || "" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "skolengo" } } },
        { name: "title", selector: { text: {} } },
        { name: "max_days", selector: { number: { min: 1, max: 60, mode: "box" } } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "display_header", selector: { boolean: {} } },
            { name: "display_lunch_break", selector: { boolean: {} } },
            { name: "display_classroom", selector: { boolean: {} } },
            { name: "display_teacher", selector: { boolean: {} } },
            { name: "display_day_hours", selector: { boolean: {} } },
            { name: "dim_ended_lessons", selector: { boolean: {} } },
            { name: "current_week_only", selector: { boolean: {} } },
            { name: "enable_slider", selector: { boolean: {} } },
            { name: "display_free_time_slots", selector: { boolean: {} } },
            { name: "switch_to_next_day", selector: { boolean: {} } },
          ],
        },
      ],
    };
  }

  _body(state) {
    const c = this._config;
    let lessons = state.attributes.lessons || [];
    const today = localIsoDate(new Date());
    lessons = lessons.filter((l) => l.start_at.slice(0, 10) >= today);
    if (c.switch_to_next_day && state.attributes.day) {
      lessons = lessons.filter((l) => l.start_at.slice(0, 10) >= state.attributes.day);
    }
    if (c.current_week_only) {
      const end = endOfWeek();
      lessons = lessons.filter((l) => l.start_at.slice(0, 10) <= end);
    }
    let days = [...groupBy(lessons, (l) => l.start_at.slice(0, 10)).entries()];
    if (c.max_days) days = days.slice(0, Number(c.max_days));
    const nav = this._nav(days.length);
    const shown = c.enable_slider ? days.slice(this._offset, this._offset + 1) : days;
    const title = c.title || `${t(this._hass, "timetable")} ${this._student(state)}`.trim();
    let html = this._header(title, "", nav);
    html += `<div class="content">`;
    if (!shown.length) html += `<div class="empty">${esc(t(this._hass, "no_lessons"))}</div>`;
    for (const [date, list] of shown) html += this._day(date, list);
    return `${html}</div>`;
  }

  _day(date, list) {
    const c = this._config;
    const active = list.filter((l) => !l.canceled);
    const hours = active.length
      ? t(this._hass, "from", { a: active[0].start_time, b: active[active.length - 1].end_time })
      : "";
    let html = `<div class="day"><span>${esc(dayLabel(this._hass, date))}</span>${
      c.display_day_hours && hours ? `<span class="hours">${esc(hours)}</span>` : ""
    }</div>`;
    let previous = null;
    let lunchShown = false;
    for (const lesson of list) {
      if (previous && !previous.canceled) {
        if (c.display_lunch_break && !lunchShown && previous.is_morning && lesson.is_afternoon) {
          html += `<div class="separator">${esc(t(this._hass, "lunch_break"))}</div>`;
          lunchShown = true;
        } else if (c.display_free_time_slots && new Date(lesson.start_at) - new Date(previous.end_at) >= 15 * 60000) {
          html += `<div class="separator">${esc(t(this._hass, "free_time"))}</div>`;
        }
      }
      html += this._row(lesson);
      if (!lesson.canceled) previous = lesson;
    }
    return html;
  }

  _row(l) {
    const c = this._config;
    const classes = ["row", l.status];
    if (l.canceled) classes.push("strike", "dim");
    else if (c.dim_ended_lessons && l.status === "ended") classes.push("dim");
    const meta = [];
    if (c.display_classroom && l.classroom) meta.push(l.classroom);
    if (c.display_teacher && l.teacher_name) meta.push(l.teacher_name);
    const badges =
      (l.canceled ? `<span class="badge">${esc(t(this._hass, "canceled"))}</span>` : "") +
      (l.homework_due && !l.canceled ? `<span class="badge info">${esc(t(this._hass, "homework_due"))}</span>` : "");
    return `<div class="${classes.join(" ")}">
      <div class="time"><div>${esc(l.start_time)}</div><div>${esc(l.end_time)}</div></div>
      <div class="bar" style="background:${safeColor(l.background_color)}"></div>
      <div class="main">
        <div class="title">${esc(l.lesson)}${badges}</div>
        ${meta.length ? `<div class="meta">${esc(meta.join(" · "))}</div>` : ""}
      </div>
    </div>`;
  }
}

/* ---------------------------------------------------------------------------------------------- */

class SkolengoMessagesCard extends SkolengoBaseCard {
  static defaults = { display_header: true, max_messages: 5, unread_only: false, ent_url: "" };

  static style = `
    .row { cursor: default; }
    .row.unread .title { font-weight: 700; }
    .row.unread .bar { background: var(--primary-color); }
    .row .bar { background: transparent; }
    .top { display: flex; justify-content: space-between; gap: 8px; }
    .date { flex: none; font-size: 0.8em; color: var(--secondary-text-color); }
    .preview { font-size: 0.85em; color: var(--secondary-text-color); overflow: hidden;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
    a.ent { color: var(--primary-color); font-size: 0.85em; text-decoration: none; }
  `;

  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) => id.startsWith("sensor.") && Array.isArray(hass.states[id].attributes.messages),
    );
    return { entity: entity || "" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "sensor", integration: "skolengo" } } },
        { name: "title", selector: { text: {} } },
        { name: "max_messages", selector: { number: { min: 1, max: 20, mode: "box" } } },
        { name: "ent_url", selector: { text: { type: "url" } } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "display_header", selector: { boolean: {} } },
            { name: "unread_only", selector: { boolean: {} } },
          ],
        },
      ],
    };
  }

  _body(state) {
    const c = this._config;
    let messages = state.attributes.messages || [];
    if (c.unread_only) messages = messages.filter((m) => !m.read);
    messages = messages.slice(0, Number(c.max_messages) || 5);
    const unread = Number(state.state) || 0;
    const sub = unread ? t(this._hass, "unread", { n: unread }) : "";
    const link = /^https?:\/\//.test(c.ent_url || "")
      ? `<a class="ent" href="${esc(c.ent_url)}" target="_blank" rel="noreferrer">${esc(t(this._hass, "open_ent"))}</a>`
      : "";
    let html = this._header(c.title || t(this._hass, "messages"), sub, link);
    html += `<div class="content">`;
    if (!messages.length) html += `<div class="empty">${esc(t(this._hass, "no_messages"))}</div>`;
    for (const m of messages) {
      html += `<div class="row ${m.read ? "" : "unread"}">
        <div class="bar"></div>
        <div class="main">
          <div class="top"><span class="title">${esc(m.subject || "—")}</span>
            ${m.date ? `<span class="date">${esc(shortDate(this._hass, m.date))}</span>` : ""}</div>
          ${m.sender ? `<div class="meta">${esc(m.sender)}</div>` : ""}
          ${m.preview ? `<div class="preview">${esc(m.preview)}</div>` : ""}
        </div>
      </div>`;
    }
    return `${html}</div>`;
  }
}

/* ---------------------------------------------------------------------------------------------- */

const CARDS = [
  ["skolengo-homework-card", SkolengoHomeworkCard, "Skolengo homework", "Homework of a student, tick to mark done"],
  ["skolengo-timetable-card", SkolengoTimetableCard, "Skolengo timetable", "Lessons of the coming days"],
  ["skolengo-messages-card", SkolengoMessagesCard, "Skolengo messages", "Latest conversations of the ENT"],
];

window.customCards = window.customCards || [];
for (const [type, cls, name, description] of CARDS) {
  if (!customElements.get(type)) customElements.define(type, cls);
  if (!window.customCards.some((card) => card.type === type)) {
    window.customCards.push({
      type,
      name,
      description,
      preview: true,
      documentationURL: "https://github.com/sylvaing/ha-skolengo#cards",
    });
  }
}

console.info(`%c SKOLENGO-CARDS %c ${VERSION} `, "color:#fff;background:#3f51b5", "color:#3f51b5");
