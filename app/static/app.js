"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const PLATFORMS = {
  steam: { label: "Steam", short: "STEAM" },
  playstation: { label: "PlayStation", short: "PS" },
  xbox: { label: "Xbox", short: "XBOX" },
  nintendo: { label: "Nintendo", short: "NSW" },
  other: { label: "Sonstige", short: "PC" },
};
const STATUS = {
  completed: { label: "100 %", ribbon: "100 %" },
  finished: { label: "Durchgespielt", ribbon: "Durchgespielt" },
  playing: { label: "Spielt gerade", ribbon: "Spielt" },
  backlog: { label: "Backlog", ribbon: "Backlog" },
  shelved: { label: "Pausiert", ribbon: "Pausiert" },
  none: { label: "Ohne Status", ribbon: "" },
};
const LS = "trophaeenschrank.view";

const state = {
  games: [],
  settings: {},
  styles: [],
  stats: null,
  view: Object.assign(
    { platforms: [], statuses: ["completed", "finished", "playing"], sort: "smart", year: "", tag: "", group: false, hidden: false, q: "" },
    JSON.parse(localStorage.getItem(LS) || "{}")
  ),
  current: null,
};
const saveView = () => { try { localStorage.setItem(LS, JSON.stringify({ ...state.view, q: "" })); } catch (_) {} };

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Fehler ${r.status}`);
  return data;
}

function toast(msg, err = false, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), ms);
}

// ------------------------------------------------------------- Formatierung
const fmtDate = (ts) => ts ? new Date(ts * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "numeric" }) : "";
const fmtHours = (min) => min ? `${(min / 60).toLocaleString("de-DE", { maximumFractionDigits: 1 })} h` : "–";
function relDay(ts) {
  if (!ts) return "nie";
  const d = new Date(ts * 1000), now = new Date();
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  if (days === 0) return `Heute, ${time}`;
  if (days === 1) return `Gestern, ${time}`;
  if (days < 7) return `vor ${days} Tagen`;
  return fmtDate(ts);
}
const yearOf = (ts) => ts ? new Date(ts * 1000).getFullYear() : null;
const pct = (g) => g.total ? Math.round((g.unlocked / g.total) * 100) : (g.status === "completed" ? 100 : 0);
const statusClass = (g) => g.status === "completed" && g.platinum ? "platinum" : g.status;
const ribbon = (g) => g.status === "completed" && g.platinum ? "Platin" : STATUS[g.status]?.ribbon || "";
const coverUrl = (g, style) => `/cover/${g.id}?style=${encodeURIComponent(style || state.settings.cover_style || "official")}&v=${g.updated_at}${String(style || state.settings.cover_style || "").startsWith("case") ? `-${state.settings.case_color}-${state.settings.case_marks}-${state.settings.case_ps_platinum}-${g.status}` : ""}`;
const activityTs = (g) => Math.max(g.last_played || 0, g.completed_at || 0);
function cardDate(g) {
  if (g.status === "completed" || g.status === "finished") return fmtDate(g.completed_at || g.last_played);
  if (g.status === "playing" && g.last_played) return relDay(g.last_played);
  return g.last_played ? fmtDate(g.last_played) : "";
}

// ------------------------------------------------------------------- Laden
async function loadAll() {
  const [games, settings, styles, stats] = await Promise.all([
    api("/api/games"), api("/api/settings"), api("/api/styles"), api("/api/stats"),
  ]);
  Object.assign(state, { games, settings, styles, stats });
  renderStyleSelect();
  renderAll();
}

function renderAll() {
  renderHero();
  renderStats();
  renderChips();
  renderSelects();
  renderGrid();
}

// --------------------------------------------------------------- Hero
function renderHero() {
  const hero = $("#hero");
  const g = state.games
    .filter((x) => !x.hidden && x.last_played && x.status !== "completed")
    .sort((a, b) => b.last_played - a.last_played)[0];
  if (!g) return hero.classList.add("hidden");
  hero.classList.remove("hidden");
  const p = pct(g);
  if (g.platform === "steam") {
    // Breites Steam-Hero-Bild, falls vorhanden – sonst bleibt das Cover rechts stehen
    const src = `https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/${g.ext_id}/library_hero.jpg`;
    const im = new Image();
    im.onload = () => {
      const sharp = document.createElement("div");
      sharp.className = "bg sharp";
      sharp.style.backgroundImage = `url('${src}')`;
      hero.querySelector(".bg.blur")?.after(sharp);
    };
    im.src = src;
  }
  hero.innerHTML = `<div class="bg blur" style="background-image:url('${coverUrl(g)}')"></div>
  <div class="shade"></div>
  <img class="hero-cover" src="${coverUrl(g)}" alt="">
  <div class="in">
    <div class="kicker">WEITERSPIELEN · ${esc(PLATFORMS[g.platform]?.label)}</div>
    <h1>${esc(g.title)}</h1>
    <div class="meta">${esc(relDay(g.last_played))}${g.playtime_min ? ` · ${fmtHours(g.playtime_min)} gespielt` : ""}${g.playtime_2w ? ` · ${fmtHours(g.playtime_2w)} in zwei Wochen` : ""}</div>
    ${g.total ? `<div class="bar"><div class="track"><i style="width:${p}%"></i></div>${g.unlocked} von ${g.total} ${g.platform === "playstation" ? "Trophäen" : "Erfolgen"}</div>` : ""}
  </div>`;
  hero.onclick = () => openDetail(g.id);
}

// -------------------------------------------------------------- Statistik
function renderStats() {
  const s = state.stats;
  if (!s) return;
  const thisYear = new Date().getFullYear();
  const years = Object.entries(s.by_year).map(([y, n]) => [Number(y), n]);
  if (!years.find(([y]) => y === thisYear)) years.push([thisYear, 0]);
  years.sort((a, b) => a[0] - b[0]);
  const shown = years.slice(-8);
  const max = Math.max(1, ...shown.map(([, n]) => n));
  const plat = Object.entries(s.by_platform).sort((a, b) => b[1] - a[1])
    .map(([p, n]) => `${PLATFORMS[p]?.label || p}: ${n}`).join(" · ");
  $("#stats").innerHTML = `
    <div class="stat"><b>${s.by_year[thisYear] || 0}</b><span>100 % in ${thisYear}</span></div>
    <div class="stat"><b>${s.completed}</b><span>100 % insgesamt</span></div>
    <div class="stat"><b>${s.platinum}</b><span>Platin-Trophäen</span></div>
    <div class="stat"><b>${s.total}</b><span>${esc(plat || "Spiele in der Bibliothek")}</span></div>
    <div class="stat years" title="Abschlüsse pro Jahr – klicken zum Filtern">
      ${shown.map(([y, n]) => `<div class="y ${String(state.view.year) === String(y) ? "on" : ""}" data-year="${y}">
        <span>${n}</span><i style="height:${Math.round((n / max) * (innerWidth < 700 ? 24 : 44))}px"></i>${y}</div>`).join("")}
    </div>`;
  $("#stats").querySelectorAll(".y").forEach((el) => el.onclick = () => {
    state.view.year = state.view.year === el.dataset.year ? "" : el.dataset.year;
    if (state.view.year) state.view.statuses = ["completed"];
    saveView(); renderAll();
  });
}

// ----------------------------------------------------------------- Filter
function baseList() {
  return state.games.filter((g) => state.view.hidden || !g.hidden);
}

function renderChips() {
  const list = baseList();
  const pc = {}, sc = {};
  list.forEach((g) => { pc[g.platform] = (pc[g.platform] || 0) + 1; sc[g.status] = (sc[g.status] || 0) + 1; });
  const v = state.view;
  $("#platformChips").innerHTML =
    `<span class="chip ${v.platforms.length ? "" : "on"}" data-p="">Alle Plattformen</span>` +
    Object.keys(PLATFORMS).filter((p) => pc[p]).map((p) =>
      `<span class="chip ${v.platforms.includes(p) ? "on" : ""}" data-p="${p}">${PLATFORMS[p].label}<small>${pc[p]}</small></span>`).join("");
  $("#statusChips").innerHTML = Object.keys(STATUS).map((s) =>
    `<span class="chip ${v.statuses.includes(s) ? "on" : ""}" data-s="${s}"><span class="dot ${s}"></span>${STATUS[s].label}<small>${sc[s] || 0}</small></span>`).join("");

  $("#platformChips").querySelectorAll(".chip").forEach((c) => c.onclick = () => {
    const p = c.dataset.p;
    v.platforms = !p ? [] : v.platforms.includes(p) ? v.platforms.filter((x) => x !== p) : [...v.platforms, p];
    saveView(); renderChips(); renderGrid();
  });
  $("#statusChips").querySelectorAll(".chip").forEach((c) => c.onclick = () => {
    const s = c.dataset.s;
    v.statuses = v.statuses.includes(s) ? v.statuses.filter((x) => x !== s) : [...v.statuses, s];
    saveView(); renderChips(); renderGrid();
  });
}

function renderSelects() {
  const years = [...new Set(state.games.map((g) => yearOf(g.completed_at)).filter(Boolean))].sort((a, b) => b - a);
  $("#yearSelect").innerHTML = `<option value="">Alle</option>` + years.map((y) => `<option>${y}</option>`).join("");
  $("#yearSelect").value = state.view.year;
  const tags = [...new Set(state.games.flatMap((g) => g.tags))].sort((a, b) => a.localeCompare(b, "de"));
  $("#tagSelect").innerHTML = `<option value="">Alle</option>` + tags.map((t) => `<option>${esc(t)}</option>`).join("");
  $("#tagSelect").value = state.view.tag;
  $("#sortSelect").value = state.view.sort;
  $("#groupYear").checked = state.view.group;
  $("#showHidden").checked = state.view.hidden;
}

function filtered() {
  const v = state.view, q = v.q.trim().toLowerCase();
  let list = baseList().filter((g) =>
    (!v.platforms.length || v.platforms.includes(g.platform)) &&
    (!v.statuses.length || v.statuses.includes(g.status)) &&
    (!v.tag || g.tags.includes(v.tag)) &&
    (!v.year || String(yearOf(g.completed_at)) === String(v.year)) &&
    (!q || g.title.toLowerCase().includes(q) || g.tags.some((t) => t.toLowerCase().includes(q))));
  const by = {
    smart: (a, b) => (b.status === "playing") - (a.status === "playing") || activityTs(b) - activityTs(a),
    completed: (a, b) => (b.completed_at || 0) - (a.completed_at || 0) || b.last_played - a.last_played,
    played: (a, b) => (b.last_played || 0) - (a.last_played || 0),
    title: (a, b) => a.title.localeCompare(b.title, "de"),
    progress: (a, b) => pct(b) - pct(a) || b.unlocked - a.unlocked,
    playtime: (a, b) => (b.playtime_min || 0) - (a.playtime_min || 0),
  }[v.sort] || (() => 0);
  return list.sort(by);
}

function cardHtml(g) {
  const p = pct(g);
  return `<div class="card s-${statusClass(g)} ${g.hidden ? "hid" : ""}" data-id="${g.id}" title="${esc(g.title)}">
    <img loading="lazy" src="${coverUrl(g)}" alt="${esc(g.title)}">
    <div class="ribbon">${esc(ribbon(g))}</div>
    <span class="plat">${PLATFORMS[g.platform]?.short || ""}</span>
    ${g.total && p < 100 && g.unlocked ? `<div class="prog"><i style="width:${p}%"></i></div>` : ""}
    <div class="ttl">${esc(g.title)}${g.total ? `<br><small>${g.unlocked}/${g.total}</small>` : ""}</div>
    ${cardDate(g) ? `<div class="date">${esc(cardDate(g))}</div>` : ""}
  </div>`;
}

function renderGrid() {
  const list = filtered();
  const grid = $("#grid");
  $("#countLabel").textContent = `${list.length} von ${baseList().length} Spielen`;
  const empty = $("#empty");
  if (!state.games.length) {
    empty.innerHTML = `Noch keine Spiele da.<br>Trag in den <a href="#" id="emptySettings">Einstellungen</a> deinen Steam-API-Key ein und starte den Abgleich –<br>oder füge Spiele über ＋ von Hand hinzu.`;
    empty.classList.remove("hidden");
    $("#emptySettings").onclick = (e) => { e.preventDefault(); openSettings(); };
  } else if (!list.length) {
    empty.textContent = "Keine Spiele für diese Filter.";
    empty.classList.remove("hidden");
  } else empty.classList.add("hidden");

  if (state.view.group) {
    const groups = new Map();
    list.forEach((g) => {
      const y = yearOf(g.completed_at) || yearOf(g.last_played) || "Ohne Datum";
      if (!groups.has(y)) groups.set(y, []);
      groups.get(y).push(g);
    });
    const keys = [...groups.keys()].sort((a, b) => (typeof b === "number" ? b : -1) - (typeof a === "number" ? a : -1));
    grid.innerHTML = keys.map((k) => {
      const items = groups.get(k);
      const done = items.filter((g) => g.status === "completed").length;
      return `<h3 class="group-title">${k}<small>${items.length} Spiele · ${done}× 100 %</small></h3>` + items.map(cardHtml).join("");
    }).join("");
  } else grid.innerHTML = list.map(cardHtml).join("");
}

$("#grid").addEventListener("click", (e) => {
  const c = e.target.closest(".card");
  if (c) openDetail(Number(c.dataset.id));
});

// --------------------------------------------------------------- Detail
function openDetail(id) {
  const g = state.games.find((x) => x.id === id);
  if (!g) return;
  state.current = g;
  const dlg = $("#detailDlg");
  const p = pct(g);
  const s = state.settings;
  const steamLinks = g.platform === "steam" ? `
      <a href="https://store.steampowered.com/app/${g.ext_id}" target="_blank" rel="noopener">Steam-Shop</a>
      <a href="steam://run/${g.ext_id}">Starten</a>
      <a href="https://steamcommunity.com/stats/${g.ext_id}/achievements" target="_blank" rel="noopener">Erfolge (global)</a>` : "";
  const dateVal = g.completed_at ? new Date(g.completed_at * 1000).toISOString().slice(0, 10) : "";
  const unit = g.platform === "playstation" ? "Trophäen" : "Erfolge";
  dlg.innerHTML = `
    <div class="dlg-head" style="margin:0 0 12px"><h2>${esc(g.title)}</h2><button class="x" data-close>✕</button></div>
    <div class="detail">
      <div class="cv">
        <img src="${coverUrl(g)}" alt="">
        <button class="btn" id="pickCover">Cover ändern</button>
      </div>
      <div>
        <div class="sub">${esc(PLATFORMS[g.platform]?.label)}${g.sub_platform ? " · " + esc(g.sub_platform) : ""}${g.manual ? " · manuell" : ""}</div>
        ${g.total ? `<div class="progress"><div class="track ${p === 100 ? "full" : ""}"><i style="width:${p}%"></i></div><b>${p} %</b> ${g.unlocked}/${g.total} ${unit}</div>` : ""}
        <div class="facts">
          <div><b>${fmtHours(g.playtime_min)}</b><span>Spielzeit</span></div>
          <div><b>${esc(relDay(g.last_played))}</b><span>Zuletzt gespielt</span></div>
          <div><b>${g.completed_at ? fmtDate(g.completed_at) : "–"}</b><span>Abgeschlossen</span></div>
          ${g.platinum ? `<div><b>🏆 Platin</b><span>Trophäe</span></div>` : ""}
        </div>
        <div class="links">${steamLinks}</div>
        <form id="detailForm">
          <div class="two">
            <label>Status
              <select name="status">
                ${Object.entries(STATUS).map(([k, v]) => `<option value="${k}" ${k === g.status ? "selected" : ""}>${v.label}</option>`).join("")}
              </select>
            </label>
            <label>Abgeschlossen am<input type="date" name="completed_at" value="${dateVal}"></label>
          </div>
          ${!g.manual ? `<label class="check" style="margin-top:0;margin-bottom:10px"><input type="checkbox" name="status_auto" ${g.status_locked ? "" : "checked"}> Status automatisch aus dem Abgleich bestimmen</label>` : `
          <div class="three">
            <label>Erreicht<input type="number" name="unlocked" min="0" value="${g.unlocked || ""}"></label>
            <label>Gesamt<input type="number" name="total" min="0" value="${g.total || ""}"></label>
            <label class="check"><input type="checkbox" name="platinum" ${g.platinum ? "checked" : ""}> Platin</label>
          </div>`}
          <label>Tags (kommagetrennt)<input name="tags" value="${esc(g.tags.join(", "))}"></label>
          <label>Notizen<textarea name="notes" rows="3">${esc(g.notes)}</textarea></label>
          <div class="dlg-foot">
            <button type="button" class="btn danger" id="hideBtn">${g.manual ? "Löschen" : g.hidden ? "Wieder einblenden" : "Ausblenden"}</button>
            <button type="submit" class="btn primary">Speichern</button>
          </div>
        </form>
      </div>
    </div>`;
  dlg.showModal();
  $("#pickCover").onclick = () => openCoverPicker(g);
  $("#hideBtn").onclick = async () => {
    if (g.manual) {
      if (!confirm(`„${g.title}“ wirklich löschen?`)) return;
      await api(`/api/games/${g.id}`, { method: "DELETE" });
    } else {
      await api(`/api/games/${g.id}`, { method: "PATCH", body: { hidden: !g.hidden } });
    }
    dlg.close(); await refresh();
  };
  const statusSel = $("#detailForm [name=status]");
  const autoBox = $("#detailForm [name=status_auto]");
  if (autoBox) statusSel.onchange = () => { autoBox.checked = false; };
  $("#detailForm").onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      completed_at: f.get("completed_at") || 0,
      tags: f.get("tags"),
      notes: f.get("notes"),
    };
    if (f.get("status") !== g.status) body.status = f.get("status");
    if (autoBox) body.status_auto = autoBox.checked;
    if (g.manual) Object.assign(body, { unlocked: f.get("unlocked"), total: f.get("total"), platinum: !!f.get("platinum") });
    if (body.completed_at === dateVal) delete body.completed_at; // unverändert → automatische Datumsbestimmung behalten
    try {
      await api(`/api/games/${g.id}`, { method: "PATCH", body });
      dlg.close(); await refresh(); toast("Gespeichert");
    } catch (err) { toast(err.message, true); }
  };
}

// ----------------------------------------------------------- Cover-Picker
async function openCoverPicker(g) {
  const dlg = $("#coverDlg");
  const box = $("#coverOptions");
  box.innerHTML = `<p class="hint">Lade Vorschläge …</p>`;
  $("#coverUrl").value = g.cover_override || "";
  dlg.showModal();
  const set = async (url) => {
    await api(`/api/games/${g.id}`, { method: "PATCH", body: { cover_override: url } });
    dlg.close(); $("#detailDlg").close(); await refresh(); openDetail(g.id);
  };
  $("#coverUrlBtn").onclick = () => set($("#coverUrl").value.trim());
  $("#coverResetBtn").onclick = () => set("");
  try {
    const opts = await api(`/api/games/${g.id}/cover-options`);
    if (!state.settings.sgdb_api_key) opts.push({ hint: true });
    box.innerHTML = opts.map((o, i) => o.hint
      ? `<p class="hint" style="grid-column:1/-1">Mit einem SteamGridDB-API-Key (Einstellungen) bekommst du hier dutzende alternative Cover pro Spiel.</p>`
      : `<figure data-i="${i}"><img loading="lazy" src="${esc(o.thumb)}" onerror="this.closest('figure').remove()"><figcaption>${esc(o.label)}</figcaption></figure>`).join("");
    box.querySelectorAll("figure").forEach((f) => f.onclick = () => set(opts[Number(f.dataset.i)].url));
  } catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}

// --------------------------------------------------------------- Stil
function renderStyleSelect() {
  const sel = $("#styleSelect");
  sel.innerHTML = state.styles.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");
  sel.value = state.settings.cover_style || "official";
  if (!sel.value) sel.value = "official";
  sel.classList.toggle("hidden", state.styles.length < 2);
  document.body.classList.toggle("style-case", sel.value.startsWith("case"));
}
$("#styleSelect").onchange = async (e) => {
  state.settings = await api("/api/settings", { method: "POST", body: { cover_style: e.target.value } });
  document.body.classList.toggle("style-case", e.target.value.startsWith("case"));
  renderHero(); renderGrid();
};

// ----------------------------------------------------------- Hinzufügen
$("#addBtn").onclick = () => { $("#addForm").reset(); $("#addDlg").showModal(); };
$("#addForm").onsubmit = async (e) => {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  f.platinum = !!f.platinum;
  try {
    const g = await api("/api/games", { method: "POST", body: f });
    $("#addDlg").close(); await refresh();
    toast(`„${g.title}“ hinzugefügt`);
  } catch (err) { toast(err.message, true); }
};

// -------------------------------------------------------- Einstellungen
function openSettings() {
  const s = state.settings, form = $("#settingsForm");
  for (const el of form.elements) if (el.name && el.name in s) el.value = s[el.name] ?? "";
  form.querySelectorAll("[data-state]").forEach((el) => {
    const p = el.dataset.state, last = s.last_sync?.[p];
    el.textContent = s.configured.includes(p)
      ? (last ? `· letzter Abgleich ${relDay(last)}${s.last_sync_msg?.[p] ? " – " + s.last_sync_msg[p] : ""}` : "· eingerichtet")
      : "· nicht eingerichtet";
  });
  $("#settingsDlg").showModal();
}
$("#settingsBtn").onclick = openSettings;
$("#settingsForm").onsubmit = async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(e.target));
  try {
    const before = new Set(state.settings.configured);
    state.settings = await api("/api/settings", { method: "POST", body });
    state.styles = await api("/api/styles");
    renderStyleSelect();
    $("#settingsDlg").close();
    const fresh = state.settings.configured.filter((p) => !before.has(p));
    toast("Einstellungen gespeichert");
    if (fresh.length) startSync(fresh);
    else renderGrid();
  } catch (err) { toast(err.message, true); }
};
$("#fullSyncBtn").onclick = () => { $("#settingsDlg").close(); startSync(null, true); };
$("#refreshCasesBtn").onclick = async (e) => {
  e.target.disabled = true;
  try { await api("/api/covers/refresh-cases", { method: "POST" }); toast("Hüllen neu geladen"); await refresh(); }
  catch (err) { toast(err.message, true, 6000); }
  finally { e.target.disabled = false; }
};
$("#clearCoversBtn").onclick = async () => { await api("/api/covers/clear", { method: "POST" }); toast("Cover-Cache geleert"); await refresh(); };
$("#importFile").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const r = await api("/api/import", { method: "POST", body: JSON.parse(await file.text()) });
    toast(`${r.imported} Einträge importiert`); await refresh();
  } catch (err) { toast(err.message, true); }
};

// ----------------------------------------------------------------- Sync
async function startSync(platforms = null, full = false) {
  try {
    await api("/api/sync", { method: "POST", body: { platforms, full } });
    pollSync();
  } catch (e) {
    if (String(e.message).includes("läuft bereits")) return pollSync();
    toast(e.message, true, 6000);
  }
}
$("#syncBtn").onclick = () => startSync();

let polling = false;
async function pollSync() {
  if (polling) return;
  polling = true;
  const btn = $("#syncBtn"), bar = $("#syncBar");
  btn.classList.add("spin"); bar.classList.remove("hidden");
  let lastReload = Date.now();
  try {
    for (;;) {
      const s = await api("/api/sync/status");
      btn.title = s.message || "Abgleich läuft …";
      $(".lbl", btn).textContent = s.total ? `${s.done}/${s.total}` : "…";
      bar.firstElementChild.style.width = s.total ? `${(s.done / s.total) * 100}%` : "15%";
      if (!s.running) {
        const errs = Object.entries(s.errors || {});
        if (errs.length) toast(errs.map(([p, m]) => `${PLATFORMS[p]?.label}: ${m}`).join("\n"), true, 9000);
        else toast("Abgleich fertig");
        break;
      }
      if (Date.now() - lastReload > 8000) { lastReload = Date.now(); refresh(); }
      await new Promise((r) => setTimeout(r, 1500));
    }
  } finally {
    polling = false;
    btn.classList.remove("spin"); bar.classList.add("hidden");
    $(".lbl", btn).textContent = "Abgleich"; btn.title = "Jetzt abgleichen";
    await refresh();
  }
}

async function refresh() {
  const [games, stats] = await Promise.all([api("/api/games"), api("/api/stats")]);
  Object.assign(state, { games, stats });
  renderAll();
}

// --------------------------------------------------------- Bedienelemente
$("#search").oninput = (e) => { state.view.q = e.target.value; renderGrid(); };
$("#sortSelect").onchange = (e) => { state.view.sort = e.target.value; saveView(); renderGrid(); };
$("#yearSelect").onchange = (e) => { state.view.year = e.target.value; saveView(); renderStats(); renderGrid(); };
$("#tagSelect").onchange = (e) => { state.view.tag = e.target.value; saveView(); renderGrid(); };
$("#groupYear").onchange = (e) => { state.view.group = e.target.checked; saveView(); renderGrid(); };
$("#showHidden").onchange = (e) => { state.view.hidden = e.target.checked; saveView(); renderChips(); renderGrid(); };
document.addEventListener("click", (e) => {
  if (e.target.matches("[data-close]")) e.target.closest("dialog").close();
  if (e.target.tagName === "DIALOG") e.target.close(); // Klick auf den Hintergrund
});

loadAll().then(async () => {
  const s = await api("/api/sync/status");
  if (s.running) pollSync();
}).catch((e) => toast(e.message, true));
