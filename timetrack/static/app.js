"use strict";

// ---------- Hilfsfunktionen ----------
const $ = (sel, root = document) => root.querySelector(sel);
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
  "September", "Oktober", "November", "Dezember"];
const WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const MARK_NAMES = { TU: "Urlaub", AU: "Krankheit", EGZ: "Gleitzeittag", NF: "Feiertag" };
const FLAG_TEXT = {
  open: "Arbeitszeit wurde nicht beendet (letzter Eintrag ist „work“).",
  missing: "Kein Eintrag an diesem Arbeitstag.",
  pause_short: "Zu wenig Pause eingetragen – gesetzliche Pause wurde automatisch abgezogen.",
  over9: "Mehr als 9 Stunden Arbeitszeit.",
  tu_over: "Mehr Urlaubstage eingetragen als verfügbar.",
  egz_neg: "Gleitzeittag bei negativem Überstundenkonto.",
  minus_neg: "Minusstunden an diesem Tag führen zu einem negativen Überstundenkonto.",
};
const FLAG_COLOR = { open: "red", tu_over: "orange", egz_neg: "orange", minus_neg: "orange",
  pause_short: "yellow", over9: "yellow", missing: "grey" };
const COLOR_ORDER = ["red", "orange", "yellow", "grey"];
const NO_WORK_MARKS = ["AU", "EGZ"]; // an diesen Tagen ist keine Arbeitszeit möglich

// Maskiert Text für das Einsetzen in HTML (innerHTML, Attributwerte).
// JEDER Wert aus Server/Datenbank, der in ein HTML-Template kommt, muss hier durch.
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function fmtDur(sec) {
  const neg = sec < 0;
  sec = Math.abs(Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return `${neg ? "−" : ""}${h}h ${String(m).padStart(2, "0")}m`;
}
function fmtSigned(sec) {
  return (sec > 0 ? "+" : "") + fmtDur(sec);
}
function setBalance(el, sec) {
  el.textContent = fmtSigned(sec);
  el.classList.toggle("neg", sec < 0);
  el.classList.toggle("pos", sec > 0);
}
function fmtDays(n) {
  return (Math.round(n * 100) / 100).toLocaleString("de-DE", { maximumFractionDigits: 2 });
}
// Dezimalzahl mit Komma oder Punkt, höchstens zwei Nachkommastellen
function parseDecimal(s) {
  const t = String(s).trim().replace(",", ".");
  return /^\d+(\.\d{1,2})?$/.test(t) ? Number(t) : null;
}
function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function deDate(iso) {
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}
function hhmm(isoDateTime) {
  return isoDateTime.slice(11, 16);
}
// Spiegel von calc.legal_net (gesetzlicher Pausenabzug)
function legalNet(gross, pause) {
  const need30 = Math.max(0, 1800 - pause), need45 = Math.max(0, 2700 - pause);
  if (gross > 9 * 3600) return Math.min(gross - need30, Math.max(9 * 3600, gross - need45));
  if (gross > 6 * 3600) return Math.max(6 * 3600, gross - need30);
  return gross;
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  // Ändernde Anfragen immer als JSON senden (verlangt der Server als CSRF-Schutz)
  if (method !== "GET") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body === undefined ? {} : body);
  }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { /* leer */ }
  if (!res.ok) throw new Error((data && data.error) || `Fehler ${res.status}`);
  return data;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
}
function handle(promise) {
  return promise.catch((e) => toast(e.message));
}

// ---------- Menü & Routing ----------
const menuBtn = $("#menu-btn"), menu = $("#menu");
menuBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  menu.hidden = !menu.hidden;
  menuBtn.setAttribute("aria-expanded", String(!menu.hidden));
});
document.addEventListener("click", () => { menu.hidden = true; menuBtn.setAttribute("aria-expanded", "false"); });

const VIEWS = {
  "": { el: "#view-main", title: "Stempeln", show: showMain },
  kalender: { el: "#view-calendar", title: "Kalender", show: showCalendar },
  jahre: { el: "#view-years", title: "Jahre & Einstellungen", show: showYears },
  export: { el: "#view-export", title: "Export & Datensicherung", show: showExport },
};
let currentView = null;

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  const name = VIEWS[parts[0]] ? parts[0] : "";
  currentView = name;
  for (const [key, v] of Object.entries(VIEWS)) $(v.el).hidden = key !== name;
  for (const a of menu.querySelectorAll("a")) a.classList.toggle("active", a.getAttribute("href") === `#/${name}`);
  $("#page-title").textContent = `timetrack · ${VIEWS[name].title}`;
  menu.hidden = true;
  VIEWS[name].show(parts.slice(1));
}
window.addEventListener("hashchange", route);

// ---------- Hauptseite ----------
let status = null, statusLoadedAt = 0, busy = false;

async function loadStatus() {
  status = await api("GET", "/api/status");
  statusLoadedAt = Date.now();
  renderMain();
}

function renderMain() {
  if (!status) return;
  const btn = $("#toggle");
  const working = status.state === "work";
  btn.className = `toggle ${working ? "work" : "pause"}`;
  $(".toggle-label", btn).textContent = working ? "WORK" : "PAUSE";

  const t = status.today;
  const elapsed = working ? Math.floor((Date.now() - statusLoadedAt) / 1000) : 0;
  const gross = t.gross + elapsed;
  const net = legalNet(gross, t.pause);
  $("#today-work").textContent = fmtDur(net);
  $("#today-pause").textContent = fmtDur(t.pause);

  let sub = "";
  if (status.since) {
    sub = working ? `Arbeit seit ${hhmm(status.since)}` : `Pause seit ${hhmm(status.since)}`;
    if (!working) {
      const serverNow = new Date(status.server_time).getTime() + (Date.now() - statusLoadedAt);
      const mins = Math.floor((serverNow - new Date(status.since).getTime()) / 60000);
      sub += ` (${fmtDur(mins * 60)})`;
    }
  }
  $("#toggle-sub").textContent = sub;

  const hints = [];
  if (gross !== net) hints.push(`Brutto ${fmtDur(gross)}, davon ${fmtDur(gross - net)} gesetzliche Pause automatisch abgezogen.`);
  if (t.target > 0) hints.push(`Soll heute: ${fmtDur(t.target)}.`);
  if (t.mark) hints.push(`Heute eingetragen: ${t.mark} (${t.mark_note || MARK_NAMES[t.mark]}).`);
  $("#today-hint").textContent = hints.join(" ");
  setBalance($("#main-balance"), status.balance);
  setBalance($("#main-today-delta"), t.delta + (net - t.net));

  const warn = $("#open-warning");
  if (status.open_days.length) {
    const links = status.open_days.slice(-5).map((d) => `<a href="#/kalender/${esc(d)}">${esc(deDate(d))}</a>`).join(", ");
    warn.innerHTML = `Arbeitszeit nicht beendet an: ${links}${status.open_days.length > 5 ? " …" : ""}`;
    warn.hidden = false;
  } else {
    warn.hidden = true;
  }
}

$("#toggle").addEventListener("click", async () => {
  if (busy || !status) return;
  busy = true;
  try {
    status = await api("POST", "/api/toggle", { from: status.state });
    statusLoadedAt = Date.now();
    renderMain();
  } catch (e) {
    toast(e.message);
  } finally {
    busy = false;
  }
});

function showMain() {
  handle(loadStatus());
}

setInterval(() => { if (currentView === "") renderMain(); }, 1000);
setInterval(() => { if (currentView === "" && !document.hidden) handle(loadStatus()); }, 60000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && currentView === "") handle(loadStatus());
});

// ---------- Kalender ----------
let calYear, calMonth, selectedDay = null, monthData = null;

function showCalendar(args) {
  const today = new Date();
  if (args[0] && /^\d{4}-\d{2}-\d{2}$/.test(args[0])) {
    selectedDay = args[0];
    calYear = +args[0].slice(0, 4);
    calMonth = +args[0].slice(5, 7);
  } else if (calYear === undefined) {
    calYear = today.getFullYear();
    calMonth = today.getMonth() + 1;
  }
  handle(loadMonth());
}

async function loadMonth() {
  monthData = await api("GET", `/api/month/${calYear}/${calMonth}`);
  renderMonth();
  if (selectedDay && selectedDay.startsWith(`${calYear}-${String(calMonth).padStart(2, "0")}`)) {
    await loadDay(selectedDay);
  } else {
    $("#day-panel").hidden = true;
  }
}

function dayColor(day) {
  const colors = day.flags.map((f) => FLAG_COLOR[f]);
  return COLOR_ORDER.filter((c) => colors.includes(c));
}

function renderMonth() {
  const m = monthData;
  $("#month-title").textContent = `${MONTHS[m.month - 1]} ${m.year}`;
  setBalance($("#cal-balance"), m.balance);
  $("#cal-vac-label").textContent = `Resturlaub ${m.year}`;
  $("#cal-vacation").textContent = `${fmtDays(m.vacation.remaining)} / ${fmtDays(m.vacation.available)} Tage`;
  $("#cal-vacation").classList.toggle("neg", m.vacation.remaining < 0);

  const cal = $("#calendar");
  cal.innerHTML = "";
  for (const wd of ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]) {
    const h = document.createElement("div");
    h.className = "cal-head";
    h.textContent = wd;
    cal.appendChild(h);
  }
  for (let i = 0; i < m.days[0].weekday; i++) {
    const e = document.createElement("div");
    e.className = "cal-day empty";
    cal.appendChild(e);
  }
  for (const day of m.days) {
    const cell = document.createElement("button");
    cell.type = "button";
    const colors = dayColor(day);
    const cls = ["cal-day"];
    if (day.weekday >= 5 || day.mark === "NF") cls.push("off");
    if (colors.length) cls.push(`c-${colors[0]}`);
    if (day.date === m.today) cls.push("today");
    if (day.date === selectedDay) cls.push("selected");
    cell.className = cls.join(" ");

    const parts = [];
    if (day.mark) parts.push(day.mark);
    if (day.stamps > 0) parts.push(fmtDur(day.net));
    cell.innerHTML = `<span class="cal-num">${+day.date.slice(8)}${day.has_note ? '<span class="cal-note" title="Kommentar vorhanden">*</span>' : ""}</span>
      <span class="cal-label">${esc(parts.join(" · "))}</span>
      <span class="cal-dots">${colors.slice(1).map((c) => `<i class="c-${c}-dot"></i>`).join("")}</span>`;
    const tips = day.flags.map((f) => FLAG_TEXT[f]);
    if (day.mark_note) tips.unshift(day.mark_note);
    cell.title = tips.join("\n");
    cell.addEventListener("click", () => {
      history.replaceState(null, "", `#/kalender/${day.date}`);
      selectedDay = day.date;
      renderMonth();
      handle(loadDay(day.date));
    });
    cal.appendChild(cell);
  }
}

function shiftMonth(delta) {
  calMonth += delta;
  if (calMonth < 1) { calMonth = 12; calYear--; }
  if (calMonth > 12) { calMonth = 1; calYear++; }
  handle(loadMonth());
}
$("#prev-month").addEventListener("click", () => shiftMonth(-1));
$("#next-month").addEventListener("click", () => shiftMonth(1));
$("#this-month").addEventListener("click", () => {
  const t = new Date();
  calYear = t.getFullYear();
  calMonth = t.getMonth() + 1;
  selectedDay = isoDate(t);
  history.replaceState(null, "", `#/kalender/${selectedDay}`);
  handle(loadMonth());
});

async function loadDay(iso) {
  renderDay(await api("GET", `/api/day/${iso}`));
}

// Nach Änderungen an einem Tag: Tagesansicht und Monat neu laden
async function afterDayChange(dayData) {
  renderDay(dayData);
  monthData = await api("GET", `/api/month/${calYear}/${calMonth}`);
  renderMonth();
}

function renderDay(d) {
  const panel = $("#day-panel");
  panel.hidden = false;
  const wd = WEEKDAYS[d.weekday];
  const markOptions = ["", "TU", "AU", "EGZ", "NF"].map((k) =>
    `<option value="${k}" ${d.mark === k || (!d.mark && !k) ? "selected" : ""}>${k ? `${k} – ${MARK_NAMES[k]}` : "– keine –"}</option>`).join("");
  const rows = d.entries.map((e) => `
    <tr data-id="${esc(e.id)}">
      <td><input type="time" step="1" value="${esc(e.time)}" class="e-time" aria-label="Uhrzeit"></td>
      <td><select class="e-kind" aria-label="Typ">
        <option value="work" ${e.kind === "work" ? "selected" : ""}>work (Arbeit beginnt)</option>
        <option value="pause" ${e.kind === "pause" ? "selected" : ""}>pause (Arbeit endet)</option>
      </select></td>
      <td><button type="button" class="danger e-del">Löschen</button></td>
    </tr>`).join("");
  const nextKind = d.entries.length && d.entries[d.entries.length - 1].kind === "work" ? "pause" : "work";

  const warnings = d.flags.map((f) => `<li>${FLAG_TEXT[f]}</li>`).join("");
  // Bei AU/EGZ werden keine Zeiten erfasst; die Zeiteingabe verschwindet.
  // Ältere Tage mit AU/EGZ UND Zeiten zeigen ihre Zeiten weiter an, damit sie gelöscht werden können.
  const noWork = NO_WORK_MARKS.includes(d.mark);
  const showTimes = !noWork || d.entries.length > 0;
  let timesHtml;
  if (!showTimes) {
    timesHtml = `<p class="hint">${esc(d.mark)} (${esc(MARK_NAMES[d.mark])}) eingetragen – keine Zeiterfassung an diesem Tag.
      Zum Eintragen von Zeiten die Tagesart auf „– keine –“ setzen.</p>`;
  } else {
    timesHtml = `
    ${noWork ? `<p class="banner warn">An diesem Tag sind ${esc(d.mark)} und Zeiten eingetragen. Bitte die Zeitstempel löschen oder die Tagesart entfernen.</p>` : ""}
    ${d.entries.length ? "" : '<p class="hint">Keine Zeitstempel an diesem Tag.</p>'}
    <table class="entries"><tbody>
      ${rows}
      ${noWork ? "" : `<tr class="add">
        <td><input type="time" step="1" id="new-time" aria-label="Neue Uhrzeit"></td>
        <td><select id="new-kind" aria-label="Neuer Typ">
          <option value="work" ${nextKind === "work" ? "selected" : ""}>work (Arbeit beginnt)</option>
          <option value="pause" ${nextKind === "pause" ? "selected" : ""}>pause (Arbeit endet)</option>
        </select></td>
        <td><button type="button" id="new-add">Hinzufügen</button></td>
      </tr>`}
    </tbody></table>`;
  }
  const timeStats = showTimes ? `
      <div><span>Arbeitszeit (brutto)</span><b>${fmtDur(d.gross)}</b></div>
      <div><span>Pausen eingetragen</span><b>${fmtDur(d.pause)}</b></div>
      <div><span>Gesetzl. Pausenabzug</span><b>${fmtDur(d.deduction)}</b></div>
      <div><span>Arbeitszeit (angerechnet)</span><b>${fmtDur(d.net)}</b></div>` : "";
  panel.innerHTML = `
    <div class="day-head">
      <h2>${esc(wd)}, ${esc(deDate(d.date))}${d.mark_note ? ` · ${esc(d.mark_note)}` : ""}</h2>
      <label>Tagesart <select id="mark-select">${markOptions}</select></label>
    </div>
    ${timesHtml}
    <div class="kv">${timeStats}
      <div><span>Soll</span><b>${fmtDur(d.target)}</b></div>
      <div><span>Saldo des Tages</span><b class="${d.delta < 0 ? "neg" : d.delta > 0 ? "pos" : ""}">${d.counted || d.stamps > 0 ? fmtSigned(d.delta) : "–"}</b></div>
    </div>
    ${warnings ? `<ul class="warnings">${warnings}</ul>` : ""}
    <div class="note">
      <label for="note-text">Kommentar</label>
      <textarea id="note-text" rows="3" maxlength="2000" placeholder="Kommentar zu diesem Tag"></textarea>
      <div><button type="button" id="note-save">Kommentar speichern</button></div>
    </div>`;

  const noteText = $("#note-text", panel);
  noteText.value = d.note || "";
  $("#note-save", panel).addEventListener("click", () =>
    handle(api("PUT", `/api/day/${d.date}/note`, { note: noteText.value })
      .then((res) => { toast(res.note ? "Kommentar gespeichert." : "Kommentar entfernt."); return afterDayChange(res); })));

  $("#mark-select", panel).addEventListener("change", (e) => {
    const mark = e.target.value || null;
    if (NO_WORK_MARKS.includes(mark) && d.entries.length) {
      toast(`${mark} kann nicht eingetragen werden: An diesem Tag sind bereits Zeiten eingetragen. Bitte zuerst alle Zeitstempel löschen.`);
      e.target.value = d.mark || "";
      return;
    }
    api("PUT", `/api/day/${d.date}/mark`, { mark }).then(afterDayChange).catch((err) => {
      toast(err.message);
      renderDay(d); // Auswahl zurücksetzen
    });
  });

  for (const tr of panel.querySelectorAll("tr[data-id]")) {
    const id = tr.dataset.id;
    const save = () => handle(api("PUT", `/api/stamps/${id}`, {
      time: $(".e-time", tr).value, kind: $(".e-kind", tr).value,
    }).then(afterDayChange));
    $(".e-time", tr).addEventListener("change", save);
    $(".e-kind", tr).addEventListener("change", save);
    $(".e-del", tr).addEventListener("click", () => {
      if (confirm("Eintrag löschen?")) handle(api("DELETE", `/api/stamps/${id}`).then(afterDayChange));
    });
  }
  const addBtn = $("#new-add", panel);
  if (addBtn) addBtn.addEventListener("click", () => {
    const time = $("#new-time", panel).value;
    if (!time) { toast("Bitte eine Uhrzeit angeben."); return; }
    handle(api("POST", `/api/day/${d.date}/stamps`, { time, kind: $("#new-kind", panel).value }).then(afterDayChange));
  });
}

// ---------- Jahre & Einstellungen ----------
function parseBalance(s) {
  const m = s.trim().replace("−", "-").match(/^([+-]?)(\d+)(?::(\d{1,2}))?$/);
  if (!m) return null;
  const sec = (+m[2] * 60 + +(m[3] || 0)) * 60;
  return m[1] === "-" ? -sec : sec;
}
function balanceInput(sec) {
  const neg = sec < 0;
  const min = Math.round(Math.abs(sec) / 60);
  return `${neg ? "-" : "+"}${Math.floor(min / 60)}:${String(min % 60).padStart(2, "0")}`;
}

async function showYears() {
  handle(api("GET", "/api/years").then(renderYears));
}

function renderYears(data) {
  const f = $("#settings-form");
  f.start_date.value = data.start_date;
  f.start_balance.value = balanceInput(data.start_balance);
  f.state.value = `${data.holiday_state_name} (${data.holiday_state})`;
  setBalance($("#years-balance"), data.balance);

  const tb = $("#years-body");
  tb.innerHTML = data.years.map((y) => `
    <tr data-year="${esc(y.year)}" class="${y.before_start ? "inactive" : ""}">
      <td><strong>${esc(y.year)}</strong></td>
      <td><input type="text" inputmode="decimal" class="y-vac" value="${esc(fmtDays(y.vacation_days))}" aria-label="Urlaubstage"></td>
      <td><input type="text" inputmode="decimal" class="y-week" value="${esc(fmtDays(y.weekly_minutes / 60))}" aria-label="Wochenstunden"></td>
      <td>${y.before_start ? "–" : fmtDays(y.carry_in)}</td>
      <td>${y.before_start ? "–" : fmtDays(y.available)}</td>
      <td>${y.before_start ? "–" : fmtDays(y.taken)}</td>
      <td>${y.before_start ? "–" : fmtDays(y.planned)}</td>
      <td class="${y.remaining < 0 ? "neg" : ""}">${y.before_start ? "–" : fmtDays(y.remaining)}</td>
      <td class="${y.overtime < 0 ? "neg" : y.overtime > 0 ? "pos" : ""}">${y.before_start ? "–" : fmtSigned(y.overtime)}</td>
      <td>
        <button type="button" class="y-save">Speichern</button>
        <button type="button" class="secondary y-hol" title="Gesetzliche Feiertage (erneut) als NF eintragen">Feiertage</button>
      </td>
    </tr>`).join("");
  for (const tr of tb.querySelectorAll("tr")) {
    const y = tr.dataset.year;
    $(".y-save", tr).addEventListener("click", () => {
      const vac = parseDecimal($(".y-vac", tr).value), week = parseDecimal($(".y-week", tr).value);
      if (vac === null || week === null) {
        toast("Bitte Zahlen mit höchstens zwei Nachkommastellen eingeben, z. B. 27,5 oder 39,8.");
        return;
      }
      handle(api("PUT", `/api/years/${y}`, { vacation_days: vac, weekly_hours: week })
        .then((d) => { renderYears(d); toast(`Jahr ${y} gespeichert.`); }));
    });
    $(".y-hol", tr).addEventListener("click", () => handle(api("POST", `/api/years/${y}/holidays`)
      .then((d) => { renderYears(d); toast(`Feiertage für ${y} eingetragen.`); })));
  }
}

$("#settings-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target;
  const bal = parseBalance(f.start_balance.value);
  if (bal === null) { toast("Startsaldo bitte als Stunden:Minuten angeben, z. B. +12:30"); return; }
  handle(api("PUT", "/api/settings", { start_date: f.start_date.value, start_balance: bal })
    .then((d) => { renderYears(d); toast("Einstellungen gespeichert."); }));
});

$("#add-year").addEventListener("submit", (e) => {
  e.preventDefault();
  handle(api("POST", "/api/years", { year: +e.target.year.value })
    .then((d) => { e.target.reset(); renderYears(d); }));
});

// ---------- Export & Datensicherung ----------
function showExport() {
  const end = new Date();
  const start = new Date(end);
  start.setFullYear(end.getFullYear() - 2);
  if (start.getMonth() !== end.getMonth()) start.setDate(0); // 29.02. -> 28.02.
  $("#export-range").textContent = `${deDate(isoDate(start))} bis ${deDate(isoDate(end))}`;
}

$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = e.target.file.files[0];
  if (!file) return;
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch (_) {
    toast("Die Datei ist keine gültige Datensicherung (kein JSON).");
    return;
  }
  if (!confirm(`Datensicherung „${file.name}“ einspielen?\n\nDabei werden ALLE vorhandenen Daten gelöscht.`)) return;
  if (!confirm("Wirklich sicher? Alle aktuellen Zeitstempel, Tagesarten, Jahre und Einstellungen "
    + "werden unwiderruflich gelöscht und durch die Datei ersetzt.")) return;
  try {
    const res = await api("POST", "/api/backup", data);
    const c = res.imported;
    e.target.reset();
    toast(`Eingespielt: ${c.stamps} Zeitstempel, ${c.day_marks} Tagesarten, ${c.years} Jahre.`);
    status = null;
    calYear = undefined;
  } catch (err) {
    toast(`Einspielen fehlgeschlagen: ${err.message}`);
  }
});

route();
