"use strict";
// Erfolge-Liste im Spiel-Dialog, Vitrine und Statistik.  Nutzt $, esc, api, state … aus app.js.

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const WEEKDAYS_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const BAND_LABEL = { extrem: "Extrem selten", sehr: "Sehr selten", selten: "Selten", ungewoehnlich: "Ungewöhnlich", haeufig: "Häufig" };
const TYPE_LABEL = { platinum: "Platin", gold: "Gold", silver: "Silber", bronze: "Bronze" };
const fmtPct = (v) => v == null ? "–" : `${v.toLocaleString("de-DE", { maximumFractionDigits: v < 10 ? 1 : 0 })} %`;
const fmtDateTime = (ts) => ts ? new Date(ts * 1000).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
const nf = (n) => Number(n || 0).toLocaleString("de-DE");

// ------------------------------------------------------------ Erfolge ---
async function loadAchievements(g, refresh = false) {
  const box = $("#achBox");
  if (!box) return;
  let data;
  try {
    data = await api(`/api/games/${g.id}/achievements${refresh ? "?refresh=1" : ""}`);
  } catch (e) {
    box.innerHTML = `<p class="hint">${esc(e.message)}</p>`;
    return;
  }
  if (state.current?.id !== g.id || !$("#achBox")) return; // Dialog inzwischen zu oder anderes Spiel
  const unit = g.platform === "playstation" ? "Trophäen" : "Erfolge";
  const sum = data.summary, list = data.achievements;
  if (!list.length) {
    box.innerHTML = `<h3>${unit}</h3><p class="hint">Noch keine ${unit} geladen – das passiert beim nächsten Abgleich.
      <button class="btn" id="achReload">Jetzt nachladen</button></p>`;
    $("#achReload").onclick = () => { box.innerHTML = `<p class="hint">Lade …</p>`; loadAchievements(g, true); };
    return;
  }
  const ui = { filter: "all", sort: "order", reveal: new Set() };
  const kpis = [
    `<div class="kpi"><span>${unit}</span><b>${sum.unlocked} / ${sum.total}</b><small>${sum.total - sum.unlocked ? `${sum.total - sum.unlocked} noch offen` : "alle geschafft"}</small></div>`,
    sum.max_100_pct != null ? `<div class="kpi accent" title="Wer 100 % hat, hat auch den seltensten Erfolg – mehr Spieler als diesen Anteil kann es also nicht geben."><span>Wie exklusiv sind 100 %?</span><b>≤ ${fmtPct(sum.max_100_pct)}</b><small>aller Spieler – seltenster: ${esc(sum.hardest?.name || "")}</small></div>` : "",
    sum.rarest_unlocked ? `<div class="kpi"><span>Dein seltenster</span><b>${fmtPct(sum.rarest_unlocked.rarity)}</b><small>${esc(sum.rarest_unlocked.name)}</small></div>` : "",
    sum.first_unlock ? `<div class="kpi"><span>Freigeschaltet an</span><b>${sum.unlock_days} ${sum.unlock_days === 1 ? "Tag" : "Tagen"}</b><small>${fmtDate(sum.first_unlock)} – ${fmtDate(sum.last_unlock)}</small></div>` : "",
  ].join("");
  const types = sum.types ? `<div class="types">${sum.types.filter((v) => v.total)
    .map((v) => `<span class="tchip t-${v.key}">${TYPE_LABEL[v.key]} ${v.unlocked}/${v.total}</span>`).join("")}</div>` : "";
  const bands = sum.bands.filter((v) => v.total);
  const bandHtml = bands.length ? `<div class="panel"><h4>Nach Seltenheit</h4>${bands.map((v) => `
      <div class="hbar" title="${v.unlocked} von ${v.total} ${unit} mit dieser Seltenheit geschafft">
        <span class="lbl"><i class="rdot r-${v.key}"></i>${BAND_LABEL[v.key]}</span>
        <span class="bar"><i style="width:${(v.unlocked / v.total) * 100}%"></i></span>
        <span class="val">${v.unlocked}/${v.total}</span></div>`).join("")}</div>` : "";
  const easy = sum.easiest_open.length ? `<div class="panel"><h4>Die leichtesten offenen</h4>${sum.easiest_open.map((a) => `
      <div class="hbar easy"><span class="lbl">${a.icon ? `<img src="${esc(a.icon)}" alt="" loading="lazy">` : ""}${esc(a.hidden ? "Versteckt" : a.name)}</span>
        <span class="bar"><i style="width:${a.rarity}%"></i></span><span class="val">${fmtPct(a.rarity)}</span></div>`).join("")}</div>` : "";

  box.innerHTML = `
    <div class="ach-head"><h3>${unit}</h3><button class="btn" id="achRefresh" title="Namen, Icons und Seltenheit neu laden">⟳</button></div>
    <div class="kpis">${kpis}</div>${types}
    <div class="panels">${bandHtml}${easy}</div>
    <div class="ach-tools">
      <div class="seg" id="achFilter">
        <button data-f="all" class="on">Alle ${list.length}</button><button data-f="done">Erreicht ${sum.unlocked}</button><button data-f="open">Offen ${list.length - sum.unlocked}</button>
      </div>
      <select id="achSort"><option value="order">Spielreihenfolge</option><option value="rare">Seltenste zuerst</option>
        <option value="common">Häufigste zuerst</option><option value="date">Neueste zuerst</option></select>
    </div>
    <div class="ach-list" id="achList"></div>`;

  const renderList = () => {
    let rows = list.filter((a) => ui.filter === "all" || (ui.filter === "done" ? a.unlocked : !a.unlocked));
    const by = {
      order: (a, b) => a.sort - b.sort,
      rare: (a, b) => (a.rarity ?? 999) - (b.rarity ?? 999),
      common: (a, b) => (b.rarity ?? -1) - (a.rarity ?? -1),
      date: (a, b) => b.unlock_time - a.unlock_time || a.sort - b.sort,
    }[ui.sort];
    rows = [...rows].sort(by);
    $("#achList").innerHTML = rows.map((a) => {
      const secret = a.hidden && !a.unlocked && !ui.reveal.has(a.api_name);
      const icon = a.unlocked ? a.icon : (a.icon_gray || a.icon);
      return `<div class="ach ${a.unlocked ? "done" : "open"} ${secret ? "secret" : ""}" data-api="${esc(a.api_name)}">
        <div class="ico">${icon ? `<img src="${esc(icon)}" alt="" loading="lazy">` : `<span class="noicon">${a.trophy_type ? "🏆" : "★"}</span>`}</div>
        <div class="txt">
          <b>${secret ? "Versteckter Erfolg" : esc(a.name || a.api_name)}${a.trophy_type ? ` <span class="tchip t-${a.trophy_type}">${TYPE_LABEL[a.trophy_type] || ""}</span>` : ""}</b>
          <span>${secret ? "Antippen zum Aufdecken" : esc(a.description || "")}</span>
        </div>
        <div class="meta">
          ${a.rarity != null ? `<span class="rpill r-${a.band}" title="${BAND_LABEL[a.band]}: ${fmtPct(a.rarity)} aller Spieler">${fmtPct(a.rarity)}</span>` : ""}
          ${a.unlocked && a.unlock_time ? `<small>${fmtDateTime(a.unlock_time)}</small>` : ""}
        </div></div>`;
    }).join("") || `<p class="hint">Nichts in dieser Auswahl.</p>`;
  };
  renderList();
  $("#achFilter").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    ui.filter = b.dataset.f;
    $("#achFilter").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
    renderList();
  };
  $("#achSort").onchange = (e) => { ui.sort = e.target.value; renderList(); };
  $("#achList").onclick = (e) => {
    const el = e.target.closest(".ach.secret"); if (!el) return;
    ui.reveal.add(el.dataset.api); renderList();
  };
  $("#achRefresh").onclick = () => { $("#achRefresh").classList.add("spinning"); loadAchievements(g, true); };
}

// ------------------------------------------------------------- Vitrine ---
function renderVitrine() {
  const v = state.view, q = v.q.trim().toLowerCase();
  const list = baseList().filter((g) => g.status === "completed" &&
    (!v.platforms.length || v.platforms.includes(g.platform)) &&
    (!v.tag || g.tags.includes(v.tag)) &&
    (!v.year || String(yearOf(g.completed_at)) === String(v.year)) &&
    (!q || g.title.toLowerCase().includes(q)))
    .sort((a, b) => (b.completed_at || 0) - (a.completed_at || 0));
  const grid = $("#grid");
  grid.className = "vitrine";
  $("#countLabel").textContent = `${list.length} Spiele auf 100 %`;
  const empty = $("#empty");
  empty.classList.toggle("hidden", !!list.length);
  if (!list.length) empty.textContent = "Noch keine Spiele auf 100 % für diese Auswahl.";
  const ach = list.reduce((n, g) => n + (g.total || 0), 0);
  const hours = Math.round(list.reduce((n, g) => n + (g.playtime_min || 0), 0) / 60);
  const plat = list.filter((g) => g.platinum).length;
  grid.innerHTML = list.length ? `
    <div class="vitrine-head">
      <div><b>Trophäenschrank</b><span>${v.year ? `Abgeschlossen ${v.year}` : "Alle deine Spiele auf 100 %"}</span></div>
      <div class="vchips"><button class="btn" id="showcaseBtn" title="Übersicht als Bild exportieren, z.B. fürs Steam-Profil">🖼 Bild exportieren</button><span title="Spiele auf 100 %">🏆 ${nf(list.length)}</span>${plat ? `<span title="Platin-Trophäen">💎 ${plat}</span>` : ""}
        <span title="Erfolge in diesen Spielen">★ ${nf(ach)}</span>${hours ? `<span title="Spielzeit">⏱ ${nf(hours)} Std.</span>` : ""}</div>
    </div>
    <div class="shelves">${list.map((g) => `
      <div class="shelf-item ${g.platinum ? "plat" : ""}" data-id="${g.id}" title="${esc(g.title)}">
        <div class="spot"></div>
        <img loading="lazy" src="${coverUrl(g)}" alt="${esc(g.title)}">
        <div class="ledge"></div>
        <div class="plaque"><b>${esc(g.title)}</b><span>${g.completed_at ? fmtDate(g.completed_at) : ""}${g.platform !== "steam" ? ` · ${PLATFORMS[g.platform].label}` : ""}</span></div>
      </div>`).join("")}</div>` : "";
  if ($("#showcaseBtn")) $("#showcaseBtn").onclick = (e) => { e.stopPropagation(); openShowcase(); };
}

// ------------------------------------------------------- Showcase-Bild ---
function openShowcase() {
  const dlg = $("#showcaseDlg"), form = $("#showcaseForm"), v = state.view;
  const years = [...new Set(state.games.filter((g) => g.status === "completed").map((g) => yearOf(g.completed_at)).filter(Boolean))].sort((a, b) => b - a);
  $("#scYear").innerHTML = `<option value="">Alle</option>` + years.map((y) => `<option>${y}</option>`).join("");
  $("#scStyle").innerHTML = state.styles.map((s) => `<option value="${esc(s.id)}">${esc(s.label)}</option>`).join("");
  $("#scStyle").value = state.settings.cover_style || "official";
  form.year.value = v.year || "";
  form.platform.value = v.platforms.length === 1 ? v.platforms[0] : "";
  let timer, seq = 0;
  const url = (download) => {
    const f = new FormData(form), p = new URLSearchParams();
    for (const k of ["format", "platform", "year", "limit", "style", "title"]) p.set(k, f.get(k) || "");
    p.set("dates", f.get("dates") ? "1" : "0");
    p.set("stats", f.get("stats") ? "1" : "0");
    p.set("scale", f.get("scale") ? "2" : "1");
    if (download) p.set("download", "1");
    return `/api/export/showcase.png?${p}`;
  };
  const update = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const my = ++seq;
      $("#scInfo").textContent = "Bild wird erzeugt …";
      try {
        const r = await fetch(url(false));
        if (!r.ok) throw new Error(`Fehler ${r.status}`);
        const blob = await r.blob();
        if (my !== seq) return;
        const img = $("#scImg");
        if (img.src.startsWith("blob:")) URL.revokeObjectURL(img.src);
        img.src = URL.createObjectURL(blob);
        const [shown, total] = (r.headers.get("X-Games") || "0/0").split("/");
        const mb = (Number(r.headers.get("X-Bytes")) / 1e6).toLocaleString("de-DE", { maximumFractionDigits: 1 });
        $("#scInfo").textContent = `${r.headers.get("X-Image-Size")} px · ${mb} MB · ${shown} von ${total} Spielen`;
        $("#scDownload").href = url(true);
      } catch (e) { if (my === seq) $("#scInfo").textContent = e.message; }
    }, 250);
  };
  form.oninput = update;
  form.onsubmit = (e) => e.preventDefault();
  dlg.showModal();
  update();
}

// ----------------------------------------------------------- Statistik ---
const SEQ = ["#2b303c", "#5a3d22", "#8d5726", "#c0752c", "#f0a14a"]; // 0 → viel, ein Farbton
function seqColor(n, max) {
  if (!n) return SEQ[0];
  return SEQ[Math.min(4, 1 + Math.floor((n / Math.max(1, max)) * 3.999))];
}

let statsYear = "";
async function renderStatsView() {
  const box = $("#statsView");
  $("#countLabel").textContent = "";
  if (!box.innerHTML) box.innerHTML = `<p class="hint">Lade Statistik …</p>`;
  let s;
  try { s = await api(`/api/stats/achievements${statsYear ? `?year=${statsYear}` : ""}`); }
  catch (e) { box.innerHTML = `<p class="hint">${esc(e.message)}</p>`; return; }
  if (state.view.mode !== "stats") return;
  const st = state.stats;
  const years = s.years;
  const yearSel = `<select id="statsYear"><option value="">Letzte 12 Monate / gesamt</option>${years.map((y) => `<option ${String(y) === statsYear ? "selected" : ""}>${y}</option>`).join("")}</select>`;
  if (!s.total) {
    box.innerHTML = `<div class="stats-top">${yearSel}</div><p class="empty">Noch keine freigeschalteten Erfolge mit Datum – starte einen Abgleich (Steam/PlayStation).</p>`;
    $("#statsYear").onchange = (e) => { statsYear = e.target.value; renderStatsView(); };
    return;
  }
  const maxDay = Math.max(1, ...s.calendar.map((d) => d[1]));
  const maxCell = Math.max(1, ...s.heatmap.flat());
  const completedYear = statsYear ? (st.by_year[statsYear] || 0) : st.completed;

  box.innerHTML = `
    <div class="stats-top"><h2>Statistik</h2>${yearSel}</div>
    <div class="kpis">
      <div class="kpi"><span>Erfolge freigeschaltet</span><b>${nf(s.total)}</b><small>an ${nf(s.days_active)} Tagen</small></div>
      <div class="kpi accent"><span>Spiele auf 100 %</span><b>${nf(completedYear)}</b><small>${statsYear ? `in ${statsYear}` : "insgesamt"}${st.platinum ? ` · ${st.platinum}× Platin` : ""}</small></div>
      <div class="kpi"><span>Bester Tag</span><b>${nf(s.best_day.count)}</b><small>${s.best_day.date ? new Date(s.best_day.date).toLocaleDateString("de-DE", { day: "numeric", month: "long", year: "numeric" }) : ""}</small></div>
      <div class="kpi"><span>Am erfolgreichsten</span><b>${WEEKDAYS_LONG[s.best_weekday]}</b><small>meist ${s.best_hour}–${s.best_hour + 1} Uhr · Spitze: ${WEEKDAYS[s.best_cell.weekday]} ${s.best_cell.hour} Uhr</small></div>
    </div>

    <div class="card2 wide"><h4>Erfolge pro Tag</h4><p class="sub2">${statsYear ? `Jahr ${statsYear}` : "Die letzten 12 Monate"} – je heller, desto mehr Erfolge an dem Tag.</p>
      ${calendarSvg(s.calendar, maxDay)}
      ${legend(maxDay)}</div>

    <div class="grid2">
      <div class="card2"><h4>Wann du am erfolgreichsten bist</h4><p class="sub2">Freigeschaltete Erfolge nach Wochentag und Uhrzeit.</p>
        ${heatmapSvg(s.heatmap, maxCell)}${legend(maxCell)}</div>
      <div class="card2"><h4>Erfolge pro Monat</h4><p class="sub2">${s.per_month.length > 1 ? `${monthLabel(s.per_month[0][0])} bis ${monthLabel(s.per_month.at(-1)[0])}` : ""}</p>
        ${monthBars(s.per_month)}</div>
    </div>

    <div class="grid2">
      <div class="card2"><h4>Wie selten sind deine Erfolge?</h4><p class="sub2">Anteil aller Spieler, die den Erfolg auch haben (${nf(s.rarity_known)} Erfolge mit bekannter Seltenheit).</p>
        ${rarityBars(s.rarity_bands)}</div>
      <div class="card2"><h4>100 % pro Jahr</h4><p class="sub2">Abgeschlossene Spiele nach Jahr des Abschlusses.</p>${yearBars(st.by_year)}</div>
    </div>

    <div class="grid2">
      <div class="card2"><h4>Deine seltensten Erfolge</h4>
        <div class="rlist">${s.rarest.map((a) => `<div class="ritem" data-game="${a.game_id}">
          ${a.icon ? `<img src="${esc(a.icon)}" alt="" loading="lazy">` : `<span class="noicon">★</span>`}
          <div><b>${esc(a.name)}</b><small>${esc(a.game)} · ${fmtDate(a.time)}</small></div>
          <span class="rpill r-${rarityBand(a.rarity)}">${fmtPct(a.rarity)}</span></div>`).join("") || `<p class="hint">Seltenheit wird beim Abgleich geladen.</p>`}</div></div>
      <div class="card2"><h4>Die meisten Erfolge ${statsYear ? `in ${statsYear}` : ""}</h4>
        ${topGames(s.top_games)}</div>
    </div>`;
  $("#statsYear").onchange = (e) => { statsYear = e.target.value; renderStatsView(); };
  box.querySelectorAll(".scroll-x").forEach((el) => { el.scrollLeft = el.scrollWidth; }); // neueste Tage sichtbar
  box.querySelectorAll("[data-game]").forEach((el) => el.onclick = () => openDetail(Number(el.dataset.game)));
}

function rarityBand(r) {
  return r < 5 ? "extrem" : r < 10 ? "sehr" : r < 25 ? "selten" : r < 50 ? "ungewoehnlich" : "haeufig";
}
const monthLabel = (k) => { const [y, m] = k.split("-"); return new Date(+y, +m - 1, 1).toLocaleDateString("de-DE", { month: "short", year: "2-digit" }); };

function legend(max) {
  return `<div class="legend">weniger ${SEQ.map((c) => `<i style="background:${c}"></i>`).join("")} mehr <span>(max. ${max})</span></div>`;
}

function calendarSvg(days, max) {
  const cell = 11, gap = 2, step = cell + gap;
  const first = new Date(days[0][0]);
  const offset = (first.getDay() + 6) % 7; // Montag = 0
  const weeks = Math.ceil((days.length + offset) / 7);
  const W = 26 + weeks * step, H = 16 + 7 * step;
  let out = "", lastMonth = -1;
  days.forEach(([iso, n], i) => {
    const k = i + offset, w = Math.floor(k / 7), d = k % 7;
    const x = 26 + w * step, y = 16 + d * step;
    const dt = new Date(iso);
    if (dt.getDate() <= 7 && d === 0 && dt.getMonth() !== lastMonth) {
      lastMonth = dt.getMonth();
      out += `<text x="${x}" y="10" class="ax">${dt.toLocaleDateString("de-DE", { month: "short" })}</text>`;
    }
    out += `<rect x="${x}" y="${y}" width="${cell}" height="${cell}" rx="2" fill="${seqColor(n, max)}"><title>${dt.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "long", year: "numeric" })}: ${n} ${n === 1 ? "Erfolg" : "Erfolge"}</title></rect>`;
  });
  [0, 2, 4].forEach((d) => { out += `<text x="0" y="${16 + d * step + 9}" class="ax">${WEEKDAYS[d]}</text>`; });
  return `<div class="scroll-x"><svg viewBox="0 0 ${W} ${H}" width="100%" style="min-width:${W}px;max-width:${Math.round(W * 1.7)}px" class="chart">${out}</svg></div>`;
}

function heatmapSvg(heat, max) {
  const cell = 16, gap = 2, step = cell + gap, L = 24, T = 16;
  const W = L + 24 * step, H = T + 7 * step;
  let out = "";
  for (let h = 0; h < 24; h += 3) out += `<text x="${L + h * step}" y="10" class="ax">${h}</text>`;
  heat.forEach((row, d) => {
    out += `<text x="0" y="${T + d * step + 12}" class="ax">${WEEKDAYS[d]}</text>`;
    row.forEach((n, h) => {
      out += `<rect x="${L + h * step}" y="${T + d * step}" width="${cell}" height="${cell}" rx="3" fill="${seqColor(n, max)}"><title>${WEEKDAYS_LONG[d]}, ${h}–${h + 1} Uhr: ${n} ${n === 1 ? "Erfolg" : "Erfolge"}</title></rect>`;
    });
  });
  return `<div class="scroll-x"><svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W * 1.4}px" class="chart">${out}</svg></div>`;
}

function vbars(items, { label, title, color = "var(--accent)" }) {
  // items: [key, value]; einfache Säulen, Werte nur am Maximum und beim Hover
  if (!items.length) return `<p class="hint">Keine Daten.</p>`;
  const max = Math.max(1, ...items.map((i) => i[1]));
  const W = 600, H = 170, B = 22, T = 16;
  const bw = Math.min(W / items.length, 70);
  const x0 = (W - bw * items.length) / 2;
  const top = items.reduce((m, it, i) => (it[1] > items[m][1] ? i : m), 0);
  let out = `<line x1="0" x2="${W}" y1="${H - B}" y2="${H - B}" class="base"/>`;
  items.forEach(([k, v], i) => {
    const h = ((H - B - T) * v) / max, x = x0 + i * bw + bw * 0.15, w = bw * 0.7, y = H - B - h;
    out += `<g><title>${title(k, v)}</title><rect x="${x0 + i * bw}" y="${T}" width="${bw}" height="${H - B - T}" fill="transparent"/>
      ${v ? `<path d="M${x},${H - B} V${y + Math.min(4, h)} q0,-4 4,-4 h${w - 8} q4,0 4,4 V${H - B} Z" fill="${color}"/>` : ""}</g>`;
    if (i === top && v) out += `<text x="${x + w / 2}" y="${y - 4}" text-anchor="middle" class="val">${v}</text>`;
    if (items.length <= 12 || i % Math.ceil(items.length / 12) === 0) out += `<text x="${x + w / 2}" y="${H - 6}" text-anchor="middle" class="ax">${label(k)}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" class="chart">${out}</svg>`;
}

const monthBars = (pm) => vbars(pm, { label: (k) => monthLabel(k).split(" ")[0], title: (k, v) => `${monthLabel(k)}: ${v} Erfolge` });
function yearBars(byYear) {
  const ys = Object.keys(byYear).map(Number);
  if (!ys.length) return `<p class="hint">Noch keine Abschlüsse mit Datum.</p>`;
  const items = [];
  for (let y = Math.min(...ys); y <= Math.max(new Date().getFullYear(), ...ys); y++) items.push([y, byYear[y] || 0]);
  return vbars(items.slice(-12), { label: (k) => `'${String(k).slice(2)}`, title: (k, v) => `${k}: ${v} Spiele auf 100 %`, color: "var(--completed)" });
}

function rarityBars(bands) {
  const max = Math.max(1, ...bands.map((v) => v.count));
  const total = bands.reduce((n, v) => n + v.count, 0) || 1;
  return bands.map((v) => { const k = v.key; return `<div class="hbar" title="${v.label}: ${v.count} Erfolge (${Math.round((v.count / total) * 100)} %)">
    <span class="lbl"><i class="rdot r-${k}"></i>${v.label}<small>${{ extrem: "unter 5 %", sehr: "5–10 %", selten: "10–25 %", ungewoehnlich: "25–50 %", haeufig: "über 50 %" }[k]}</small></span>
    <span class="bar"><i style="width:${(v.count / max) * 100}%"></i></span><span class="val">${nf(v.count)}</span></div>`; }).join("");
}

function topGames(items) {
  if (!items.length) return `<p class="hint">Keine Daten.</p>`;
  const max = Math.max(...items.map((i) => i.count));
  return items.map((g) => `<div class="hbar link" data-game="${g.game_id}" title="${esc(g.title)}: ${g.count} Erfolge">
    <span class="lbl">${esc(g.title)}</span><span class="bar"><i style="width:${(g.count / max) * 100}%"></i></span><span class="val">${g.count}</span></div>`).join("");
}
