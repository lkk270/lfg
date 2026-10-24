/* The full-screen pages (product home, intro) never flash the dashboard shell while the first data loads. */
(h => { if (!h || h === "#" || /^#(lfg|onboarding|unlock=)/.test(h)) document.body.classList.add("bare"); })(location.hash);
/* Appearance (Settings → Appearance), kept per browser: mode, a light and a dark theme, accent, density, text size,
   glow and motion. Applied before the first paint, and again when the system switches light/dark. */
const AP_DEFAULT = { mode: "system", light: "lfg", dark: "midnight", accent: "blue", density: "comfortable", text: "m", glow: "on", motion: "on" };
function apRead() { try { return Object.assign({}, AP_DEFAULT, JSON.parse(localStorage.getItem("lfg.appearance") || "{}")); } catch (e) { return Object.assign({}, AP_DEFAULT); } }
function apApply(a) {
  a = a || apRead();
  const dark = a.mode === "dark" || (a.mode === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  const r = document.documentElement.dataset;
  r.mode = dark ? "dark" : "light"; r.theme = dark ? a.dark : a.light;
  r.accent = a.accent; r.density = a.density; r.text = a.text; r.glow = a.glow; r.motion = a.motion;
}
function apSet(k, v) { const a = apRead(); a[k] = v; try { localStorage.setItem("lfg.appearance", JSON.stringify(a)); } catch (e) { /* private window: this visit only */ } apApply(a); apFavicon(); return a; }
/* The logo, drawn in the accent colour (inline, so it follows the theme); the favicon is rebuilt to match. */
let LOGO_N = 0;
function logoSvg(size) {
  const g = "lg" + (++LOGO_N);
  return `<svg class="lfg-logo" width="${size}" height="${size}" viewBox="0 0 32 32" aria-hidden="true"><defs><linearGradient id="${g}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" style="stop-color:var(--logo-a)"/><stop offset=".55" style="stop-color:var(--logo-b)"/><stop offset="1" style="stop-color:var(--logo-c)"/></linearGradient></defs><rect width="32" height="32" rx="7" fill="url(#${g})"/><path d="M8.5 9.5 15 16l-6.5 6.5" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15.5 9.5 22 16l-6.5 6.5" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="26.2" cy="16" r="1.6" fill="#fff"/></svg>`;
}
function hexMix(a, b, t) {  // t of a, the rest b
  const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return "#" + x.map((v, i) => Math.round(v * t + y[i] * (1 - t)).toString(16).padStart(2, "0")).join("");
}
function apFavicon() {
  const c = (getComputedStyle(document.documentElement).getPropertyValue("--blue") || "").trim();
  if (!/^#[0-9a-f]{6}$/i.test(c)) return;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${hexMix(c, "#ffffff", .72)}"/><stop offset=".55" stop-color="${c}"/><stop offset="1" stop-color="${hexMix(c, "#000000", .62)}"/></linearGradient></defs><rect width="32" height="32" rx="7" fill="url(#g)"/><path d="M8.5 9.5 15 16l-6.5 6.5" fill="none" stroke="#fff" stroke-opacity=".55" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15.5 9.5 22 16l-6.5 6.5" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/><circle cx="26.2" cy="16" r="1.6" fill="#fff"/></svg>`;
  const link = document.querySelector('link[rel="icon"]');
  if (link) link.href = "data:image/svg+xml," + encodeURIComponent(svg);
}
apApply();
document.addEventListener("DOMContentLoaded", apFavicon); apFavicon();
try { matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { apApply(); apFavicon(); }); } catch (e) { /* old browsers */ }
/* LFG dashboard: a plain-language view of what LFG is doing in your repos. Read-only, except Settings, which saves
   only with the local edit key from `lfg ui`. Author: Varun Singh. No external resources. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const n = v => (v == null || v === "" ? "—" : Number(v).toLocaleString());
function compact(v) {
  if (v == null || isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (a >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
  return String(v);
}
function ago(ts) {
  if (!ts) return "never";
  if (/^\d{4}-\d{2}-\d{2}$/.test(ts)) {  // day-granular (Omnigraph Date): compare calendar days, local time
    const t = new Date(), days = Math.round((new Date(t.getFullYear(), t.getMonth(), t.getDate()) - new Date(ts + "T00:00")) / 864e5);
    return days <= 0 ? "today" : days === 1 ? "yesterday" : days + " days ago";
  }
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (isNaN(s)) return esc(ts);
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : d + " days ago";
}
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
const plural = (k, w) => `${n(k)} ${w}${k === 1 ? "" : "s"}`;
const words = s => String(s || "").replace(/[-_]+/g, " ").replace(/\.md$/, "");
const state = { repo: localStorage.getItem("lfg.repo") || "", branch: "", repos: [], cache: {} };
const branchPref = () => "lfg.branch." + state.repo;

async function api(view, params = {}) {
  const q = new URLSearchParams({ repo: state.repo, ...(state.branch ? { branch: state.branch } : {}), ...params });
  const r = await fetch(`/api/${view}?${q}`, { headers: { "X-LFG": "1" } });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

const repoName = (id = state.repo) => (state.repos || []).find(x => x.id === id)?.name || id;
const usd = v => "$" + (v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(2));
// ------------------------------------------------------------------ plain words for tool status values
/* Every status value the tools write, as [what a person reads, tone]. Unknown values show as written. */
const SAY = {
  // checks before commit (ready.json)
  green: ["Checks pass", "ok"], red: ["Checks failing", "bad"],
  // review verdict
  approve: ["Approved", "ok"], changes: ["Changes requested", "warn"], block: ["Blocked", "bad"],
  // security verdict
  safe: ["No problems", "ok"], "safe with caveats": ["Minor notes", "warn"], "don't": ["Problems to fix", "bad"],
  // ship check
  pass: ["Passed", "ok"], fail: ["Failed", "bad"],
  // graphs
  fresh: ["Up to date", "ok"], stale: ["Out of date", "warn"], syncing: ["Updating", "warn"], missing: ["Not built yet", "warn"], error: ["Error", "bad"],
  // issues and knowledge
  backlog: ["Backlog", ""], todo: ["To do", ""], in_progress: ["In progress", "on"], needs_review: ["In review", "warn"], hold: ["On hold", "warn"],
  done: ["Done", "ok"], canceled: ["Canceled", ""], duplicate: ["Duplicate", ""],
  accepted: ["Accepted", "ok"], proposed: ["Proposed", "warn"], rejected: ["Rejected", ""], superseded: ["Replaced", ""],
  holds: ["Holds", "ok"], violated: ["Broken", "bad"], unheld: ["Not checked by a test", "warn"],
  active: ["Active", "ok"], relaxed: ["Relaxed", ""], retired: ["Retired", ""],
  narrowing: ["Shrinking", "ok"], widened: ["Growing", "bad"], closed: ["Closed", "ok"],
  // review severity
  blocker: ["Must fix", "bad"], major: ["Should fix", "warn"], minor: ["Minor", ""], nit: ["Nitpick", ""],
  critical: ["Critical", "bad"], high: ["High", "bad"], medium: ["Medium", "warn"], moderate: ["Medium", "warn"], low: ["Low", ""],
  accept: ["You agreed", "ok"], reject: ["You disagreed", ""],
  // security test (pentest)
  refused: ["Didn't run", "warn"], completed: ["Finished", "ok"], findings: ["Found problems", "bad"],
};
const say = v => SAY[String(v ?? "").toLowerCase()] || [v == null || v === "" ? "" : String(v), ""];
function st(v, fallback) {
  const [text, t] = say(v);
  if (!text) return `<span class="muted">${esc(fallback || "—")}</span>`;
  return `<span class="st"><span class="dot ${t}"></span>${esc(text)}</span>`;
}
const dot = t => `<span class="dot ${t}"></span>`;
const fmtWhy = w => esc(w || "").replace(/`([^`]+)`/g, "<code>$1</code>");

/* Pipeline steps, in the words a person uses */
const STEP = { brief: "Idea written up", design: "Plan", tasks: "Task list", build: "Built", qa: "Tested", gate: "Checks run",
  secure: "Security check", review: "Code review", ship: "Ship check", packet: "Ready to commit" };
const NEXT = { brief: "write up the idea", design: "make a plan", tasks: "split it into tasks", build: "build it", qa: "test it",
  gate: "run the checks", secure: "check security", review: "review the code", ship: "run the ship check", packet: "prepare the commit message",
  "fix-checks": "fix the failing checks (/lfg:fix)", "fix-block": "decide what to do about the blocked review",
  "fix-review": "address the review's requested changes", "fix-security": "fix the security problems (/lfg:fix)",
  "fix-ship": "fix what the ship check found" };
function runPlace(stages, done, r) {
  /* done = steps that really happened; next = what blocks first (a failing check, a review asking for changes),
     else the step after the furthest one done (review-only runs skip the early steps, so those don't count as next) */
  const keys = stages.map(s => s[0]), last = keys.reduce((a, x, i) => (done[x] ? i : a), -1);
  const count = keys.filter(k => done[k]).length;
  const block = r && (r.ready === "red" ? "fix-checks" : r.review === "block" ? "fix-block" : r.secure === "don't" ? "fix-security"
    : r.review === "changes" ? "fix-review" : r.shipcheck === "fail" ? "fix-ship" : null);  // most serious first
  const next = block || keys.slice(last + 1)[0];
  return { done: count, total: keys.length, next, blocked: !!block, finished: !next };
}
const runName = r => r.title || (w => w.charAt(0).toUpperCase() + w.slice(1))(words(r.slug || "untitled run"));

// ------------------------------------------------------------------ components
function empty(title, body) {
  return `<div class="empty"><h3>${esc(title)}</h3><div>${body || ""}</div></div>`;
}
function unavailable(d, title) {
  return `<div class="callout warn"><b>${esc(title || "Not available yet")}</b><div class="small" style="margin-top:2px">${fmtWhy(d && d.why)}</div></div>`;
}
function head(title, text, back) {
  return `<div class="head">${back || ""}<h1>${esc(title)}</h1>${text ? `<p>${text}</p>` : ""}</div>`;
}
function section(title, body, sub) {
  return `<div class="section"><h2>${esc(title)}${sub ? `<span class="sub">${sub}</span>` : ""}</h2>${body}</div>`;
}
function stat(k, v, s) {
  return `<div class="box stat"><div class="k">${esc(k)}</div><div class="v">${v}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
}

/* table(rows, cols, opts): cols = [{k, label, num, html: row => string, sort: row => value}] */
let TID = 0;
const TABLES = {};
function table(rows, cols, opts = {}) {
  const id = "t" + ++TID;
  if (!rows || !rows.length) return empty(opts.emptyTitle || "Nothing here yet", opts.emptyBody || "");
  TABLES[id] = { rows, cols, opts, sort: opts.sort || null, dir: opts.dir || -1, filter: "" };
  const tools = rows.length > 15 && opts.filter !== false ?
    `<div class="table-tools"><input type="search" placeholder="Search…" data-filter="${id}"><span class="count" id="${id}-count"></span></div>` : "";
  return `${tools}<div class="table-wrap"><table id="${id}"></table></div>`;
}
function drawTable(id) {
  const t = TABLES[id], el = document.getElementById(id);
  if (!t || !el) return;
  const f = t.filter.toLowerCase();
  const rows = f ? t.rows.filter(r => JSON.stringify(r).toLowerCase().includes(f)) : t.rows.slice();
  if (t.sort != null) {
    const c = t.cols.find(c => c.k === t.sort);
    const val = r => (c && c.sort ? c.sort(r) : r[t.sort]);
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * t.dir;
    });
  }
  const shown = rows.slice(0, t.opts.limit || 500);
  el.innerHTML = `<thead><tr>${t.cols.map(c => `<th data-k="${esc(c.k)}" class="${c.num ? "num" : ""} ${t.sort === c.k ? (t.dir > 0 ? "sorted-asc" : "sorted-desc") : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>
    <tbody>${shown.map(r => `<tr class="${t.opts.onRow ? "click" : ""}" data-i="${t.rows.indexOf(r)}">${t.cols.map(c => `<td class="${c.num ? "num" : ""}">${c.html ? c.html(r) : c.num ? n(r[c.k]) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")}</tbody>`;
  const cnt = document.getElementById(id + "-count");
  if (cnt) cnt.textContent = rows.length === t.rows.length ? plural(rows.length, "item") : `${n(rows.length)} of ${n(t.rows.length)}`;
  $$("th", el).forEach(th => th.onclick = () => { const k = th.dataset.k; t.dir = t.sort === k ? -t.dir : -1; t.sort = k; drawTable(id); });
  if (t.opts.onRow) $$("tbody tr", el).forEach(tr => tr.onclick = () => t.opts.onRow(t.rows[+tr.dataset.i]));
}
function mountTables(root = document) {
  $$("table[id^=t]", root).forEach(el => drawTable(el.id));
  $$("input[data-filter]", root).forEach(inp => inp.oninput = () => { TABLES[inp.dataset.filter].filter = inp.value; drawTable(inp.dataset.filter); });
}

/* tabs(id, [[key, label, count, htmlFn]]): renders lazily; tabs with a 0 count are left out unless all are empty */
const TABS = {};
function tabs(id, items) {
  const shown = items.filter(it => it[2] == null || it[2] > 0);
  const list = shown.length ? shown : items.slice(0, 1);
  TABS[id] = list;
  return `<div class="tabs" data-tabs="${id}">${list.map(([k, l, c]) => `<button class="tab" data-k="${esc(k)}">${esc(l)}${c ? `<span class="n">${compact(c)}</span>` : ""}</button>`).join("")}</div><div id="${id}-body"></div>`;
}
function mountTabs(root = document) {
  $$("[data-tabs]", root).forEach(bar => {
    const id = bar.dataset.tabs;
    const show = k => {
      $$(".tab", bar).forEach(b => { b.classList.toggle("on", b.dataset.k === k); if (b.dataset.k === k && bar.scrollWidth > bar.clientWidth) bar.scrollLeft = b.offsetLeft - 16; });
      const it = TABS[id].find(x => x[0] === k);
      const body = document.getElementById(id + "-body");
      body.innerHTML = it[3]();
      mountTables(body); mountTabs(body); wire(body);
      sessionStorage.setItem("lfg.tab." + id, k);
    };
    $$(".tab", bar).forEach(b => b.onclick = () => show(b.dataset.k));
    const saved = sessionStorage.getItem("lfg.tab." + id);
    show(TABS[id].some(x => x[0] === saved) ? saved : TABS[id][0][0]);
  });
}

/* Interactive bars: hover or focus a day for its numbers, click it to pin it (onPick), click a legend key to hide a
   series. data: [{label, values: [..], raw}], series: [[name, color, fmt]]. The y-axis gutter fits its labels. */
const ICHARTS = {};
let ICID = 0;
function iChart(data, series, opts = {}) {
  const id = "ic" + ++ICID;
  ICHARTS[id] = { data, series, opts, hidden: new Set(opts.hidden || []), pick: opts.pick ?? null };
  return `<div class="ichart" id="${id}">${iChartBody(id)}</div>`;
}
function iChartBody(id) {
  const C = ICHARTS[id], { data, series, opts } = C, h = opts.h || 180;
  if (!data.length) return '<div class="muted small">Nothing recorded in this period.</div>';
  const fmt = series[0][2] || compact;
  const shown = series.map((_, j) => !C.hidden.has(j));
  const tot = d => d.values.reduce((a, v, j) => a + (shown[j] ? v || 0 : 0), 0);
  const max = Math.max(...data.map(tot), 1);
  const P = Math.max(34, 8 + 7 * fmt(max).length), W = 760, top = 14, base = h - 22;
  const step = (W - P - 8) / data.length, bw = Math.max(3, Math.min(28, step - Math.max(2, step * 0.18)));
  const x = i => P + 4 + i * step + (step - bw) / 2;
  const every = Math.ceil(data.length / 9);
  let bars = "";
  data.forEach((d, i) => {
    let y = base;
    const segs = d.values.map((v, j) => {
      if (!shown[j] || !v) return "";
      const bh = Math.max(1, (v / max) * (base - top));
      y -= bh;
      const ghost = series[j][3] && series[j][3].ghost;
      return ghost ? `<rect class="ghost" x="${x(i) + 0.75}" y="${y + 0.75}" width="${bw - 1.5}" height="${Math.max(0, bh - 1.5)}" rx="2" style="stroke:${series[j][1]}"></rect>`
        : `<rect x="${x(i)}" y="${y}" width="${bw}" height="${bh}" rx="2" style="fill:${series[j][1]}"></rect>`;
    }).join("");
    bars += `<g class="bar ${C.pick === i ? "on" : ""}" data-i="${i}" tabindex="0" role="button" aria-label="${esc(d.label)}: ${esc(series.map((sr, j) => shown[j] ? sr[0] + " " + (sr[2] || compact)(d.values[j] || 0) : "").filter(Boolean).join(", "))}"><rect class="hit" x="${P + 4 + i * step}" y="${top}" width="${step}" height="${base - top}"></rect>${segs}</g>`;
    if (i % every === 0 || data.length <= 10) bars += `<text x="${x(i) + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(d.short || d.label.slice(5))}</text>`;
  });
  const grid = [0, 0.5, 1].map(t => `<line class="axis${t ? " faint" : ""}" x1="${P}" x2="${W}" y1="${base - t * (base - top)}" y2="${base - t * (base - top)}"/><text x="${P - 6}" y="${base - t * (base - top) + 4}" text-anchor="end">${esc(fmt(max * t))}</text>`).join("");
  const legend = series.length > 1 ? `<div class="legend">${series.map(([nm, c, , o], j) => `<button class="lkey ${shown[j] ? "" : "off"}" data-ic-key="${j}" title="Show or hide ${esc(nm)}"><i class="${o && o.ghost ? "ghost" : ""}" style="${o && o.ghost ? "border-color" : "background"}:${c}"></i>${esc(nm)}</button>`).join("")}</div>` : "";
  return `<div class="chart"><svg viewBox="0 0 ${W} ${h}" role="img" aria-label="${esc(opts.title || "")}">${grid}${bars}</svg><div class="ic-tip" hidden></div></div>${legend}`;
}
function wireIChart(id) {
  const el = document.getElementById(id), C = ICHARTS[id];
  if (!el || !C) return;
  const tip = $(".ic-tip", el), svg = $("svg", el);
  const show = (g, ev) => {
    const i = +g.dataset.i, d = C.data[i];
    tip.textContent = "";
    const t = document.createElement("div"); t.className = "ic-t"; t.textContent = d.label; tip.appendChild(t);
    C.series.forEach(([nm, c, f], j) => {
      if (C.hidden.has(j)) return;
      const r = document.createElement("div"); r.className = "ic-r";
      const k = document.createElement("i"); k.style.background = c;
      const v = document.createElement("b"); v.textContent = (f || compact)(d.values[j] || 0);
      const l = document.createElement("span"); l.textContent = nm;
      r.append(k, v, l); tip.appendChild(r);
    });
    if (C.opts.total) {
      const tt = C.opts.total(d, C.hidden);
      if (tt) { const r = document.createElement("div"); r.className = "ic-h"; r.textContent = tt; tip.appendChild(r); }
    }
    if (C.opts.onPick) { const h = document.createElement("div"); h.className = "ic-h"; h.textContent = "Click for the breakdown"; tip.appendChild(h); }
    tip.hidden = false;
    const box = el.querySelector(".chart").getBoundingClientRect(), gr = g.getBoundingClientRect();
    const left = Math.min(Math.max(gr.left - box.left + gr.width / 2 - tip.offsetWidth / 2, 0), box.width - tip.offsetWidth);
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, gr.top - box.top - tip.offsetHeight - 6) + "px";
  };
  $$("g.bar", svg).forEach(g => {
    g.onpointerenter = e => show(g, e);
    g.onfocus = e => show(g, e);
    g.onpointerleave = g.onblur = () => (tip.hidden = true);
    const pick = () => { if (!C.opts.onPick) return; C.pick = C.pick === +g.dataset.i ? null : +g.dataset.i; el.innerHTML = iChartBody(id); wireIChart(id); C.opts.onPick(C.pick); };
    g.onclick = pick;
    g.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
  });
  $$("[data-ic-key]", el).forEach(b => b.onclick = () => {
    const j = +b.dataset.icKey;
    if (C.hidden.has(j)) C.hidden.delete(j); else if (C.hidden.size < C.series.length - 1) C.hidden.add(j);
    el.innerHTML = iChartBody(id); wireIChart(id);
  });
}
function wireICharts(root) { $$(".ichart", root).forEach(el => wireIChart(el.id)); }
/* simple bar chart: data=[{label, values:[...]}], series=[[name,color]] */
function barChart(data, series, h = 160) {
  if (!data.length) return '<div class="muted small">Nothing recorded in this period.</div>';
  const W = 760, P = 34, bw = Math.max(4, Math.min(24, (W - P - 10) / data.length - 4));
  const max = Math.max(...data.map(d => d.values.reduce((a, b) => a + (b || 0), 0)), 1);
  const x = i => P + 6 + i * ((W - P - 10) / data.length);
  let bars = "";
  data.forEach((d, i) => {
    let y = h - 20;
    d.values.forEach((v, j) => {
      const bh = ((v || 0) / max) * (h - 34);
      y -= bh;
      bars += `<rect x="${x(i)}" y="${y}" width="${bw}" height="${bh}" rx="2" style="fill:${series[j][1]}"><title>${esc(d.label)} · ${esc(series[j][0])}: ${n(v)}</title></rect>`;
    });
    if (data.length <= 16 || i % Math.ceil(data.length / 8) === 0) bars += `<text x="${x(i) + bw / 2}" y="${h - 6}" text-anchor="middle">${esc(d.label.slice(5))}</text>`;
  });
  const ticks = [0, 1].map(t => `<line class="axis" x1="${P}" x2="${W}" y1="${h - 20 - t * (h - 34)}" y2="${h - 20 - t * (h - 34)}"/><text x="${P - 4}" y="${h - 17 - t * (h - 34)}" text-anchor="end">${compact(Math.round(max * t))}</text>`).join("");
  return `<div class="chart"><svg viewBox="0 0 ${W} ${h}" role="img">${ticks}${bars}</svg></div><div class="legend">${series.map(([s, c]) => `<span><i style="background:${c}"></i>${esc(s)}</span>`).join("")}</div>`;
}

// ------------------------------------------------------------------ markdown (safe: escape first, allow-list links)
function inline(s, link) {
  const codes = [];
  s = esc(s).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, t, u) => {
    const raw = u.replace(/&amp;/g, "&");
    if (/^https?:\/\//i.test(raw)) return `<a href="${esc(raw)}" target="_blank" rel="noopener noreferrer">${t}</a>`;
    const xd = link && /^lfgdoc:([a-z]+)\/(.+\.md)$/i.exec(raw);  // link to another docs source
    if (xd) return `<a href="#docs/${esc(xd[1])}/${esc(encodeURIComponent(xd[2]))}">${t}</a>`;
    if (link && /\.md(#.*)?$/i.test(raw) && !/^[a-z]+:/i.test(raw)) return `<a href="#" data-doclink="${esc(raw)}">${t}</a>`;
    return t;
  });
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[\s(])_([^_]+)_(?=[\s).,;:]|$)/g, "$1<em>$2</em>")
    .replace(/(^|[\s(])\*([^*]+)\*(?=[\s).,;:]|$)/g, "$1<em>$2</em>");
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}
function md(text, link) {
  const L = String(text || "").replace(/\r/g, "").split("\n");
  let out = "", i = 0;
  const para = [];
  const flush = () => { if (para.length) { out += `<p>${inline(para.join(" "), link)}</p>`; para.length = 0; } };
  while (i < L.length) {
    const l = L[i];
    if (/^```/.test(l)) {
      flush(); const buf = []; i++;
      while (i < L.length && !/^```/.test(L[i])) buf.push(L[i++]);
      i++; out += `<pre><code>${esc(buf.join("\n"))}</code></pre>`; continue;
    }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < L.length && /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(L[i + 1])) {
      flush();
      const cells = r => r.trim().replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, "|"));
      const hd = cells(l); i += 2; const body = [];
      while (i < L.length && /^\s*\|/.test(L[i])) body.push(cells(L[i++]));
      out += `<div class="md-table"><table><thead><tr>${hd.map(h => `<th>${inline(h, link)}</th>`).join("")}</tr></thead><tbody>${body.map(r => `<tr>${r.map(c => `<td>${inline(c, link)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
      continue;
    }
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.*)$/))) { flush(); out += `<h${m[1].length}>${inline(m[2], link)}</h${m[1].length}>`; i++; continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(l)) { flush(); out += "<hr>"; i++; continue; }
    if (/^>\s?/.test(l)) {
      flush(); const buf = [];
      while (i < L.length && /^>\s?/.test(L[i])) buf.push(L[i++].replace(/^>\s?/, ""));
      out += `<blockquote>${md(buf.join("\n"), link)}</blockquote>`; continue;
    }
    if (/^\s*([-*+]|\d+\.)\s+/.test(l)) {
      flush(); const ordered = /^\s*\d+\./.test(l); const buf = [];
      while (i < L.length && /^\s*([-*+]|\d+\.)\s+/.test(L[i])) {
        let item = L[i++].replace(/^\s*([-*+]|\d+\.)\s+/, "");
        while (i < L.length && /^\s{2,}\S/.test(L[i]) && !/^\s*([-*+]|\d+\.)\s+/.test(L[i])) item += " " + L[i++].trim();
        buf.push(item);
      }
      const li = b => { const t = /^\[( |x|X)\]\s+(.*)$/.exec(b); return t ? `<li class="task${t[1] === " " ? "" : " done"}"><span class="cb" aria-hidden="true"></span><span>${inline(t[2], link)}</span></li>` : `<li>${inline(b, link)}</li>`; };
      out += `<${ordered ? "ol" : "ul"}>${buf.map(li).join("")}</${ordered ? "ol" : "ul"}>`; continue;
    }
    if (!l.trim()) { flush(); i++; continue; }
    para.push(l.trim()); i++;
  }
  flush();
  return out;
}

// ------------------------------------------------------------------ drawer (file viewer)
function openDrawer(title, html) {
  $("#drawer-title").textContent = title;
  $("#drawer-body").innerHTML = html;
  $("#drawer").hidden = false;
  mountTables($("#drawer-body"));
}
function closeDrawer() { $("#drawer").hidden = true; }
function renderFile(name, text) {
  if (/\.md$/i.test(name)) return `<div class="md">${md(frontMatter(text).body)}</div>`;
  if (/\.json$/i.test(name)) {
    let d;
    try { d = JSON.parse(text); } catch (e) { d = undefined; }
    if (d !== undefined) { const v = JSON_VIEWS[name.split("/").pop()]; return `<div class="readable">${v ? v(d) : readable(d)}</div>`; }
  }
  return `<pre class="raw">${esc(text)}</pre>`;
}

// ------------------------------------------------------------------ readable views (never raw JSON)
const txt = v => inline(typeof v === "string" ? v : v == null ? "" : String(v));
const label = k => { const s = words(k).replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); };
/* Any JSON as headings, lists and sentences */
function readable(v) {
  if (v == null || v === "") return '<span class="muted">—</span>';
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v !== "object") return txt(v);
  if (Array.isArray(v)) {
    if (!v.length) return '<span class="muted">None</span>';
    if (v.every(x => x == null || typeof x !== "object")) return `<ul>${v.map(x => `<li>${readable(x)}</li>`).join("")}</ul>`;
    return v.map(x => `<div class="card">${readable(x)}</div>`).join("");
  }
  return `<dl class="kv">${Object.entries(v).map(([k, x]) => `<dt>${esc(label(k))}</dt><dd>${readable(x)}</dd>`).join("")}</dl>`;
}
function moreDetails(d, skip) {
  const r = Object.fromEntries(Object.entries(d || {}).filter(([k, v]) => !skip.includes(k) && v != null && v !== "" && !(Array.isArray(v) && !v.length)));
  return Object.keys(r).length ? `<details class="more"><summary>More details</summary>${readable(r)}</details>` : "";
}
const AXIS = { standards: "Coding standards", spec: "Does what was asked", blast_radius: "Effect on other code", blast: "Effect on other code" };
/* One review or security finding: what's wrong, why, what to do, where */
function findingCard(f) {
  // scanner findings (lfg secure) have an id, item and evidence instead of a title
  const ev = [].concat(f.evidence || []).map(String);
  const head = f.title || f.finding || f.message || (f.type === "vuln" && f.item ? `${f.item} has a known vulnerability (${f.id})` : ev[0] && f.type === "code" ? ev[0] : f.item || f.id) || "Finding";
  const more = f.title ? f.detail || f.finding || f.message : f.detail;
  const where = f.file ? f.file + (f.line ? ":" + f.line : "") : f.where || f.package || f.target || "";
  const links = ev.filter(x => /^https?:\/\//.test(x));
  return `<div class="card"><div class="row">${st(f.severity)}${f.blocking === true ? '<span class="tag">must fix before shipping</span>' : ""}${f.axis ? `<span class="tag">${esc(AXIS[f.axis] || words(f.axis))}</span>` : ""}${f.feedback ? st(f.feedback) : ""}</div>
    <div class="title">${txt(head)}</div>
    ${more ? `<p>${txt(more)}</p>` : ""}
    ${f.fix ? `<p><b>What to do:</b> ${txt(f.fix)}</p>` : ""}
    ${f.reachable ? `<p class="muted small">Can an attacker reach it? ${txt(f.reachable)}</p>` : ""}
    ${f.principle && f.principle !== "None" ? `<p class="muted small">Based on: ${txt(f.principle)}</p>` : ""}
    ${links.length ? `<p class="small">${links.map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">Read the advisory ↗</a>`).join(" · ")}</p>` : ""}
    ${where ? `<div class="muted small mono">${esc(where)}</div>` : ""}</div>`;
}
const SEV_RANK = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, moderate: 2, minor: 3, low: 3, nit: 4 };
const sevRank = f => (f.blocking === true ? -1 : 0) + (SEV_RANK[String(f.severity).toLowerCase()] ?? 5);
const findingList = (fs, none) => (fs || []).length ? [...fs].sort((a, b) => sevRank(a) - sevRank(b)).map(findingCard).join("") : `<p class="muted">${esc(none || "Nothing found.")}</p>`;
/* A task: its description, opening to the steps and how it's checked */
function taskItem(t) {
  if (!t || typeof t !== "object") return "";
  const steps = Array.isArray(t.steps) ? t.steps : [], deps = Array.isArray(t.depends_on) ? t.depends_on : [];
  const body = `${steps.length ? `<div class="k">Steps</div><ol>${steps.map(s => `<li>${txt(s)}</li>`).join("")}</ol>` : ""}
    ${t.verification ? `<div class="k">How we know it works</div><p>${txt(t.verification)}</p>` : ""}
    ${t.notes ? `<div class="k">Notes</div><p>${txt(t.notes)}</p>` : ""}
    ${deps.length ? `<p class="muted small">Waits for: ${esc(deps.join(", "))}</p>` : ""}`;
  return `<details class="item"><summary>${dot(t.passes ? "ok" : "")}<span class="grow">${txt(t.description || t.id || "Task")}</span><span class="muted small nowrap">${t.passes ? "done" : "to do"}</span></summary><div class="item-body">${body}</div></details>`;
}
/* A check that ran (tests, lint, ship check): failed ones open to show the error */
const CHECK_NAMES = { lint: "Lint", types: "Type check", test: "Tests", build: "Build", secrets: "Secret scan",
  suppressions: "No new lint or test suppressions" };
function checkItem(name, result, out, cmd) {
  const [word, tone] = { pass: ["passed", "ok"], fail: ["failed", "bad"], skip: ["not run", ""], na: ["doesn't apply", ""], manual: ["for you to do", "warn"] }[result];
  const body = !["pass", "skip", "na"].includes(result) && out ? `${cmd ? `<div class="muted small mono">${esc(cmd)}</div>` : ""}<pre class="out">${esc(out)}</pre>` : "";
  return `<details class="item${body ? "" : " plain"}"><summary>${dot(tone)}<span class="grow">${esc(CHECK_NAMES[name] || (/\s/.test(name || "") ? name : (w => w.charAt(0).toUpperCase() + w.slice(1))(words(name || ""))))}</span><span class="muted small nowrap">${word}</span></summary>${body ? `<div class="item-body">${body}</div>` : ""}</details>`;
}
const readyChecks = cs => (cs || []).map(c => checkItem(c.name, c.exit === 0 ? "pass" : c.exit == null ? "skip" : "fail", c.tail, c.cmd)).join("");
const shipChecks = cs => (cs || []).map(c => checkItem(c.check || c.name, c.manual ? "manual" : c.status === "n/a" ? "na" : c.ok ? "pass" : c.ok == null ? "skip" : "fail", c.detail)).join("");
/* 07-shipcheck.json: part A (container) checks + the shipping checklist, as one list (same as dash.shipcheck_items) */
const shipItems = d => [].concat(((d.part_a || {}).checks || []).map(c => ({ check: c.check, ok: c.severity === "warn" && c.ok === false ? null : c.ok, detail: c.detail })),
  (d.checklist || (d.part_b || {}).checks || []).map(i => ({ check: i.requirement || i.check, detail: i.detail, manual: i.status === "manual", status: i.status,
    ok: "ok" in i ? i.ok : i.status === "pass" ? true : i.status === "fail" ? false : null })));
const verdictOf = v => (v && typeof v === "object" ? v.overall : v);
const JSON_VIEWS = {
  "06-review.json": d => `<p>${st(d.verdict)}</p>${typeof d.summary === "string" ? `<p>${txt(d.summary)}</p>` : d.summary ? readable(d.summary) : ""}
    <h3>Findings</h3>${findingList(d.findings, "The review found nothing to change.")}${moreDetails(d, ["verdict", "summary", "findings", "run", "base", "lane", "remember"])}`,
  "05-secure.json": d => `<p>${st(verdictOf(d.verdict))}</p>${d.scope ? `<p class="muted">Checked: ${txt(d.scope)}</p>` : ""}
    <h3>Findings</h3>${findingList(d.findings, "No security problems found.")}${moreDetails(d, ["verdict", "scope", "findings", "ts", "run"])}`,
  "05-pentest.json": d => `<p>${st(d.status)}</p>${d.summary || d.conclusion ? `<p>${txt(d.summary || d.conclusion)}</p>` : ""}
    ${(d.preflight_failures || []).length ? `<h3>Why it didn't run</h3><ul>${d.preflight_failures.map(x => `<li>${txt(x)}</li>`).join("")}</ul>` : ""}
    ${d.next_steps ? `<h3>What to do next</h3><p>${txt(d.next_steps)}</p>` : ""}
    ${(d.findings || []).length ? `<h3>Findings</h3>${findingList(d.findings)}` : ""}${moreDetails(d, ["status", "summary", "conclusion", "preflight_failures", "next_steps", "findings", "ts", "ran"])}`,
  "tasks.json": d => { const l = Array.isArray(d) ? d : d.tasks || []; return l.length ? l.map(taskItem).join("") : '<p class="muted">No tasks.</p>'; },
  "ready.json": d => `<p>${st(d.green ? "green" : "red")}</p>${readyChecks(d.checks)}`,
  "07-shipcheck.json": d => `<p>${st(d.pass ? "pass" : "fail")}</p>${(d.part_a || {}).note ? `<p class="muted">${txt(d.part_a.note)}</p>` : ""}${shipChecks(shipItems(d))}${moreDetails(d, ["pass", "part_a", "part_b", "checklist", "ts", "run", "run_id"])}`,
};
/* Skill and rule files start with a YAML header; show its description, not the YAML */
function frontMatter(text) {
  const m = /^---\n([\s\S]*?)\n---\n?/.exec(String(text || ""));
  if (!m) return { meta: {}, body: String(text || "") };
  const meta = {};
  let key = null;  // "key: value", or "key: >" / "key: |" followed by indented lines
  m[1].split("\n").forEach(l => {
    const k = /^([\w-]+):\s*(.*)$/.exec(l);
    if (k) { key = k[1]; meta[key] = /^[>|][-+]?$/.test(k[2]) ? "" : k[2].replace(/^["']|["']$/g, ""); }
    else if (key && /^\s+\S/.test(l)) meta[key] = (meta[key] ? meta[key] + " " : "") + l.trim();
  });
  return { meta, body: text.slice(m[0].length) };
}
// Knowledge entries open their full text: one listener for the page, so lazily drawn tabs need no wiring.
const openKnow = e => {
  const li = e.target.closest && e.target.closest("[data-kn]");
  if (!li || (e.type === "keydown" && e.key !== "Enter")) return;
  const make = (state.know || [])[+li.dataset.kn];
  if (make) openDrawer(...make());
};
document.addEventListener("click", openKnow);
document.addEventListener("click", async e => {  // [data-copy="<id>"]: copy that element's text
  const b = e.target.closest("[data-copy]");
  if (!b) return;
  const el = document.getElementById(b.dataset.copy);
  try { await navigator.clipboard.writeText(el ? el.textContent : ""); b.textContent = "Copied"; } catch (err) { b.textContent = "Select and copy"; }
  setTimeout(() => (b.textContent = "Copy"), 1600);
});
document.addEventListener("keydown", openKnow);

async function checkUpdates() {
  const box = $("#update-banner");
  if (!box) return;
  let upd;
  try { upd = await api("updates"); } catch (e) { return; }
  if (!upd || !upd.update_available) return;
  let dismissed = null;
  try { dismissed = localStorage.getItem("lfg.update.dismissed"); } catch (e) { /* ignore */ }
  if (dismissed === upd.upstream) return;
  box.innerHTML = `<div class="promo" role="region" aria-label="Update available">
    <div class="grow">
      <div class="promo-title"><span class="tag">Update</span> LFG ${esc(upd.upstream)} is available</div>
      <div class="promo-text">You have ${esc(upd.current)}. In your LFG clone run <code id="upd-cmd">git pull && ./install.sh</code> <button class="btn small" data-copy="upd-cmd">Copy</button>, then restart <code>lfg ui</code>.</div>
      ${upd.notes ? `<details class="promo-notes"><summary>What's new</summary><div class="md">${md(upd.notes)}</div></details>` : ""}
    </div>
    <button class="icon-btn" id="update-close" aria-label="Close" title="Don't show for this version">&times;</button>
  </div>`;
  $("#update-close", box).onclick = () => {
    try { localStorage.setItem("lfg.update.dismissed", upd.upstream); } catch (e) { /* ignore */ }
    box.innerHTML = "";
  };
}

function wireOnboarding(root) {
  const saveBtn = $("#onboard-save", root);
  const skipBtn = $("#onboard-skip", root);
  const msgEl = $("#onboard-msg", root);
  if (!saveBtn) return;
  const count = () => { const n = $$("[data-feature]", root).filter(c => c.checked).length; $("#wl-count", root).textContent = `${n} selected`; };
  $$("[data-feature]", root).forEach(c => c.addEventListener("change", count)); count();
  saveBtn.onclick = async () => {
    saveBtn.disabled = true; saveBtn.textContent = "Saving…";
    const selected = $$("[data-feature]", root).filter(c => c.checked).map(c => c.dataset.feature);
    const r = await save("onboarding_save", { features: selected });
    if (r.ok) {
      state.pages = r.pages || NAV.map(p => p[0]);
      renderNav("sessions");
      state.pendingTour = "page-sessions";
      location.hash = "#sessions";
    } else {
      saveBtn.disabled = false; saveBtn.textContent = "Start with these";
      if (msgEl) saidMsg(msgEl, r);
    }
  };
  skipBtn.onclick = async () => {
    skipBtn.disabled = true;
    const r = await save("onboarding_save", { skip: true });
    if (r.ok) {
      state.pages = NAV.map(p => p[0]);
      renderNav("sessions");
      state.pendingTour = "page-sessions";
      location.hash = "#sessions";
    } else {
      skipBtn.disabled = false;
      if (msgEl) saidMsg(msgEl, r);
    }
  };
}

function wire(root) {
  $$("[data-run-file]", root).forEach(a => a.onclick = async e => {
    e.preventDefault();
    const [run, f] = JSON.parse(a.dataset.runFile);
    const d = await api("file", { run, f });
    openDrawer(a.textContent, renderFile(f, d.text));
  });
  $$("[data-rule-module]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    const m = (state.rules.modules || []).find(x => x.name === a.dataset.ruleModule);
    if (m) openDrawer(words(m.name), renderFile(m.name + ".md", m.text));
  });
  wireSettings(root);
  wireMap(root);
  $$("[data-run-checks]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("run_checks", { repo: state.repo, run: b.dataset.runChecks });
    if (!r.ok) { b.disabled = false; b.textContent = "Run checks again"; alert(String(r.why || "Couldn't start the checks.").replace(/`/g, "")); return; }
    state.cache = {}; route();
  });
  $$("[data-run-needed]", root).forEach(b => b.onclick = async () => {
    b.disabled = true;
    const r = await save("run_needed", { repo: state.repo, run: b.dataset.run, needed: b.dataset.runNeeded === "1" });
    if (!r.ok) { b.disabled = false; return alert(String(r.why || "Not saved.")); }
    state.cache = {}; route();
  });
  if ($("[data-checks-running]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-checks-running]", root)) { state.cache = {}; route(); } }, 10000);
  if ($("[data-run-working]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-run-working]", root)) { state.cache = {}; route(); } }, 8000);
  if ($("[data-spend-pending]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-spend-pending]", root)) route(); }, 4000);
}

// ------------------------------------------------------------------ rules: hover any mention to see what it means
const RULE_RX = /\b(?:[Rr]ule (\d{1,2})\b|lfg rule ([a-z][a-z-]+))/g;
function ruleTip(num, mod) {
  const R = state.rules;
  if (!R) return "";
  if (num) {
    const r = R.rules.find(x => x.id === num);
    return r ? `Rule ${r.id}: ${r.title}\n${r.summary}` : "";
  }
  const m = R.modules.find(x => x.name === mod);
  return m ? `${words(m.name)}\n${m.summary}` : "";
}
function decorateRules(root) {
  if (!state.rules || !root || root.nodeType !== 1 || root.closest(".rule-ref, textarea, script, style, option")) return;
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: t => (t.parentElement.closest(".rule-ref, textarea, script, style, option, select") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const hits = [];
  for (let t = walk.nextNode(); t; t = walk.nextNode()) { RULE_RX.lastIndex = 0; if (RULE_RX.test(t.data)) hits.push(t); }
  for (const t of hits) {
    const frag = document.createDocumentFragment();
    let last = 0;
    RULE_RX.lastIndex = 0;
    for (const m of t.data.matchAll(RULE_RX)) {
      const tip = ruleTip(m[1], m[2]);
      if (!tip) continue;
      frag.append(t.data.slice(last, m.index));
      const span = document.createElement("span");
      span.className = "rule-ref"; span.dataset.tip = tip; span.textContent = m[0];
      frag.append(span);
      last = m.index + m[0].length;
    }
    if (!last) continue;
    frag.append(t.data.slice(last));
    t.replaceWith(frag);
  }
}
function mountRuleTips() {
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(decorateRules))).observe(document.body, { childList: true, subtree: true });
  decorateRules(document.body);
  const tip = document.createElement("div");
  tip.id = "tip"; tip.hidden = true; document.body.append(tip);
  document.addEventListener("mouseover", e => {
    const el = e.target.closest && e.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip; tip.hidden = false;
    const r = el.getBoundingClientRect(), w = Math.min(360, window.innerWidth - 16);
    tip.style.maxWidth = w + "px";
    tip.style.left = Math.max(8, Math.min(r.left, window.innerWidth - w - 8)) + "px";
    const below = r.bottom + 6, h = tip.offsetHeight;
    tip.style.top = (below + h > window.innerHeight ? r.top - h - 6 : below) + "px";
  });
  window.addEventListener("scroll", () => (tip.hidden = true), true);
}

// ------------------------------------------------------------------ settings (the only writes)
const editKey = () => localStorage.getItem("lfg.editKey") || "";
async function isUnlocked() { return true; }  // editing is always on; the server only takes changes from this page
async function save(what, body) {
  try {
    const r = await fetch(`/api/save/${what}`, { method: "POST", body: JSON.stringify(body),
      headers: { "X-LFG": "1", "X-LFG-Key": editKey(), "Content-Type": "application/json" } });
    return await r.json();
  } catch (e) { return { ok: false, why: e.message }; }
}
function saidMsg(el, d, okText) {
  el.className = "save-msg " + (d.ok ? "ok" : "bad");
  el.innerHTML = d.ok ? esc(okText || "Saved.") + [].concat(d.notes || [], d.note || []).map(x => " " + fmtWhy(x)).join("") : fmtWhy(d.why || "Not saved.");
}
function fieldInput(f, locked) {
  const id = `cfg-${f.key}`, dis = locked ? "disabled" : "", v = f.value;
  if (f.type === "bool") return `<span class="tgl-wrap"><input type="checkbox" id="${id}" data-cfg="${esc(f.key)}" ${v ? "checked" : ""} ${dis} role="switch"><span class="tgl"></span></span>`;
  if (f.type === "choice") return `<select id="${id}" data-cfg="${esc(f.key)}" ${dis}>${f.options.map(o => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  if (f.type === "int") return `<input type="number" id="${id}" data-cfg="${esc(f.key)}" min="${f.min}" max="${f.max}" value="${esc(v)}" ${dis}>`;
  const val = Array.isArray(v) ? v.join(", ") : v ?? "";
  return `<input type="text" id="${id}" data-cfg="${esc(f.key)}" value="${esc(val)}" ${dis}>`;
}
/* General settings, grouped by what they're for; the model choices get their own card */
const SET_GROUPS = [
  ["How LFG works", "What Claude may do, how big a change can be for each lane, and the line LFG adds to replies.", k => /^(guard|lanes|replies|graphs)\./.test(k)],
  ["Agent models", "Which Claude model each of LFG's agents uses.", k => k.startsWith("models.")],
  ["Dashboard and disk space", "", k => /^(ui|storage)\./.test(k)],
];
const settingRow = (f, unlocked) => `<label class="set-row" for="cfg-${esc(f.key)}"><div><div class="set-label">${esc(f.label.replace(/^Model:\s*/, "").replace(/-/g, " ").replace(/^./, c => c.toUpperCase()))}</div>${f.help ? `<div class="set-help">${esc(f.help)}</div>` : ""}</div><div class="set-input">${fieldInput(f, !unlocked)}</div></label>`;
function settingsGroups(cfg, unlocked) {
  const fields = cfg.fields.filter(f => !f.owner && f.key !== "updates.auto_check"), used = new Set();
  const row = f => settingRow(f, unlocked);
  const card = (title, note, list) => list.length ? `<div class="set-section"><h4>${esc(title)}</h4>${note ? `<p class="muted">${esc(note)}</p>` : ""}${list.map(row).join("")}</div>` : "";
  let out = SET_GROUPS.map(([t, n, test]) => { const list = fields.filter(f => test(f.key)); list.forEach(f => used.add(f.key)); return card(t, n, list); }).join("");
  out += card("Other", "", fields.filter(f => !used.has(f.key)));
  return out;
}
const AP_THEMES = {
  light: [["lfg", "LFG", "Soft white and blue", ["#f6f8fc", "#ffffff", "#0e1729", "#2563eb", "#f1f4fa"]],
    ["paper", "Paper", "Warm neutral, easy on the eyes", ["#fbfaf7", "#ffffff", "#2b2a26", "#2563eb", "#f6f4ef"]],
    ["mist", "Mist", "Cool grey, crisp contrast", ["#f4f5f7", "#ffffff", "#111318", "#2563eb", "#eceef2"]]],
  dark: [["midnight", "Midnight", "Deep navy with a blue glow", ["#070b14", "#0d1424", "#e6ebf5", "#3b82f6", "#0a101e"]],
    ["graphite", "Graphite", "Neutral grey, no tint", ["#111214", "#18191c", "#ececee", "#3b82f6", "#141518"]],
    ["carbon", "Carbon", "True black for OLED screens", ["#000000", "#0a0a0b", "#f2f2f3", "#3b82f6", "#050506"]]],
};
const AP_ACCENTS = [["blue", "#2563eb"], ["violet", "#7c3aed"], ["green", "#059669"], ["orange", "#ea580c"], ["rose", "#e11d48"]];
function settingsAppearance() {
  const a = apRead();
  const seg = (k, opts) => `<div class="seg">${opts.map(([v, t]) => `<button class="pill${a[k] === v ? " on" : ""}" data-ap="${k}" data-v="${v}">${t}</button>`).join("")}</div>`;
  const card = (kind, [id, name, about, [pg, sf, tx, ac, sd]]) => `<button class="ap-theme${a[kind] === id ? " on" : ""}" data-ap="${kind}" data-v="${id}" style="--p:${pg}">
    <span class="ap-prev" style="background:${pg}"><i class="s" style="background:${sd}"></i><span class="c" style="background:${sf};box-shadow:0 0 0 1px ${tx}1a"><b style="background:${tx}"></b><b style="background:${tx}55"></b><b class="a" style="background:${ac}"></b></span></span>
    <span class="ap-name">${esc(name)}<span class="muted">${esc(about)}</span></span></button>`;
  const row = (label, help, ctl) => `<div class="set-row"><div><div class="set-label">${label}</div>${help ? `<div class="set-help">${help}</div>` : ""}</div><div class="set-input">${ctl}</div></div>`;
  return `<div class="set-section"><h4>Mode</h4>${row("Light or dark", "System follows your computer's setting.", seg("mode", [["system", "System"], ["light", "Light"], ["dark", "Dark"]]))}</div>
    <div class="set-section"><h4>Light theme</h4><div class="ap-grid">${AP_THEMES.light.map(t => card("light", t)).join("")}</div><p class="muted small">Used in light mode.</p></div>
    <div class="set-section"><h4>Dark theme</h4><div class="ap-grid">${AP_THEMES.dark.map(t => card("dark", t)).join("")}</div><p class="muted small">Used in dark mode.</p></div>
    <div class="set-section"><h4>Look and feel</h4>
      ${row("Accent colour", "Buttons, links, selection and focus.", `<div class="ap-acc">${AP_ACCENTS.map(([v, c]) => `<button class="${a.accent === v ? "on" : ""}" data-ap="accent" data-v="${v}" style="background:${c}" title="${v}" aria-label="${v}"></button>`).join("")}</div>`)}
      ${row("Density", "Compact fits more rows on screen.", seg("density", [["comfortable", "Comfortable"], ["compact", "Compact"]]))}
      ${row("Text size", "", seg("text", [["s", "Small"], ["m", "Default"], ["l", "Large"]]))}
      ${row("Background glow", "The faint coloured light behind the page.", seg("glow", [["on", "On"], ["off", "Off"]]))}
      ${row("Motion", "Animations and transitions.", seg("motion", [["on", "On"], ["off", "Reduced"]]))}
    </div>
    <div class="set-actions"><button class="btn" data-ap-reset>Reset to default</button><span class="muted small">Saved in this browser.</span></div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-ap]");
  if (b) { apSet(b.dataset.ap, b.dataset.v); $$(`[data-ap="${b.dataset.ap}"]`).forEach(x => x.classList.toggle("on", x === b)); return; }
  if (e.target.closest("[data-ap-reset]")) { try { localStorage.removeItem("lfg.appearance"); } catch (err) { /* ignore */ } apApply(); apFavicon(); route({ soft: true }); }
});
function settingsGeneral() {
  const { cfg, unlocked } = state.settings;
  return `<div class="set-section"><h4>Features</h4><p class="muted">Pick what you use; the sidebar shows only those pages. Changes apply right away.</p>
      <div id="features-section"><div class="loading">Loading features…</div></div>
      <label class="row mt"><input type="checkbox" id="show-all-pages" ${state.settings?.showAll ? "checked" : ""} ${!unlocked ? "disabled" : ""}> Show every page in the sidebar anyway</label>
      <p class="muted small" style="margin-top:8px"><a href="#onboarding">Run the welcome again</a></p>
    </div>
    <div class="set-section"><h4>Updates</h4>
      ${cfg.fields.filter(f => f.key === "updates.auto_check").map(f => settingRow(f, unlocked)).join("")}
      <div class="row" style="padding: 10px 0 4px"><button class="btn" id="check-updates-btn" ${!unlocked ? "disabled" : ""}>Check for updates</button><span id="updates-msg" class="save-msg ml"></span></div>
    </div>
    ${settingsGroups(cfg, unlocked)}
    <div class="set-actions"><button class="btn primary" id="cfg-save" ${unlocked ? "" : "disabled"}>Save</button><span class="save-msg" id="cfg-msg"></span></div>`;
}
function settingsSkills() {
  const { sk } = state.settings;
  return `<div class="skill-edit"><nav>${sk.skills.map(x => `<a href="#" data-skill="${esc(x.name)}" title="${esc(x.description)}">/lfg:${esc(x.name)}${x.edited ? '<span class="tag">edited</span>' : ""}</a>`).join("")}</nav>
    <div class="grow"><div id="skill-editor">${empty("Pick a skill to read or change it", "Your changes survive updates and apply to new Claude Code sessions.")}</div></div></div>`;
}
function settingsClaude() {
  const { cm, unlocked } = state.settings;
  return `<div class="row"><p class="muted grow">Your own instructions for every Claude Code session (<code>~/.claude/CLAUDE.md</code>). They always win over LFG, and LFG never writes to this file.${cm.has_lfg_section ? " It still has a block an older LFG added: Settings → Claude Code can remove it." : ""}</p>${unlocked ? '<button class="btn" id="cm-edit">Change</button>' : ""}</div>
    <div id="cm-read" class="box pad md">${md(cm.text)}</div>
    <div id="cm-write" hidden><p class="muted small">Written in Markdown.</p><textarea class="editor" id="cm-text" spellcheck="false">${esc(cm.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="cm-save">Save</button><button class="btn" id="cm-cancel">Cancel</button><span class="save-msg" id="cm-msg"></span></div></div>`;
}
function settingsRules() {
  const R = state.rules || { rules: [], modules: [] }, un = state.settings.unlocked;
  const rows = R.rules.map(r => `<li><span class="muted nowrap">${esc(r.id)}.</span><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta">${esc(r.summary)}</div></div></li>`).join("");
  const tag = m => m.yours ? '<span class="tag">yours</span>' : m.edited ? '<span class="tag">edited</span>' : "";
  return `<div class="set-section" style="margin-top:0"><h4>Guidance agents read</h4>
    <p class="muted">Agents load these with <code>lfg rule &lt;name&gt;</code>. ${un ? "Change any of them in Markdown, or add your own: every new Claude Code session is told to follow rules you add." : "Unlock editing to change them or add your own."}</p>
    <div class="skill-edit"><nav>${R.modules.map(m => `<a href="#" data-rule="${esc(m.name)}" title="${esc(m.summary)}">${esc(words(m.name))}${tag(m)}</a>`).join("")}${un ? '<a href="#" data-rule-new class="add">+ Add a rule</a>' : ""}</nav>
    <div class="grow"><div id="rule-editor">${empty("Pick a rule to read or change it", "Your changes survive updates. A copy is kept every time you save.")}</div></div></div></div>
    <div class="set-section"><h4>Safety rules</h4><p class="muted">What every LFG session must follow. LFG enforces these in code, so they can't be changed or switched off here.</p>
    <div class="box"><ul class="list">${rows}</ul></div></div>`;
}
async function reloadRules(pick) {
  state.rules = await api("rules");
  const body = $("#settings-body");
  if (body) { body.innerHTML = settingsRules(); wire(body); }
  if (pick) { $$("[data-rule]").forEach(x => x.classList.toggle("on", x.dataset.rule === pick)); showRule(pick); }
}
function wireRules(root) {
  $$("[data-rule]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    $$("[data-rule], [data-rule-new]", root).forEach(x => x.classList.toggle("on", x === a));
    showRule(a.dataset.rule);
  });
  const nw = $("[data-rule-new]", root);
  if (nw) nw.onclick = e => {
    e.preventDefault();
    $$("[data-rule], [data-rule-new]", root).forEach(x => x.classList.toggle("on", x === nw));
    newRule();
  };
}
function newRule() {
  const box = $("#rule-editor");
  box.innerHTML = `<p><b>Add a rule</b></p><p class="muted small">Give it a short name (lowercase, dashes) and write it in Markdown. Agents read it with <code>lfg rule &lt;name&gt;</code>, and new sessions are told to follow it.</p>
    <label class="set-label" for="rule-name">Name</label><input type="text" id="rule-name" placeholder="api-style" maxlength="41" style="width:100%;margin:4px 0 12px">
    <textarea class="editor" id="rule-text" spellcheck="false"># api-style: one line saying what this rule is about

- What to always do
- What never to do, and why
</textarea>
    <div class="set-actions"><button class="btn primary" id="rule-save">Add</button><span class="save-msg" id="rule-msg"></span></div>`;
  $("#rule-save").onclick = async () => {
    const name = $("#rule-name").value.trim().toLowerCase();
    if ((state.rules?.modules || []).some(m => m.name === name) && !confirm(`A rule called "${name}" already exists. Replace its text with this?`)) return;
    const r = await save("rule", { name, text: $("#rule-text").value });
    saidMsg($("#rule-msg"), r);
    if (r.ok) reloadRules(r.saved);
  };
}
function showRule(name) {
  const box = $("#rule-editor"), un = state.settings.unlocked;
  const m = (state.rules?.modules || []).find(x => x.name === name);
  if (!m) { box.innerHTML = empty("Rule not found", ""); return; }
  const undo = m.yours ? '<button class="btn danger" id="rule-reset">Delete this rule</button>' : m.edited ? '<button class="btn" id="rule-reset">Undo my changes</button>' : "";
  box.innerHTML = `<div class="row" style="margin-bottom:8px"><b>${esc(words(name))}</b>${m.yours ? '<span class="tag">added by you</span>' : m.edited ? '<span class="tag">edited by you</span>' : ""}<span class="grow"></span>${un ? '<button class="btn" id="rule-edit">Change</button>' : ""}</div>
    <div id="rule-read"><p class="muted small">Agents read this with <code>lfg rule ${esc(name)}</code>.</p><div class="md">${md(m.text)}</div></div>
    <div id="rule-write" hidden><p class="muted small">Written in Markdown.</p>
    <textarea class="editor" id="rule-text" spellcheck="false">${esc(m.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="rule-save">Save</button><button class="btn" id="rule-cancel">Cancel</button>${undo}<span class="save-msg" id="rule-msg"></span></div></div>`;
  const mode = edit => { $("#rule-read").hidden = edit; $("#rule-write").hidden = !edit; if ($("#rule-edit")) $("#rule-edit").hidden = edit; };
  if ($("#rule-edit")) $("#rule-edit").onclick = () => mode(true);
  $("#rule-cancel").onclick = () => showRule(name);
  $("#rule-save").onclick = async () => {
    const r = await save("rule", { name, text: $("#rule-text").value });
    saidMsg($("#rule-msg"), r);
    if (r.ok) reloadRules(name);
  };
  const rs = $("#rule-reset");
  if (rs) rs.onclick = async () => {
    if (!confirm(m.yours ? `Delete the rule "${name}"? A copy is kept in LFG's backups.` : `Put "${name}" back to how LFG ships it? A copy of your version is kept.`)) return;
    const r = await save("rule_reset", { name });
    if (!r.ok) return saidMsg($("#rule-msg"), r);
    reloadRules(r.deleted ? null : name);
    if (r.deleted) $("#rule-editor").innerHTML = empty("Rule deleted", "A copy is kept in LFG's backups.");
  };
}
// ------------------------------------------------------------------ settings → Claude Code (LFG's footprint, all undoable)
/* Dictate's own options, right on its pack row */
function dictateControls(o, dis) {
  if (o.preview) dis = "disabled";
  return `<div class="dictate-opts${o.preview ? " preview" : ""}">${o.preview ? '<div class="preview-note">These controls work once Dictate is on.</div>' : ""}
    <label>Shortcut <select data-dict="dictate.shortcut" ${dis}>${o.shortcuts.map(([k, l]) => `<option value="${esc(k)}" ${k === o.shortcut ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>
    <label>Put text in by <select data-dict="dictate.insert" ${dis}><option value="paste" ${o.insert === "paste" ? "selected" : ""}>Pasting</option><option value="type" ${o.insert === "type" ? "selected" : ""}>Typing</option></select></label>
    <label class="row"><input type="checkbox" data-dict="dictate.cleanup" ${o.cleanup ? "checked" : ""} ${dis}><span>Clean up with Claude <span class="meta">· removes filler words; sends the text (never audio) to Claude</span></span></label>
    <a href="#" class="small" data-tour-start="${o.preview ? "dictate-intro" : "dictate"}">Take the tour</a>
  </div>`;
}
function settingsClaudeCode() {
  return '<div id="cc-box"><div class="loading">Looking at your Claude Code setup…</div></div>';
}
let ccTimer = null;
const where = r => r.root.replace(/^\/Users\/[^/]+/, "~");
async function loadClaudeCode() {
  const box = $("#cc-box");
  if (!box) return;
  const d = await api("claude"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const R = d.repos, hr = d.headroom, sc = d.scan;
  const repoRows = R.repos.filter(r => r.exists).map(r => `<li>${dot(r.enabled ? "ok" : "")}<div class="grow"><div class="title">${esc(r.name)}</div><div class="meta">${esc(where(r))}${r.hardened ? " · hardened" : ""}${r.headroom ? " · Headroom" : ""}</div></div>
    ${R.everywhere ? '<span class="muted small">on everywhere</span>' : `<button class="btn small" data-cc="${r.enabled ? "repo_off" : "repo_on"}" data-root="${esc(r.root)}" ${dis}>${r.enabled ? "Turn off" : "Turn on"}</button>`}</li>`).join("");
  const job = name => {
    const j = d.jobs[name];
    return j ? `<div class="meta">${j.status === "running" ? "Installing…" : j.status === "done" ? "Installed." : "Install failed."}</div>${j.log.length ? `<pre class="joblog">${esc(j.log.slice(-12).join("\n"))}</pre>` : ""}` : "";
  };
  const packRows = d.packs.map(p => `<li data-pack="${esc(p.name)}">${dot(p.on ? (p.missing.length ? "warn" : "ok") : "")}<div class="grow"><div class="title">${esc(p.title.replace(" (experimental)", ""))}${p.experimental ? ' <span class="tag">Experimental</span>' : ""}</div><div class="meta">${esc(p.about)}${p.detail ? `<br>${fmtWhy(p.detail)}` : ""}${p.settings ? dictateControls(p.settings, dis) : ""}${p.on && p.missing.length ? ` · missing: ${esc(p.missing.map(m => m.split(":")[1]).join(", "))}` : ""}</div>${job(p.name)}</div>
    ${p.name === "core" ? '<span class="muted small">always on</span>' : p.on && !p.missing.length ? `<button class="btn small" data-cc="pack_remove" data-name="${esc(p.name)}" ${dis}>Turn off</button>` : `<button class="btn small" data-cc="pack_add" data-name="${esc(p.name)}" ${dis || ((d.jobs[p.name] || {}).status === "running" ? "disabled" : "")}>${p.on ? "Install missing" : "Add"}</button>`}</li>`).join("");
  const hrOpts = [["off", "Off"], ["repos", "Only repos where LFG is on"], ["everywhere", "Every Claude Code session"]];
  const hrBlocked = hr.cloud_provider ? `Not available: Claude Code uses ${esc(hr.cloud_provider)} here.` : !hr.installed ? "Add the Headroom pack first." : "";
  const changes = d.changes.length ? `<div class="box"><ul class="list">${d.changes.slice().reverse().map(c => `<li><span class="muted nowrap">#${c.id}</span><div class="grow"><div class="title">${fmtWhy(c.text)}</div><div class="meta">${esc(c.why)} · ${ago(c.ts)}</div></div><button class="btn small" data-cc="change_undo" data-id="${c.id}" ${dis}>Undo</button></li>`).join("")}</ul></div>`
    : `<div class="box calm">${dot("ok")}LFG has changed nothing outside ~/.lfg.</div>`;
  const legacy = d.legacy.length ? `<div class="set-section"><h4>Left over from an older LFG</h4><p class="muted">Older versions changed Claude Code for every session. Each fix below removes exactly what LFG added.</p>
    <div class="box"><ul class="list">${d.legacy.map(l => `<li>${dot("warn")}<div class="grow"><div class="title">${esc(l.title)}</div><div class="meta">${esc(l.fix)}</div></div>${l.default ? `<button class="btn small" data-cc="legacy_fix" data-id="${esc(l.id)}" ${dis}>Fix</button>` : ""}</li>`).join("")}</ul></div></div>` : "";
  box.innerHTML = `<p class="muted">What LFG does to Claude Code, and where. Everything here is recorded and can be undone; nothing outside the repos you pick is touched.</p>
    <span class="save-msg" id="cc-msg"></span>${legacy}
    <div class="set-section" id="cc-where"><h4>Where LFG is on</h4><p class="muted">In other repos Claude Code works exactly as if LFG weren't installed: no skills, hooks or MCP servers.</p>
      <label class="row"><input type="checkbox" data-cc="everywhere" ${R.everywhere ? "checked" : ""} ${dis}> Turn LFG on in every repo <span class="muted small">(not recommended)</span></label>
      <div class="box mt">${repoRows ? `<ul class="list">${repoRows}</ul>` : empty("No repos yet", "Run <code>lfg enable</code> in a repo, or open one in Claude Code after enabling it.")}</div></div>
    <div class="set-section"><h4>Integrations</h4><p class="muted">Feature packs (Headroom, SonarQube, Dictate, pentest with Ollama and Strix, and the rest) and their settings are on the <a href="#integrations">Integrations</a> page.</p></div>
    <div class="set-section"><h4>Safety</h4>
      <div class="box pad"><div class="row">${dot("ok")}<div class="grow"><b>Guard</b><div class="meta">On in every LFG repo: blocks pushes, secret reads, deploys and the rest of the 18 rules (Settings → Rules), and asks you before any commit. Recently blocked: ${d.blocked.length ? d.blocked.slice(0, 3).map(b => `rule ${esc(b.rule)} (${esc(b.tool)})`).join(", ") : "nothing"}.</div></div></div>
      <label class="row mt"><input type="checkbox" data-cc="commits" ${d.allow_commits ? "checked" : ""} ${dis}><span><b>Let Claude commit when I ask</b><span class="meta"> · each commit becomes an approval prompt in Claude Code; pushing, merging, rebasing, PRs, secrets and deploys stay blocked</span></span></label>
      <label class="row mt" id="cc-hardened"><input type="checkbox" data-cc="hardened" ${d.hardened ? "checked" : ""} ${dis}><span><b>Hardened mode</b><span class="meta"> · also add Claude Code deny rules (git commit/push, secret files…) to each LFG repo's <code>.claude/settings.local.json</code>, never to your user settings</span></span></label></div></div>
    <div class="set-section"><h4>MCP servers LFG brings</h4><p class="muted">Only in LFG repos. One that isn't set up stays quiet and offers no tools.</p>
      <div class="box"><ul class="list">${d.mcp.map(m => `<li>${dot(m.ready ? "ok" : "")}<div class="grow"><div class="title">${esc(m.name)}</div><div class="meta">${m.ready ? "ready" : fmtWhy(m.why)}</div></div></li>`).join("")}</ul></div></div>
    <div class="set-section"><h4>Your Claude Code setup <span class="muted small">(read-only; LFG leaves these alone)</span></h4>
      <div class="box"><ul class="list">
        <li><div class="grow"><div class="title">Claude Code ${esc(sc.claude.version || "not found")}</div><div class="meta">${sc.managed_settings ? "Managed by your organisation's policy: " + esc(sc.managed_settings) : "No organisation policy"}${sc.base_url_host ? " · API endpoint " + esc(sc.base_url_host) : ""}</div></div></li>
        <li><div class="grow"><div class="title">Your hooks</div><div class="meta">${sc.user_hooks.length ? esc(sc.user_hooks.join(", ")) : "none"}</div></div></li>
        <li><div class="grow"><div class="title">Your MCP servers (every session)</div><div class="meta">${sc.user_mcp_servers.length ? esc(sc.user_mcp_servers.join(", ")) : "none"}</div></div></li>
        <li><div class="grow"><div class="title">Skills that share a name with LFG's</div><div class="meta">${sc.skill_collisions.length ? sc.skill_collisions.map(x => `<code>/${esc(x)}</code> is yours, LFG's is <code>/lfg:${esc(x)}</code>`).join(" · ") : "none"}</div></div></li>
      </ul></div></div>
    <div class="set-section"><h4>Changes LFG made outside ~/.lfg</h4>${changes}
      <p class="muted small mt">To remove LFG completely, run <code>lfg uninstall</code> in your terminal. It lists everything it will undo before it does anything.</p></div>`;
  $$("[data-dict]", box).forEach(el => el.onchange = async () => {
    el.disabled = true;
    state.ccMsg = await save("config", { values: { [el.dataset.dict]: el.type === "checkbox" ? el.checked : el.value } });
    loadClaudeCode();
  });
  $$("[data-cc]", box).forEach(el => {
    const act = el.dataset.cc, ev = el.type === "checkbox" ? "onchange" : "onclick";
    el[ev] = async () => {
      if (act === "commits") { state.ccMsg = await save("config", { values: { "guard.allow_commits": el.checked } }); loadClaudeCode(); return; }
      const body = act === "everywhere" || act === "hardened" ? { on: el.checked } : act === "headroom" ? { scope: $("#cc-hr").value }
        : { root: el.dataset.root, name: el.dataset.name, id: el.dataset.id };
      if (act === "repo_off" && !confirm(`Turn LFG off in ${el.dataset.root}? Its graphs and runs are kept.`)) return;
      if (act === "everywhere" && el.checked && !confirm("Turn LFG on in every repo, including ones you never set up? Each repo can't opt out while this is on.")) { el.checked = false; return; }
      el.disabled = true;
      state.ccMsg = await save(act, body);
      loadClaudeCode();
    };
  });
  if (state.ccMsg) { saidMsg($("#cc-msg", box), state.ccMsg, state.ccMsg.ok ? "Done." : ""); state.ccMsg = null; }
  $$("[data-tour-start]", box).forEach(l => l.onclick = e => { e.preventDefault(); startTour(l.dataset.tourStart); });
  if (state.pendingTour && $('[data-pack="dictate"]', box)) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 250); }
  clearTimeout(ccTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) ccTimer = setTimeout(() => { if (document.body.contains(box)) loadClaudeCode(); }, 2000);
}

// ------------------------------------------------------------------ integrations: every tool LFG works with, on one page
async function integrationsPage() {
  const [cfg, unlocked] = await Promise.all([api("settings"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { cfg, unlocked });
  return `${head("Integrations", "The tools LFG works with. Turn one on and its settings appear on its card; everything installs locally and can be turned off again.")}
    ${unlocked ? "" : `<div class="callout">Read-only. To change anything, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <span class="save-msg" id="int-msg"></span><div id="int-box"><div class="loading">Checking each integration…</div></div>`;
}
let intTimer = null;
const INT_ICON = { core: "code", knowledge: "knowledge", headroom: "compress", sonarqube: "checks", dictate: "mic", pentest: "target", security: "lock", shipcheck: "box", linear: "issues", github: "branch" };
async function loadIntegrations() {
  const box = $("#int-box");
  if (!box) return;
  const d = await api("integrations"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const claude = await api("claude").catch(() => ({}));
  state.intOpen = state.intOpen || new Set();
  if (state.pendingTour) state.intOpen.add("dictate");
  const job = name => { const j = d.jobs[name]; return j ? `<div class="int-job"><span class="meta">${j.status === "running" ? "Installing…" : j.status === "done" ? "Installed" : "Install failed"}</span>${j.log.length ? `<pre class="joblog">${esc(j.log.slice(-8).join("\n"))}</pre>` : ""}</div>` : ""; };
  const sw = i => i.fixed || i.name === "core" ? '<span class="muted small nowrap">Always on</span>'
    : `<button class="tgl${i.on ? " on" : ""}" role="switch" aria-checked="${i.on}" aria-label="${i.on ? "Turn off" : "Turn on"} ${esc(i.title)}" data-int-switch="${esc(i.name)}" ${dis || ((d.jobs[i.name] || {}).status === "running" ? "disabled" : "")}></button>`;
  const field = f => `<label class="int-field"><span class="grow"><span class="set-label">${esc(f.label.replace(/^(Headroom|Ship check|SonarQube|Dictate|Pentest|Linear)\s*:?\s*/i, "").replace(/^./, c => c.toUpperCase()))}</span>${f.help ? `<span class="set-help">${esc(f.help)}</span>` : ""}</span>${f.type === "bool" ? `<span class="tgl-wrap"><input type="checkbox" data-cfg="${esc(f.key)}" aria-label="${esc(f.label)}" ${f.value ? "checked" : ""} ${dis}><span class="tgl" aria-hidden="true"></span></span>` : fieldInput(f, !un)}</label>`;
  const extra = i => {
    if (i.name === "headroom" && claude.headroom) {
      const hr = claude.headroom, opts = [["off", "Off"], ["repos", "LFG repos"], ["everywhere", "Every session"]];
      return `<label class="int-field"><span class="grow"><span class="set-label">Route Claude Code through it</span><span class="set-help">${hr.cloud_provider ? `Not available: Claude Code uses ${esc(hr.cloud_provider)} here.` : "New sessions pick it up."}</span></span><select id="int-hr" data-int-act="headroom" ${dis}>${opts.map(([v, l]) => `<option value="${v}" ${v === hr.scope ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
    }
    if (i.name === "knowledge") return `<div class="int-acts"><button class="btn small" data-int-act="omnigraph_restart" ${dis}>Restart the servers</button></div>`;
    if (i.name === "sonarqube") return `<div class="int-acts">${/needs a restart/.test(i.status) ? `<button class="btn small primary" data-int-act="sonar_apply" ${dis}>Restart to apply</button>` : ""}<a class="btn small" href="http://127.0.0.1:9000" target="_blank" rel="noopener noreferrer">Open SonarQube ↗</a><span class="muted small">sign in as admin · <code>lfg sonar login</code></span></div>`;
    if (i.name === "dictate" && i.settings) return dictateControls(i.settings, dis);
    if (i.name === "pentest" && i.on) return '<div class="int-sub"><div class="set-label">Local AI models (Ollama)</div><div id="ollama-box"><div class="loading">Asking the local Ollama…</div></div></div>';
    return "";
  };
  const fieldsOf = i => i.name === "dictate" ? [] : i.name === "pentest" ? i.fields.filter(f => f.key !== "pentest.model") : i.fields;
  const hasPanel = i => !!((i.on || i.name === "dictate") && (fieldsOf(i).length || extra(i) || i.missing.length || d.jobs[i.name]));
  const status = i => i.on ? (i.status ? `<span class="int-st ${i.tone === "warn" || i.tone === "bad" ? i.tone : ""}">${fmtWhy(i.status)}</span>` : "")
    : `<span class="int-st">${esc((i.about || "").split(/(?<=\.)\s/)[0].replace(/\.$/, ""))}</span>`;
  const row = i => {
    const open = state.intOpen.has(i.name) && hasPanel(i);
    return `<div class="int-item${open ? " open" : ""}" data-pack="${esc(i.name)}"><div class="int-row"><button class="int-main" ${hasPanel(i) ? `data-int-open="${esc(i.name)}" aria-expanded="${open}"` : "tabindex=\"-1\""} title="${esc(i.about || "")}">${icon(INT_ICON[i.name] || "settings")}<span class="grow"><span class="int-nm">${esc(i.title.replace(/ \((experimental|local)\)/, ""))}${i.experimental ? ' <span class="tag">Experimental</span>' : ""}</span>${status(i)}</span>${hasPanel(i) ? icon(open ? "chevron-up" : "chevron-down", "ico chev") : ""}</button>${sw(i)}</div>
      ${open ? `<div class="int-panel">${i.missing.length && i.on ? `<div class="int-acts"><span class="int-st warn">Missing: ${esc(i.missing.map(m => m.split(":").pop()).join(", "))}</span><button class="btn small" data-cc="pack_add" data-name="${esc(i.name)}" ${dis}>Install missing</button></div>` : ""}${fieldsOf(i).map(field).join("")}${extra(i)}${job(i.name)}</div>` : ""}</div>`;
  };
  box.innerHTML = `<div class="int-list">${d.integrations.map(row).join("")}</div>
    <details class="int-tools"><summary class="muted small">Command-line tools LFG uses</summary><div id="int-tools" class="mt"><div class="loading">Checking…</div></div></details>`;
  const msg = $("#int-msg");
  const said = r => { if (msg) saidMsg(msg, r, r.ok ? "Saved" : ""); };
  $$("[data-int-open]", box).forEach(b => b.onclick = () => { const k = b.dataset.intOpen; state.intOpen.has(k) ? state.intOpen.delete(k) : state.intOpen.add(k); loadIntegrations(); });
  $$("[data-int-switch]", box).forEach(b => b.onclick = async () => {
    const name = b.dataset.intSwitch, on = b.classList.contains("on");
    if (on && !confirm(`Turn off ${name}? Its tools stay installed; you can turn it on again any time.`)) return;
    b.disabled = true; b.classList.toggle("on", !on);
    if (!on) state.intOpen.add(name);
    said(await save(on ? "pack_remove" : "pack_add", { name })); loadIntegrations();
  });
  $$("[data-cfg]", box).forEach(el => el.addEventListener("change", async () => {
    const v = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    const r = await save("config", { values: { [el.dataset.cfg]: v } }); said(r); if (r.ok) loadIntegrations();
  }));
  $$("[data-dict]", box).forEach(el => el.onchange = async () => { el.disabled = true; said(await save("config", { values: { [el.dataset.dict]: el.type === "checkbox" ? el.checked : el.value } })); loadIntegrations(); });
  $$("[data-cc]", box).forEach(b => b.onclick = async () => { b.disabled = true; said(await save(b.dataset.cc, { name: b.dataset.name })); loadIntegrations(); });
  $$("[data-int-act]", box).forEach(b => b[b.tagName === "SELECT" ? "onchange" : "onclick"] = async () => {
    const act = b.dataset.intAct;
    if (act === "sonar_apply" && !confirm("Restart SonarQube with the new setting? It takes a minute or two; your login and results are kept.")) return;
    b.disabled = true; if (b.tagName === "BUTTON") b.textContent = "Working…";
    said(await save(act, act === "headroom" ? { scope: b.value } : {})); loadIntegrations();
  });
  $$("[data-tour-start]", box).forEach(l => l.onclick = e => { e.preventDefault(); startTour(l.dataset.tourStart); });
  if (state.pendingTour && $('[data-pack="dictate"]', box)) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 250); }
  if ($("#ollama-box", box)) loadOllama();
  api("tools").then(t => { const el = $("#int-tools"); if (!el) return; const miss = t.tools.filter(x => !x.installed);
    el.innerHTML = miss.length ? `<div class="box"><ul class="list">${miss.map(x => `<li>${dot(x.required ? "bad" : "")}<div class="grow"><div class="title">${esc(x.tool)} is not installed</div><div class="meta">${esc(x.purpose)}</div></div></li>`).join("")}</ul></div>` : `<p class="muted small">All ${n(t.tools.length)} tools are installed.</p>`; });
  clearTimeout(intTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) intTimer = setTimeout(() => { if (document.body.contains(box)) loadIntegrations(); }, 2000);
}

function settingsTools() {
  return '<div id="tools-box"><div class="loading">Checking…</div></div>';
}
// "MCP: ✔ Connected" (raw `claude mcp list` text) -> "Connected"
const plainDetail = s => (s || "").replace(/MCP:\s*/g, "").replace(/[✔✓✘✗⏸]\uFE0F?\s*/g, "");
async function loadTools() {
  const box = $("#tools-box");
  if (!box) return;
  const d = await api("tools");
  const missing = d.tools.filter(t => !t.installed);
  box.innerHTML = `<p class="muted">Everything LFG connects to, checked ${ago(d.checked_at)}.</p>
    <div class="box"><ul class="list">${d.integrations.map(i => `<li>${dot(i.ok ? "ok" : i.optional ? "" : "bad")}<div class="grow"><div class="title">${esc(i.name)}</div><div class="meta">${esc(plainDetail(i.detail))}</div></div></li>`).join("")}</ul></div>
    <div class="set-section"><h4>Command-line tools</h4>${missing.length
      ? `<div class="box"><ul class="list">${missing.map(t => `<li>${dot(t.required ? "bad" : "")}<div class="grow"><div class="title">${esc(t.tool)} is not installed</div><div class="meta">${esc(t.purpose)}${t.required ? (t.pack === "core" ? " · needed: run lfg setup" : ` · needed by the ${esc(t.pack)} pack: lfg add ${esc(t.pack)}`) : ` · ${esc(t.pack)} pack, not added`}</div></div></li>`).join("")}</ul></div>`
      : `<div class="box calm">${dot("ok")}All ${n(d.tools.length)} tools are installed.</div>`}</div>`;
}
function settingsOllama() {
  return '<div id="ollama-box"><div class="loading">Asking the local Ollama…</div></div>';
}
const gb = v => (v ? `${v} GB` : "—");
function pullBar(name, p) {
  const pc = p.total ? Math.round((100 * p.completed) / p.total) : 0;
  const s = p.error ? `<span class="save-msg bad">${esc(p.error)}</span>` : p.done ? '<span class="save-msg ok">done</span>' : `${esc(p.status)}${p.total ? ` · ${pc}%` : ""}`;
  return `<div class="pull"><div class="row"><b>${esc(name)}</b><span class="muted small">${s}</span></div>${p.done || p.error ? "" : `<div class="bar"><span style="width:${pc}%"></span></div>`}</div>`;
}
let ollamaTimer = null;
async function loadOllama() {
  const box = $("#ollama-box");
  if (!box) return;
  const d = await api("ollama"), un = state.settings.unlocked, dis = un ? "" : "disabled";
  const canPull = un && d.running ? "" : "disabled";
  const pulls = Object.entries(d.pulls || {});
  const use = name => (name === d.current ? `<span class="st">${dot("ok")}In use</span>` : `<button class="btn" data-ollama-use="${esc(name)}" ${dis}>Use</button>`);
  box.innerHTML = `<p class="muted">Security tests (<code>/lfg:pentest</code>) run on a model on this computer, never in the cloud. ${d.running ? "" : fmtWhy(d.why)}</p>
    <div class="row">${dot(d.running ? "ok" : "bad")}<span>${d.running ? "Ollama is running" : "Ollama is not running"}</span><span class="muted small">· model in use: ${d.current ? esc(d.current) : "none yet"}${d.ram_gb ? ` · this computer has ${d.ram_gb} GB memory` : ""}</span></div>
    ${pulls.length ? `<div class="set-section"><h4>Downloading</h4>${pulls.map(([k, p]) => pullBar(k, p)).join("")}</div>` : ""}
    <div class="set-section"><h4>On this computer</h4><div class="box">${table(d.installed, [
      { k: "name", label: "Model", html: r => esc(r.name) }, { k: "size_gb", label: "Size", num: true, html: r => gb(r.size_gb) },
      { k: "use", label: "", html: r => (r.cloud ? '<span class="muted small">cloud model: not allowed</span>' : r.tools ? use(r.name) : '<span class="muted small">can\'t run pentests</span>') },
    ], { filter: false, emptyTitle: "No models yet", emptyBody: d.running ? "Download one below." : "" })}</div></div>
    <div class="set-section"><h4>Download a model</h4><div class="box">${table(d.catalog, [
      { k: "name", label: "Model", html: r => `${esc(r.name)}<div class="sub">${esc(r.note || "")}</div>` },
      { k: "size_gb", label: "Download", num: true, html: r => gb(r.size_gb) },
      { k: "fit", label: "Fits this computer", html: r => ({ fits: `${dot("ok")} Yes`, tight: `${dot("warn")} Just`, "too big": `${dot("bad")} No` }[r.fit] || "—") },
      { k: "act", label: "", html: r => (r.installed ? use(r.name) : `<button class="btn" data-ollama-pull="${esc(r.name)}" ${canPull}>Download</button>`) },
    ], { filter: false })}</div>
      <div class="row mt"><input type="text" id="ollama-name" placeholder="Other model, e.g. qwen3:14b" ${dis}><button class="btn" id="ollama-pull" ${canPull}>Download</button><span class="save-msg" id="ollama-msg"></span></div></div>`;
  mountTables(box);
  const pull = async name => {
    const r = await save("ollama_pull", { name });
    saidMsg($("#ollama-msg"), r, r.ok ? `Downloading ${name}…` : "");
    if (r.ok) loadOllama();
  };
  $$("[data-ollama-pull]", box).forEach(b => b.onclick = () => pull(b.dataset.ollamaPull));
  $("#ollama-pull", box).onclick = () => pull($("#ollama-name").value.trim());
  $$("[data-ollama-use]", box).forEach(b => b.onclick = async () => {
    const r = await save("config", { values: { "pentest.model": b.dataset.ollamaUse } });
    if (!r.ok) return saidMsg($("#ollama-msg"), r);
    state.settings.cfg = await api("settings");
    loadOllama();
  });
  clearTimeout(ollamaTimer);
  if (pulls.some(([, p]) => !p.done)) ollamaTimer = setTimeout(() => { if (document.body.contains(box)) loadOllama(); }, 1500);
}
function settingsStorage() {
  return '<div id="storage-box"><div class="loading">Measuring…</div></div>';
}
async function loadStorage() {
  const box = $("#storage-box");
  if (!box) return;
  const d = await api("storage"), un = state.settings.unlocked;
  const cands = d.candidates.length ? `<div class="box">${table(d.candidates, [
      { k: "pick", label: "", html: r => `<input type="checkbox" data-clean="${esc(r.id)}" ${un ? "" : "disabled"}>` },
      { k: "label", label: "What", html: r => `${esc(r.label)}<div class="sub">${esc(r.reason)}</div>` },
      { k: "mb", label: "Size", num: true, html: r => `${r.mb} MB` }], { filter: false })}</div>
    <div class="set-actions"><button class="btn danger" id="clean-go" disabled>Delete selected</button><span class="save-msg" id="clean-msg"></span></div>`
    : `<div class="box calm">${dot("ok")}Nothing to clean up. Everything kept is still in use.</div>`;
  box.innerHTML = `<p><b>${d.total_mb} MB</b> <span class="muted">used of your ${d.limit_mb} MB limit</span></p>
    <div class="bar ${d.over ? "over" : ""}"><span style="width:${Math.min(100, pct(d.total_mb, d.limit_mb))}%"></span></div>
    <p class="muted small">The code maps inside your projects (${d.in_repos_mb || 0} MB) don't count toward this. Git ignores them.</p>
    <div class="set-section"><h4>Safe to delete</h4>${cands}</div>
    <div class="set-section"><h4>By project</h4><div class="box">${table(d.repos, [
      { k: "repo", label: "Project", html: r => esc(repoName(r.repo)) },
      { k: "total", label: "Size", num: true, sort: r => (r.graphs_mb || 0) + (r.runs_mb || 0), html: r => `${Math.round(((r.graphs_mb || 0) + (r.runs_mb || 0)) * 10) / 10} MB` }], { filter: false })}</div></div>`;
  mountTables(box);
  const go = $("#clean-go", box);
  if (!go) return;
  const picked = () => $$("[data-clean]", box).filter(c => c.checked).map(c => c.dataset.clean);
  $$("[data-clean]", box).forEach(c => c.onchange = () => (go.disabled = !picked().length));
  go.onclick = async () => {
    const ids = picked();
    if (!confirm(`Permanently delete ${ids.length} item(s)?`)) return;
    go.disabled = true;
    const r = await save("storage_cleanup", { ids });
    if (!r.ok) { go.disabled = false; return saidMsg($("#clean-msg"), r); }
    await loadStorage();
    const msg = $("#clean-msg") || $("#storage-box p");
    if (msg) saidMsg(msg, r, "Done.");
    loadBranches();
  };
}
function wireSettings(root) {
  if ($("#cc-box", root)) loadClaudeCode();
  if ($("#skills-box", root)) loadSkills();
  if ($("#ollama-box", root)) loadOllama();
  if ($("#storage-box", root)) loadStorage();
  if ($("#tools-box", root)) loadTools();
  if ($("#int-box", root)) loadIntegrations();
  if ($("#features-section", root)) loadFeatures();
  wireRules(root);
  const cs = $("#cfg-save", root);
  if (cs) cs.onclick = async () => {
    const values = {};
    for (const f of state.settings.cfg.fields) {
      const el = document.getElementById(`cfg-${f.key}`);
      let v = f.type === "bool" ? el.checked : f.type === "int" ? Number(el.value) : el.value;
      if (f.type === "list") v = el.value.split(",").map(x => x.trim()).filter(Boolean);
      if (JSON.stringify(v) !== JSON.stringify(f.value ?? (f.type === "list" ? [] : ""))) values[f.key] = v;
    }
    if (!Object.keys(values).length) return saidMsg($("#cfg-msg"), { ok: true }, "Nothing changed.");
    const d = await save("config", { values });
    saidMsg($("#cfg-msg"), d, d.ok ? `Saved ${plural(d.changed.length, "change")}.` : "");
    if (d.ok) state.settings.cfg = await api("settings");
  };
  const checkBtn = $("#check-updates-btn", root);
  if (checkBtn) checkBtn.onclick = async () => {
    checkBtn.disabled = true; checkBtn.textContent = "Checking…";
    let r;
    try { r = await save("updates_check", {}); } catch (e) { r = { ok: false, why: e.message }; }
    if (r.ok && r.current) {
      if (r.update_available) {
        saidMsg($("#updates-msg"), r, `LFG ${esc(r.upstream)} is available (you have ${esc(r.current)}). In your LFG clone run <code>git pull && ./install.sh</code>.`);
      } else {
        saidMsg($("#updates-msg"), r, `You're on the latest version (${esc(r.current)}).`);
      }
    } else if (!r.ok && !r.upstream) {
      saidMsg($("#updates-msg"), { ok: false }, `Couldn't reach GitHub: ${esc(r.why || "Unknown error")}`);
    }
    checkBtn.disabled = false; checkBtn.textContent = "Check for updates";
  };
  $$("[data-skill]", root).forEach(a => a.onclick = e => {
    e.preventDefault();
    $$("[data-skill]", root).forEach(x => x.classList.toggle("on", x === a));
    showSkill(a.dataset.skill);
  });
  const cmMode = edit => { $("#cm-read").hidden = edit; $("#cm-write").hidden = !edit; $("#cm-edit").hidden = edit; };
  const ce = $("#cm-edit", root);
  if (ce) ce.onclick = () => cmMode(true);
  const cc = $("#cm-cancel", root);
  if (cc) cc.onclick = () => { $("#cm-text").value = state.settings.cm.text; cmMode(false); };
  const ms = $("#cm-save", root);
  if (ms) ms.onclick = async () => {
    const d = await save("claudemd", { text: $("#cm-text").value });
    saidMsg($("#cm-msg"), d);
    if (d.ok) { state.settings.cm = await api("claudemd"); $("#cm-read").innerHTML = md(state.settings.cm.text); }
  };
}
async function showSkill(name) {
  const box = $("#skill-editor"), un = state.settings.unlocked;
  const d = await api("skill", { name });
  if (d.available === false) { box.innerHTML = unavailable(d); return; }
  const fm = frontMatter(d.text);
  box.innerHTML = `<div class="row" style="margin-bottom:8px"><b>/lfg:${esc(name)}</b>${d.edited ? '<span class="tag">edited by you</span>' : ""}<span class="grow"></span>${un ? '<button class="btn" id="skill-edit">Change</button>' : ""}</div>
    <div id="skill-read">${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}<div class="md">${md(fm.body)}</div></div>
    <div id="skill-write" hidden><p class="muted small">Written in Markdown. Keep the header between the <code>---</code> lines; Claude Code reads it.</p>
    <textarea class="editor" id="skill-text" spellcheck="false">${esc(d.text)}</textarea>
    <div class="set-actions"><button class="btn primary" id="skill-save">Save</button><button class="btn" id="skill-cancel">Cancel</button>${d.edited ? '<button class="btn" id="skill-reset">Undo my changes</button>' : ""}<span class="save-msg" id="skill-msg"></span></div></div>`;
  const mode = edit => { $("#skill-read").hidden = edit; $("#skill-write").hidden = !edit; if ($("#skill-edit")) $("#skill-edit").hidden = edit; };
  if ($("#skill-edit")) $("#skill-edit").onclick = () => mode(true);
  $("#skill-cancel").onclick = () => showSkill(name);
  const refreshList = async () => { state.settings.sk = await api("skills"); const a = $(`[data-skill="${name}"]`); if (a) a.innerHTML = `/lfg:${esc(name)}${state.settings.sk.skills.find(x => x.name === name)?.edited ? '<span class="tag">edited</span>' : ""}`; };
  $("#skill-save").onclick = async () => {
    const r = await save("skill", { name, text: $("#skill-text").value });
    saidMsg($("#skill-msg"), r);
    if (r.ok) { await refreshList(); showSkill(name); }
  };
  const rs = $("#skill-reset");
  if (rs) rs.onclick = async () => {
    if (!confirm(`Put /lfg:${name} back to how LFG ships it? A copy of your version is kept.`)) return;
    const r = await save("skill_reset", { name });
    if (!r.ok) return saidMsg($("#skill-msg"), r);
    await refreshList();
    showSkill(name);
  };
}

// ------------------------------------------------------------------ guided tours (first time, skippable)
const shortcutLabel = () => { const o = $('[data-dict="dictate.shortcut"]'); return o ? o.options[o.selectedIndex].text : "your shortcut"; };
/* One walkthrough of every Dictate control. While Dictate is off the controls are shown greyed and the last step is
   Add; once it's on, the same steps end with Turn off. */
function dictateTour(on) {
  const pre = on ? "" : " Works once Dictate is on.";
  return [
    { sel: '[data-pack="dictate"]', title: on ? "Meet LFG Dictate" : "New: LFG Dictate", body: () => `Speech-to-text that works in any app on your Mac: Slack, your editor, the browser, Claude. Speech is turned into text on this computer, so audio never leaves it and nothing you say is saved.${on ? " This row shows its shortcut, whether it's running and how many times you used it today." : " It's off until you add it."}` },
    { title: "How to talk to it", body: () => `<b>Hold ${esc(shortcutLabel())}</b>, speak, and let go: the words appear where your cursor is.<br><br><b>Double-tap</b> it for hands-free dictation; press it again or <b>Esc</b> to finish.<br><br>While it listens, a small pill at the bottom of your screen shows bars that move with your voice:<div class="tour-pill" aria-hidden="true">${"<i></i>".repeat(9)}</div>` },
    { sel: '[data-dict="dictate.shortcut"]', title: "Shortcut", body: () => `Which keys start Dictate: Option+Space, Right Option, Fn (globe), Control+Space or Command+Shift+Space. Right Option and Fn work on their own. Pick another one if an app already uses yours (the ChatGPT app and Raycast like Option+Space).${pre}` },
    { sel: '[data-dict="dictate.insert"]', title: "Put text in by", body: () => `Your words always go two places: where your cursor is, and your clipboard, so you can paste them again anywhere with ⌘V. <b>Pasting</b> is instant. <b>Typing</b> is for the odd app that blocks pasting; it's slower for long text.${pre}` },
    { sel: '[data-dict="dictate.cleanup"]', title: "Clean up with Claude", body: () => `On by default. Removes filler words ("um", "like"), applies spoken corrections ("Tuesday, no, Wednesday") and fixes punctuation: the text, never the audio, goes to Claude with your Claude Code sign-in. Untick it to keep everything on your Mac.${pre}` },
    on ? { sel: '[data-pack="dictate"] [data-int-switch]', title: "Turn it off", body: () => "Stops Dictate and deletes everything it installed: the model, its app and its login item. You can add it again any time." }
       : { sel: '[data-pack="dictate"] [data-int-switch]', title: "Turn it on", body: () => '<b>Add</b> downloads the speech model (about 90 MB, into ~/.lfg/dictate) and starts Dictate. macOS then asks for <b>Microphone</b> and <b>Accessibility</b> permission for "LFG Dictate". After that, the controls above come alive.' },
    { title: "From the terminal", body: () => `The same controls, if you prefer typing:<pre class="out">lfg add dictate                    # turn it on\nlfg dictate status\nlfg dictate shortcut right_option\nlfg dictate insert type            # or paste\nlfg dictate cleanup off            # or on\nlfg remove dictate                 # turn it off</pre>Replay this tour any time with <b>Take the tour</b> on the Dictate row.` },
  ];
}
const TOURS = { get dictate() { return dictateTour(true); }, get "dictate-intro"() { return dictateTour(false); } };
let TOUR = null;
function startTour(name) {
  endTour();
  const box = document.createElement("div");
  box.className = "tour";
  box.innerHTML = '<div class="tour-shade"></div><div class="tour-hole" hidden></div><div class="tour-card" role="dialog" aria-modal="true" aria-labelledby="tour-title"></div>';
  document.body.append(box);
  TOUR = { name, i: 0, box, onKey: e => { if (e.key === "Escape") finishTour("skipped"); else if (e.key === "ArrowRight") tourGo(1); else if (e.key === "ArrowLeft") tourGo(-1); } };
  document.addEventListener("keydown", TOUR.onKey);
  window.addEventListener("resize", tourDraw);
  tourDraw();
}
function tourGo(d) { if (!TOUR) return; const n = TOUR.i + d; if (n >= TOURS[TOUR.name].length) return finishTour("finished"); TOUR.i = Math.max(0, n); tourDraw(); }
function tourDraw() {
  if (!TOUR) return;
  const steps = TOURS[TOUR.name], st = steps[TOUR.i], last = TOUR.i === steps.length - 1;
  const hole = $(".tour-hole", TOUR.box), card = $(".tour-card", TOUR.box), shade = $(".tour-shade", TOUR.box);
  const target = st.sel && $(st.sel);
  card.innerHTML = `<div class="tour-step">${TOUR.i + 1} of ${steps.length}</div><h3 id="tour-title">${esc(st.title)}</h3><div class="tour-body">${st.body()}</div>
    <div class="tour-actions"><button class="link" data-t="skip">Skip tour</button><span class="grow"></span>${TOUR.i ? '<button class="btn small" data-t="back">Back</button>' : ""}<button class="btn small primary" data-t="next">${last ? "Done" : "Next"}</button></div>`;
  $('[data-t="skip"]', card).onclick = () => finishTour("skipped");
  $('[data-t="next"]', card).onclick = () => tourGo(1);
  const back = $('[data-t="back"]', card); if (back) back.onclick = () => tourGo(-1);
  shade.classList.toggle("solid", !target);
  if (!target) {  // a step about how to use it, not a button: centred card
    hole.hidden = true;
    card.style.left = `${Math.max(16, (innerWidth - card.offsetWidth) / 2)}px`; card.style.top = `${Math.max(16, (innerHeight - card.offsetHeight) / 2)}px`;
  } else {
    const el = target.closest("label") && !target.closest("li > .grow > .title") && target.type === "checkbox" ? target.closest("label") : target;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect(), pad = 6;
    Object.assign(hole.style, { left: `${r.left - pad}px`, top: `${r.top - pad}px`, width: `${r.width + 2 * pad}px`, height: `${r.height + 2 * pad}px` });
    hole.hidden = false;
    const below = r.bottom + pad + 12, h = card.offsetHeight, w = card.offsetWidth;
    card.style.top = `${below + h < innerHeight - 8 ? below : Math.max(8, r.top - pad - 12 - h)}px`;
    card.style.left = `${Math.min(innerWidth - w - 16, Math.max(16, r.left))}px`;
  }
  $('[data-t="next"]', card).focus();
}
function finishTour(how) {
  if (!TOUR) return;
  const name = TOUR.name;
  try { localStorage.setItem("lfg.tour." + name, how); } catch (e) { /* private window: the server copy still counts */ }
  save("tour_done", { name, how });
  endTour();
  const p = $("#tour-prompt"); if (p) p.remove();
}
function endTour() {
  if (!TOUR) return;
  document.removeEventListener("keydown", TOUR.onKey);
  window.removeEventListener("resize", tourDraw);
  TOUR.box.remove();
  TOUR = null;
}
/* The first time the dashboard opens after Dictate is set up: offer the tour, or skip it for good */
async function offerTours() {
  let t;
  try { t = await api("tours"); } catch (e) { return; }
  if (!t.setup_guide_done) { setupGuide(true); return; }  // first run: the setup guide comes before anything else
  const seen = k => { try { return localStorage.getItem("lfg.tour." + k); } catch (e) { return null; } };
  const remember = (k, how) => { try { localStorage.setItem("lfg.tour." + k, how); } catch (e) { /* ignore */ } save("tour_done", { name: k, how }); };
  const d = t.dictate || {};
  const promo = $("#promo");
  promo.innerHTML = "";
  // New in this version: Welcome (choose your pages) and Insights. Shown before the Dictate banner, once.
  if (!t.news_welcome_closed && !seen("news-welcome") && (location.hash.slice(1).split("/")[0] || "home") !== "onboarding") {
    promo.innerHTML = `<div class="promo" role="region" aria-label="New in LFG">
      <div class="grow"><div class="promo-title"><span class="tag">New</span> Choose your pages, and Insights</div>
        <div class="promo-text"><b>Welcome</b> lets you pick the features you use so the sidebar shows only their pages. <b>Insights</b> runs quick checks on this project: a review coach for your changes, explain a file, and test ideas.</div></div>
      <div class="promo-actions"><button class="btn small primary" data-news="welcome">Choose pages</button><button class="btn small" data-news="insights">Open Insights</button>
        <button class="icon-btn" data-news="close" aria-label="Close" title="Don't show again">&times;</button></div></div>`;
    const close = () => { remember("news-welcome", "closed"); promo.innerHTML = ""; };
    $('[data-news="welcome"]', promo).onclick = () => { close(); location.hash = "#onboarding"; };
    $('[data-news="insights"]', promo).onclick = () => { close(); location.hash = "#insights"; };
    $('[data-news="close"]', promo).onclick = close;
    return;
  }
  // A hidden feature the user has started to need: offer its pages once (yes, or "not now" for a month)
  let feats = null;
  try { feats = await api("features"); } catch (e) { feats = null; }
  const sug = feats && feats.suggestion;
  if (sug) {
    promo.innerHTML = `<div class="promo" role="region" aria-label="Show more of LFG">
      <div class="grow"><div class="promo-title">${esc(sug.name)}</div><div class="promo-text">${esc(sug.why)}</div></div>
      <div class="promo-actions"><button class="btn small primary" data-sug="yes">Show it</button><button class="btn small" data-sug="later">Not now</button></div></div>`;
    $$("[data-sug]", promo).forEach(b => b.onclick = async () => {
      const r = await save("feature_suggestion", { feature: sug.feature, answer: b.dataset.sug });
      promo.innerHTML = "";
      if (r.ok && b.dataset.sug === "yes") { applyPages(r); location.hash = "#" + sug.pages[0]; }
    });
    return;
  }
  // Dictate off: a banner on every page until it is turned on or closed (new installs and updates alike)
  if (!d.on && !d.banner_closed && !seen("dictate-banner")) {
    promo.innerHTML = `<div class="promo" role="region" aria-label="New: LFG Dictate">
      <div class="tour-pill" aria-hidden="true">${"<i></i>".repeat(9)}</div>
      <div class="grow"><div class="promo-title"><span class="tag">New</span> LFG Dictate</div>
        <div class="promo-text">Hold <b>Option+Space</b> anywhere on your Mac, speak, and let go: the words appear where your cursor is. Your voice is transcribed on this Mac and never saved; Claude tidies up the text.</div></div>
      <div class="promo-actions"><button class="btn small primary" data-promo="on">Turn it on</button><button class="btn small" data-promo="tour">Take the tour</button>
        <button class="icon-btn" data-promo="close" aria-label="Close" title="Don't show again">&times;</button></div></div>`;
    const go = () => { if ((location.hash.slice(1) || "home").split("/")[0] === "integrations") route(); else location.hash = "#integrations"; };
    $('[data-promo="close"]', promo).onclick = () => { remember("dictate-banner", "closed"); promo.innerHTML = ""; };
    $('[data-promo="tour"]', promo).onclick = () => { state.pendingTour = "dictate-intro"; go(); };
    $('[data-promo="on"]', promo).onclick = async e => {
      const r = await save("pack_add", { name: "dictate" });
      if (!r.ok) { e.target.closest(".promo").querySelector(".promo-text").innerHTML = `${fmtWhy(r.why || "Couldn't start it.")} You can also run <code>lfg add dictate</code> in your terminal.`; return; }
      promo.innerHTML = "";
      go();  // Integrations shows the download's progress
    };
    return;
  }
  // Dictate on: offer the controls tour once
  // (the walkthrough taken before turning it on already showed every control, so it counts)
  if (!d.on || d.done || seen("dictate") || seen("dictate-intro") === "finished" || $("#tour-prompt")) return;
  const card = document.createElement("div");
  card.id = "tour-prompt"; card.className = "tour-prompt"; card.setAttribute("role", "dialog"); card.setAttribute("aria-label", "LFG Dictate is ready");
  card.innerHTML = `<div class="tour-pill small" aria-hidden="true">${"<i></i>".repeat(7)}</div><div class="grow"><b>LFG Dictate is ready</b><div class="meta">Take a 1-minute tour of its controls?</div></div>
    <button class="link" data-p="skip">Skip</button><button class="btn small primary" data-p="go">Start tour</button>`;
  document.body.append(card);
  $('[data-p="skip"]', card).onclick = () => { remember("dictate", "skipped"); card.remove(); };
  $('[data-p="go"]', card).onclick = () => {
    card.remove();
    state.pendingTour = "dictate";
    if ((location.hash.slice(1) || "home").split("/")[0] === "integrations") route(); else location.hash = "#integrations";
  };
}

// ------------------------------------------------------------------ pages
const NAV = [["sessions", "Studio"], ["todos", "Todos"], ["runs", "Runs"], ["issues", "Issues"], ["review", "Reviews"], ["checks", "Checks"], ["code", "Code"], ["insights", "Insights"], ["docs", "Docs"],
  ["knowledge", "Knowledge"], ["usage", "Usage"], ["skills", "Skills"], ["integrations", "Integrations"], ["settings", "Settings"], ["help", "Help"]];
const TITLES = Object.fromEntries(NAV);
TITLES.onboarding = "Welcome"; TITLES.lfg = "Home";
const PAGES = {};
state.pages = NAV.map(p => p[0]);  // visible nav pages, set from onboarding

async function cachedRuns() {
  const key = "runs:" + state.repo;
  if (!state.cache[key]) state.cache[key] = await api("runs");
  return state.cache[key];
}

/* What a run is doing, in one line: "Step 5 of 10 · next: run the checks" */
function runLine(r, stages) {
  if (r.fix) return r.fix.working ? `AI fixing ${plural(r.fix.total, "review comment")}` : r.fix.ok === undefined || r.fix.ok === null ? "Fix run" : r.fix.ok
    ? `Fixed ${r.fix.done.fixed} of ${r.fix.total}${r.fix.done.skipped ? ` · ${r.fix.done.skipped} skipped` : ""}${r.fix.done.failed ? ` · ${r.fix.done.failed} failed` : ""} · next: review and commit` : "The AI fix run didn't finish";
  const p = runPlace(stages, r.stages, r);
  return p.finished ? "All steps done" : `${p.done} of ${p.total} steps · next: ${NEXT[p.next]}`;
}
/* Things on a run that need a person, as [tone, text] */
function runAttention(r) {
  const out = [];
  if (r.review === "block") out.push(["bad", "The code review found something that must be fixed"]);
  else if (r.review === "changes") out.push(["warn", "The code review asked for changes"]);
  if (r.secure === "don't") out.push(["bad", "The security check found problems to fix"]);
  if (r.ready === "red") out.push(["bad", "Tests or checks are failing"]);
  else if (r.ready === "stale") out.push(["warn", "The last checks ran before the latest work, so their result is out of date: run /lfg:check"]);
  if (r.shipcheck === "fail") out.push(["bad", "The ship check failed"]);
  if (r.pentest === "refused") out.push(["warn", "The security test didn't run: open the Security test document to see why"]);
  return out.sort((a, b) => (a[0] === "bad" ? 0 : 1) - (b[0] === "bad" ? 0 : 1));
}

const FEATURE_ICON = { coding: "code", reviews: "review", security: "checks", knowledge: "knowledge", planning: "issues" };

/* Insights: understand code you didn't write, without opening an editor. Three tabs, each answering one question:
   Your changes (is this safe to approve?), Hotspots (where does this codebase break?), Files (what is this and why
   is it like this?). Everything comes from git on this computer; nothing here edits code. */
const INS = { file: "" };
PAGES.insights = async arg => {
  const [tab, ...rest] = (arg || "").split("/");
  if (tab === "files" && rest.length) { INS.file = rest.join("/"); sessionStorage.setItem("lfg.tab.insights", "files"); }
  else if (["changes", "hotspots", "files"].includes(tab)) sessionStorage.setItem("lfg.tab.insights", tab);
  return `${head("Insights", "Understand what changed, where the code is fragile, and why it looks the way it does. From your git history, on this computer.")}
    ${tabs("insights", [
      ["changes", "Your changes", null, () => `<div id="ins-changes"><div class="loading">Reading your changes…</div></div>`],
      ["hotspots", "Hotspots", null, () => `<div id="ins-hot"><div class="loading">Reading the history…</div></div>`],
      ["files", "Files", null, () => `<div class="fx-search"><span class="fx-search-ico">${icon("docs")}</span><input id="ins-file" list="ins-files" placeholder="Type a file path, e.g. src/billing.py" value="${esc(INS.file)}" autocomplete="off" aria-label="File"><button class="btn primary" id="ins-open">Explain</button></div><div id="ins-file-out"></div>`],
    ])}
    <datalist id="ins-files"></datalist>`;
};
const insLink = p => `<a href="#insights/files/${esc(p)}" class="ins-path">${esc(p)}</a>`;
const LEVEL = { HIGH_RISK: ["bad", "Fix before merging"], NEEDS_WORK: ["warn", "Needs a look"], READY_TO_REVIEW: ["ok", "No red flags"] };
function insChanges(d) {
  if (d.error) return unavailable({ why: d.error }, "Couldn't read your changes");
  if (d.message) return empty("No changes yet", "When this branch has changes, committed or not, they show up here with what to check before merging.");
  const [tone, label] = LEVEL[d.risk_level] || ["", d.risk_level];
  const files = d.files_reviewed || [];
  const added = files.reduce((a, f) => a + (f.additions || 0), 0);
  const issues = (d.issues || []).map(i => ({ severity: i.severity, file: i.file, line: i.line, title: i.message, fix: i.suggestion }));
  const shown = issues.filter(i => i.severity !== "low"), low = issues.filter(i => i.severity === "low");
  const q = d.questions || [], hot = d.touches_hotspots || [], pat = d.patterns || [];
  return `<div class="ins-summary"><span class="st"><span class="dot ${tone}"></span>${esc(label)}</span><span class="muted">${plural(files.length, "file")} · +${n(added)} lines · compared with <code>${esc(d.base_branch || "")}</code></span><span class="grow"></span><button class="btn small" id="ins-recheck">Check again</button></div>
    ${q.length ? `<h3 class="ins-h">Before you approve, ask</h3><ol class="ins-questions box">${q.map(x => `<li>${esc(x.q)}</li>`).join("")}</ol>` : ""}
    ${shown.length ? `<h3 class="ins-h">Worth a look</h3>${shown.map(findingCard).join("")}` : ""}
    ${hot.length ? `<h3 class="ins-h">Touches fragile code</h3><ul class="ins-hot box">${hot.slice(0, 5).map(h => `<li>${dot(h.level === "high" ? "bad" : "warn")}<div class="grow">${insLink(h.path)}<div class="muted small">${esc(h.reasons.join(" · "))}</div></div></li>`).join("")}${hot.length > 5 ? `<li class="muted">and ${hot.length - 5} more, in <a href="#insights/hotspots">Hotspots</a></li>` : ""}</ul>` : ""}
    ${pat.length ? `<h3 class="ins-h">Keeps coming up</h3><ul class="ins-list box">${pat.map(p => `<li>${esc(p.kind)}<span class="muted"> · in ${p.times} of your last ${p.of} checks</span></li>`).join("")}</ul>` : ""}
    ${!q.length && !shown.length && !hot.length ? `<p class="muted">Nothing stood out. These are pattern checks, not a review: <code>/lfg:review-coach</code> in Claude Code gives you one.</p>` : ""}
    <details class="ins-more"><summary>${plural(files.length, "changed file")}${low.length ? ` · ${plural(low.length, "note")} in tests` : ""}</summary>
      <ul class="ins-list">${files.map(f => `<li>${insLink(f.path)}<span class="muted"> · ${f.new ? "new, " : ""}+${n(f.additions || 0)}${f.deletions ? ` −${n(f.deletions)}` : ""}</span></li>`).join("")}</ul>
      ${low.length ? low.map(findingCard).join("") : ""}
      <div class="ins-pick mt"><input id="ins-base" placeholder="Compare with another branch (default: found automatically)"><button class="btn small" id="ins-base-go">Compare</button></div>
    </details>`;
}
function insHotspots(d) {
  if (d.error) return unavailable({ why: d.error }, "Couldn't read the history");
  const f = d.files || [];
  if (!f.length) return empty("No hotspots yet", `Nothing changed often enough in the last ${d.days} days to stand out.`);
  return `<p class="muted">The files that keep needing fixes are where the next bug most likely is. From ${plural(d.commits, "commit")} in the last ${d.days} days.</p>
    ${(d.rising || []).length ? `<p class="ins-warn">${dot("bad")}Fixes are rising in ${d.rising.map(a => `<code>${esc(a)}</code>`).join(", ")}: more in the last ${d.half} days than the ${d.half} before.</p>` : ""}
    <ul class="ins-hot box">${f.map(h => `<li>${dot(h.level === "high" ? "bad" : "warn")}<div class="grow">${insLink(h.path)}<div class="muted small">${esc(h.reasons.join(" · "))}</div>
      ${h.recent_fixes.length ? `<details class="ins-fixes"><summary>Recent fixes</summary><ul>${h.recent_fixes.map(c => `<li><code>${esc(c.sha.slice(0, 7))}</code> ${esc(c.date)} ${esc(c.subject)}</li>`).join("")}</ul></details>` : ""}</div></li>`).join("")}</ul>
    ${(d.areas || []).length > 1 ? `<h3 class="ins-h">By folder</h3><div class="box">${table(d.areas, [{ k: "area", label: "Folder", html: r => `<code>${esc(r.area)}</code>` }, { k: "files", label: "Files changed", num: true }, { k: "changes", label: "Changes", num: true }, { k: "fixes", label: "Fixes", num: true }, { k: "trend", label: "Trend", html: r => r.trend === "rising" ? `<b>rising</b> <span class="muted">${r.fixes_recent} vs ${r.fixes_earlier}</span>` : r.trend === "falling" ? `falling <span class="muted">${r.fixes_recent} vs ${r.fixes_earlier}</span>` : '<span class="muted">steady</span>' }], { sort: "fixes", filter: false })}</div>` : ""}
    <p class="muted small mt">Dependency risks (known vulnerabilities, end-of-life packages) are in <a href="#checks">Checks</a>, from <code>/lfg:secure</code>.</p>`;
}
function insWhy(d) {
  if (d.error) return `<p class="muted">${esc(d.error)}</p>`;
  if (!d.commits.length) return `<p class="muted">No history yet: this hasn't been committed.</p>`;
  return `<ol class="ins-timeline">${d.commits.map(c => `<li><div><b>${esc(c.subject)}</b></div>
    <div class="muted small">${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer"><code>${esc(c.sha.slice(0, 7))}</code></a>` : `<code>${esc(c.sha.slice(0, 7))}</code>`} · ${esc(c.author)} · ${esc(c.date)}${c.fix ? ' <span class="tag bad">fix</span>' : ""}${c.refs.map(r => ` · ${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.label)}</a>` : esc(r.label)}`).join("")}</div>
    ${c.body ? `<details><summary class="small">Details</summary><div class="ins-body">${esc(c.body)}</div></details>` : ""}</li>`).join("")}</ol>`;
}
/* Files: understand one file without opening it. Empty: what this is for, and files worth starting with. */
function insFilePicker(hot) {
  const files = (hot && hot.files) || [];
  const fragile = files.slice(0, 5), recent = files.slice().sort((a, b) => (b.last || "").localeCompare(a.last || "")).slice(0, 5);
  const chip = f => `<button class="fx-chip" data-pick="${esc(f.path)}"><span class="fx-chip-dir">${esc(f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/") + 1) : "")}</span><b>${esc(f.path.split("/").pop())}</b></button>`;
  return `<div class="fx-intro box pad"><div class="fx-intro-h"><h3>Understand any file without opening it</h3><p class="muted">Pick a file and LFG reads it and its git history for you.</p></div>
    <div class="fx-what">${[["docs", "What it does", "Its purpose, in its own words, and everything it defines."], ["runs", "Why it's like this", "The commits, PRs and tickets that shaped each part."], ["checks", "What to test", "Test ideas, past bugs to guard, and a test file to start from."]].map(([ic, t, d]) => `<div><span class="fx-what-ico">${icon(ic)}</span><b>${t}</b><span class="muted">${d}</span></div>`).join("")}</div></div>
    ${fragile.length ? `<h3 class="ins-h">Start with a fragile file</h3><div class="fx-chips">${fragile.map(chip).join("")}</div>` : ""}
    ${recent.length ? `<h3 class="ins-h">Changed recently</h3><div class="fx-chips">${recent.map(chip).join("")}</div>` : ""}`;
}
function insFile(ex, ts) {
  if (ex.error) return unavailable({ why: ex.error }, "Couldn't open it");
  const w = ex.why_its_here || {};
  const defs = (ex.how_it_works || []).slice().sort((a, b) => a.line - b.line);
  const ideas = (ts && ts.suggested_tests) || [];
  const tests = ex.related_tests || [], fixes = w.recent_fixes || [];
  const dir = ex.file.includes("/") ? ex.file.slice(0, ex.file.lastIndexOf("/") + 1) : "", name = ex.file.split("/").pop();
  const P = { 1: "Start here", 2: "Edge case", 3: "Nice to have" };
  ideas.forEach(t => { if (t.category === "regression") t.kind = "Past bug"; });
  const kindTag = k => `<span class="tag ${k === "class" ? "blue" : ""}">${k === "class" ? "class" : "fn"}</span>`;
  const overview = `${ex.summary ? `<p class="fx-sum">${inline(ex.summary)}</p>` : '<p class="muted">The file doesn\'t describe itself. Ask Claude: <code>/lfg:explain</code> how it works.</p>'}
    ${fixes.length ? `<div class="callout warn fx-warn"><b>Fixed ${plural(fixes.length, "time")} in the last six months:</b> ${fixes.slice(0, 2).map(f => `“${esc(f.message.replace(/[.\s]+$/, ""))}”`).join(", ")}${fixes.length > 2 ? "…" : ""}. Change it carefully.</div>` : ""}
    ${defs.length ? `<h3 class="ins-h">What's in it <span class="tag">${defs.length}</span></h3>
      <div class="fx-defs box">${defs.map((x, k) => `<div class="fx-def"><div class="fx-def-row">${kindTag(x.type)}<code class="fx-def-n">${esc(x.name)}</code><span class="fx-def-d">${x.docstring ? inline(x.docstring) : '<span class="faint">no description</span>'}</span><span class="fx-def-l">line ${x.line}</span><button class="btn small" data-why="${x.line}" data-end="${defs[k + 1] ? defs[k + 1].line - 1 : ""}">History</button></div><div class="ins-why"></div></div>`).join("")}</div>` : ""}
    ${(ex.potential_issues || []).length ? `<h3 class="ins-h">Worth a look</h3><div class="box">${ex.potential_issues.map(i => `<div class="fx-issue"><span class="tag warn">line ${esc(i.line)}</span>${esc(i.message)}</div>`).join("")}</div>` : ""}`;
  const history = `<div id="ins-why-file"><div class="loading">Reading the history…</div></div>`;
  const testsTab = `${tests.length ? `<p class="muted">Already tested in ${tests.map(t => insLink(t)).join(", ")}.</p>` : '<p class="muted">No test file covers it yet: start with the file below.</p>'}
    ${ts && ts.skeleton ? `<div class="ins-skel"><div class="row"><b>A test file to start from</b><span class="muted small">every test is skipped until it's written, so it runs as-is</span><span class="grow"></span><button class="btn small" data-copy="ins-skel-code">Copy</button></div><pre class="out" id="ins-skel-code">${esc(ts.skeleton)}</pre></div>` : ""}
    ${ideas.length ? `<h3 class="ins-h">Test ideas <span class="tag">${ideas.length}</span></h3><div class="box">${table(ideas, [{ k: "priority", label: "", html: r => `<span class="tag ${r.kind ? "bad" : r.priority === 1 ? "blue" : ""}">${esc(r.kind || P[r.priority] || "")}</span>`, sort: r => r.priority }, { k: "test_name", label: "Test", html: r => `<code>${esc(r.test_name)}</code>` }, { k: "reason", label: "Why" }], { sort: "priority", dir: 1, filter: false })}</div>` : ""}`;
  return `<div class="fx-file">
    <div class="fx-head box pad"><div class="fx-path"><span>${esc(dir)}</span><b>${esc(name)}</b></div>
      <div class="fx-tags">${ex.language ? `<span class="tag">${esc(ex.language)}</span>` : ""}${w.total_commits ? `<span class="tag">${plural(w.total_commits, "commit")}</span>` : '<span class="tag">not committed yet</span>'}${tests.length ? `<span class="tag ok">tested</span>` : '<span class="tag warn">no tests</span>'}${fixes.length ? `<span class="tag bad">${fixes.length} recent ${fixes.length === 1 ? "fix" : "fixes"}</span>` : ""}</div>
      ${w.created_by ? `<div class="muted small">Added by ${esc(w.created_by)} on ${esc(w.created_date)} · last changed by ${esc(w.last_modified_by)} on ${esc(w.last_modified_date)}</div>` : ""}
      <button class="link small fx-back" data-fx-back>← Pick another file</button></div>
    ${tabs("insfile", [["overview", "Overview", null, () => overview], ["history", "History", null, () => history], ["tests", "Tests", ideas.length || null, () => testsTab]])}
  </div>`;
}
function wireInsights(root) {
  const dl = $("#ins-files", root);
  if (dl && !dl.dataset.loaded) { dl.dataset.loaded = "1"; api("insight_files").then(d => { dl.innerHTML = (d.files || []).map(f => `<option value="${esc(f)}">`).join(""); }).catch(() => {}); }
  const ch = $("#ins-changes", root);
  if (ch && !ch.dataset.done) {
    ch.dataset.done = "1";
    const load = async base => {
      ch.innerHTML = '<div class="loading">Reading your changes…</div>';
      try { ch.innerHTML = insChanges(await api("insight_review", base ? { base } : {})); } catch (e) { ch.innerHTML = unavailable({ why: e.message }); }
      const again = $("#ins-recheck", ch); if (again) again.onclick = () => load(base);
      const go = $("#ins-base-go", ch); if (go) go.onclick = () => load($("#ins-base", ch).value.trim());
    };
    load("");
  }
  const hot = $("#ins-hot", root);
  if (hot && !hot.dataset.done) {
    hot.dataset.done = "1";
    api("insight_hotspots").then(d => { hot.innerHTML = insHotspots(d); mountTables(hot); }).catch(e => { hot.innerHTML = unavailable({ why: e.message }); });
  }
  const out = $("#ins-file-out", root), inp = $("#ins-file", root);
  if (out && inp && !out.dataset.wired) {
    out.dataset.wired = "1";
    const wireFile = file => {
      const histBox = () => $("#ins-why-file", out);
      const loadHist = async () => { const b = histBox(); if (b && !b.dataset.done) { b.dataset.done = "1"; b.innerHTML = insWhy(await api("insight_why", { file })); } };
      $$("[data-tabs=insfile] .tab", out).forEach(t => t.addEventListener("click", () => setTimeout(() => { if (t.dataset.k === "history") loadHist(); wireDefs(); }, 0)));
      if (sessionStorage.getItem("lfg.tab.insfile") === "history") loadHist();
      const wireDefs = () => $$("[data-why]", out).forEach(b => b.onclick = async () => {
        const box = b.closest(".fx-def").querySelector(".ins-why");
        if (box.innerHTML) { box.innerHTML = ""; b.textContent = "History"; return; }
        b.textContent = "Reading…";
        box.innerHTML = insWhy(await api("insight_why", { file, start: b.dataset.why, end: b.dataset.end }));
        b.textContent = "Hide";
      });
      wireDefs();
      const back = $("[data-fx-back]", out); if (back) back.onclick = () => { INS.file = ""; inp.value = ""; showPicker(); };
    };
    const open = async file => {
      file = (file || inp.value).trim();
      if (!file) return;
      INS.file = file; inp.value = file;
      out.innerHTML = '<div class="loading">Reading the file and its history…</div>';
      const [ex, ts] = await Promise.all([api("insight_explain", { file }), api("insight_tests", { file }).catch(() => null)]);
      out.innerHTML = insFile(ex, ts); mountTabs(out); mountTables(out); wireFile(file);
    };
    const showPicker = async () => {
      out.innerHTML = insFilePicker(null);
      let hot = null; try { hot = await api("insight_hotspots"); } catch (e) { hot = null; }
      if (!INS.file) out.innerHTML = insFilePicker(hot);
      $$("[data-pick]", out).forEach(b => b.onclick = () => open(b.dataset.pick));
    };
    $("#ins-open", root).onclick = () => open();
    inp.onkeydown = e => { if (e.key === "Enter") open(); };
    if (INS.file) open(INS.file); else showPicker();
  }
  $$(".tab", root).forEach(t => { if (!t.dataset.insWired) { t.dataset.insWired = "1"; t.addEventListener("click", () => setTimeout(() => wireInsights(root), 0)); } });
}

/* ------------------------------------------------------------------ product home, intro journey, page tours
   The home (#lfg, what `lfg ui` opens) and the first-run intro are full-screen pages without the sidebar. Their
   pictures are small HTML snapshots of the real screens (aria-hidden), not screenshots, so they follow the theme. */
const BARE = ["lfg", "onboarding"];
/* Snapshots of the real screens, for the landing page and the intro. `A(d)` marks a part that animates in on the
   landing page, d steps after its row scrolls into view (elsewhere they just show). */
const A = (d, cls = "") => ` class="lp-a${cls ? " " + cls : ""}" style="--d:${d}"`;
const MOCK = {
  run: () => `<div class="mk mk-run"><div class="mk-row"><span class="tag blue">Standard lane</span><span class="mk-dim">run 0142 · feature/rate-limit</span></div>
    <div class="mk-title">Add rate limiting to the public API</div>
    <div class="mk-steps">${[["Brief", "done"], ["Plan", "done"], ["Build", "done"], ["Check", "now"], ["Review", ""], ["Ship", ""]].map(([st, c], i) => `<span${A(1 + i * .6, `mk-step ${c}`)}>${c === "done" ? "✓ " : ""}${st}</span>`).join("")}</div>
    <div class="mk-bar"><span style="--w:62%"></span></div>
    <div${A(5, "mk-dim")}>Tests 48 passed · lint clean · security check running…</div></div>`,
  diff: () => `<div class="mk mk-diff"><div class="mk-file"><span class="mk-st">M</span>api/limits.py<span class="grow"></span><span class="mk-add">+14</span><span class="mk-del">−3</span></div>
    <div class="mk-lines">
      <div${A(0, "mk-l")}><i>18</i><i></i><code>def allow(client, now):</code></div>
      <div${A(.5, "mk-l del")}><i>19</i><i>−</i><code>    window = now // 60</code></div>
      <div${A(1, "mk-l add")}><i>19</i><i>+</i><code>    hits = [t for t in log[client] if now - t &lt; 60]</code></div>
      <div${A(1.5, "mk-l add sel")}><i>20</i><i>+</i><code>    if len(hits) &gt;= LIMIT:</code></div>
      <div${A(2, "mk-l add")}><i>21</i><i>+</i><code>        return False</code></div>
    </div>
    <div class="mk-thread"><div${A(3.5, "mk-me")}>Why a sliding window and not a fixed one?</div>
      <div${A(5, "mk-ai wipe")}><span class="mk-ai-h"><span class="ai-badge">AI</span> from the diff and callers</span>A fixed minute lets a client send 2× the limit across the boundary (59s + 61s). The sliding window counts the last 60 seconds, so bursts stay capped. <code>login()</code> and <code>search()</code> call this.</div>
      <div${A(9, "mk-acts")}><span class="tag">Ask a follow-up</span><span class="tag ok">Resolve</span></div></div></div>`,
  comment: () => `<div class="mk mk-cmt"><div class="mk-row"><span class="tag bad">High</span><span class="mk-dim">reviewer · api/auth.py:42</span></div>
    <div class="mk-title">Token expiry isn't checked before refresh</div>
    <div class="mk-ai"><span class="mk-ai-h"><span class="ai-badge">AI</span> take</span>Valid: <code>refresh()</code> trusts the cached token. Fix is one line: compare <code>exp</code> first.</div>
    <div class="mk-acts"><span class="tag blue">Will fix</span><span class="tag">Discuss</span><span class="tag">Not now</span></div></div>`,
  questions: () => `<div class="mk mk-q"><div class="mk-row"><span class="st"><span class="dot warn"></span>Needs a look</span><span class="mk-dim">6 files · +212 lines vs main</span></div>
    <div class="mk-h">Before you approve, ask</div>
    <ol class="mk-ol"><li${A(1)}>It changes <code>billing.py</code>, which needed 4 fixes recently. How would you know if it broke?</li>
      <li${A(3)}>Your team decided <b>“money is integer cents”</b>. Does this still follow it?</li>
      <li${A(5)}>Nothing tests <code>refunds.py</code>. Which check shows it still works?</li></ol></div>`,
  hotspots: () => `<div class="mk mk-hot">${[["bad", "billing/charge.py", "needed 5 fixes · fixes rising · no tests", 92], ["warn", "api/limits.py", "changed 14 times · 3 people", 64], ["warn", "auth/session.py", "needed 2 fixes · 900 lines", 41]].map(([t, p, r, w], i) => `<div${A(i * 1.2, "mk-hot-r")}>${dot(t)}<div class="grow"><code>${p}</code><div class="mk-dim">${r}</div><span class="mk-heat ${t}"><i style="--w:${w}%;--d:${1 + i * 1.2}"></i></span></div></div>`).join("")}</div>`,
  why: () => `<div class="mk mk-why"><div class="mk-row"><code>def allow()</code><span class="mk-dim">· why is this here?</span></div>
    <ol class="mk-tl">${[["Count the last 60s instead of the minute", "PR #318", "Sarah · 3 days ago", ""], ["fix: clients doubled their burst at :00", "ENG-412", "Rahul · 2 weeks ago", "fix"], ["Add per-client rate limits", "PR #201", "Mike · 4 months ago", ""]].map(([t, r, w, f], i) => `<li${A(1 + i * 1.6)}><b>${t}</b><div class="mk-dim">${w} · <span class="tag blue">${r}</span>${f ? ' <span class="tag bad">fix</span>' : ""}</div></li>`).join("")}</ol></div>`,
  guard: () => `<div class="mk mk-term"><div class="mk-dots"><i></i><i></i><i></i></div>
    <div${A(0)}><span class="mk-p">claude ›</span> git push origin main</div>
    <div${A(1.5, "mk-red")}>✕ LFG guard: pushing is yours to do. Changes are ready to commit.</div>
    <div${A(3)}><span class="mk-p">claude ›</span> cat .env</div>
    <div${A(4.5, "mk-red")}>✕ LFG guard: secrets stay unread.</div>
    <div${A(6)}><span class="mk-p">claude ›</span> git commit -m "Add sliding-window rate limit"</div>
    <div${A(7.5, "mk-yel")}>? Asks you first. Approve in Claude Code.</div></div>`,
  dictate: () => `<div class="mk mk-dict"><div class="mk-dict-text">“${"Add a test for the refund path, and make it fail on negative amounts".split(" ").map((w, i, all) => `<span${A(1 + i * .35)}>${w}${i < all.length - 1 ? " " : ""}</span>`).join("")}”<span class="mk-caret"></span></div>
    <div class="mk-pill">${"<i></i>".repeat(9)}</div><div class="mk-dim mk-center">Hold <kbd>⌥</kbd> <kbd>Space</kbd>, speak, let go</div></div>`,
};
/* Go editorless: each editor as an app tile with its logo (ui_assets/editors): [name, file, tile background, logo size] */
const EDITORS = [["VS Code", "vscode", "#ffffff", 68], ["Cursor", "cursor", "", 100], ["JetBrains", "jetbrains", "linear-gradient(135deg, #ff8f1f, #ff318c 45%, #7b5cff)", 56],
  ["Zed", "zed", "#0c0e14", 54], ["Sublime Text", "sublime", "", 100], ["Xcode", "xcode", "#ffffff", 80], ["Antigravity", "antigravity", "#ffffff", 82]];
/* the hero's window: a Studio session, one sentence in, the pipeline running */
const HERO_STEPS = [["Grill", "brief and acceptance criteria"], ["Plan", "4 tasks · standard lane"], ["Build", "test-first, in its own worktree"],
  ["Check", "lint · types · tests · security"], ["Review", "standards · spec · blast radius"], ["Ship", "commit message and PR notes ready"]];
const FLOW = [["Ask", "/lfg:lfg add rate limiting", "One sentence in Claude Code."], ["Grill", "brief + acceptance criteria", "It asks until the goal is sharp."],
  ["Plan", "design · tasks · lane", "Small, testable slices."], ["Build", "agents in worktrees", "Test-first, one task each."],
  ["Check", "lint · tests · security · review", "Proof from exit codes."], ["Ship", "ready to commit", "You push. Always."]];
const SHOWCASE = [  // [kicker, icon, punch line (em = the highlight), what it is, snapshot, link]
  ["Reviews", "review", "Argue with the diff. <em>Win.</em>", "Open any pull request and ask about one line. Answers come from the code and everything that calls it, not from memory. Push back, decide what to fix, move on.", () => MOCK.diff(), "#review"],
  ["Insights", "insights", "Know what to ask <em>before you approve.</em>", "Every change arrives with the questions a senior engineer would ask: the fragile files it touches, the tests it skipped, the team decisions it might break.", () => MOCK.questions(), "#insights"],
  ["Hotspots", "target", "See the next bug <em>before it's filed.</em>", "Files that keep needing fixes, ranked from your own history, with the reason in plain words. Pay down debt where it actually hurts.", () => MOCK.hotspots(), "#insights/hotspots"],
  ["History", "branch", "Every line has a story. <em>Read it in seconds.</em>", "Any function's history, newest first: the commits that shaped it and the PRs and tickets behind them. Context without blame, without an editor.", () => MOCK.why(), "#insights/files"],
  ["Runs", "runs", "Watch the work, <em>not the keystrokes.</em>", "One sentence becomes a run you can follow: brief, plan, build, checks, review. You step in only where it needs a decision.", () => MOCK.run(), "#runs"],
  ["Guard", "checks", "It can't push, deploy or <em>read your secrets.</em>", "Guard rails enforced in code on every command, not asked for nicely in a prompt. Commits wait for your yes.", () => MOCK.guard(), "#settings"],
  ["Dictate", "mic", "Say it. <em>It's typed.</em>", "Hold a shortcut anywhere on your Mac and talk. Transcribed on the Mac and pasted where your cursor is; your audio never leaves it.", () => MOCK.dictate(), "#integrations"],
];
/* The open-source tools LFG stands on. Thank you. */
const THANKS = [
  ["Claude Code", "the agent LFG runs inside", "https://claude.com/claude-code"],
  ["code-review-graph", "the code map agents read instead of whole files", "https://pypi.org/project/code-review-graph/"],
  ["graphify", "the code wiki, call flows and architecture map", "https://pypi.org/project/graphifyy/"],
  ["Omnigraph", "dev-graph and second-brain: what LFG remembers", ""],
  ["Headroom", "context compression that saves tokens", ""],
  ["Cactus · Whistle", "on-device speech-to-text for Dictate", "https://cactuscompute.com/blog/whistle"],
  ["mattpocock/skills", "the grill, plan and TDD skills LFG adapts", "https://github.com/mattpocock/skills"],
  ["Cloudflare security-audit-skill", "the security review method", "https://github.com/cloudflare/security-audit-skill"],
  ["Semgrep", "code scanning", ""], ["Gitleaks", "secret scanning", ""], ["Trivy", "container and dependency scanning", ""],
  ["OSV-Scanner", "known vulnerabilities in dependencies", ""], ["Hadolint", "Dockerfile checks", ""], ["zizmor · actionlint", "GitHub Actions checks", ""],
  ["Strix", "offline pentests", ""], ["Ollama", "the local model for pentests", ""], ["SonarQube", "code quality, run locally", ""],
  ["uv", "fast, isolated Python tool installs", ""], ["PyObjC", "the macOS bits of Dictate", ""],
];
const lfgMark = () => `<span class="lp-mark">${logoSvg(22)}LFG</span>`;

PAGES.lfg = async () => {
  let n = 0;
  try { n = ((await api("guide")).skills || []).length; } catch (e) { n = 0; }
  return `<div class="lp">
  <header class="lp-nav"><a href="#lfg" class="lp-home" data-scroll="top" aria-label="Back to the top">${lfgMark()}</a><nav><a href="#lfg" data-scroll="lp-features">Features</a><a href="#lfg" data-scroll="lp-reviews">Reviews</a><a href="#lfg" data-scroll="lp-thanks">Open source</a><a href="#onboarding">Intro</a></nav>
    <a class="btn primary" href="#sessions">Open dashboard →</a></header>
  <section class="lp-hero">
    <span class="wl-pill"><span class="tag">New</span> Insights and talk-to-the-diff reviews</span>
    <h1>Stop writing code.<br><em>Start directing it.</em></h1>
    <p>The bottleneck moved. It isn't typing any more; it's deciding what to build, steering the agents that build it, and trusting what ships. LFG is the cockpit for that, inside Claude Code.</p>
    <div class="lp-cta"><a class="btn primary big" href="#sessions">Open dashboard</a><a class="btn big lp-ghost" href="#onboarding">Take the intro</a></div>
    <div class="lp-win" aria-hidden="true"><div class="lp-win-bar"><i></i><i></i><i></i><span>Studio · your-project</span></div>
      <div class="lp-win-b"><div class="lp-win-me">/lfg:lfg add rate limiting to the public API</div>
        <ol class="lp-win-steps">${HERO_STEPS.map(([t, d], i) => `<li class="todo" data-step="${t}" style="--i:${i}"><span class="lp-win-dot"></span><b>${t}</b><span>${d}</span><em></em></li>`).join("")}</ol>
        <div class="lp-win-ask"><span>Claude wants to edit <code>api/limits.py</code></span><span class="lp-win-btns"><span class="lp-win-btn on">Allow once</span><span class="lp-win-btn">Deny</span></span><span class="lp-win-ok">✓ Allowed</span></div>
        <div class="lp-win-done"><span class="lp-win-check">✓</span><b>Ready to commit.</b><span>6 files · 48 tests pass · review approved · nothing pushed</span></div></div></div>
  </section>
  <section class="lp-editors" id="lp-editors">
    <h2 class="lp-ed-h">Go editorless</h2>
    <div class="lp-ed">${EDITORS.map(([name, file, bg, size], i) => `<div class="lp-ed-i" style="--i:${i}"><span class="lp-ed-tile${bg ? "" : " bare"}" style="${bg ? `background:${bg};` : ""}--s:${size}%"><img src="/assets/editors/${file}.svg" alt="" draggable="false"><i class="lp-ed-x" aria-hidden="true"></i></span><span class="lp-ed-n">${esc(name)}</span></div>`).join("")}</div>
    <p class="lp-ed-p">Great editors. You just won't be editing.<br><b>Describe the change, review the result, ship.</b></p></section>
  <section class="lp-punch lp-reveal">
    <div><b>Coding was the skill.<br><em>Orchestration</em> is the new one.</b><p>You decide what gets built and in what order. Specialist agents do the typing, in their own worktrees.</p></div>
    <div><b>Read intent,<br>not diffs.</b><p>Every change arrives with why it was made, what it touches and what to ask before you approve it.</p></div>
    <div><b>Ship with proof,<br>not hope.</b><p>Lint, types, tests, security and a review on every change, judged from exit codes, never an agent's claim.</p></div>
  </section>
  <section class="lp-sec lp-feats" id="lp-features"><div class="lp-k">What you get</div><h2>Everything you'd open an editor for. <em>Without one.</em></h2>
    ${SHOWCASE.map(([k, ico, punch, d, v, href], i) => `<div class="lp-row lp-reveal${i % 2 ? " flip" : ""}"${k === "Reviews" ? ' id="lp-reviews"' : ""}><div class="lp-copy"><span class="lp-kick">${icon(ico)}${k}</span><h3>${punch}</h3><p>${d}</p><a href="${href}" class="lp-link">Open ${k} →</a></div><div class="lp-vis" aria-hidden="true">${v()}</div></div>`).join("")}
  </section>
  <section class="lp-facts lp-reveal"><div><b>${n || "25+"}</b><span>skills, one per job</span></div><div><b>8</b><span>specialist agents</span></div><div><b>18</b><span>guard rules, in code</span></div><div><b>0</b><span>lines of your code sent by Insights</span></div></section>
  <section class="lp-sec lp-thanks lp-reveal" id="lp-thanks"><div class="lp-k">Built on open source</div><h2>Thank you</h2>
    <p class="muted">LFG is a thin layer on top of other people's excellent work. These projects do the heavy lifting.</p>
    <div class="lp-tk">${THANKS.map(([n, what, url]) => `<${url ? `a href="${url}" target="_blank" rel="noopener noreferrer"` : "div"} class="lp-tk-i"><b>${esc(n)}</b><span>${esc(what)}</span></${url ? "a" : "div"}>`).join("")}</div></section>
  <section class="lp-end lp-reveal"><h2>Ready when you are.</h2><p class="muted">Open Claude Code in a repo, run <code>lfg enable</code>, and say what you want.</p>
    <div class="lp-cta"><a class="btn primary big" href="#sessions">Open dashboard</a><a class="btn big" href="https://github.com/varun-singhh/lfg" target="_blank" rel="noopener noreferrer" data-gh-star>★ Star on GitHub</a></div></section>
  <footer class="lp-foot"><div class="lp-lfg">Let's F<span>**</span>king go.</div>
    <div class="lp-foot-row">${lfgMark()}<span class="muted small">Runs on your computer · never pushes or deploys · open source</span><span class="grow"></span><a href="#sessions">Dashboard</a><a href="#help">Help</a></div></footer>
  </div>`;
};

/* The landing page: sections animate in as they scroll into view (once; none with reduced motion) */
function wireLanding(root) {
  const parts = $$("#lp-editors, .lp-reveal", root), win = $(".lp-win", root);
  if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    parts.forEach(x => x.classList.add("in"));
    if (win) { $$(".lp-win-steps li", win).forEach(li => { li.className = "done"; }); $(".lp-win-ask", win).classList.add("on", "ok"); $(".lp-win-done", win).classList.add("on"); }
    return;
  }
  if (win) heroRun(win);
  const io = new IntersectionObserver(es => es.forEach(x => { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }), { threshold: 0.2 });
  parts.forEach(x => io.observe(x));
}

/* The hero's window plays a whole run: each stage works, then is done; the permission prompt shows up during Build
   and is allowed; then "Ready to commit", a pause, and again. Stops once the page is left. */
function heroRun(win) {
  const steps = $$(".lp-win-steps li", win), ask = $(".lp-win-ask", win), done = $(".lp-win-done", win);
  const set = (li, st) => { li.className = st; $("em", li).textContent = st === "run" ? "working…" : ""; };
  let t = 0;
  const at = (ms, fn) => setTimeout(() => { if (document.body.contains(win)) fn(); }, t += ms);
  const play = () => {
    t = 0;
    steps.forEach(li => set(li, "todo")); ask.classList.remove("on", "ok"); done.classList.remove("on");
    steps.forEach((li, i) => {
      at(i ? 250 : 1400, () => set(li, "run"));
      if (li.dataset.step === "Build") { at(1000, () => ask.classList.add("on")); at(1100, () => ask.classList.add("ok")); }
      at(li.dataset.step === "Build" ? 900 : 1150, () => set(li, "done"));
    });
    at(300, () => done.classList.add("on"));
    at(4500, play);
  };
  play();
}

/* The setup guide: run `lfg init` in a repo, turn LFG on for it in Settings, hardened mode, and where to find this
   again. The first time, it opens by itself and has to be finished: no close button, Escape and clicks outside do
   nothing. The ⓘ button in the top bar opens it any time. Steps on Settings light up the real controls, which stay
   usable (the dimmed parts around them are not). */
const SG_STEPS = [
  { title: "Set up LFG in three steps", next: "Start", body: () => `<p>Two minutes, once. LFG only works in repos you turn it on for, so let's do that for your first one.</p>
      <ol class="sg-list"><li><div><b>Run <code>lfg init</code></b> in your repo</div><span>builds the code map LFG's agents read</span></li>
        <li><div><b>Turn LFG on</b> for it in Settings</div><span>skills, guard and hooks, in that repo only</span></li>
        <li><div><b>Choose hardened mode</b></div><span>a second lock, enforced by Claude Code itself</span></li></ol>` },
  { title: "1 · Run lfg init in your repo", body: () => `<p>In a terminal, go to the project you want LFG to work on and run:</p>
      <div class="sg-cmd"><pre id="sg-cmd">cd path/to/your-repo
lfg init</pre><button class="btn small" data-copy="sg-cmd">Copy</button></div>
      <p class="muted small">It builds the code map (a minute or two the first time). The repo then shows up in the project picker and in Settings.</p>
      <div class="sg-found" id="sg-found"></div>`,
    live: card => {
      const box = $("#sg-found", card);
      const tick = async () => {
        const r = await api("repos").catch(() => null), n = (r && r.repos) || [];
        if (box.isConnected) box.innerHTML = n.length ? `${dot("ok")}<span>LFG sees ${n.length === 1 ? "" : `${n.length} repos: `}<b>${n.slice(0, 3).map(x => esc(x.name || x.id)).join(", ")}</b>${n.length > 3 ? "…" : ""}</span>`
          : `${dot("warn")}<span>No repo yet. Run <code>lfg init</code> in one and it shows up here.</span>`;
      };
      tick(); return setInterval(tick, 3000);
    } },
  { title: "2 · Turn LFG on for that repo", page: "settings", tab: "claudecode", target: "#cc-where",
    body: () => `<p>Find your repo in this list and press <b>Turn on</b>. Claude Code then gets LFG's skills, guard and hooks in that repo; every other repo stays exactly as it was.</p><p class="muted small">Same as running <code>lfg enable</code> inside the repo.</p>` },
  { title: "3 · Hardened mode", page: "settings", tab: "claudecode", target: "#cc-hardened",
    body: () => `<p>Recommended. On top of LFG's guard, it writes Claude Code's own deny rules (commit and push, secret files) into each LFG repo's <code>.claude/settings.local.json</code>, so Claude Code itself refuses them too.</p><p class="muted small">Never touches your user settings. Same as <code>lfg enable --hardened</code>.</p>` },
  { title: "Find this again any time", target: "#guide-btn", next: "Finish",
    body: () => `<p>This guide lives behind the <b>ⓘ</b> button in the top bar. Every command LFG understands is under <a href="#help">Help</a>, and these switches stay in <b>Settings → Claude Code</b>.</p>` },
];
function setupGuide(first) {
  if ($("#sg")) return;
  const back = location.hash || "#sessions";
  const root = document.createElement("div");
  root.id = "sg"; root.className = "sg";
  root.innerHTML = `${'<div class="sg-m"></div>'.repeat(4)}<div class="sg-ring" hidden></div><div class="sg-card" role="dialog" aria-modal="true" aria-labelledby="sg-t" tabindex="-1"></div>`;
  document.body.append(root); document.body.classList.add("sg-open");
  const card = $(".sg-card", root), masks = $$(".sg-m", root), ring = $(".sg-ring", root);
  let target = null, live = null;  // target: the selector being lit up (pages re-render, so it's found again each time)
  const place = () => {
    const vw = innerWidth, vh = innerHeight, el = target && $(target);
    if (!el) {
      masks[0].style.cssText = "left:0;top:0;width:100%;height:100%"; masks.slice(1).forEach(m => { m.style.cssText = "display:none"; });
      ring.hidden = true; card.classList.add("center"); card.style.cssText = ""; return;
    }
    const r = el.getBoundingClientRect(), p = 8;
    const x = Math.max(0, r.left - p), y = Math.max(0, r.top - p), x2 = Math.min(vw, r.right + p), y2 = Math.min(vh, r.bottom + p);
    masks[0].style.cssText = `left:0;top:0;width:100%;height:${y}px`;
    masks[1].style.cssText = `left:0;top:${y2}px;width:100%;height:${Math.max(0, vh - y2)}px`;
    masks[2].style.cssText = `left:0;top:${y}px;width:${x}px;height:${y2 - y}px`;
    masks[3].style.cssText = `left:${x2}px;top:${y}px;width:${Math.max(0, vw - x2)}px;height:${y2 - y}px`;
    ring.hidden = false; ring.style.cssText = `left:${x}px;top:${y}px;width:${x2 - x}px;height:${y2 - y}px`;
    card.classList.remove("center");
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const top = y2 + 14 + ch <= vh ? y2 + 14 : y - 14 - ch >= 0 ? y - 14 - ch : Math.max(12, vh - ch - 12);
    card.style.cssText = `left:${Math.min(Math.max(12, x2 - cw), vw - cw - 12)}px;top:${top}px`;
  };
  const waitFor = async (sel, tab) => {
    for (let k = 0; k < 300; k++) {  // Settings → Claude Code reads Claude Code's setup first: give it time
      if (tab) { const b = $(`[data-tabs="settings"] .tab[data-k="${tab}"]`); if (b && !b.classList.contains("on")) b.click(); }
      const el = $(sel); if (el) return el;
      await new Promise(r => setTimeout(r, 100));
    }
    return null;
  };
  const keys = e => {  // no way out but through; Tab stays inside the card
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); }
    if (e.key === "Tab") { const f = $$("button, a[href]", card); if (f.length && !card.contains(document.activeElement)) { e.preventDefault(); f[0].focus(); } }
  };
  const timer = setInterval(place, 250);
  addEventListener("resize", place); document.addEventListener("keydown", keys, true);
  let seq = 0;
  const show = async i => {
    const s = SG_STEPS[i], mine = ++seq;
    clearInterval(live); live = null; target = null;
    if (s.page && (location.hash.slice(1).split("/")[0] || "") !== s.page) location.hash = "#" + s.page;
    card.innerHTML = `<div class="sg-dots" aria-hidden="true">${SG_STEPS.map((_, k) => `<i class="${k === i ? "on" : k < i ? "done" : ""}"></i>`).join("")}</div>
      <h2 id="sg-t">${s.title}</h2><div class="sg-b">${s.body()}</div>
      <div class="sg-a">${i ? '<button class="btn" data-sg="back">Back</button>' : ""}<span class="grow"></span><span class="muted small">${i + 1} of ${SG_STEPS.length}</span><button class="btn primary" data-sg="next">${s.next || "Next"}</button></div>`;
    place(); card.focus();
    if (s.live) live = s.live(card);
    const bk = $('[data-sg="back"]', card); if (bk) bk.onclick = () => show(i - 1);
    $('[data-sg="next"]', card).onclick = () => i < SG_STEPS.length - 1 ? show(i + 1) : finish();
    $$("a[href^='#']", card).forEach(a => a.onclick = e => e.preventDefault());  // links are pointers here, not exits
    if (!s.target) return;
    const wait = document.createElement("p"); wait.className = "muted small sg-wait"; wait.textContent = s.page ? "Loading Settings…" : "";
    if (s.page && !$(s.target)) $(".sg-b", card).append(wait);
    const el = await waitFor(s.target, s.tab);
    if (mine !== seq) return;  // moved on meanwhile
    wait.remove();
    if (el) { target = s.target; el.scrollIntoView({ block: "center" }); place(); }
  };
  const finish = () => {
    clearInterval(timer); clearInterval(live); removeEventListener("resize", place); document.removeEventListener("keydown", keys, true);
    root.remove(); document.body.classList.remove("sg-open");
    if (first) save("tour_done", { name: "setup-guide" });
    if (location.hash !== back) location.hash = back;
  };
  show(0);
}
document.addEventListener("click", e => { if (e.target.closest("#guide-btn")) setupGuide(false); });

/* Star buttons: with the GitHub CLI signed in, one click stars it from your account; otherwise they open GitHub */
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-gh-star]");
  if (!b || b.dataset.busy) return;
  const g = state.gh;  // fetched at startup, so this click can decide now
  if (!g || !g.ready) return;  // not signed in: the link opens github.com as usual
  e.preventDefault();
  if (g.starred) { b.textContent = "★ Starred, thank you"; return; }
  b.dataset.busy = "1"; b.textContent = "Starring…";
  const r = await save("github_star", {});
  b.textContent = r.ok && r.starred ? "★ Starred, thank you" : "★ Star on GitHub";
  if (r.ok && r.starred) state.gh = Object.assign({}, g, { starred: true });
  delete b.dataset.busy;
  if (!(r.ok && r.starred)) window.open(r.url || b.href, "_blank", "noopener");
}, true);
/* In-page links on the home page scroll to their section; the hash stays #lfg, so the router never sees them */
document.addEventListener("click", e => {
  const a = e.target.closest("[data-scroll]");
  if (!a) return;
  e.preventDefault();
  const el = a.dataset.scroll === "top" ? null : document.getElementById(a.dataset.scroll);
  if (a.dataset.scroll !== "top" && !el) return;
  const top = el ? Math.max(0, el.getBoundingClientRect().top + scrollY - 68) : 0, from = scrollY;
  const calm = document.documentElement.dataset.motion === "off" || matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top, behavior: calm ? "auto" : "smooth" });
  setTimeout(() => { if (scrollY === from && Math.abs(top - from) > 4) window.scrollTo(0, top); }, 350);  // smooth scrolling unsupported
});
/* The first-run intro: one feature per step, each with its snapshot, then pick what to use. */
const JOURNEY = [
  { k: "Welcome", t: "Welcome to LFG", d: "You're about to stop writing code and start directing it. Here's the 60-second version of how.", v: () => `<div class="jv-stack">${MOCK.run()}</div>` },
  { k: "The flow", t: "One sentence in, a checked change out", d: "Say what you want in Claude Code. LFG grills it into a brief, plans small slices, builds them test-first and checks everything before you see it.", v: () => `<ol class="lp-flow mini">${FLOW.map(([t, c], i) => `<li><span class="lp-n">${String(i + 1).padStart(2, "0")}</span><b>${t}</b><code>${esc(c)}</code></li>`).join("")}</ol>` },
  { k: "Reviews", t: "Talk to the diff", d: "Ask about a single line or a single review comment and get an answer from the code. Decide what to fix without opening a file.", v: () => MOCK.diff() },
  { k: "Insights", t: "Know what to ask before you approve", d: "The fragile files a change touches, the tests it skipped and the team decisions it might break, as questions.", v: () => MOCK.questions() },
  { k: "History", t: "Why is this code here?", d: "Every function's story: the commits that shaped it, with the PRs and tickets behind them.", v: () => MOCK.why() },
  { k: "Guard", t: "Agents can't do the scary things", d: "No pushes, no deploys, no reading secrets. Commits ask you first. Enforced on every command.", v: () => MOCK.guard() },
];
const OBS = { step: 0 };
async function journeyPicker() {
  const d = await api("onboarding");
  const unlocked = await isUnlocked();
  const tile = f => {
    const on = d.complete ? f.enabled : f.id === "coding";
    return `<label class="wl-tile"><input type="checkbox" data-feature="${esc(f.id)}" ${on ? "checked" : ""} ${unlocked ? "" : "disabled"}><span class="wl-check" aria-hidden="true"></span>
      <span class="wl-ico">${icon(FEATURE_ICON[f.id] || "home")}</span><b>${esc(f.name)}</b><span class="wl-desc">${esc(f.description)}</span>
      ${(f.page_titles || []).length ? `<span class="wl-pages">${f.page_titles.map(t => `<span class="tag blue">${esc(t)}</span>`).join("")}</span>` : ""}<span class="wl-skills">${(f.skills || []).slice(0, 4).map(k => `<code>${esc(k)}</code>`).join(" ")}</span></label>`;
  };
  return `${unlocked ? "" : `<div class="callout wl-note">Read-only. To change anything, run <code>lfg ui</code> in your own terminal.</div>`}
    <div class="wl-pick-h"><div><h2>What will you use?</h2><p class="muted">The sidebar shows only these pages. Change it any time in Settings.</p></div><span class="tag blue" id="wl-count"></span></div>
    <div class="wl-grid">${(d.features || []).map(tile).join("")}</div>
    <div class="wl-actions"><button class="btn primary big" id="onboard-save" ${unlocked ? "" : "disabled"}>Start with these</button><button class="btn big" id="onboard-skip" ${unlocked ? "" : "disabled"}>Show me everything</button><span class="save-msg" id="onboard-msg"></span><span class="grow"></span><a class="btn big" href="https://github.com/varun-singhh/lfg" target="_blank" rel="noopener noreferrer" data-gh-star>★ Star LFG on GitHub</a></div>`;
}
PAGES.onboarding = async arg => {
  OBS.step = arg === "pick" ? JOURNEY.length : 0;
  return `<div class="ob">
    <header class="lp-nav">${lfgMark()}<span class="grow"></span><a class="ob-skip" href="#onboarding/pick" data-ob-skip>Skip intro</a></header>
    <div id="ob-body"></div></div>`;
};
async function drawJourney(root) {
  const body = $("#ob-body", root);
  if (!body) return;
  const i = OBS.step, last = JOURNEY.length;
  const dots = `<div class="ob-dots">${JOURNEY.concat([{ k: "Pick" }]).map((s, j) => `<button class="ob-dot${j === i ? " on" : j < i ? " done" : ""}" data-ob-go="${j}" aria-label="${esc(s.k)}"><span></span>${esc(s.k)}</button>`).join("")}</div>`;
  if (i >= last) {
    body.innerHTML = `${dots}<section class="wl-pick ob-pick">${await journeyPicker()}</section>`;
    wireOnboarding(root);
  } else {
    const s = JOURNEY[i];
    body.innerHTML = `${dots}<section class="ob-card"><div class="ob-copy"><span class="tag blue">${esc(s.k)}</span><h1>${esc(s.t)}</h1><p>${esc(s.d)}</p>
      <div class="ob-nav">${i ? '<button class="btn big" data-ob="back">Back</button>' : ""}<button class="btn primary big" data-ob="next">${i === last - 1 ? "Pick what you'll use →" : "Next →"}</button></div>
      <div class="muted small">${i + 1} of ${last}</div></div><div class="ob-vis" aria-hidden="true">${s.v()}</div></section>`;
  }
  $$("[data-ob-go]", body).forEach(b => b.onclick = () => { OBS.step = +b.dataset.obGo; drawJourney(root); });
  const nx = $('[data-ob="next"]', body); if (nx) nx.onclick = () => { OBS.step++; drawJourney(root); };
  const bk = $('[data-ob="back"]', body); if (bk) bk.onclick = () => { OBS.step--; drawJourney(root); };
  const sk = $("[data-ob-skip]", root); if (sk) sk.onclick = e => { e.preventDefault(); OBS.step = last; drawJourney(root); };
}

/* A tour for every dashboard page: the Tour button in the top bar starts the one for the page you're on. */
const PAGE_TOURS = {
  sessions: [
    { sel: "#nav", title: "Your dashboard", body: () => "Everything LFG does, by what you're doing: <b>Your work</b> (runs, todos, reviews, checks), <b>This project</b> (code, insights, docs) and <b>LFG</b> itself (usage, skills, settings)." },
    { sel: "#repo", title: "Pick a project", body: () => "Every page shows the project picked here, and the branch below it narrows runs and checks to one branch." },
    { sel: "#ss-comp", title: "Studio", body: () => "Run Claude Code here: describe the task, <code>/</code> for skills, <code>@</code> for files, drop in screenshots. Sessions from your terminal and the desktop app show up too." },
    { sel: "#bell", title: "Notifications", body: () => "When a check finishes, a run needs a decision or a review is ready, it shows up here." },
    { sel: "#tour-btn", title: "A tour on every page", body: () => "Press <b>Tour</b> on any page to see what it's for." },
  ],
  todos: [{ sel: "[data-td-add]", title: "Add a todo", body: () => "Type and press Enter. It's tagged with the project you're in." }, { sel: ".td-st", title: "Status", body: () => "Click the coloured tag to move it along: to do, in progress, done." }, { sel: ".td-a", title: "Linear and notes", body: () => "Turn any todo into a Linear ticket, or add notes." }],
  runs: [{ title: "Runs", body: () => "Every request you give LFG becomes a run: brief, plan, build, checks, review and ship, with each stage's files." }, { sel: ".runs-bar", title: "Find a run", body: () => "Search by what it was for, its branch or its issue." }],
  review: [{ title: "Reviews", body: () => "Review pull requests and AI chats here. Open one to see the diff, the comments and a chat beside it." }, { sel: ".rv-top", title: "Start a review", body: () => "Pick a pull request or a chat. LFG reads the diff and its callers before it says anything." }, { title: "Talk to the diff", body: () => "In a review, click a line number to ask about that line, or <b>Discuss</b> on a comment to argue with it. Mark each comment <b>Will fix</b> or <b>Not now</b>." }],
  checks: [{ sel: ".view .cols", title: "Latest checks", body: () => "The newest code review, security check and ship check for this project, and what they found." }, { sel: ".view .tabs", title: "Findings", body: () => "Every finding with what's wrong, why it matters and what to do, sorted by severity." }],
  code: [{ title: "Code", body: () => "The code map LFG's agents read instead of whole files, and the architecture's health." }],
  insights: [{ sel: '[data-tabs="insights"]', title: "Three questions", body: () => "<b>Your changes</b>: is this safe to approve? <b>Hotspots</b>: where does this code break? <b>Files</b>: what is this and why is it like this?" }, { sel: "#ins-changes", title: "Before you approve", body: () => "The questions a senior engineer would ask, the fragile files you touched and the problems that keep coming back." }],
  docs: [{ sel: ".doc-nav", title: "Docs", body: () => "LFG's wiki for this project and the docs you asked for: project-wide at the top, then one folder per branch." }],
  knowledge: [{ title: "Knowledge", body: () => "Decisions, rules and lessons LFG remembers about this project, and your own notes. Save one with <code>/lfg:note</code>." }],
  usage: [{ title: "Usage", body: () => "What Claude Code cost, by day, model and project, and what Headroom saved." }],
  skills: [{ title: "Skills", body: () => "Every skill Claude Code can load on this computer, yours and every plugin's, with name clashes and how much context they cost." }],
  integrations: [{ sel: ".int-list", title: "Integrations", body: () => "Turn tools on and off: knowledge graphs, Headroom, SonarQube, Dictate, pentests, Linear. Each one installs locally and can be removed." }],
  settings: [{ sel: ".view .tabs", title: "Settings", body: () => "<b>Claude Code</b>: where LFG is on. <b>General</b>: features, updates, models. Every change is backed up and can be undone." }],
  help: [{ title: "Help", body: () => "How LFG works, every command grouped by what it is for, and short answers." }],
};
Object.keys(PAGE_TOURS).forEach(k => Object.defineProperty(TOURS, "page-" + k, { get: () => PAGE_TOURS[k], enumerable: true }));
function wireTourButton(key) {
  const b = $("#tour-btn");
  if (!b) return;
  b.hidden = !PAGE_TOURS[key];
  b.onclick = () => startTour("page-" + key);
}

/* Runs: each with tags (its PR and that PR's state, its issue, a fix run) and whether it still needs anything (done,
   or not needed: its PR merged or closed, its branch merged, or you said so). Search finds runs by meaning: a vector
   search over each run's brief, tasks and notes, on this computer. */
const LIFE = { active: ["Active", "on"], done: ["Done", "ok"], "not-needed": ["Not needed", ""] };
const runTags = r => `${(r.tags || []).map(t => t.href ? `<a class="tg ${t.tone || ""}" href="${esc(t.href)}" target="_blank" rel="noopener noreferrer" title="${esc(t.state ? `${t.text} is ${t.state.toLowerCase()} on GitHub` : t.text)}" data-stop>${esc(t.text)}${t.state === "MERGED" ? " · merged" : t.state === "CLOSED" ? " · closed" : ""}</a>` : `<span class="tg ${t.tone || ""}"${t.title ? ` title="${esc(t.title)}"` : ""}>${esc(t.text)}</span>`).join("")}${r.life && r.life !== "active" ? `<span class="tg${r.life === "done" ? " ok" : " faded"}" title="${esc(r.life_why || "")}">${esc(LIFE[r.life][0])}${r.life_why && r.life === "not-needed" ? ` · ${esc(r.life_why)}` : ""}</span>` : ""}`;
PAGES.runs = async arg => {
  if (arg) return runDetail(arg);
  const d = await cachedRuns();
  if (d.available === false) return unavailable(d);
  const v = state.runsView = Object.assign({ filter: "active", q: "", hits: null, engine: null }, state.runsView || {});
  const count = k => d.runs.filter(r => k === "all" || (r.life || "active") === k).length;
  const chip = (k, label) => `<button class="pill${v.filter === k ? " on" : ""}" data-runs-filter="${k}">${label} <span class="muted">${count(k)}</span></button>`;
  return `${head("Runs", "Each run is one piece of work LFG took from idea to a commit you can review. Click one to see where it is.")}
    <div class="runs-bar"><input type="search" id="runs-q" placeholder="Search runs by what they're about, e.g. &quot;partition id on windows&quot;" value="${esc(v.q)}" autocomplete="off">
      <span class="seg">${chip("active", "Active")}${chip("done", "Done")}${chip("not-needed", "Not needed")}${chip("all", "All")}</span></div>
    <div id="runs-note" class="muted small"></div>
    <div class="box" id="runs-box"></div>`;
};
function runsTable() {
  const d = state.cache["runs:" + state.repo], v = state.runsView, box = $("#runs-box");
  if (!d || !box) return;
  let rows = d.runs.filter(r => v.filter === "all" || (r.life || "active") === v.filter);
  if (v.hits) {  // search: only matches, best first
    const rank = Object.fromEntries(v.hits.map((h, i) => [h.run, [i, h.score]]));
    rows = d.runs.filter(r => rank[r.run] && (v.filter === "all" || (r.life || "active") === v.filter)).sort((x, y) => rank[x.run][0] - rank[y.run][0]);
    rows.forEach(r => { r.match = rank[r.run][1]; });
  }
  box.innerHTML = table(rows, [
    { k: "slug", label: "Work", html: r => `${esc(runName(r))}${r.current ? ' <span class="tag">current</span>' : ""}${v.hits && r.match != null ? ` <span class="tg on" title="How close it is to your search">${Math.round(r.match * 100)}% match</span>` : ""}${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="sub">${r.owner ? `filed under ${esc(r.owner_name)} · ${plural(r.tasks_here, "task")} for this repo, ${n(r.tasks_here_done)} done` : r.branch ? `<span class="brtag">${esc(r.branch)}</span>` : ""}</div><div class="run-tags">${runTags(r)}</div>`, sort: r => runName(r) },
    { k: "progress", label: "Where it is", html: r => esc(runLine(r, d.stages)), sort: r => r.progress },
    { k: "attn", label: "Status", html: r => { if (r.fix && r.fix.working) return `<span class="st">${dot("on")}AI working</span>`; if (r.life === "not-needed") return `<span class="st">${dot("")}${esc(r.life_why || "Not needed")}</span>`; const a = runAttention(r); return a.length ? `<span class="st">${dot(a[0][0])}${esc(a[0][1])}</span>` : `<span class="st">${dot("ok")}${r.life === "done" ? "Done" : "On track"}</span>`; }, sort: r => runAttention(r).length },
    { k: "created", label: "Started", html: r => `<span class="nowrap">${ago(r.created)}</span>` },
  ], { filter: false, onRow: r => (location.hash = "#runs/" + encodeURIComponent(r.run)), emptyTitle: v.hits ? "No run matches that" : v.filter === "active" ? "Nothing active" : "No runs here", emptyBody: v.hits ? "Try other words, or the All filter." : v.filter === "active" ? "Every run is done or not needed. See Done or All." : "Start one in Claude Code with <code>/lfg:lfg</code> and what you want built." });
  mountTables(box);
}
let runsTimer = null;
function wireRuns(root) {
  if (!$("#runs-box", root)) return;
  const v = state.runsView, note = $("#runs-note", root);
  const engineNote = r => {
    if (!r || !r.engine) { note.innerHTML = ""; return; }
    note.innerHTML = r.engine === "embeddings" ? `Searching by meaning with <code>${esc(r.model)}</code> on your Ollama.`
      : `Word-based vector search (TF-IDF). For search by meaning, install the local embedding model <code>${esc(r.model)}</code> (about 270 MB, from the Ollama library, runs only on your Ollama): <button class="btn small" id="runs-model">Install</button>`;
    const b = $("#runs-model", note);
    if (b) b.onclick = async () => { b.disabled = true; b.textContent = "Installing…"; const s = await save("ollama_pull", { name: r.model }); note.innerHTML = s.ok ? "Downloading the model in the background; search uses it once it's ready." : fmtWhy(s.why || "Couldn't start the download."); };
  };
  const run = async () => {
    const q = $("#runs-q", root).value.trim(); v.q = q;
    if (!q) { v.hits = null; engineNote(null); return runsTable(); }
    note.innerHTML = '<span class="spin"></span> Searching…';
    const r = await api("runs_search", { q });
    if (v.q !== q) return;  // a newer search is on its way
    v.hits = r.results || []; engineNote(r); runsTable();
  };
  $("#runs-q", root).oninput = () => { clearTimeout(runsTimer); runsTimer = setTimeout(run, 350); };
  $$("[data-runs-filter]", root).forEach(b => b.onclick = () => { v.filter = b.dataset.runsFilter; $$("[data-runs-filter]", root).forEach(x => x.classList.toggle("on", x === b)); runsTable(); });
  if (v.q) run(); else runsTable();
}

const FILE_NAMES = { "01-brief.md": "The idea, written up", "02-design.md": "The plan", "tasks.json": "Task list", "04-qa.md": "Test report",
  "ready.json": "Check results", "05-secure.json": "Security check", "05-pentest.json": "Security test", "06-review.json": "Code review",
  "07-shipcheck.json": "Ship check", "COMMIT_MSG.md": "Commit message", "PR_BODY.md": "Pull request text", "progress.md": "Progress notes", "fix-report.md": "What the AI fix run did" };
const fileName = f => FILE_NAMES[f] || (/^03-build-(.+)\.md$/.test(f) ? `Build notes · ${f.slice(9, -3)}` : /^03-fix-(.+)\.md$/.test(f) ? `Fix notes · ${f.slice(7, -3)}` : null);
/* documents in pipeline order: brief, plan, tasks, build notes, tests, checks, security, review, ship, packet, notes */
const FILE_ORDER = ["01-brief.md", "02-design.md", "tasks.json", "03-build-", "04-qa.md", "ready.json", "05-secure.json", "05-pentest.json",
  "06-review.json", "07-shipcheck.json", "COMMIT_MSG.md", "PR_BODY.md", "progress.md"];
const fileRank = f => { const i = FILE_ORDER.findIndex(x => f === x || (x.endsWith("-") && f.startsWith(x))); return i < 0 ? 99 : i; };

const runLifeBar = (d, run) => d.owner_name ? "" : `<div class="run-life"><div class="run-tags">${runTags(d)}</div><span class="grow"></span>${d.archived
  ? `<button class="btn small" data-run-needed="1" data-run="${esc(run)}">Needed again</button>`
  : `<button class="btn small" data-run-needed="0" data-run="${esc(run)}" title="Hide it from Active; nothing is deleted">Mark not needed</button>`}</div>`;
async function runDetail(run) {
  const [d, all] = await Promise.all([api("run", { run }), cachedRuns()]);
  if (d.available === false) return unavailable(d);
  const p = runPlace(all.stages, d.stages, d), attn = runAttention(d);
  const stuck = { "fix-checks": "gate", "fix-review": "review", "fix-block": "review", "fix-security": "secure", "fix-ship": "ship" }[p.next];
  const steps = `<div class="steps">${all.stages.map(([k]) => `<span class="${k === stuck ? "stuck" : d.stages[k] ? "done" : k === p.next ? "next" : ""}">${esc(STEP[k] || k)}</span>`).join("")}</div>`;
  const files = d.files.filter(f => fileName(f.name)).map(f => ({ ...f, run, label: fileName(f.name) }))
    .sort((a, b) => fileRank(a.name) - fileRank(b.name) || a.name.localeCompare(b.name));
  const tasks = d.tasks_list.length ? `<div class="box items">${d.tasks_list.map(taskItem).join("")}</div>` : "";
  const recheck = d.owner_name || !d.current ? "" : d.checking
    ? `<p class="muted small" data-checks-running>Running the checks now (started ${ago(d.checking === true ? "" : d.checking)}). This page updates when they finish; a big project can take several minutes.</p>`
    : `<p><button class="btn small" data-run-checks="${esc(run)}">Run checks again</button> <span class="muted small">lint, types, tests and build, in the background</span></p>`;
  const checks = d.checks.length ? `${recheck}<div class="box items">${readyChecks(d.checks)}</div>` : recheck;
  crumbs("runs", runName(d));
  const docs = files.length ? section("Documents", `<div class="box"><ul class="list">${files.map(f => `<li><a href="#" class="grow" data-run-file='${esc(JSON.stringify([f.run, f.name]))}'>${esc(f.label)}</a><span class="muted small nowrap" title="${esc(f.mtime)}">${ago(f.mtime.replace(" ", "T"))}</span></li>`).join("")}</ul></div>`) : "";
  if (d.fix) return `${head(runName(d), `On branch <span class="brtag">${esc(d.branch)}</span>${d.pr ? ` · <a href="#review/yours/${esc(d.pr)}">PR #${esc(d.pr)} in Reviews</a>${d.pr_url ? ` · <a href="${esc(d.pr_url)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>` : ""}` : ""} · started ${ago(d.created)}`, '<a class="back" href="#runs">← All runs</a>')}${runLifeBar(d, run)}
    <div class="panel"${d.fix.working ? " data-run-working" : ""}><div class="row"><b>${d.fix.working ? '<span class="spin"></span> ' : ""}${esc(runLine(d))}</b></div>
      ${d.worktree ? `<p class="muted small">Working in <code>${esc(d.worktree)}</code>. Nothing is committed or pushed; review the changes there with <code>git diff</code>.</p>` : ""}
      ${Object.keys(d.fix.titles || {}).length ? `<div class="box items">${Object.entries(d.fix.titles).map(([i, c]) => [i, c, d.fix.items[i] || (d.fix.working ? { status: "working" } : {})]).map(([i, c, x]) => `<div class="fx-i"><span class="grow fx-t"><span>${esc(c.title || i)}${c.path ? ` <span class="muted small">${esc(c.path.split("/").pop())}${c.line ? ":" + c.line : ""}</span>` : ""}</span>${x.note ? `<span class="fx-note">${esc(x.note)}</span>` : ""}${(x.files || []).length ? `<span class="muted small">${x.files.map(esc).join(", ")}</span>` : ""}</span>${FIX_SAY[x.status] ? tagHtml(...FIX_SAY[x.status]) : ""}</div>`).join("")}</div>` : ""}</div>
    ${docs}`;
  return `${head(runName(d), `${d.owner_name ? `Filed under ${esc(d.owner_name)} · ` : ""}${d.branch ? `On branch ${esc(d.branch)} · ` : ""}started ${ago(d.created)}`, '<a class="back" href="#runs">← All runs</a>')}${runLifeBar(d, run)}
    ${d.about ? `<p class="about lead">${txt(d.about)}</p>` : ""}
    <div class="panel"><div class="row"><b>${p.finished ? "All steps done" : `${p.done} of ${p.total} steps done`}</b><span class="muted${p.blocked ? " stuck-text" : ""}">${p.finished ? "· the commit message is ready for you to review" : `· next: ${esc(NEXT[p.next])}`}</span></div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>${steps}</div>
    ${attn.length ? section("Needs your attention", `<div class="callout ${attn.some(a => a[0] === "bad") ? "bad" : "warn"}"><ul class="attn">${attn.map(([tn, text]) => `<li>${dot(tn)}<span class="grow">${esc(text)}</span></li>`).join("")}</ul></div>`) : ""}
    ${tasks ? section("Tasks", tasks, `${d.tasks.done} of ${d.tasks.total} done · click one for its steps`) : ""}
    ${checks ? section("Checks", d.ready === "stale" && d.checks.length ? `<p class="muted small">These ran ${ago(d.checked_at)}, before the latest work on this run, so they may no longer hold. Run <code>/lfg:check</code> for a fresh result.</p>${checks}` : checks, d.ready === "stale" ? "out of date" : "click a failed one to see why") : d.owner_name ? section("Checks", `<p class="muted small">This run's checks run in ${esc(d.owner_name)}, on its code, so they aren't shown here.</p>`) : ""}
    ${docs}`;
}

PAGES.issues = async () => {
  const d = await api("issues");
  if (d.available === false) return `${head("Issues", "Your Linear issues, copied into dev-graph by <code>/lfg:inbox</code>.")}${unavailable(d, "Issues aren't available")}`;
  const ws = d.linear_workspace;
  const key = r => [r.legacyRef, r.slug].find(v => /^[A-Z][A-Z0-9]+-\d+$/.test(v || ""));
  const title = r => {
    const k = key(r), link = k && ws ? ` <a class="small" href="https://linear.app/${encodeURIComponent(ws)}/issue/${encodeURIComponent(k)}" target="_blank" rel="noopener noreferrer">${esc(k)} ↗</a>` : k ? ` <span class="muted small">${esc(k)}</span>` : "";
    const name = !r.title || !/\s/.test(r.title) ? words(String(r.title || r.slug).replace(/^iss-/, "")) : r.title;  // a bare ID reads as words
    return `${esc(name)}${link}`;
  };
  const bySlug = Object.fromEntries(d.issues.map(i => [i.slug, i]));
  const fill = rows => rows.map(r => ({ ...bySlug[r.slug], ...r }));
  const cols = [{ k: "title", label: "Issue", html: title }, { k: "status", label: "Status", html: r => `${st(r.status)}${r.graph_status ? `<div class="sub">finished in its run</div>` : ""}` },
    { k: "branches", label: "Branch", html: r => (r.branches || []).length ? r.branches.map(b => `<code>${esc(b)}</code>`).join(" ") : '<span class="muted">—</span>', sort: r => (r.branches || []).join(" ") },
    { k: "updatedAt", label: "Updated", html: r => `<span class="nowrap">${ago(r.updatedAt)}</span>` }];
  const open = r => openDrawer(r.title || words(r.slug), `<div class="readable"><p>${st(r.status)} <span class="tag">${esc(words(r.issueType || "issue"))}</span>${(r.branches || []).map(b => ` <code>${esc(b)}</code>`).join("")}</p>
    ${r.graph_status ? `<p class="muted small">Its task passed in the run; dev-graph still says ${esc(words(r.graph_status))}.</p>` : ""}
    ${r.text_from ? `<p class="muted small">This text comes from the run's plan (<a href="#runs/${encodeURIComponent(r.text_from)}">${esc(runName({ slug: String(r.text_from).slice(14) }))}</a>); the issue itself was saved without it.</p>` : ""}
    ${r.description ? `<div class="md">${md(r.description)}</div>` : '<p class="muted">No description was written for this issue.</p>'}
    ${r.acceptanceCriteria ? `<h3>Done when</h3><div class="md">${md(r.acceptanceCriteria)}</div>` : ""}</div>`);
  const sub = r => { const t = String(r.description || ""); return (r.title && t.startsWith(r.title) ? t.slice(r.title.length) : t).replace(/^\s*Steps:\s*/, "").trim(); };
  cols[0].html = r => `${title(r)}${sub(r) ? `<div class="sub clamp">${esc(sub(r))}</div>` : ""}`;
  const plain = rows => table(fill(rows), cols, { onRow: open });
  const where = `${esc(repoName())}${state.branch ? ` on <code>${esc(state.branch === "-" ? "no branch recorded" : state.branch)}</code>` : ""}`;
  return `${head("Issues", `Issues for ${where}: ${n(d.ready.length)} ready to start, ${n(d.blocked.length)} waiting on other work.`)}
    ${d.error ? `<div class="callout bad">Couldn't read the issues: ${esc(d.error)}</div>` : ""}
    ${d.hidden ? `<p class="muted small">${plural(d.hidden, "issue")} not shown: ${d.hidden === 1 ? "it belongs" : "they belong"} to another repo or branch, or no run or branch name ties ${d.hidden === 1 ? "it" : "them"} to one.</p>` : ""}
    ${tabs("issues", [
      ["ready", "Ready to start", d.ready.length, () => `<div class="box">${plain(d.ready)}</div>`],
      ["blocked", "Waiting on other work", d.blocked.length, () => `<div class="box">${plain(d.blocked)}</div>`],
      ["stale", "Stale", d.stale.length, () => `<p class="muted small">Still open and not touched for ${n(d.stale_days)} days or more.</p><div class="box">${table(d.stale, cols, { onRow: open, emptyTitle: "Nothing stale", emptyBody: `Every open issue changed in the last ${n(d.stale_days)} days.` })}</div>`],
      ["all", "All", d.issues.length, () => `<div class="box">${table(d.issues, cols, { onRow: open, emptyTitle: "No issues yet", emptyBody: "Run <code>/lfg:inbox</code> in Claude Code to bring in your Linear issues." })}</div>`],
    ])}`;
};

/* Local SonarQube: what SonarCloud would flag, found before you push */
function sonarTab(q) {
  const m = q.measures || {};
  const SEV = { BLOCKER: "bad", CRITICAL: "bad", HIGH: "bad", MAJOR: "warn", MEDIUM: "warn" };
  const KIND = { BUG: "Bug", VULNERABILITY: "Vulnerability", CODE_SMELL: "Code smell", SECURITY_HOTSPOT: "Hotspot" };
  const gate = q.gate === "OK" ? tagHtml("Gate passed", "ok") : q.gate === "ERROR" ? tagHtml("Gate failed", "bad") : q.gate ? tagHtml(q.gate, "warn") : tagHtml("Not scanned yet", "");
  const scan = q.server !== "up" ? "" : q.scanning ? `<span class="rv-note" data-sq-scanning><span class="spin"></span>Scanning · started ${ago(q.scanning)}</span>` : `<button class="btn small" data-sq-scan>${icon("refresh")} Scan now</button>`;
  const what = q.ts ? `scanned <span class="brtag">${esc(q.branch || "?")}</span>${q.head ? ` at <span class="brtag">${esc(q.head)}</span>` : ""}${q.base_name ? ` vs <span class="brtag">${esc(q.base_name)}</span>` : ""} · ${ago(q.ts)}` : "";
  const tile = (k, v) => `<div class="sq-tile"><div class="k">${k}</div><div class="v">${esc(v ?? "–")}</div></div>`;
  const issue = r => `<div class="sq-row">${tagHtml((words(String(r.severity || "").toLowerCase()) || "–").replace(/^./, c => c.toUpperCase()), SEV[r.severity] || "")}${tagHtml(KIND[r.kind] || words(String(r.kind || "").toLowerCase()), "")}<span class="grow"><span class="sq-msg">${esc(r.message || "")}</span><span class="rv-row-m"><span class="brtag" title="${esc(r.path || "")}">${esc((r.path || "").split("/").pop())}${r.line ? ":" + r.line : ""}</span><span class="mono">${esc(r.rule || "")}</span></span></span></div>`;
  const mine = (q.issues || []).filter(i => i.mine), rest = (q.issues || []).filter(i => !i.mine);
  const byKind = Object.entries(q.rest_by_kind || {}).map(([k, v]) => tagHtml(`${KIND[k] || words(k.toLowerCase())} ${v}`, "")).join("");
  return `${q.server !== "up" ? `<div class="callout warn">SonarQube isn't running (${esc(q.server)}). Turn it on in <a href="#integrations">Integrations</a>.</div>` : ""}
    <div class="rv-card sq-head"><div class="sq-line">${gate}<span class="rv-row-m">${what}</span><span class="grow"></span>${scan}</div>
      ${q.ts ? `<div class="sq-tiles">${tile("Bugs", m.bugs)}${tile("Vulnerabilities", m.vulnerabilities)}${tile("Code smells", m.code_smells)}${tile("Hotspots", m.security_hotspots)}${tile("Duplication", m.duplicated_lines_density != null ? m.duplicated_lines_density + "%" : null)}</div>` : ""}
      ${(q.conditions || []).filter(c => c.status === "ERROR").map(c => `<div class="sq-line">${tagHtml("Failed", "bad")}<span>${esc(words(c.metricKey))} is ${esc(c.actualValue)} (limit ${esc(c.comparator)} ${esc(c.errorThreshold)})</span></div>`).join("")}
      <div class="sq-line" id="sq-cloud"><span class="muted small">Checking SonarCloud…</span></div></div>
    ${q.ts ? `<div class="rv-card-h sq-sub">On your branch<span class="muted small">${plural(mine.length, "issue")} on lines it changed</span></div>
      <div class="rv-card sq-list">${mine.length ? mine.map(issue).join("") : '<p class="muted small">Nothing on the lines this branch changed.</p>'}</div>` : ""}
    ${rest.length ? `<details class="rv-card"><summary class="rv-card-h">Rest of the repo · ${plural(rest.length, "issue")}<span class="sq-kinds">${byKind}</span></summary><div class="sq-list">${rest.map(issue).join("")}</div></details>` : ""}
    ${q.url ? `<p class="muted small">Full report in <a href="${esc(q.url)}" target="_blank" rel="noopener noreferrer">SonarQube ↗</a> · sign in as admin, <code>lfg sonar login</code> shows the password</p>` : ""}`;
}
async function wireSonar(root) {
  $$("[data-sq-scan]", root).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "Starting…";
    const r = await save("sonar_scan", { repo: state.repo });
    if (!r.ok) { alert(String(r.why || "Couldn't start the scan.").replace(/`/g, "")); b.disabled = false; b.textContent = "Scan now"; return; }
    route({ soft: true });
  });
  if ($("[data-sq-scanning]", root)) setTimeout(() => { if (location.hash.startsWith("#checks") && $("[data-sq-scanning]")) route({ soft: true }); }, 10000);
  const box = $("#sq-cloud", root);
  if (box) {
    const c = await api("sonar_cloud");
    const failed = c && /fail|cancel/i.test(`${c.conclusion} ${c.title}`), crashed = c && /analysis failed/i.test(c.title || c.summary || "");
    box.innerHTML = !c || !c.found ? '<span class="muted small">No SonarCloud check on this commit (not pushed yet, or the repo doesn\'t use SonarCloud)</span>'
      : `${tagHtml(`SonarCloud: ${crashed ? "analysis failed" : c.conclusion || c.status || "?"}`, c.conclusion === "success" ? "ok" : failed ? "bad" : "warn")}<span class="rv-row-m">on <span class="brtag">${esc(String(c.sha).slice(0, 7))}</span>${crashed ? " · their side, not your code" : c.title ? ` · ${esc(c.title)}` : ""}${c.url ? ` · <a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">open ↗</a>` : ""}</span>`;
  }
}

PAGES.checks = async () => {
  const [r, s] = await Promise.all([api("reviews"), api("security")]);
  const last = s.secure[0], ship = s.shipcheck[0], rev = r.verdicts[0];
  const open = r.findings.filter(f => !f.feedback);
  const sum = `<div class="cols">${stat("Latest code review", rev ? say(rev.verdict)[0] : "None yet", rev ? plural(rev.findings, "finding") : "run <code>/lfg:review-coach</code>")}${stat("Latest security check", last ? say(last.verdict)[0] : "None yet", last ? (last.blocking ? `${plural(last.blocking, "problem")} to fix` : "nothing blocking") : "run <code>/lfg:secure</code>")}${stat("Latest ship check", ship ? (ship.pass ? "Passed" : "Failed") : "None yet", ship ? `${ship.ok} of ${ship.total} checks passed${(ship.manual || []).length ? ` · ${ship.manual.length} for you to do` : ""}` : "run <code>/lfg:ship</code>")}</div>`;
  const sevSort = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, minor: 3, low: 3, nit: 4 };
  return `${head("Checks", "What the code reviews and security checks found, and the actions LFG stopped to keep your work safe.")}
    ${sum}
    <div class="section">${tabs("checks", [
      ["review", "Review findings", r.findings.length, () => `<div class="box">${table(r.findings, [
        { k: "severity", label: "How serious", html: x => st(x.severity), sort: x => -(sevSort[String(x.severity).toLowerCase()] ?? 5) },
        { k: "message", label: "Finding", html: x => `${txt(x.title || x.finding || x.message || x.id)}${x.fix ? `<div class="sub clamp">What to do: ${txt(x.fix)}</div>` : ""}${x.file ? `<div class="sub mono">${esc(x.file)}${x.line ? ":" + esc(x.line) : ""}</div>` : ""}<div class="sub">from <a href="#runs/${encodeURIComponent(x.run)}">${esc(runName({ slug: String(x.run || "").slice(14) }))}</a></div>` },
        { k: "feedback", label: "Your call", html: x => st(x.feedback, "not decided") }], { onRow: x => openDrawer("Review finding", `<div class="readable">${findingCard(x)}</div>`), emptyTitle: "No findings", emptyBody: "Run <code>/lfg:review-coach</code> on a change." })}</div>${open.length ? `<p class="muted small">Record your call with <code>lfg feedback add &lt;id&gt; accept|reject</code>.</p>` : ""}`],
      ["security", "Security checks", s.secure.length, () => `<div class="box">${table(s.secure, [
        { k: "verdict", label: "Result", html: x => st(x.verdict) },
        { k: "blocking", label: "Problems to fix", num: true },
        { k: "inventory", label: "New things checked", html: x => esc(Object.entries(x.inventory).filter(([, v]) => v).map(([k, v]) => `${v} ${words(k)}`).join(", ") || "none") },
        { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }],
        { onRow: x => openDrawer("Security check", `<div class="readable"><p>${st(x.verdict)}</p>${x.scope ? `<p class="muted">Checked: ${txt(x.scope)}</p>` : ""}${findingList(x.findings, "No security problems found.")}</div>`) })}</div>`],
      ["pentest", "Security tests", s.pentest.length, () => `<div class="box">${table(s.pentest, [{ k: "status", label: "Result", html: x => st(x.status) }, { k: "summary", label: "What happened", html: x => `<div class="clamp">${txt(x.summary)}</div>` }, { k: "model", label: "Local model" }],
        { onRow: x => openDrawer("Security test", `<div class="readable">${JSON_VIEWS["05-pentest.json"](x)}</div>`) })}</div>`],
      ["ship", "Ship checks", s.shipcheck.length, () => `<div class="box">${table(s.shipcheck, [{ k: "pass", label: "Result", html: x => st(x.pass ? "pass" : "fail") }, { k: "ok", label: "Passed", html: x => `${x.ok} of ${x.total}` }, { k: "failed", label: "What failed", html: x => esc((x.failed || []).join(", ") || "—") }, { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }],
        { onRow: x => openDrawer("Ship check", `<div class="readable"><p>${st(x.pass ? "pass" : "fail")}</p>${x.note ? `<p class="muted">${txt(x.note)}</p>` : ""}<div class="items">${shipChecks(x.checks)}</div></div>`) })}</div>`],
      ...(s.sonar ? [["sonar", "SonarQube", s.sonar.mine || null, () => sonarTab(s.sonar)]] : []),
      ["stopped", "Stopped actions", r.blocked.length, () => `<p class="muted">Actions an agent tried that break a rule, so LFG stopped them. Nothing here needs you; it shows the guard working.</p><div class="box">${table(r.blocked, [{ k: "why", label: "What was stopped", html: x => esc(x.why || x.tool) }, { k: "rule", label: "Rule", html: x => `rule ${esc(x.rule)}` }, { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }])}</div>`],
    ])}</div>`;
};

PAGES.code = async () => {
  const [c, a] = await Promise.all([api("code"), api("architecture")]);
  const g = await api("graphs");
  const [gText, gTone] = say(g.status);
  const mapRow = `<div class="box pad row">${dot(gTone)}<div class="grow"><b>Code map: ${esc((gText || "unknown").toLowerCase())}</b><div class="meta">${g.status === "syncing" ? "Building in the background. This page updates when it's done." : g.synced_at ? `Updated ${ago(g.synced_at)}${g.seconds ? ` in ${Math.round(g.seconds)}s` : ""}.` : "Not built yet."}${g.error ? ` Last error: ${esc(String(g.error).slice(0, 200))}` : ""}</div></div>
    ${mapBtn(g.status)}${g.status !== "missing" && g.status !== "syncing" ? '<button class="btn small" data-map-build="rebuild">Rebuild from scratch</button><button class="btn small" data-map-build="docs" title="Wikis, call flows and playbooks">Refresh docs</button>' : ""}</div>`;
  if (c.available === false && a.available === false) return `${head("Code", "LFG keeps a map of this project so agents read only the parts that matter.")}${mapRow}
    ${g.status === "syncing" ? "" : empty("No code map yet", "Build it now. It runs in the background on this computer and usually takes a minute or two.")}`;
  let summary = "";
  if (c.available !== false) {
    const cov = pct(c.coverage.tested, c.coverage.tested + c.coverage.untested);
    summary = `${n(c.nodes.File)} code files, ${n((c.nodes.Function || 0) + (c.nodes.Class || 0))} functions and classes; code-review-graph links ${cov}% of them to a test.`;
  }
  const risky = c.available !== false ? (c.hotspots || []).slice(0, 10) : [];
  const notes = a.available !== false ? a.rationale : [];
  return `${head("Code", `LFG keeps a map of this project so agents read only the parts that matter. ${summary}`)}
    ${mapRow}
    ${risky.length ? section("Where changes are riskiest", `<div class="box">${table(risky, [
      { k: "symbol", label: "Code", html: r => `${esc(r.symbol)}<div class="sub">${esc(r.file)}</div>` },
      { k: "callers", label: "Used by", num: true, html: r => plural(r.callers, "place") },
      { k: "coverage", label: "Tested", html: r => (r.coverage === "tested" ? `${dot("ok")} Yes` : `${dot("warn")} No`) }], { filter: false })}</div>`, "used in many places, so a change here reaches far") : ""}
    ${notes.length ? section("Why the code is the way it is", `<div class="box">${table(notes, [{ k: "note", label: "Explanation" }, { k: "file", label: "Where", html: r => `<span class="small muted mono nowrap">${esc(r.file + (r.line ? ":" + r.line : ""))}</span>` }])}</div>`, `docstrings and WHY / NOTE / HACK comments${a.rationale_total > notes.length ? `, first ${notes.length} of ${n(a.rationale_total)}` : ""}`) : ""}`;
};

/* Docs: a tree. Project docs (LFG's wiki, glossary, decisions, guides you asked for) at the root, then one folder
   per branch for docs about that branch's work. */
PAGES.docs = async arg => {
  const d = await api("docs");
  if (d.available === false) return unavailable(d);
  const parts = (arg || "").split("/");
  let src = parts[0], path = decodeURIComponent(parts.slice(1).join("/"));
  const all = t => t.items.concat(...t.folders.map(f => f.items));
  if (!src) { const pick = (d.intro || [])[0] || (d.views || [])[0] || all(d.root)[0]; if (pick) { src = pick.src; path = pick.path; } }
  const on = it => it.src === src && it.path === path;
  const link = (it, ico) => `<a href="#docs/${esc(it.src)}/${encodeURIComponent(it.path)}" class="${on(it) ? "on" : ""}" title="${esc(it.title)}">${ico ? icon(ico) : ""}${esc(it.title)}</a>`;
  const folder = (name, items, tag, open) => `<details class="doc-folder"${open || items.some(on) ? " open" : ""}><summary>${icon("folder")}<span class="grow">${esc(name)}</span>${tag || ""}<span class="count">${items.length}</span></summary>${items.map(x => link(x)).join("")}</details>`;
  const STATE = { current: "current", default: "default", merged: "merged", deleted: "deleted" };
  const mine = all(d.root).length + d.branches.reduce((n, b) => n + all(b).length, 0);
  const grp = (t, extra) => `<div class="grp"><span>${t}</span>${extra || ""}</div>`;
  const nav = `${grp("Getting started")}${(d.intro || []).map(x => link(x, "docs")).join("")}
    ${(d.views || []).length || (d.code || []).length ? grp("Code wiki", '<span class="tag" title="Generated by graphify from the code">graphify</span>') : ""}
    ${(d.views || []).map(x => link(x, x.path === "callflow" ? "runs" : "code")).join("")}
    ${(d.code || []).map(x => link(x, "docs")).join("")}
    ${grp("Your docs")}${mine ? d.root.items.map(x => link(x)).join("") + d.root.folders.map(f => folder(f.name, f.items)).join("") : '<p class="meta small pad">None yet. Write one with <b>New doc</b>.</p>'}
    ${d.branches.length ? grp("Branches") + d.branches.map(b => folder(b.name, all(b), b.state ? `<span class="tag${b.state === "current" ? " blue" : ""}">${STATE[b.state]}</span>` : "", b.name === state.branch || b.state === "current")).join("") : ""}`;
  let body;
  if (src === "new" || src === "edit") body = await docEditor(src === "edit" ? path : "");
  else if (src === "view") {
    const v = await api("view", { kind: path });
    body = v.src ? `<iframe class="viewer tall" src="${esc(v.src)}" title="${esc(path)}" referrerpolicy="no-referrer"></iframe>` : empty("Not built yet", fmtWhy(v.message || ""));
  } else if (src && path) {
    const doc = await api("doc", { src, path });
    body = doc.text === "not found" ? empty("Document not found", "") : `${src === "repo" ? `<div class="doc-bar"><span class="tag">${path.startsWith("branches/") ? "Branch doc" : "Project doc"}</span><span class="grow"></span><a class="btn small" href="#docs/edit/${encodeURIComponent(path)}">Edit</a></div>` : src === "gwiki" ? '<div class="doc-bar"><span class="tag">graphify</span><span class="muted small">Written from the code graph; it updates when the code map does.</span></div>' : ""}<div class="md">${md(doc.text, true)}</div>`;
  } else body = empty("No docs yet", "Write one with New doc.");
  return `${head("Docs", "Start here, explore the code wiki graphify builds from your code, and keep your own docs in Markdown.")}
    <div class="docs"><div class="box doc-nav"><div class="doc-tools"><input type="search" id="doc-filter" placeholder="Search docs…"><a class="btn primary small" href="#docs/new">New doc</a></div>${nav}</div>
    <div class="box" id="doc-body" data-src="${esc(src || "")}" data-path="${esc(path || "")}">${body}</div></div>`;
};
async function docEditor(path) {
  let title = "", text = "";
  if (path) {
    const doc = await api("doc", { src: "repo", path });
    text = doc.text === "not found" ? "" : doc.text;
    const m = /^# (.+)\n+/.exec(text); if (m) { title = m[1]; text = text.slice(m[0].length); }
  }
  const br = state.branch && state.branch !== "-" ? state.branch : "";
  return `<div class="doc-edit"><input type="text" id="de-title" placeholder="Title" value="${esc(title)}" maxlength="140">
    ${path ? `<p class="muted small">Editing <code>${esc(path)}</code></p>` : `<div class="row"><span class="muted small">Save it to</span><div class="seg" id="de-where"><button class="pill on" data-w="project">Project</button>${br ? `<button class="pill" data-w="branch" title="Docs about the work on this branch">Branch ${esc(br)}</button>` : ""}</div></div>`}
    <div class="seg de-mode"><button class="pill on" data-m="write">Write</button><button class="pill" data-m="preview">Preview</button></div>
    <textarea class="editor" id="de-text" placeholder="Write or paste Markdown: # headings, - lists, - [ ] checklists, \`code\`, tables…">${esc(text)}</textarea>
    <div class="md de-preview" id="de-preview" hidden></div>
    <div class="set-actions"><button class="btn primary" id="de-save" data-path="${esc(path)}">Save</button><a class="btn" href="#docs${path ? `/repo/${encodeURIComponent(path)}` : ""}">Cancel</a><span class="save-msg" id="de-msg"></span></div></div>`;
}
function wireKnowledgeAdd(root) {
  const b = $("#kn-save", root);
  if (!b) return;
  let kind = "note";
  $$("#kn-kind .pill", root).forEach(p => p.onclick = () => { kind = p.dataset.k; $$("#kn-kind .pill", root).forEach(x => x.classList.toggle("on", x === p)); });
  b.onclick = async () => {
    b.disabled = true;
    const r = await save("knowledge_add", { repo: state.repo, title: $("#kn-title", root).value, text: $("#kn-text", root).value, kind });
    b.disabled = false;
    if (r.ok) { sessionStorage.setItem("lfg.tab.know", "mine"); route(); } else saidMsg($("#kn-msg", root), r);
  };
}
function wireDocEditor(root) {
  const save$ = $("#de-save", root);
  if (!save$) return;
  let where = "project";
  $$("#de-where .pill", root).forEach(b => b.onclick = () => { where = b.dataset.w; $$("#de-where .pill", root).forEach(x => x.classList.toggle("on", x === b)); });
  $$(".de-mode .pill", root).forEach(b => b.onclick = () => {
    $$(".de-mode .pill", root).forEach(x => x.classList.toggle("on", x === b));
    const pv = b.dataset.m === "preview";
    $("#de-text", root).hidden = pv; $("#de-preview", root).hidden = !pv;
    if (pv) $("#de-preview", root).innerHTML = md(`# ${$("#de-title", root).value || "Untitled"}\n\n${$("#de-text", root).value}`);
  });
  save$.onclick = async () => {
    save$.disabled = true;
    const r = await save("doc_save", { repo: state.repo, title: $("#de-title", root).value, text: $("#de-text", root).value, where, branch: state.branch, path: save$.dataset.path });
    save$.disabled = false;
    if (r.ok) location.hash = `#docs/repo/${encodeURIComponent(r.path)}`; else saidMsg($("#de-msg", root), r);
  };
}

PAGES.knowledge = async () => {
  const [k, b, loc] = await Promise.all([api("knowledge"), api("brain"), api("knowledge_local").catch(() => ({ items: [] }))]);
  const L = (loc && loc.items) || [];
  const K = k.available === false ? { decisions: [], principles: [], invariants: [], unheld: [], gaps: [], learnings: [] } : k;
  const B = b.available === false ? { notes: [], preferences: [] } : b;
  const unheld = new Set((K.unheld || []).map(r => r.slug));
  const KN = state.know = [];
  const part = (label, v) => v ? `<h3>${label}</h3><div class="md">${md(String(v))}</div>` : "";
  const listOf = (rows, fn, detail) => rows.length ? `<div class="box"><ul class="list">${rows.map(r => {
    KN.push(() => detail(r));
    return fn(r).replace(/^<li>/, `<li class="click" data-kn="${KN.length - 1}" tabindex="0">`);
  }).join("")}</ul></div>` : empty("Nothing saved yet", "Tell Claude Code what to remember, or use <code>/lfg:note</code>.");
  const sheet = (title, tags, body) => [title, `<div class="readable"><p>${tags}</p>${body}</div>`];
  const rules = K.principles.map(p => ({ text: p.statement, why: p.rationale, s: p.status, kind: p.polarity === "forbids" ? "Never" : "Always", alt: p.correctAlternative, spec: p.specRef }))
    .concat(K.invariants.map(i => ({ text: i.statement, s: unheld.has(i.slug) ? "unheld" : i.status, kind: "Must stay true", guard: i.guardRef, spec: i.specRef })));
  const note = r => sheet(r.name || words(r.slug), `${r.kind ? `<span class="tag">${esc(words(r.kind))}</span>` : ""} ${r.when ? `<span class="muted small">${ago(r.when)}</span>` : ""}`,
    `${r.content ? `<div class="md">${md(String(r.content))}</div>` : '<p class="muted">No text was saved with this note.</p>'}${r.tags && String(r.tags) !== "[]" ? `<p class="muted small">Tags: ${esc(String(r.tags).replace(/[[\]']/g, ""))}</p>` : ""}`);
  const dec = r => sheet(r.title, `${st(r.status)} <span class="muted small">${ago(r.createdAt)}</span>`, `${part("Why it came up", r.context)}${part("What was decided", r.decision)}${part("What follows from it", r.consequences)}`);
  const lrn = r => sheet(r.title, `${r.learningKind ? `<span class="tag">${esc(words(r.learningKind))}</span>` : ""} <span class="muted small">${ago(r.createdAt)}</span>`, r.body ? `<div class="md">${md(String(r.body))}</div>` : '<p class="muted">No text was saved with this lesson.</p>');
  const rule = r => sheet(r.text, `<span class="tag">${esc(r.kind)}</span> ${st(r.s)}`, `${part("Why", r.why)}${part("Do this instead", r.alt)}${part("Checked by", r.guard)}${part("Where it comes from", r.spec)}`);
  const gap = r => sheet(r.title, `${st(r.state)}${r.updatedAt ? ` <span class="muted small">${ago(r.updatedAt)}</span>` : ""}`, `${part("What happens today", r.currentBehavior)}${part("What it should do", r.targetBehavior)}`);
  const missing = [k, b].filter(x => x.available === false).map(x => `<div class="callout warn">${fmtWhy(x.why)}</div>`).join("");
  const KIND = { note: ["Note", ""], decision: ["Decision", "blue"], lesson: ["Lesson", "ok"], rule: ["Rule", "warn"] };
  const mineRow = r => `<li><span class="tag ${KIND[r.kind] ? KIND[r.kind][1] : ""}">${esc((KIND[r.kind] || ["Note"])[0])}</span><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${esc(r.text.replace(/^# .*\n+(> .*\n+)?/, "").replace(/[*_`#>]|^\s*[-+] (\[[ x]\] )?/gm, "").slice(0, 240))}</div></div><span class="muted small nowrap">${esc(r.date)}</span></li>`;
  const mine = r => sheet(r.title, `<span class="tag ${KIND[r.kind] ? KIND[r.kind][1] : ""}">${esc((KIND[r.kind] || ["Note"])[0])}</span> <span class="muted small">${esc(r.date)} · ${esc(r.file)}</span>`, `<div class="md">${md(r.text.replace(/^# .*\n+(> .*\n+)?/, ""))}</div>`);
  const addForm = `<details class="kn-add box pad"><summary><b>Add knowledge</b><span class="muted small">Paste Markdown: a decision, a lesson, a rule or a note. Claude reads it in this project.</span></summary>
    <div class="kn-form"><input type="text" id="kn-title" placeholder="Title, e.g. Money is integer cents" maxlength="140">
      <div class="seg" id="kn-kind">${Object.entries(KIND).map(([k2, [t]], n) => `<button class="pill${n ? "" : " on"}" data-k="${k2}">${t}</button>`).join("")}</div>
      <textarea class="editor" id="kn-text" placeholder="Paste or write Markdown…"></textarea>
      <div class="set-actions"><button class="btn primary" id="kn-save">Save to knowledge</button><span class="save-msg" id="kn-msg"></span><span class="grow"></span><span class="muted small">Saved in <code>${esc((loc && loc.dir) || "")}</code></span></div></div></details>`;
  return `${head("Knowledge", "What LFG remembers between sessions: decisions and lessons about this project, and your own preferences. Agents read these before they work.")}
    ${addForm}
    ${missing}
    ${tabs("know", [
      ["dec", "Decisions", K.decisions.length, () => listOf(K.decisions, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${esc(r.decision)}</div></div><span class="muted small nowrap">${ago(r.createdAt)}</span></li>`, dec)],
      ["lrn", "Lessons learned", K.learnings.length, () => listOf(K.learnings, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${esc(r.body || "")}</div></div><span class="muted small nowrap">${ago(r.createdAt)}</span></li>`, lrn)],
      ["rules", "Code rules", rules.length, () => listOf(rules, r => `<li><span class="tag">${esc(r.kind)}</span><div class="grow"><div class="title">${esc(r.text)}</div>${r.why ? `<div class="meta clamp">${esc(r.why)}</div>` : ""}</div>${st(r.s)}</li>`, rule)],
      ["gaps", "Known gaps", K.gaps.length, () => listOf(K.gaps, r => `<li><div class="grow"><div class="title">${esc(r.title)}</div><div class="meta clamp">${r.currentBehavior ? `Today: ${esc(r.currentBehavior)}` : ""}${r.targetBehavior ? ` · Goal: ${esc(r.targetBehavior)}` : ""}</div></div>${st(r.state)}</li>`, gap)],
      ["pref", "Your preferences", B.preferences.length, () => listOf(B.preferences, r => `<li><div class="grow"><div class="title">${esc(r.name || words(r.slug))}</div>${r.content ? `<div class="meta clamp">${esc(String(r.content))}</div>` : ""}</div></li>`, note)],
      ["notes", "Your notes", B.notes.length, () => listOf(B.notes, r => `<li><div class="grow"><div class="title">${esc(r.name || words(r.slug))}</div>${r.content ? `<div class="meta clamp">${esc(String(r.content))}</div>` : ""}</div><span class="muted small nowrap">${esc(words(r.kind))}</span></li>`, note)],
      ["mine", "Added by you", L.length || null, () => L.length ? listOf(L, mineRow, mine) : empty("Nothing added yet", "Use Add knowledge above, or tell Claude what to remember with <code>/lfg:note</code>.")],
    ])}
    <p class="muted small mt">To add something, tell Claude Code what to remember, or use <code>/lfg:note</code>.</p>`;
};

/* Usage: range and measure in one row above everything they scope; each chart says what it counts. */
const UR = { days: 30, by: "day", measure: "usd" };
function weekOf(day) { const d = new Date(day + "T00:00"); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d.toISOString().slice(0, 10); }
function bucket(rows, by, sum) {
  if (by === "day") return rows.map(r => ({ ...r, key: r.day, label: r.day, short: r.day.slice(5) }));
  const m = new Map();
  for (const r of rows) { const k = weekOf(r.day); if (!m.has(k)) m.set(k, []); m.get(k).push(r); }
  return [...m].map(([k, rs]) => ({ ...sum(rs), key: k, days: rs, label: "Week of " + k, short: k.slice(5) }));
}
function addRows(rs, keys) {
  const o = {};
  for (const k of keys) o[k] = rs.reduce((a, r) => a + (r[k] || 0), 0);
  const models = {};
  for (const r of rs) for (const [m, v] of Object.entries(r.models || {})) { const t = models[m] || (models[m] = {}); for (const [k2, x] of Object.entries(v)) t[k2] = (t[k2] || 0) + x; }
  return { ...o, models };
}
// ------------------------------------------------------------------ reviews (other people's pull requests)
const RV_SAY = { new: ["Not started", ""], working: ["AI is working", "warn"], ready: ["Ready for you", "ok"], posted: ["Posted", "ok"], closed: ["Closed", ""] };
const tagHtml = (t, tone) => `<span class="tg ${tone || ""}">${esc(t)}</span>`;
const initials = name => (String(name || "?").replace(/[-_.\d]+/g, " ").trim().split(/\s+|(?=[A-Z])/).filter(Boolean).slice(0, 2).map(x => x[0]).join("") || "?").toUpperCase();
const RV_TAG = { new: ["Not started", ""], working: ["AI working", "on"], ready: ["Ready for you", "ok"], posted: ["Posted", "ok"], closed: ["Closed", ""] };
const rvTag = rv => { const [t, tone] = RV_TAG[(rv || {}).status] || [(rv || {}).status || "", ""]; return `${tagHtml(t, tone)}${rv && rv.new_commits ? tagHtml("New commits", "warn") : ""}`; };
/* one pull request row: who, which branch into which, size, and where it stands */
function prRow(p, href, who, side) {
  const size = p.changedFiles ? `${plural(p.changedFiles, "file")} <span class="add">+${n(p.additions || 0)}</span> <span class="del">−${n(p.deletions || 0)}</span>` : "";
  return `<a class="rv-row" href="${href}"><span class="av" title="${esc(p.author || "")}">${esc(initials(p.author))}</span><span class="grow"><span class="rv-row-t">${esc(p.title || "#" + p.number)} <span class="muted">#${p.number}</span></span>
    <span class="rv-row-m">${who ? `${who} · ` : ""}${p.stack ? `<span class="tg stk" title="Stacked pull request: ${p.stack.pos} of ${p.stack.size} from the bottom">${icon("stack")}Stack ${p.stack.pos}/${p.stack.size}</span> ` : ""}<span class="brtag" title="${esc(p.headRefName || "")}">${esc(p.headRefName || "?")}</span><span class="arrow">→</span><span class="brtag">${esc(p.baseRefName || "?")}</span>${size ? ` · ${size}` : ""}${p.updatedAt ? ` · ${ago(p.updatedAt)}` : ""}</span></span>${side}</a>`;
}
const pill = (t, tone) => `<span class="st"><span class="dot ${tone}"></span>${esc(t)}</span>`;
const rvChip = rv => { const [t, tone] = RV_SAY[(rv || {}).status] || [rv && rv.status || "", ""]; return `<span class="rv-chips">${pill(t, tone)}${rv && rv.new_commits ? pill("New commits", "warn") : ""}</span>`; };
/* A stacked PR's stack, newest on top as the branches pile up; the trunk at the bottom. Each opens its own review. */
function stackCard(s) {
  if (!s || !s.prs || s.prs.length < 2) return "";
  const cur = s.prs.find(p => p.current) || {};
  const row = p => { const [t, tone] = p.status ? RV_SAY[p.status] || [p.status, ""] : ["Not started", ""];
    const inner = `<span class="stk-dot"></span><span class="grow stk-t"><span>${esc(p.title || "#" + p.number)} <span class="muted">#${p.number}</span></span><span class="rv-row-m">${esc(p.mine ? "you" : p.author || "?")}${p.draft ? " · draft" : ""} · <span class="brtag" title="${esc(p.head || "")}">${esc(p.head || "?")}</span></span></span>${p.current ? tagHtml("this one", "on") : pill(t, tone)}`;
    return p.current ? `<div class="stk-i on" aria-current="true">${inner}</div>` : `<a class="stk-i" href="#review/${p.mine ? "yours/" : ""}${p.number}">${inner}</a>`; };
  return `<details class="rv-card stk" open><summary class="rv-card-h">${icon("stack")}Stack · ${plural(s.size, "pull request")}<span class="muted small">this is ${cur.pos} of ${s.size} from the bottom</span></summary>
    <div class="stk-list">${s.prs.slice().reverse().map(row).join("")}<div class="stk-i trunk"><span class="stk-dot"></span><span class="brtag">${esc(s.trunk || "main")}</span><span class="muted small">trunk</span></div></div></details>`;
}
const EVENT_SAY = { COMMENT: "Comment", REQUEST_CHANGES: "Request changes", APPROVE: "Approve" };

PAGES.review = async arg => {
  const dm = /^(yours\/)?(\d+)\/diff$/.exec(arg);
  if (dm) return diffPage(parseInt(dm[2], 10), !!dm[1]);
  const n = parseInt(arg, 10);
  const unlocked = await isUnlocked();
  if (/^yours\//.test(arg)) return triagePage(parseInt(arg.slice(6), 10), unlocked);
  if (!n) {
    const fresh = state.prFresh ? { fresh: "1" } : {};
    const [d, y] = await Promise.all([api("prs", fresh), api("mine", fresh)]);
    state.prFresh = false;
    const top = `<div class="rv-top"><span class="muted small">${d.fetched_at ? `checked ${ago(d.fetched_at)}` : ""}</span><button class="btn small" data-rv-refresh>Refresh</button></div>`;
    if (d.available === false) return `${head("Reviews")}${top}${unavailable(d, "Couldn't read your review requests")}`;
    const rows = d.prs.map(p => prRow(p, `#review/${p.number}`, `${esc(p.author || "?")}${p.requested === false ? " · no longer asks you" : ""}`,
      `<span class="rv-side">${rvTag(p.review)}${p.review && p.review.worktree_name ? `<span class="brtag">${icon("folder")}${esc(p.review.worktree_name)}</span>` : ""}</span>`)).join("");
    const DEC = { APPROVED: ["Approved", "ok"], CHANGES_REQUESTED: ["Changes requested", "warn"], REVIEW_REQUIRED: ["Review required", ""] };
    const yours = y.available === false ? unavailable(y, "Couldn't read your pull requests") : y.prs.length ? `<div class="box rv-list">${y.prs.map(p => prRow(p, `#review/yours/${p.number}`,
      p.reviewDecision ? tagHtml(...(DEC[p.reviewDecision] || [words(p.reviewDecision), ""])) : "",
      `<span class="rv-side">${p.review && p.review.status === "working" ? tagHtml("AI reading", "on") : p.review && p.review.status !== "new" ? `${p.worth_open ? tagHtml(`${p.worth_open} worth fixing`, "bad") : tagHtml("Nothing to fix", "ok")}${p.low_open ? tagHtml(`${p.low_open} low`, "") : ""}${p.decided ? tagHtml(`${p.decided} ready to send`, "on") : ""}` : tagHtml("Not read yet", "")}</span>`)).join("")}</div>` : empty("No open pull requests", "You have no open pull request in this repo.");
    const closedList = (d.closed || []).length ? `<details class="rv-closed"><summary class="muted small">Closed · ${d.closed.length} <span class="muted">(merged or closed on GitHub)</span></summary><div class="box rv-list">${d.closed.map(c => `<a class="rv-row" href="#review/${c.mine ? "yours/" : ""}${c.number}"><span class="grow"><span class="rv-row-t">${esc(c.title || "#" + c.number)} <span class="muted">#${c.number}</span></span><span class="rv-row-m">${c.mine ? "your pull request" : esc(c.author || "?")}${c.ended_at ? ` · ${ago(c.ended_at)}` : ""}${c.worktree ? ` · <span class="brtag">${icon("folder")}${esc(c.worktree)}</span>` : ""}</span></span><span class="rv-side">${prEnd(c.state)}</span></a>`).join("")}</div></details>` : "";
    return `${head("Reviews", `Pull requests in ${esc(repoName())}. Each one is read in its own worktree, so your checkout stays as it is, and nothing goes to GitHub until you post.`)}${top}
      ${tabs("rvl", [["waiting", "Waiting on me", d.prs.length, () => d.prs.length ? `<div class="box rv-list">${rows}</div>` : empty("Nothing waiting on you", "No open pull request in this repo asks for your review.")],
        ["yours", "My PRs", y.available === false ? null : y.prs.length, () => yours]])}${closedList}`;
  }
  const d = await api("pr", { n });
  if (d.available === false) return unavailable(d);
  state.pr = d;
  const p = d.pr || {}, rv = d.review || {}, dr = d.draft || {}, working = rv.status === "working";
  crumbs("review", `#${n}`);
  const header = rvHeader(d, n, p, rv, `@${esc(p.author || "?")} · ${esc(p.baseRefName || "")} ← ${esc(p.headRefName || "")}`,
    `${rv.new_commits ? `<button class="btn small" data-rv-update${working || !unlocked ? " disabled" : ""}>Pull new commits</button>` : ""}${rv.status === "new" || rv.pr_state ? "" : `<button class="btn small" data-rv-rerun${working || !unlocked ? " disabled" : ""}${working ? ' title="The AI is still working"' : ""}>Re-run review</button>`}`, "data-rv-refresh");
  if (rv.status === "new") return `${header}${stackCard(d.stack)}${rvStart("Start review", "data-rv-start", unlocked, "An AI reviewer reads it in its own worktree with LFG's code review skill, the code graphs and the brains. You talk it through and post when you're happy.")}`;
  const dis = working || rv.status === "posted" || rv.pr_state || !unlocked ? " disabled" : "";
  const ratings = dr.ratings || [], comments = dr.comments || [], questions = dr.questions || [];
  const ai = ratings.map(r => r.ai).filter(Boolean);
  const score = r => `<div class="rv-score" title="${esc(r.why || "")}"><span class="grow">${esc(r.area)}</span>${r.ai ? `<span class="muted small">AI ${r.ai}</span>` : ""}<span class="pills" data-area="${esc(r.area)}">${[1, 2, 3, 4, 5].map(v => `<button class="pill${r.mine === v ? " on" : ""}" data-v="${v}"${dis}>${v}</button>`).join("")}</span></div>`;
  const comment = c => `<div class="rv-c" data-c="${esc(c.id)}" data-path="${esc(c.path || "")}" data-line="${c.line || ""}" data-sev="${esc(c.severity || "")}" data-src="${esc(c.source || "")}"><input type="checkbox" aria-label="Include this comment"${c.include !== false ? " checked" : ""}${dis}><div class="grow"><div class="rv-c-m"><span title="${esc(c.path || "")}">${esc((c.path || "general").split("/").pop())}${c.line ? ":" + c.line : ""}</span> · <select class="rv-sev" aria-label="Severity, posted as the comment's first line"${dis}>${[["", "No label"], ["blocker", "Blocker"], ["major", "Major"], ["minor", "Minor"], ["nit", "Nitpick"]].map(([v, l]) => `<option value="${v}"${sevKey(c.severity) === v ? " selected" : ""}>${l}</option>`).join("")}</select> · ${c.inline ? "on the line" : "in the summary"}</div><textarea class="inline-edit" rows="1"${dis}>${esc(c.body || "")}</textarea></div><button class="icon-btn" data-rv-drop title="Remove" aria-label="Remove"${dis}>&times;</button></div>`;
  const question = q => `<div class="rv-q" data-q="${esc(q.id)}"><div>${txt(q.ask)}${q.why ? `<div class="meta">${txt(q.why)}</div>` : ""}</div><textarea class="inline-edit" rows="1" placeholder="Your answer"${dis}>${esc(q.answer || "")}</textarea><a href="#" class="small" data-rv-discuss="${esc(q.id)}">Discuss</a></div>`;
  const more = (items, keep, fn, what) => items.slice(0, keep).map(fn).join("") + (items.length > keep ? `<div class="rv-more" hidden>${items.slice(keep).map(fn).join("")}</div><a href="#" class="rv-more-link small" data-more>+${items.length - keep} more ${what}</a>` : "");
  const kept = comments.filter(c => c.include !== false).length;
  const main = `<div class="rv-main">${rvEnded(rv, unlocked)}${stackCard(d.stack)}
    ${working ? `<p class="rv-note" data-rv-working><span class="spin"></span>The AI is ${rv.job === "review" ? "reviewing the pull request" : "answering"} · started ${ago(d.working_since)}</p>` : ""}
    ${!working && ((d.chat || []).slice(-1)[0] || {}).error ? `<p class="rv-note bad">The last AI run failed (details on the right).<button class="btn small" data-rv-start${unlocked ? "" : " disabled"}>Try again</button></p>` : ""}
    ${rv.posted ? `<p class="rv-note ok">Posted ${ago(rv.posted.at)} as ${esc((EVENT_SAY[rv.posted.event] || rv.posted.event).toLowerCase())}${rv.posted.url ? ` · <a href="${esc(rv.posted.url)}" target="_blank" rel="noopener noreferrer">see it on GitHub</a>` : ""}</p>` : ""}
    <div class="rv-card"><div class="rv-card-h">Summary for the author${dr.ai_verdict ? `<span class="muted small">AI's call: ${esc(dr.ai_verdict)}</span>` : ""}</div><textarea id="rv-summary" class="inline-edit" rows="2" placeholder="What you'll tell the author"${dis}>${esc(dr.summary || "")}</textarea></div>
    ${ratings.length ? `<div class="rv-card"><div class="rv-card-h">Your scores${ai.length ? `<span class="muted small">AI suggests ${Math.min(...ai)}–${Math.max(...ai)}</span>` : ""}</div>${more(ratings, 2, score, "areas")}</div>` : ""}
    <div class="rv-card"><div class="rv-card-h">Comments<span class="muted small">${kept} to post</span></div>${comments.length ? more(comments, 3, comment, "comments") : '<p class="muted small">No comments yet.</p>'}</div>
    ${questions.length ? `<details class="rv-card"><summary class="rv-card-h">${questions.length} ${questions.length === 1 ? "question" : "questions"} to settle</summary>${questions.map(question).join("")}</details>` : ""}
    ${(dr.context || []).length ? `<details class="rv-card"><summary class="rv-card-h">What the brains added<span class="muted small">${dr.context.length}</span></summary><ul class="small">${dr.context.map(x => `<li>${txt(x)}</li>`).join("")}</ul></details>` : ""}
    ${rv.posted ? `<div class="rv-bar"><span class="grow"></span><button class="btn small" data-rv-close${!unlocked || working ? " disabled" : ""}>Done: remove the worktree</button></div>`
      : `<div class="rv-bar"><input type="hidden" id="rv-event" value="${esc(dr.event || "COMMENT")}"><span class="seg">${Object.entries(EVENT_SAY).map(([k, v]) => `<button class="pill wide${(dr.event || "COMMENT") === k ? " on" : ""}" data-ev="${k}"${dis}>${v}</button>`).join("")}</span><label class="small muted"><input type="checkbox" id="rv-rates"${dr.include_ratings !== false ? " checked" : ""}${dis}> scores</label><span class="grow"></span><span class="muted small" id="rv-saved"></span><button class="btn primary" data-rv-preview${dis}>Post review</button></div>`}
  </div>`;
  return `${header}<div class="rv">${main}${rvChat(d, working, dis)}</div>`;
};

const prEnd = st => st === "MERGED" ? `<span class="tg merged">Merged</span>` : tagHtml("Closed", "bad");
/* A review whose PR was merged or closed on GitHub: say so at the top, and offer to free its worktree */
function rvEnded(rv, unlocked) {
  if (!rv || !rv.pr_state) return "";
  return `<div class="rv-note rv-ended">${prEnd(rv.pr_state)}<span class="grow">This pull request was ${rv.pr_state === "MERGED" ? "merged" : "closed"} on GitHub${rv.ended_at ? ` ${ago(rv.ended_at)}` : ""}, so this review is closed. You can still read it${rv.worktree_name ? " and its diff" : ""}.</span>${rv.worktree_name ? `<button class="btn small" data-rv-close${unlocked ? "" : " disabled"}>Remove the worktree</button>` : ""}</div>`;
}
const sevKey = v => { const k = String(v || "").toLowerCase(); return k === "nitpick" ? "nit" : k === "critical" ? "blocker" : ["blocker", "major", "minor", "nit"].includes(k) ? k : ""; };
function rvTabs(n) {
  const mine = /^#review\/yours\//.test(location.hash), diff = /\/diff$/.test(location.hash), base = `#review/${mine ? "yours/" : ""}${n}`;
  return `<nav class="rv-tabs"><a href="${base}"${diff ? "" : ' class="on" aria-current="page"'}>${mine ? "Comments" : "Review"}</a><a href="${base}/diff"${diff ? ' class="on" aria-current="page"' : ""}>Diff</a></nav>`;
}
function rvHeader(d, n, p, rv, meta, extra, refresh) {
  const wt = rv.worktree_name || (d.worktree_to_be || "").split("/").pop();
  return `${rvTabsWrap(n, `<div class="rvh"><div class="grow"><h1>${esc(p.title || "Pull request")} <span class="muted">#${n}</span></h1>
    <div class="rvh-m">${meta} · <span class="wtchip" title="${esc((d.meta || {}).worktree || d.worktree_to_be || "")}">${icon("folder")}${esc(wt)}</span>${p.url ? ` · <a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">GitHub ↗</a>` : ""}</div></div>
    <div class="rvh-a">${extra}${rv.status === "new" ? "" : `<button class="icon-btn" ${refresh} title="Refresh" aria-label="Refresh">${icon("refresh")}</button>`}</div></div>`)}`;
}
const rvTabsWrap = (n, header) => `${header}${rvTabs(n)}`;
const FOCUS_HINT = "Anything specific for the AI? e.g. focus on the migration and auth, ignore the generated client, check it against ATO-123 (optional)";
function rvStart(label, attr, unlocked, text) {
  return `<div class="rv-empty"><p>${text}</p><textarea class="rv-focus" rows="3" placeholder="${esc(FOCUS_HINT)}"></textarea><button class="btn primary" ${attr}${unlocked ? "" : ' disabled title="Run lfg ui in your terminal to unlock"'}>${label}</button></div>`;
}
/* Start or redo an AI pass with optional instructions: the box on the start screen, else a small sheet */
function withFocus(b, title, explain, label, go) {
  const box = b.closest(".rv-empty") && $(".rv-focus", b.closest(".rv-empty"));
  if (box) return go(box.value.trim());
  openDrawer(title, `<div class="readable td-sheet"><p class="muted small">${explain}</p>
    <label>Instructions for the AI<textarea id="fx-focus" rows="5" placeholder="${esc(FOCUS_HINT)}"></textarea></label>
    <p class="row"><button class="btn primary" id="fx-go">${esc(label)}</button><button class="btn" id="fx-cancel">Cancel</button></p></div>`);
  $("#fx-focus").focus();
  $("#fx-cancel").onclick = closeDrawer;
  $("#fx-focus").onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#fx-go").click(); };
  $("#fx-go").onclick = () => { const f = $("#fx-focus").value.trim(); closeDrawer(); go(f); };
}
const VIA_SAY = { headroom: "via Headroom", direct: "not through Headroom" };
function rvChat(d, working, dis) {
  const msgs = (d.chat || []).map(m => `<div class="msg ${m.role === "me" ? "me" : "ai"}${m.error ? " bad" : ""}">${m.role === "me" ? esc(m.text) : `<div class="md">${md(m.text)}</div>`}${(m.changed && m.changed.length) || m.via ? `<div class="meta">${[m.changed && m.changed.length ? `Updated ${esc(m.changed.join(", "))}` : "", m.cost ? usd(m.cost) : "", VIA_SAY[m.via] || ""].filter(Boolean).join(" · ")}</div>` : ""}</div>`).join("");
  return `<aside class="rv-chat"><div class="rv-chat-head">Talk it through</div><div class="rv-msgs" id="rv-msgs">${msgs || '<p class="muted small">The AI\'s read lands here. Push back, answer its questions, or ask for changes.</p>'}${working ? '<div class="msg ai muted"><span class="spin"></span>Thinking…</div>' : ""}</div>
    <div class="rv-send"><textarea id="rv-text" rows="2" placeholder="${d.mode === "triage" ? "Why only 30% on the null check?" : "Ask or push back"}"${dis}></textarea><button class="btn small" data-rv-ask${dis}>Send</button></div></aside>`;
}

/* Review bots (CodeRabbit, Devin and the like) open with a label line ("Stability | Major | Quick win") and wrap
   parts in HTML: the label becomes tags, the AI-agent prompt goes, <summary> becomes a bold line. */
function botComment(body) {
  let b = String(body || "").replace(/<details>\s*<summary>[^<]*Prompt for AI[^<]*<\/summary>[\s\S]*?<\/details>/gi, "")
    .replace(/<summary>\s*([\s\S]*?)\s*<\/summary>/gi, "\n**$1**\n").replace(/<\/?details>/gi, "").replace(/<picture>[\s\S]*?<\/picture>/gi, "").replace(/<\/?(br|p|div|span|b|i|em|strong|a|img|source|sup|sub)\b[^>]*>/gi, "");
  const lines = b.split("\n"), i0 = lines.findIndex(l => l.trim());
  let tags = [];
  if (i0 >= 0 && lines[i0].includes("|") && lines[i0].length < 160) {
    tags = lines[i0].split("|").map(x => x.replace(/[*_`]/g, "").replace(/\p{Extended_Pictographic}\uFE0F?/gu, "").trim()).filter(Boolean);
    lines.splice(i0, 1);
  }
  return { tags, body: lines.join("\n").replace(/\n{3,}/g, "\n\n").trim() };
}
const TAG_TONE = { critical: "bad", major: "warn" };

const firstSentence = x => { const s = String(x || "").replace(/\s+/g, " ").trim(), m = s.match(/^.{20,}?[.!?](?=\s|$)/); const f = m ? m[0] : s; return f.length > 150 ? f.slice(0, 148) + "…" : f; };
const FIX_SAY = { working: ["AI fixing", "on"], fixed: ["Fixed", "ok"], skipped: ["AI skipped it", ""], failed: ["Fix failed", "bad"] };
const fixTag = t => t.fix_run && FIX_SAY[t.fix_status] ? ` ${tagHtml(...FIX_SAY[t.fix_status])}` : t.fix_queued ? ` ${tagHtml("on the fix list", "on")}` : "";

/* The fix list: comments you pressed Fix on, until Fix all hands them to an AI /lfg:fix run on the PR's branch */
function fixCard(all, d, title, score, unlocked) {
  const waiting = all.filter(t => t.fix_queued && !t.resolved && (!t.fix_run || t.fix_status === "failed")).sort((a, b) => (b.worth ?? -1) - (a.worth ?? -1));
  const runs = d.fixes || [], w = d.fix_where, busy = runs.some(r => r.working);
  if (!waiting.length && !runs.length) return "";
  const where = t => t.path ? `<span class="muted small" title="${esc(t.path)}">${esc(t.path.split("/").pop())}${t.line ? ":" + t.line : ""}</span>` : "";
  const item = (t, extra) => `<div class="fx-i">${score(t)}<span class="grow fx-t">${esc(title(Object.assign({}, t, { body: botComment(t.body).body })))} ${where(t)}${extra || ""}</span>`;
  const byId = Object.fromEntries(all.map(t => [t.id, t]));
  const runHtml = r => {
    const ids = Object.keys(r.items).length ? Object.keys(r.items) : all.filter(t => t.fix_run === r.run).map(t => t.id);
    const head = r.working ? `<span class="spin"></span>AI fixing ${plural(ids.length, "comment")} · started ${ago(r.working === true ? "" : r.working)}`
      : r.ok ? `Fix run finished ${ago(r.at)}${r.cost ? ` · ${usd(r.cost)}` : ""}${VIA_SAY[r.via] ? ` · ${VIA_SAY[r.via]}` : ""}` : `The fix run didn't finish ${ago(r.at)}`;
    return `<div class="fx-run"${r.working ? " data-fx-working" : ""}><div class="fx-run-h"><span class="grow">${head}</span><a class="small" href="#runs/${encodeURIComponent(r.run)}">Open the run →</a></div>
      ${ids.map(i => { const t = byId[i], x = r.items[i]; if (!t) return ""; const st = x ? FIX_SAY[x.status] : r.working ? FIX_SAY.working : null;
        return `${item(t, x && x.note ? `<span class="fx-note">${esc(x.note)}</span>` : "")}${st ? tagHtml(...st) : ""}</div>`; }).join("")}</div>`;
  };
  return `<div class="rv-card fx-card"><div class="fx-h"><b>Fix list</b><span class="muted small">${waiting.length ? `${plural(waiting.length, "comment")} to fix` : "nothing waiting"}${w ? ` · on <span class="brtag">${esc(w.branch)}</span>` : ""}</span><span class="grow"></span>
      <button class="btn primary small" data-fx-all${waiting.length && !busy && unlocked && w ? "" : " disabled"}${busy ? ' title="A fix run is still going"' : ""}>Fix all${waiting.length ? ` (${waiting.length})` : ""}</button></div>
    ${waiting.map(t => `${item(t)}<button class="x" data-fx-rm="${esc(t.id)}" title="Take it off the fix list" aria-label="Remove from the fix list"${unlocked ? "" : " disabled"}>×</button></div>`).join("")}
    ${waiting.length && w ? `<p class="muted small fx-foot">Fix all runs <code>/lfg:fix</code> in ${w.exists ? "the checkout that has this branch" : "a new worktree"}, <code title="${esc(w.path)}">${esc(w.path.split("/").slice(-2).join("/"))}</code>, as a run you can follow on the Runs page. Changes stay unstaged; you commit.</p>` : ""}
    ${runs.map(runHtml).join("")}</div>`;
}

/* Your own PR: every comment thread, the AI's read on it, and the reply you'll send */
async function triagePage(n, unlocked) {
  const d = await api("triage", { n });
  if (d.available === false) return unavailable(d);
  state.pr = d;
  const p = d.pr || {}, rv = d.review || {}, working = rv.status === "working";
  crumbs("review", `Yours #${n}`, `#review/yours/${n}`);
  const all = Object.values((d.triage || {}).threads || {});
  const open = all.filter(t => !t.resolved && !t.posted).sort((a, b) => (b.worth ?? -1) - (a.worth ?? -1));
  const closed = all.filter(t => t.resolved || t.posted);
  const header = rvHeader(d, n, p, rv, `your pull request · ${esc(p.baseRefName || "")} ← ${esc(p.headRefName || "")}`, "",
    `data-tr-start${working || !unlocked ? " disabled" : ""}`);
  if (rv.status === "new") return `${header}${stackCard(d.stack)}${rvStart("Read the comments", "data-tr-start", unlocked, "An AI reads every comment on this pull request against your code, the code graphs and the brains, says how likely each is worth fixing, and drafts your reply either way. Nothing is sent until you send it.")}`;
  const dis = working || rv.pr_state || !unlocked ? " disabled" : "";
  const title = t => {  // a comment's first line, as a person would summarise it: no markup, no emoji
    const unlink = l => { let p; do { p = l; l = l.replace(/!?\[([^[\]]*)\]\([^)]*\)/g, "$1"); } while (l !== p); return l; };
    const lines = (t.body || "").replace(/<[^>]*>?/g, " ").split("\n").map(l => unlink(l).replace(/[#*`>|\[\]]/g, "").replace(/(^|\s)_+|_+(?=\s|$|[.,;:])/g, "$1").replace(/\p{Extended_Pictographic}\uFE0F?/gu, "").replace(/\s+/g, " ").trim()).filter(Boolean);
    const first = lines[0] || "";
    const x = first.length >= 12 ? first : lines.slice(0, 2).join(" ");
    return x.length > 110 ? x.slice(0, 108) + "…" : x;
  };
  const score = t => t.worth == null ? `<span class="score">${working ? "…" : "–"}</span>` : `<span class="score ${t.worth >= 70 ? "hi" : t.worth >= 40 ? "mid" : "lo"}" title="How likely it's worth fixing">${t.worth}%</span>`;
  const row = t => {
    const reasons = [t.reply_wont].concat(t.wont_reasons || []).filter(Boolean);
    const reply = t.reply != null && t.reply !== "" ? t.reply : t.decision === "fix" ? t.reply_fix || "" : t.decision === "wont" ? t.reply_wont || "" : "";
    const bc = botComment(t.body);
    return `<div class="rv-t" data-t="${esc(t.id)}"><div class="rv-t-row">${score(t)}<details class="grow rv-t-d"><summary><span class="rv-t-title">${esc(title({ body: bc.body }))}</span><span class="rv-t-m">${bc.tags.map(x => tagHtml(x, TAG_TONE[x.toLowerCase()] || "")).join("")}${esc(t.author || "?")}${t.bot ? " (bot)" : ""}${t.path ? ` · <span title="${esc(t.path)}">${esc(t.path.split("/").pop())}${t.line ? ":" + t.line : ""}</span>` : ""}${t.outdated ? " · outdated" : ""}${t.from_summary ? ` ${tagHtml("in the review summary", "")}` : ""}${fixTag(t)}</span>${t.why ? `<span class="ai-line"><b>AI</b>${esc(firstSentence(t.why))}</span>` : ""}</summary>
        <div class="rv-t-x">${t.why || t.fix ? `<div class="ai-take"><div class="ai-h"><span class="ai-badge">AI</span>${t.worth != null ? `${t.worth}% worth fixing` : "The AI's read"}</div>${t.why ? `<p>${txt(t.why)}</p>` : ""}${t.fix ? `<p class="ai-fix"><b>Suggested fix</b>${txt(t.fix)}</p>` : ""}</div>` : ""}<div class="rv-src">${esc(t.author || "?")}${t.bot ? " (bot)" : ""} wrote</div><div class="md">${md(bc.body)}</div>${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer" class="small">Open on GitHub ↗</a>` : ""}</div></details>
      <span class="seg">${[["fix", "Fix"], ["wont", "Won't fix"]].map(([k, l]) => `<button class="pill wide${t.decision === k ? " on" : ""}" data-dec="${k}"${k === "fix" ? ' title="Fix it, and put it on the fix list"' : ""}${dis}>${l}</button>`).join("")}</span></div>
      ${t.decision === "fix" || t.decision === "wont" ? `<div class="rv-reply"><span class="muted">↳</span><textarea class="inline-edit" rows="1"${dis}>${esc(reply)}</textarea></div>` : ""}
      ${t.decision === "wont" && reasons.length > 1 ? `<div class="reasons">${reasons.map((r, i) => `<button class="chip${reply === r ? " on" : ""}" data-reason="${i}" title="${esc(r)}"${dis}>${esc(r.length > 48 ? r.slice(0, 46) + "…" : r)}</button>`).join("")}</div>` : ""}</div>`;
  };
  state.trReasons = Object.fromEntries(all.map(t => [t.id, [t.reply_wont].concat(t.wont_reasons || []).filter(Boolean)]));
  const top = open.filter(t => t.worth == null || t.worth >= 30 || t.decision), low = open.filter(t => !top.includes(t));
  const ready = open.filter(t => t.decision === "fix" || t.decision === "wont").length;
  const main = `<div class="rv-main">${rvEnded(rv, unlocked)}${stackCard(d.stack)}
    ${working ? `<p class="rv-note" data-rv-working><span class="spin"></span>The AI is ${rv.job === "triage" ? "reading the comments" : "answering"} · started ${ago(d.working_since)}</p>` : ""}
    ${!working && ((d.chat || []).slice(-1)[0] || {}).error ? `<p class="rv-note bad">The last AI run failed (details on the right).<button class="btn small" data-tr-start${unlocked ? "" : " disabled"}>Try again</button></p>` : ""}
    ${fixCard(all, d, title, score, unlocked)}
    <div class="rv-card rv-list-card">${top.map(row).join("") || (low.length ? "" : '<p class="muted small">No unresolved comments.</p>')}${low.length ? `<div class="rv-divider">${low.length} under 30% · probably not worth fixing</div>${low.map(row).join("")}` : ""}</div>
    ${closed.length ? `<details class="rv-card"><summary class="rv-card-h">${closed.length} resolved or answered</summary>${closed.map(t => `<div class="meta">${esc(t.author || "?")}${t.path ? ` · ${esc(t.path.split("/").pop())}` : ""} · ${t.posted ? `replied (${t.posted.decision === "fix" ? "fixing" : "won't fix"})` : "resolved"}</div>`).join("")}</details>` : ""}
    <div class="rv-bar"><span class="muted small">${open.length} unresolved · ${ready} ${ready === 1 ? "reply" : "replies"} ready</span><span class="grow"></span><span class="muted small" id="rv-saved"></span><button class="btn primary" data-tr-preview${ready && !working && unlocked ? "" : " disabled"}>Send replies</button></div></div>`;
  return `${header}<div class="rv">${main}${rvChat(Object.assign({ mode: "triage" }, d), working, dis)}</div>`;
}

function rvDraft(root) {
  const g = s => $(s, root);
  return {
    summary: g("#rv-summary") ? g("#rv-summary").value : undefined,
    event: g("#rv-event") ? g("#rv-event").value : undefined,
    include_ratings: g("#rv-rates") ? g("#rv-rates").checked : undefined,
    ratings: $$(".pills", root).map(p => ({ area: p.dataset.area, mine: +(($(".pill.on", p) || {}).dataset || {}).v || null })),
    questions: $$(".rv-q", root).map(q => ({ id: q.dataset.q, answer: $("textarea", q).value })),
    comments: $$(".rv-c", root).map(c => ({ id: c.dataset.c, path: c.dataset.path, line: c.dataset.line ? +c.dataset.line : null, severity: $(".rv-sev", c) ? $(".rv-sev", c).value : c.dataset.sev, source: c.dataset.src, body: $("textarea", c).value, include: $("input[type=checkbox]", c).checked })),
  };
}
let rvTimer = null, rvPoll = null;
function wireReview(root) {
  if (/^#review\/(yours\/)?\d+\/diff$/.test(location.hash)) return wireDiff(root);
  const d = state.pr, n = d && d.number;
  clearTimeout(rvPoll);
  $$("[data-rv-refresh]", root).forEach(b => b.onclick = () => { state.prFresh = true; if (n) api("prs", { fresh: "1" }).then(() => route({ soft: true })); else route(); });
  if (!n || !/^#review\/(yours\/)?\d+/.test(location.hash)) return;
  const act = async (what, extra, btn, label) => {
    if (btn) { btn.disabled = true; btn.textContent = label || "Working…"; }
    const r = await save(what, Object.assign({ repo: state.repo, n }, extra || {}));
    if (!r.ok) { alert(String(r.why || "That didn't work.").replace(/`/g, "")); if (btn) btn.disabled = false; }
    route({ soft: true });
    return r;
  };
  const msgs = $("#rv-msgs", root);
  if (msgs) msgs.scrollTop = msgs.scrollHeight;
  $$("[data-rv-start]", root).forEach(b => b.onclick = () => withFocus(b, "Try the review again", "The AI starts the review over in a fresh session.", "Start review", focus => act("pr_start", { focus }, b, "Setting up the worktree…")));
  $$("[data-rv-update]", root).forEach(b => b.onclick = () => act("pr_update", {}, b, "Pulling…"));
  $$("[data-rv-rerun]", root).forEach(b => b.onclick = () => withFocus(b, "Re-run the review", "The AI reviews this pull request again from the top and rewrites the summary, its scores and the comments. Your own scores and answers are kept.", "Re-run review", focus => act("pr_start", { focus }, b, "Starting…")));
  $$("[data-rv-close]", root).forEach(b => b.onclick = () => confirm("Remove this review's worktree? The chat and draft are kept.") && act("pr_close", {}, b));
  const send = $("[data-rv-ask]", root), box = $("#rv-text", root);
  if (send) send.onclick = () => box.value.trim() && act("pr_ask", { text: box.value }, send, "Sending…");
  if (box) box.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send.click(); };
  $$("[data-rv-discuss]", root).forEach(b => b.onclick = e => { e.preventDefault(); const q = (d.draft.questions || []).find(x => x.id === b.dataset.rvDiscuss); box.value = `About ${q.id} (“${q.ask}”): `; box.focus(); });
  const CAP = 66;  // comments show three lines until you click into them
  const grow = t => { t.style.height = "auto"; const full = t.scrollHeight + 2, cap = t.closest(".rv-c, .rv-reply") && document.activeElement !== t;
    t.style.height = (cap ? Math.min(full, CAP) : full) + "px"; t.classList.toggle("clipped", cap && full > CAP); };
  $$(".inline-edit", root).forEach(t => { grow(t); ["input", "focus", "blur"].forEach(ev => t.addEventListener(ev, () => grow(t))); });
  $$("[data-more]", root).forEach(a => a.onclick = e => { e.preventDefault(); const m = a.previousElementSibling; m.hidden = false; $$(".inline-edit", m).forEach(grow); a.remove(); });
  const saved = $("#rv-saved", root);
  const persist = () => { clearTimeout(rvTimer); if (saved) saved.textContent = "…"; rvTimer = setTimeout(async () => { const r = await save("pr_draft", { repo: state.repo, n, draft: rvDraft(root) }); if (saved) saved.textContent = r.ok ? "saved" : (r.why || "not saved"); }, 700); };
  $$(".rv-main textarea, .rv-main select, .rv-main input", root).filter(el => !el.closest(".rv-t")).forEach(el => el.addEventListener(el.tagName === "TEXTAREA" ? "input" : "change", persist));
  $$("[data-ev]", root).forEach(b => b.onclick = () => { $$("[data-ev]", root).forEach(x => x.classList.toggle("on", x === b)); $("#rv-event", root).value = b.dataset.ev; persist(); });
  $$(".pills .pill", root).forEach(b => b.onclick = () => { const on = b.classList.contains("on"); $$(".pill", b.parentNode).forEach(x => x.classList.remove("on")); if (!on) b.classList.add("on"); persist(); });
  $$("[data-rv-drop]", root).forEach(b => b.onclick = () => { b.closest(".rv-c").remove(); persist(); });
  $$("[data-rv-preview]", root).forEach(b => b.onclick = async () => {
    clearTimeout(rvTimer);
    await save("pr_draft", { repo: state.repo, n, draft: rvDraft(root) });
    const o = await api("pr_outgoing", { n });
    if (o.available === false) return alert(o.why);
    openDrawer(`Post to #${n}?`, `<div class="readable"><p><b>${esc(EVENT_SAY[o.event] || o.event)}</b> · ${plural(o.comments.length, "comment")} on lines${o.in_body ? ` · ${o.in_body} in the summary` : ""}</p>
      <div class="md box pad">${md(o.body || "_No summary._")}</div>
      ${o.comments.map(c => `<div class="box pad mt"><code>${esc(c.path)}:${c.line}</code><div class="md">${md(c.body)}</div></div>`).join("")}
      <p class="mt"><button class="btn primary" id="rv-post-go">Post to GitHub</button> <span class="muted small">as you, on commit ${esc(o.commit_id.slice(0, 7))}</span></p></div>`);
    $("#rv-post-go").onclick = async e => { if (!confirm("Post this review to GitHub now?")) return; const r = await act("pr_post", {}, e.target, "Posting…"); if (r.ok) closeDrawer(); };
  });
  wireTriage(root, n, act);
  if ($("[data-rv-working], [data-fx-working]", root)) rvPoll = setTimeout(() => { if (/^#review\/(yours\/)?\d+/.test(location.hash) && !document.activeElement.closest(".rv-send, .rv-t, .rv-card textarea")) route({ soft: true }); }, $("[data-rv-working]", root) ? 4000 : 8000);
}

function wireTriage(root, n, act) {
  $$("[data-tr-start]", root).forEach(b => b.onclick = () => withFocus(b, "Read the comments", "The AI reads the comments it hasn't scored yet. With instructions, it reads every open comment again with them.", "Read the comments", focus => act("pr_triage", { focus }, b, "Reading…")));
  $$("[data-fx-rm]", root).forEach(b => b.onclick = () => act("pr_fixlist", { remove: b.dataset.fxRm }, b, "…"));
  const fixAll = b => async () => {
    const w = state.pr.fix_where || {}, k = $$("[data-fx-rm]", root).length;
    if (!confirm(`Start an AI fix run for ${k} ${k === 1 ? "comment" : "comments"} on ${w.branch}?\n\nIt runs /lfg:fix in ${w.path}${w.exists ? "" : " (a new worktree)"} and leaves the changes unstaged for you to review and commit.`)) return;
    clearTimeout(rvTimer);
    await save("pr_decide", { repo: state.repo, n, decisions: decisions() });
    act("pr_fixall", {}, b, "Starting…");
  };
  const saved = $("#rv-saved", root);
  const decisions = () => Object.fromEntries($$(".rv-t", root).map(c => [c.dataset.t, { decision: ($(".seg .pill.on", c) || { dataset: {} }).dataset.dec || null, reply: $("textarea", c) ? $("textarea", c).value : undefined }]));
  const persist = (rerender) => { clearTimeout(rvTimer); if (saved) saved.textContent = "…"; rvTimer = setTimeout(async () => { const r = await save("pr_decide", { repo: state.repo, n, decisions: decisions() }); if (saved) saved.textContent = r.ok ? "saved" : (r.why || "not saved"); if (rerender) route({ soft: true }); }, rerender ? 0 : 700); };
  $$(".rv-t .seg .pill", root).forEach(b => b.onclick = () => { const c = b.closest(".rv-t"), on = b.classList.contains("on"); $$(".seg .pill", c).forEach(x => x.classList.remove("on")); if (!on) b.classList.add("on"); const ta = $("textarea", c); if (ta) ta.value = ""; persist(true); });
  $$(".rv-t [data-reason]", root).forEach(b => b.onclick = () => { const c = b.closest(".rv-t"); $("textarea", c).value = state.trReasons[c.dataset.t][+b.dataset.reason]; $$("[data-reason]", c).forEach(x => x.classList.toggle("on", x === b)); persist(); });
  $$(".rv-t textarea", root).forEach(t => t.addEventListener("input", () => persist()));
  $$("[data-fx-all]", root).forEach(b => b.onclick = fixAll(b));
  $$("[data-tr-preview]", root).forEach(b => b.onclick = async () => {
    clearTimeout(rvTimer);
    await save("pr_decide", { repo: state.repo, n, decisions: decisions() });
    const o = await api("triage_out", { n });
    openDrawer(`Post ${o.replies.length} ${o.replies.length === 1 ? "reply" : "replies"} to #${n}?`, `<div class="readable">${o.replies.map(r => `<div class="box pad mt"><div class="meta">to @${esc(r.author || "?")}${r.path ? ` · <code>${esc(r.path)}${r.line ? ":" + r.line : ""}</code>` : ""} · ${r.decision === "fix" ? "fixing" : "won't fix"}</div><div class="md">${md(r.body)}</div></div>`).join("")}
      <p class="mt"><button class="btn primary" id="tr-post-go">Post to GitHub</button> <span class="muted small">as you, each under its comment</span></p></div>`);
    $("#tr-post-go").onclick = async e => { if (!confirm("Post these replies to GitHub now?")) return; const r = await act("pr_replies", {}, e.target, "Posting…"); if (r.ok) closeDrawer(); };
  });
}

/* The Diff tab: the pull request's diff, GitHub style. Drag down the line numbers (or click one, then shift-click
   another) to select lines, even across removed and added ones, and ask the AI about them; it answers in a thread
   under them and you go back and forth. All local: nothing goes to GitHub. */
const DF_ICON = { added: ["+", "add"], deleted: ["−", "del"], renamed: ["→", "ren"], modified: ["•", "mod"] };
const rowKey = l => l.new != null ? `R${l.new}` : `L${l.old}`;
const keyLabel = (a, b) => a === b ? `line ${a}` : `lines ${a} to ${b}`;
let dfPoll = null;

async function diffPage(n, mine) {
  const [d, info] = await Promise.all([api("pr_diff", { n }), api(mine ? "triage" : "pr", { n })]);
  state.diff = d; state.pr = Object.assign({ number: n }, info && info.available !== false ? info : {});
  crumbs("review", mine ? `Yours #${n}` : `#${n}`, `#review/${mine ? "yours/" : ""}${n}`);
  const p = (info && info.pr) || {}, rv = (info && info.review) || {};
  const header = rvHeader(info || {}, n, p, rv, `${mine ? "your pull request" : `@${esc(p.author || "?")}`} · ${esc(p.baseRefName || d.base || "")} ← ${esc(p.headRefName || "")}`, "", "data-df-refresh");
  if (d.available === false) return `${header}${unavailable(d, "Couldn't load the diff")}`;
  const total = d.files.reduce((a, f) => a + f.hunks.reduce((b, h) => b + h.lines.length, 0), 0);
  const adds = d.files.reduce((a, f) => a + f.additions, 0), dels = d.files.reduce((a, f) => a + f.deletions, 0);
  const byFile = {};
  d.threads.forEach(t => (byFile[t.path] = byFile[t.path] || []).push(t));
  const keep = state.dfOpen && state.dfOpen.n === n;
  const open = new Set(keep ? state.dfOpen.paths : d.files.filter((f, i) => total <= 3000 || i < 3 || byFile[f.path]).map(f => f.path));
  state.dfOpen = { n, paths: [...open], shut: keep ? state.dfOpen.shut : [], filter: keep ? state.dfOpen.filter : "" };
  const files = d.files.map((f, i) => diffFile(f, i, byFile[f.path] || [], open.has(f.path))).join("");
  return `${header}<div class="df">
    <aside class="df-side"><div class="df-filter"><input type="search" id="df-filter" placeholder="Filter files…" value="${esc(state.dfOpen.filter)}" aria-label="Filter files"></div>
      <div class="df-sum">${plural(d.files.length, "file")} · <span class="add">+${n_(adds)}</span> <span class="del">−${n_(dels)}</span></div>
      <div class="df-tree" id="df-tree">${diffTree(d.files, byFile)}</div></aside>
    <div class="df-main"><p class="muted small df-note">Drag down the line numbers, or click one and shift-click another, to ask the AI about those lines. Its answers stay on this computer: nothing is posted to GitHub.</p>${files || empty("No changes", "This pull request doesn't change any file.")}</div></div>`;
}
const n_ = v => Number(v || 0).toLocaleString();

/* The file list as folders, single-child folders joined into one path the way GitHub shows them */
function diffTree(files, byFile) {
  const root = { dirs: {}, files: [] };
  files.forEach((f, i) => { let node = root; const parts = f.path.split("/"); parts.slice(0, -1).forEach(p => { node = node.dirs[p] = node.dirs[p] || { dirs: {}, files: [] }; }); node.files.push([parts[parts.length - 1], f, i]); });
  const shut = new Set(state.dfOpen.shut || []);
  const walk = (node, depth, prefix) => Object.keys(node.dirs).sort().map(name => {
    let label = name, cur = node.dirs[name], path = prefix + name;
    while (!cur.files.length && Object.keys(cur.dirs).length === 1) { const k = Object.keys(cur.dirs)[0]; label += "/" + k; path += "/" + k; cur = cur.dirs[k]; }
    return `<div class="df-dir${shut.has(path) ? " shut" : ""}" data-dir="${esc(path)}"><a href="#" class="df-row" style="--d:${depth}" data-df-dir><span class="df-chev">${icon("chev")}</span>${icon("folder")}<span class="df-name">${esc(label)}</span></a><div class="df-kids">${walk(cur, depth + 1, path + "/")}${leaves(cur, depth + 1)}</div></div>`;
  }).join("");
  const leaves = (node, depth) => node.files.sort((a, b) => a[0].localeCompare(b[0])).map(([name, f, i]) => {
    const [g, cls] = DF_ICON[f.status] || DF_ICON.modified, th = byFile[f.path] || [];
    return `<a href="#" class="df-row df-leaf" style="--d:${depth}" data-df-goto="${i}" data-name="${esc(f.path.toLowerCase())}" title="${esc(f.path)}"><span class="df-st ${cls}">${g}</span><span class="df-name">${esc(name)}</span>${th.length ? `<span class="df-cnt" title="${plural(th.length, "thread")}">${icon("review")}${th.length}</span>` : ""}</a>`;
  }).join("");
  return walk(root, 0, "") + leaves(root, 0);
}

/* Light syntax colouring for the Diff tab, like GitHub's: comments in a lighter grey, strings in blue. Comment
   syntax comes from the file's extension; strings are read so a "//" inside "http://..." isn't taken for a comment.
   `st` carries an open block comment from one line to the next. */
const HL_LANG = (() => {
  const c = { line: ["//"], block: [["/*", "*/"]], q: "\"'`" }, hash = { line: ["#"], block: [], q: "\"'" }, sql = { line: ["--"], block: [["/*", "*/"]], q: "'\"" };
  const xml = { line: [], block: [["<!--", "-->"]], q: "\"" }, prose = { line: [], block: [["<!--", "-->"]], q: "" };
  const ps = { line: ["#"], block: [["<#", "#>"]], q: "\"'" }, lua = { line: ["--"], block: [], q: "\"'" };
  const m = {};
  "js jsx ts tsx mjs cjs go java kt kts c h cc cpp hpp cs swift rs scala dart php css scss less proto groovy gradle".split(" ").forEach(e => m[e] = c);
  "py sh bash zsh rb yml yaml toml r pl conf ini env tf hcl dockerfile makefile mk cmake nix".split(" ").forEach(e => m[e] = hash);
  "sql".split(" ").forEach(e => m[e] = sql); "lua".split(" ").forEach(e => m[e] = lua);
  "html htm xml wxs wxi svg vue xaml csproj props targets".split(" ").forEach(e => m[e] = xml);
  "md mdx markdown txt".split(" ").forEach(e => m[e] = prose);  // prose: an apostrophe isn't a string
  "ps1 psm1 psd1".split(" ").forEach(e => m[e] = ps);
  return m;
})();
const hlLang = path => { const base = path.split("/").pop().toLowerCase(), ext = base.includes(".") ? base.split(".").pop() : base; return HL_LANG[ext] || null; };
function hlLine(text, lang, st) {
  if (!lang) return esc(text);
  let out = "", i = 0, buf = "";
  const flush = () => { if (buf) { out += esc(buf); buf = ""; } };
  const span = (cls, s) => { flush(); out += `<span class="${cls}">${esc(s)}</span>`; };
  while (i < text.length) {
    if (st.block) {  // inside a comment that started on an earlier line
      const end = text.indexOf(st.block, i);
      if (end < 0) { span("tk-c", text.slice(i)); return out; }
      span("tk-c", text.slice(i, end + st.block.length)); i = end + st.block.length; st.block = null; continue;
    }
    const ch = text[i];
    if (lang.q.includes(ch)) {
      let j = i + 1;
      while (j < text.length && text[j] !== ch) j += text[j] === "\\" ? 2 : 1;
      span("tk-s", text.slice(i, j + 1)); i = j + 1; continue;
    }
    const lc = lang.line.find(t => text.startsWith(t, i) && (t !== "#" || !/[\w$]/.test(text[i - 1] || "")));
    const bc = lang.block.find(([a]) => text.startsWith(a, i));
    if (bc) { st.block = bc[1]; span("tk-c", bc[0]); i += bc[0].length; continue; }
    if (lc) { span("tk-c", text.slice(i)); return out; }
    buf += ch; i++;
  }
  flush();
  return out;
}

function diffFile(f, i, threads, open) {
  const [g, cls] = DF_ICON[f.status] || DF_ICON.modified;
  const keys = new Set(f.hunks.flatMap(h => h.lines.map(rowKey)));
  const at = {}, loose = [];
  threads.forEach(t => t.outdated || !keys.has(t.end) ? loose.push(t) : (at[t.end] = at[t.end] || []).push(t));
  const lang = hlLang(f.path);
  let st = { block: null };  // block comments carry over within a hunk
  const row = l => {
    const k = rowKey(l);
    return `<tr class="df-l ${l.t === "+" ? "add" : l.t === "-" ? "del" : ""}" data-k="${k}"><td class="df-n" data-df-pick>${l.old ?? ""}</td><td class="df-n" data-df-pick>${l.new ?? ""}<button class="df-plus" data-df-pick tabindex="-1" aria-label="Ask the AI about this line">+</button></td><td class="df-s">${l.t === " " ? "" : l.t}</td><td class="df-c">${hlLine(l.text, lang, st) || " "}</td></tr>${(at[k] || []).map(t => `<tr class="df-trow"><td colspan="4">${diffThread(t)}</td></tr>`).join("")}`;
  };
  const body = f.binary ? `<p class="muted small df-pad">Binary file: no lines to show.</p>` : f.too_big ? `<p class="muted small df-pad">This file's diff is too big to show here (${n_(f.additions)} added, ${n_(f.deletions)} removed).</p>`
    : `<table class="df-t" data-path="${esc(f.path)}"><colgroup><col class="c-n"><col class="c-n"><col class="c-s"><col></colgroup><tbody>${f.hunks.map(h => { st = { block: null }; return `<tr class="df-h"><td colspan="2"></td><td colspan="2">${esc(h.header)}</td></tr>${h.lines.map(row).join("")}`; }).join("")}</tbody></table>`;
  return `<details class="df-file" id="df-f${i}" data-path="${esc(f.path)}"${open ? " open" : ""}><summary><span class="df-chev">${icon("chev")}</span><span class="df-st ${cls}">${g}</span><span class="df-path">${esc(f.status === "renamed" && f.old_path ? `${f.old_path} → ${f.path}` : f.path)}</span>${threads.length ? `<span class="df-cnt">${icon("review")}${threads.length}</span>` : ""}<span class="grow"></span><span class="small"><span class="add">+${f.additions}</span> <span class="del">−${f.deletions}</span></span></summary>
    ${loose.length ? `<div class="df-loose">${loose.map(diffThread).join("")}</div>` : ""}${body}</details>`;
}

/* An AI thread on some diff lines: a review conversation, one row per message (avatar, who and when, then the text) */
const avMe = () => `<span class="th-av me" aria-hidden="true">You</span>`;
const avAi = () => `<span class="th-av ai" aria-hidden="true">${logoSvg(28)}</span>`;
function diffThread(t) {
  const where = keyLabel(t.start, t.end);
  if (t.resolved) return `<div class="th resolved" data-th="${esc(t.id)}"><span class="tag ok">Resolved</span><span class="muted small">${esc(where)} · ${plural(t.messages.length, "message")}</span><span class="grow"></span><button class="btn small" data-th-act="reopen">Show</button></div>`;
  const answers = t.messages.filter(m => m.role === "ai" && !m.error), spent = answers.reduce((a, m) => a + (m.cost || 0), 0);
  const cost = c => c ? `<span class="th-cost" title="What this answer cost">${c < 0.01 ? "&lt;$0.01" : usd(c)}</span>` : "";
  const msgs = t.messages.map(m => m.role === "me"
    ? `<div class="th-m">${avMe()}<div class="th-c"><div class="th-who"><b>You</b>${m.ts ? `<span>${ago(m.ts)}</span>` : ""}</div><div class="th-text">${esc(m.text)}</div></div></div>`
    : `<div class="th-m${m.error ? " bad" : ""}">${avAi()}<div class="th-c"><div class="th-who"><b>LFG</b><span class="tag blue">AI</span>${m.error ? '<span class="tag bad">didn\'t answer</span>' : ""}${m.ts ? `<span>${ago(m.ts)}</span>` : ""}${VIA_SAY[m.via] ? `<span>${VIA_SAY[m.via]}</span>` : ""}${cost(m.cost)}</div><div class="md th-text">${md(m.text)}</div></div></div>`).join("");
  return `<div class="th" data-th="${esc(t.id)}"><div class="th-h"><span class="th-lines">${icon("review")}${esc(where.charAt(0).toUpperCase() + where.slice(1))}</span>${t.outdated ? tagHtml("outdated", "warn") : ""}${answers.length ? `<span class="muted small">${plural(answers.length, "answer")}${spent ? ` · ${usd(spent)}` : ""}</span>` : ""}<span class="grow"></span><button class="btn small" data-th-act="resolve"${t.job ? " disabled" : ""}>Resolve</button><button class="icon-btn" data-th-act="delete" title="Delete this thread" aria-label="Delete this thread">&times;</button></div>
    <div class="th-list">${msgs}${t.job ? `<div class="th-m" data-df-working>${avAi()}<div class="th-c"><div class="th-who"><b>LFG</b><span class="tag blue">AI</span></div><div class="th-text muted"><span class="spin"></span> Reading the diff and its callers…</div></div></div>` : ""}</div>
    <div class="th-reply df-reply"><textarea rows="1" placeholder="${t.job ? "Wait for the answer…" : "Reply or ask a follow-up"}"${t.job ? " disabled" : ""}></textarea><button class="btn primary small" data-th-reply${t.job ? " disabled" : ""}>Reply</button></div></div>`;
}

function wireDiff(root) {
  const d = state.diff, n = state.pr && state.pr.number;
  clearTimeout(dfPoll);
  if (!d || d.available === false || !n) return;
  const refresh = () => route({ soft: true });
  $$("[data-df-refresh]", root).forEach(b => b.onclick = async () => { b.disabled = true; await api("pr_diff", { n, fresh: "1" }); refresh(); });
  $$(".df-file", root).forEach(det => det.addEventListener("toggle", () => {
    const s = new Set(state.dfOpen.paths); det.open ? s.add(det.dataset.path) : s.delete(det.dataset.path); state.dfOpen.paths = [...s];
  }));
  // the tree: folders fold, files jump to their diff, the filter narrows the list
  $$("[data-df-dir]", root).forEach(a => a.onclick = e => { e.preventDefault(); const dir = a.parentNode; dir.classList.toggle("shut"); const s = new Set(state.dfOpen.shut); dir.classList.contains("shut") ? s.add(dir.dataset.dir) : s.delete(dir.dataset.dir); state.dfOpen.shut = [...s]; });
  $$("[data-df-goto]", root).forEach(a => a.onclick = e => { e.preventDefault(); $$(".df-leaf.on", root).forEach(x => x.classList.remove("on")); a.classList.add("on"); const f = $(`#df-f${a.dataset.dfGoto}`, root); f.open = true; f.scrollIntoView({ block: "start", behavior: "smooth" }); });
  const filt = $("#df-filter", root);
  const applyFilter = () => {
    const q = filt.value.trim().toLowerCase(); state.dfOpen.filter = filt.value;
    $$(".df-leaf", root).forEach(a => { a.hidden = !!q && !a.dataset.name.includes(q); });
    $$(".df-dir", root).slice().reverse().forEach(dir => { dir.hidden = !!q && !$$(".df-leaf", dir).some(a => !a.hidden); if (q) dir.classList.remove("shut"); });
  };
  if (filt) { filt.oninput = applyFilter; if (filt.value) applyFilter(); }

  // selecting lines: drag down the numbers, or click then shift-click; one file at a time, across - and + rows
  let sel = null, dragging = false;
  const rowsOf = table => $$(".df-l", table);
  const range = () => { const rows = rowsOf(sel.table), i = rows.indexOf(sel.a), j = rows.indexOf(sel.b); return rows.slice(Math.min(i, j), Math.max(i, j) + 1); };
  const clear = () => { $$(".df-l.sel", root).forEach(r => r.classList.remove("sel")); };
  const mark = () => { clear(); if (sel) range().forEach(r => r.classList.add("sel")); };
  const compose = () => {
    $$(".df-compose", root).forEach(r => r.remove());
    if (!sel) return;
    const rows = range(), first = rows[0].dataset.k, last = rows[rows.length - 1].dataset.k;
    const tr = document.createElement("tr");
    tr.className = "df-compose";
    tr.innerHTML = `<td colspan="4"><div class="th th-ask"><div class="th-h"><span class="th-lines">${icon("review")}Ask about ${esc(keyLabel(first, last))}</span></div><textarea rows="4" placeholder="What does this do? Is it safe when the list is empty? Why was the label removed?"></textarea><div class="df-reply"><span class="muted small grow">Stays on this computer: nothing goes to GitHub. ⌘↵ to ask.</span><button class="btn small" data-df-cancel>Cancel</button><button class="btn primary small" data-df-ask>Ask AI</button></div></div></td>`;
    rows[rows.length - 1].after(tr);
    const ta = $("textarea", tr); ta.focus();
    const cancel = () => { sel = null; clear(); tr.remove(); };
    ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("[data-df-ask]", tr).click(); if (e.key === "Escape") cancel(); };
    $("[data-df-cancel]", tr).onclick = cancel;
    $("[data-df-ask]", tr).onclick = async e => {
      if (!ta.value.trim()) return ta.focus();
      e.target.disabled = true; e.target.textContent = "Asking…";
      const r = await save("pr_diff_ask", { repo: state.repo, n, text: ta.value, path: sel.table.dataset.path, start: first, end: last });
      if (!r.ok) { e.target.disabled = false; e.target.textContent = "Ask AI"; return alert(String(r.why || "Couldn't ask.").replace(/`/g, "")); }
      sel = null; refresh();
    };
  };
  $$("[data-df-pick]", root).forEach(el => el.addEventListener("mousedown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    const tr = el.closest(".df-l"), table = el.closest(".df-t");
    if (e.shiftKey && sel && sel.table === table) sel.b = tr; else sel = { table, a: tr, b: tr };
    dragging = true; mark();
  }));
  $$(".df-t", root).forEach(table => table.addEventListener("mouseover", e => {
    if (!dragging || !sel || sel.table !== table) return;
    const tr = e.target.closest(".df-l");
    if (tr && tr !== sel.b) { sel.b = tr; mark(); }
  }));
  const up = () => { if (!dragging) return; dragging = false; compose(); };
  document.removeEventListener("mouseup", state.dfUp || (() => {}));
  state.dfUp = up; document.addEventListener("mouseup", up);

  $$(".th[data-th]", root).forEach(box => {
    const id = box.dataset.th;
    $$("[data-th-act]", box).forEach(b => b.onclick = async () => {
      if (b.dataset.thAct === "delete" && !confirm("Delete this thread? Its questions and answers go too.")) return;
      const r = await save("pr_diff_thread", { repo: state.repo, n, thread: id, action: b.dataset.thAct });
      if (!r.ok) return alert(String(r.why || "That didn't work."));
      refresh();
    });
    const rb = $("[data-th-reply]", box), ta = $(".df-reply textarea", box);
    if (rb && ta) {
      ta.onkeydown = e => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) rb.click(); };
      rb.onclick = async () => {
        if (!ta.value.trim()) return ta.focus();
        rb.disabled = true; rb.textContent = "Sending…";
        const r = await save("pr_diff_ask", { repo: state.repo, n, thread: id, text: ta.value });
        if (!r.ok) { rb.disabled = false; rb.textContent = "Reply"; return alert(String(r.why || "Couldn't send.").replace(/`/g, "")); }
        refresh();
      };
    }
  });
  if ($("[data-df-working]", root)) dfPoll = setTimeout(function again() {
    if (!/\/diff$/.test(location.hash)) return;
    const busy = (document.activeElement && document.activeElement.closest(".df textarea, .df-compose, #df-filter")) || $(".df-compose", root) || dragging;
    if (busy) { dfPoll = setTimeout(again, 3000); return; }
    const y = window.scrollY; route({ soft: true }).then(() => window.scrollTo(0, y));
  }, 4000);
}

/* Did Claude use LFG in this repo's replies? From each reply's **LFG:** line, recorded by the Stop hook. */
function lfgReplies(r) {
  const c = (r || {}).counts || {}, total = Object.values(c).reduce((a, x) => a + x, 0);
  if (!total) return "";
  const why = x => x.kind === "missing" ? '<span class="muted">The reply didn\'t say whether it used LFG</span>' : txt(x.detail || "no reason given");
  return section(`${repoName()}: did Claude use LFG?`, `<div class="cols">${stat("Used an LFG skill", n(c.skill || 0), `of ${n(total)} ${total === 1 ? "reply" : "replies"}`)}${stat("Used LFG's tools", n(c.tools || 0), "graphs, dev-graph, lfg commands")}${stat("Didn't use LFG", n(c["not-used"] || 0), "each with its reason, below")}${stat("Didn't say", n(c.missing || 0), c.missing ? "replies without the LFG line" : "every reply said")}</div>
    ${(r.recent || []).length ? `<div class="box mt">${table(r.recent, [{ k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }, { k: "detail", label: "Why not", html: why }], { filter: false })}</div>` : ""}`, "last 30 days");
}

PAGES.integrations = integrationsPage;

/* Todos: one list across every project, each todo to do, in progress, cancelled or done. A todo becomes a Linear
   ticket only from its Create Linear ticket button, after you confirm the exact text; it is then tagged with the
   issue's id, linked to Linear. */
const TD_SAY = { todo: "To do", in_progress: "In progress", cancelled: "Cancelled", done: "Done" };
let tdPoll = null;
PAGES.todos = async () => {
  const d = await api("todos");
  if (d.available === false) return unavailable(d);
  state.todos = d;
  const of = st => d.todos.filter(t => t.status === st);
  const lin = t => t.linear && t.linear.key ? `<a class="tg on td-lin" href="${esc(t.linear.url)}" target="_blank" rel="noopener noreferrer" title="Open ${esc(t.linear.key)} in Linear${t.linear.project ? ` · ${esc(t.linear.project)}` : ""}${t.linear.assignee ? ` · ${esc(t.linear.assignee === "me" ? "you" : t.linear.assignee)}` : ""}">${esc(t.linear.key)} ↗</a>`
    : t.linear_job ? `<span class="tg td-lin" data-td-creating><span class="spin"></span>Creating Linear ticket…</span>`
    : t.linear_error ? `<span class="td-err small" title="${esc(t.linear_error)}">Linear ticket not created: ${fmtWhy(t.linear_error)}</span>` : "";
  const row = t => `<div class="td st-${t.status}" data-td="${esc(t.id)}">
      <select class="td-st" data-td-status aria-label="Status">${d.statuses.map(k => `<option value="${k}"${k === t.status ? " selected" : ""}>${TD_SAY[k]}</option>`).join("")}</select>
      <div class="grow td-main"><div class="td-text" contenteditable="plaintext-only" spellcheck="true" data-td-text>${esc(t.text)}</div>
        <div class="td-m">${lin(t)}${t.repo ? `<span class="tag">${icon("folder")}${esc(repoName(t.repo))}</span>` : ""}<span class="td-when">${ago(t.status_at || t.created)}</span>${t.notes ? `<span class="muted small" title="${esc(t.notes)}">· notes</span>` : ""}</div></div>
      <span class="td-a">${t.linear && t.linear.key || t.linear_job ? "" : `<button class="btn small" data-td-linear>${t.linear_error ? "Try again" : "Create Linear ticket"}</button>`}<button class="icon-btn" data-td-more title="Notes and more" aria-label="Notes and more">⋯</button></span></div>`;
  const group = (st, open) => { const xs = of(st); if (!xs.length) return ""; const body = `<div class="box td-list">${xs.map(row).join("")}</div>`;
    return open ? section(TD_SAY[st], body, `<span class="tag">${xs.length}</span>`) : `<details class="td-fold"><summary>${TD_SAY[st]} <span class="tag">${xs.length}</span></summary>${body}</details>`; };
  const active = d.counts.todo + d.counts.in_progress;
  return `${head("Todos", "Things to do, across all your projects. Make any of them a Linear ticket when it needs one.")}
    <form class="td-add" data-td-add><span class="td-add-ico">${icon("plus")}</span><input type="text" id="td-new" placeholder="Add a todo and press Enter" maxlength="300" autocomplete="off"><button class="btn primary">Add</button></form>
    ${group("in_progress", true)}${group("todo", true)}${active ? "" : `<div class="box">${empty("Nothing to do", "Add one above. It's tagged with the project you're in.")}</div>`}
    ${group("done", false)}${group("cancelled", false)}`;
};

function wireTodos(root) {
  const d = state.todos;
  clearTimeout(tdPoll);
  if (!d || !d.todos) return;
  const byId = Object.fromEntries(d.todos.map(t => [t.id, t]));
  const act = async (what, body) => { const r = await save(what, body); if (!r.ok) alert(String(r.why || "That didn't work.").replace(/`/g, "")); return r; };
  const reload = () => route({ soft: true });
  const form = $("[data-td-add]", root);
  if (form) form.onsubmit = async e => { e.preventDefault(); const i = $("#td-new", root); if (!i.value.trim()) return; const r = await act("todo_add", { text: i.value, repo: state.repo }); if (r.ok) { i.value = ""; await reload(); const n = $("#td-new"); if (n) n.focus(); } };
  $$(".td", root).forEach(el => {
    const t = byId[el.dataset.td];
    const st = $("[data-td-status]", el); if (st) st.onchange = async () => { await act("todo_update", { id: t.id, status: st.value }); reload(); };
    const tx = $("[data-td-text]", el);
    if (tx) {
      tx.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); tx.blur(); } if (e.key === "Escape") { tx.textContent = t.text; tx.blur(); } };
      tx.onblur = async () => { const v = tx.textContent.replace(/\s+/g, " ").trim(); if (v === t.text) return; if (!v) { tx.textContent = t.text; return; } const r = await act("todo_update", { id: t.id, text: v }); if (r.ok) t.text = v; else tx.textContent = t.text; };
    }
    const ln = $("[data-td-linear]", el); if (ln) ln.onclick = () => todoToLinear(t, d.linear);
    const more = $("[data-td-more]", el); if (more) more.onclick = () => todoMore(t);
  });
  if ($("[data-td-creating]", root)) tdPoll = setTimeout(() => { if ((location.hash.slice(1) || "").split("/")[0] === "todos" && !document.activeElement.closest(".td-main, .td-add, #drawer")) reload(); }, 4000);
}

function todoMore(t) {
  openDrawer("Todo", `<div class="readable td-sheet"><label>Todo<input type="text" id="td-t" maxlength="300" value="${esc(t.text)}"></label>
    <label>Status<select id="td-s">${Object.entries(TD_SAY).map(([k, v]) => `<option value="${k}"${k === t.status ? " selected" : ""}>${v}</option>`).join("")}</select></label>
    <label>Notes<textarea id="td-n" rows="6" placeholder="Anything worth keeping with it">${esc(t.notes || "")}</textarea></label>
    <p class="muted small">${t.repo ? `From ${esc(repoName(t.repo))} · ` : ""}added ${ago(t.created)}${t.linear && t.linear.key ? ` · Linear <a href="${esc(t.linear.url)}" target="_blank" rel="noopener noreferrer">${esc(t.linear.key)} ↗</a>` : ""}</p>
    <p class="row"><button class="btn primary" id="td-save">Save</button><span class="grow"></span><button class="btn small bad" id="td-del">Delete</button></p></div>`);
  $("#td-save").onclick = async () => { const r = await save("todo_update", { id: t.id, text: $("#td-t").value, notes: $("#td-n").value, status: $("#td-s").value }); if (!r.ok) return alert(String(r.why || "Not saved.")); closeDrawer(); route({ soft: true }); };
  $("#td-del").onclick = async () => { if (!confirm(`Delete this todo?\n\n${t.text}${t.linear && t.linear.key ? `\n\n(${t.linear.key} stays in Linear.)` : ""}`)) return; const r = await save("todo_delete", { id: t.id }); if (!r.ok) return alert(String(r.why || "Not deleted.")); closeDrawer(); route({ soft: true }); };
}

/* Create Linear ticket: you check the exact title and description and pick the team, project and assignee from
   Linear's own lists (fetched read-only, kept a day); only then is one issue created, and the todo is tagged with
   its id and linked to it. */
let tlPoll = null;
async function todoToLinear(t, lin) {
  const desc = [t.notes || "", t.repo ? `Repo: ${repoName(t.repo)}` : ""].filter(Boolean).join("\n\n");
  openDrawer("Create Linear ticket", `<div class="readable td-sheet">
    <label>Title<input type="text" id="tl-t" maxlength="300" value="${esc(t.text)}"></label>
    <label>Description<textarea id="tl-d" rows="6" placeholder="Optional">${esc(desc)}</textarea></label>
    <div id="tl-opts"><p class="muted small"><span class="spin"></span> Getting your Linear teams, projects and people…</p></div>
    ${t.linear_error ? `<p class="td-err small">Last try: ${fmtWhy(t.linear_error)}</p>` : ""}
    <p class="muted small">Creates this one issue in Linear, exactly as written and picked here. Nothing else in Linear changes.</p>
    <p class="row"><button class="btn primary" id="tl-go" disabled>Create Linear ticket</button><span class="muted small" id="tl-msg"></span></p></div>`);
  const box = $("#tl-opts"), go = $("#tl-go");
  const pick = { team: lin.team || "", project: "", assignee: "" };
  const paint = o => {
    if (!document.body.contains(box)) return;
    if (!o.teams.length) {
      box.innerHTML = o.loading ? `<p class="muted small"><span class="spin"></span> Getting your Linear teams, projects and people…</p>`
        : `<p class="td-err small">${fmtWhy(o.error || o.why || "Couldn't read Linear.")}</p><p><a href="#" class="small" data-tl-refresh>Try again</a></p>`;
    } else {
      if (!o.teams.some(x => x.key === pick.team)) pick.team = (o.teams.find(x => x.key === o.default_team) || o.teams.find(x => !x.retired) || o.teams[0]).key;
      const projects = o.projects.filter(p => !p.teams.length || p.teams.includes(pick.team));
      if (!projects.some(p => p.name === pick.project)) pick.project = "";
      const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;
      box.innerHTML = `<label>Team<select id="tl-team">${o.teams.map(x => opt(x.key, `${x.name} (${x.key})${x.retired ? " · retired" : ""}`, pick.team)).join("")}</select></label>
        <label>Project<select id="tl-project">${opt("", "No project", pick.project)}${projects.map(p => opt(p.name, p.name, pick.project)).join("")}</select></label>
        <label>Assignee<select id="tl-who">${opt("", "Unassigned", pick.assignee)}${opt("me", "Me", pick.assignee)}${o.users.map(u => opt(u.name, u.display && u.display !== u.name ? `${u.name} (${u.display})` : u.name, pick.assignee)).join("")}</select></label>
        <p class="muted small">${o.loading ? '<span class="spin"></span> Updating from Linear… · ' : o.at ? `From Linear ${ago(new Date(o.at * 1000).toISOString())} · ` : ""}<a href="#" data-tl-refresh>Refresh</a></p>`;
      $("#tl-team").onchange = e => { pick.team = e.target.value; paint(o); };
      $("#tl-project").onchange = e => { pick.project = e.target.value; };
      $("#tl-who").onchange = e => { pick.assignee = e.target.value; };
    }
    go.disabled = !o.teams.length;
    const r = $("[data-tl-refresh]", box); if (r) r.onclick = e => { e.preventDefault(); load(true); };
    clearTimeout(tlPoll);
    if (o.loading) tlPoll = setTimeout(() => load(false), 3000);
  };
  const load = async fresh => paint(await api("linear_options", fresh ? { fresh: "1" } : {}).then(o => Object.assign({ teams: [], projects: [], users: [] }, o)));
  load(false);
  go.onclick = async () => {
    const who = pick.assignee === "me" ? "you" : pick.assignee || "nobody";
    if (!confirm(`Create this ticket in Linear?\n\n${$("#tl-t").value}\n\nTeam ${pick.team}${pick.project ? ` · project ${pick.project}` : ""} · assigned to ${who}`)) return;
    go.disabled = true; go.textContent = "Starting…";
    const r = await save("todo_linear", { id: t.id, title: $("#tl-t").value, description: $("#tl-d").value, team: pick.team, project: pick.project, assignee: pick.assignee });
    if (!r.ok) { go.disabled = false; go.textContent = "Create Linear ticket"; $("#tl-msg").innerHTML = fmtWhy(r.why || "Not started."); return; }
    clearTimeout(tlPoll); closeDrawer(); route({ soft: true });
  };
}

PAGES.usage = async () => {
  const [d, H] = await Promise.all([api("usage", { days: UR.days > 30 ? 90 : 30 }), api("headroom", { days: UR.days > 30 ? 90 : 30 })]);
  const hrDay = Object.fromEntries((((H || {}).when || {}).days || []).map(x => [x.day, x]));
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (d.days || []).filter(x => x.day >= since).map(x => ({ ...x, hr_saved: (hrDay[x.day] || {}).saved || 0, hr_usd: (hrDay[x.day] || {}).usd || 0 }));
  const hrPending = H && H.pending;
  const rangeUsd = days.reduce((a, x) => a + (x.usd || 0), 0), hrUsd = days.reduce((a, x) => a + (x.hr_usd || 0), 0);
  const hrTokens = days.reduce((a, x) => a + (x.hr_saved || 0), 0);
  const t = days.reduce((a, x) => { for (const k of ["input", "output", "cache_read", "cache_write"]) a[k] += x[k] || 0; return a; }, { input: 0, output: 0, cache_read: 0, cache_write: 0 });
  const hit = pct(t.cache_read, t.cache_read + t.input + t.cache_write);
  const hr = d.headroom || {}, life = hr.lifetime || {}, sp = d.spend || {};
  const seg = (key, opts) => `<div class="seg inline">${opts.map(([v, l]) => `<label class="${UR[key] === v ? "on" : ""}"><input type="radio" name="ur-${key}" data-ur="${key}" value="${v}" ${UR[key] === v ? "checked" : ""}>${l}</label>`).join("")}</div>`;
  const rows = bucket(days, UR.by, rs => addRows(rs, ["input", "output", "cache_read", "cache_write", "usd", "hr_saved", "hr_usd"]));
  const usdFmt = v => usd(v || 0);
  const filters_row = `<div class="row filters">${seg("days", [[7, "7 days"], [14, "14 days"], [30, "30 days"], [90, "90 days"]])}${seg("by", [["day", "By day"], ["week", "By week"]])}${seg("measure", [["usd", "Dollars"], ["tokens", "Tokens"]])}</div>`;
  const ghost = { ghost: true };
  if (hrPending) setTimeout(() => { if ((location.hash.slice(1) || "").startsWith("usage")) softRoute(); }, 2500);
  const chart = UR.measure === "usd"
    ? iChart(rows.map(r => ({ label: r.label, short: r.short, values: [r.usd, r.hr_usd], raw: r })), [["Actual cost", "var(--series-1)", usdFmt], ["Saved by Headroom", "var(--series-1)", usdFmt, ghost]],
        { title: "Cost per " + UR.by, onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(1) ? "" : `Without Headroom: ${usd((x.values[0] || 0) + (x.values[1] || 0))}` })
    : iChart(rows.map(r => ({ label: r.label, short: r.short, values: [(r.input || 0) + (r.cache_write || 0), r.cache_read || 0, r.output || 0, r.hr_saved || 0], raw: r })), [["Sent new", "var(--series-1)"], ["Reused from cache", "var(--series-2)"], ["Written by Claude", "var(--series-3)"], ["Removed by Headroom", "var(--series-1)", compact, ghost]],
        { title: "Tokens per " + UR.by, hidden: [1], onPick: i => usageDetail(rows, i), total: (x, hid) => hid.has(3) ? "" : `Without Headroom: ${compact(x.values.reduce((a, v, j) => a + (hid.has(j) ? 0 : v || 0), 0))} tokens` });
  state.usageRows = rows;
  return `${head("Usage", "What Claude Code used and what it would cost at API prices, across every session on this computer.")}
    ${filters_row}
    <div class="cols">${stat(`Cost, last ${UR.days} days`, usd(rangeUsd), "the work priced at Anthropic's API rates, from every session's log; on a subscription you pay your plan, not this")}${stat("Cost today", usd(sp.today || 0), "since midnight")}${stat(`Saved by Headroom, last ${UR.days} days`, hrTokens ? usd(hrUsd) : "—", hrTokens ? `${compact(hrTokens)} tokens removed, by Headroom's count` : hrPending ? "checking…" : "nothing recorded")}</div>
    <div class="cols">${stat(`Tokens sent, last ${UR.days} days`, compact(t.input + t.cache_read + t.cache_write), `${hit}% reused from cache, which costs about a tenth as much`)}${stat(`Tokens written, last ${UR.days} days`, compact(t.output), "Claude's replies")}</div>
    ${section(UR.measure === "usd" ? `Cost per ${UR.by}` : `Tokens per ${UR.by}`, `<div class="box pad" id="usage-main">${chart}<div id="usage-detail"></div></div>`, UR.measure === "usd"
      ? `the solid bar is what that ${UR.by}'s work cost at Anthropic's API prices; the dashed part on top is what Headroom saved, so the whole bar is what it would have cost without Headroom${hrPending ? " (Headroom's numbers are still loading)" : ""}. Hover for numbers, click for the breakdown by model.`
      : `solid: what was sent (new text, and text reused from cache, hidden until you click its key) and what Claude wrote back. Dashed on top: what Headroom removed before sending, so the whole bar is what would have been sent without it${hrPending ? " (Headroom's numbers are still loading)" : ""}.`)}
    ${(d.models || []).length ? section("By model", `<div class="box">${table(d.models, [{ k: "model", label: "Model" }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }, { k: "usd", label: "Cost", num: true, html: r => r.usd != null ? usd(r.usd) : "" }], { filter: false })}</div>`, "last " + (d.days || []).length + " days") : ""}
    <div id="hr-detail"><div class="loading">Reading Headroom's logs…</div></div>
    ${lfgReplies(d.replies)}
    ${(d.runs || []).length ? section(`${repoName()}, by run`, `<div class="box">${table(d.runs, [{ k: "run", label: "Run", html: r => r.run && r.run !== "(no run)" ? `<a href="#runs/${encodeURIComponent(r.run)}">${esc(runName({ slug: r.run.slice(14) }))}</a>` : '<span class="muted">Outside a run</span>' }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }], { filter: false })}</div>`, "this project only, all time") : ""}`;
};
function usageDetail(rows, i) {
  const box = $("#usage-detail");
  if (!box) return;
  if (i == null) { box.innerHTML = ""; return; }
  const r = rows[i], ms = Object.entries(r.models || {}).map(([m, v]) => ({ model: m, ...v })).sort((a, b) => (b.usd || 0) - (a.usd || 0));
  box.innerHTML = `<div class="k">${esc(r.label)}: ${usd(r.usd || 0)}, ${compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0))} tokens sent, ${compact(r.output || 0)} written</div>
    <div class="box">${table(ms, [{ k: "model", label: "Model" }, { k: "usd", label: "Cost", num: true, html: x => usd(x.usd || 0) }, { k: "input", label: "Sent new", num: true, html: x => compact((x.input || 0) + (x.cache_write_5m || 0) + (x.cache_write_1h || 0)) }, { k: "cache_read", label: "Reused", num: true, html: x => compact(x.cache_read || 0) }, { k: "output", label: "Written", num: true, html: x => compact(x.output || 0) }], { filter: false, sort: "usd" })}</div>`;
  mountTables(box);
}
function wireUsage(root) {
  $$("[data-ur]", root).forEach(el => el.onchange = () => {
    const k = el.dataset.ur; UR[k] = k === "days" ? +el.value : el.value;
    $$(".seg label", el.closest(".seg")).forEach(l => l.classList.toggle("on", l.contains(el)));
    const m = $("#usage-main");
    if (m) { m.classList.add("is-loading"); m.setAttribute("aria-busy", "true"); }
    softRoute();
  });
  wireICharts(root);
}

async function loadHeadroom() {
  const box = $("#hr-detail");
  if (!box) return;
  const d = await api("headroom", { days: UR.days > 30 ? 90 : 30 });
  if (d.pending) { setTimeout(loadHeadroom, 2000); return; }
  if (d.available === false) { box.innerHTML = ""; return; }
  const W = d.when || {};
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (W.days || []).filter(x => x.day >= since);
  const rows = bucket(days, UR.by, rs => addRows(rs, ["saved", "calls", "usd", "before"]));
  const status = d.routed ? `<span class="row" style="gap:8px">${dot(d.live ? "ok" : "bad")}<span>${d.live ? "On: every Claude Code session goes through it." : "Every session goes through it, but it isn't running right now, so sessions can't reach Claude."}</span></span>` : d.live ? `<span class="row" style="gap:8px">${dot("warn")}<span>Running, but Claude Code doesn't go through it.</span></span>` : `<span class="row" style="gap:8px">${dot("")}<span>Off.</span></span>`;
  const hours = (W.today_by_hour || []).filter(h => h.calls).sort((a, b) => b.calls - a.calls).slice(0, 3);
  box.innerHTML = section("Saved by Headroom", `<p class="muted">Headroom is a small program on this computer that every request from Claude Code passes through on its way to Anthropic. It removes repeated and unneeded text first, so less is sent and billed.</p>
    <p>${status}</p>
    ${rows.length ? `<p class="muted small">In this range: ${compact(rows.reduce((a, x) => a + (x.saved || 0), 0))} tokens removed from ${n(rows.reduce((a, x) => a + (x.calls || 0), 0))} requests, about ${usd(rows.reduce((a, x) => a + (x.usd || 0), 0))} by Headroom's count. It's the dashed part of the chart above.${hours.length ? ` Busiest today: ${hours.map(h => `${h.hour}:00 (${n(h.calls)} requests)`).join(", ")}.` : ""}</p>` : ""}`);
  mountTables(box);
  wireICharts(box);
}

PAGES.settings = async () => {
  const [cfg, sk, cm, unlocked] = await Promise.all([api("settings"), api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = { cfg, sk, cm, unlocked };
  return `${head("Settings", unlocked ? "Changes are checked, refused if they look like a password or key, and backed up." : "")}
    ${unlocked ? "" : `<div class="callout">Read-only. To make changes, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("settings", [["claudecode", "Claude Code", null, settingsClaudeCode], ["general", "General", null, settingsGeneral], ["storage", "Disk space", null, settingsStorage], ["rules", "Rules", null, settingsRules], ["claudemd", "Your instructions", null, settingsClaude], ["appearance", "Appearance", null, settingsAppearance]])}</div>`;
};

// ------------------------------------------------------------------ skills: every skill Claude Code loads, from every source
const SRC_LABEL = { personal: "Yours", "personal command": "Your command", project: "This project", plugin: "Plugin" };
PAGES.skills = async () => {
  const [sk, cm, unlocked] = await Promise.all([api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { sk, cm, unlocked, cfg: (state.settings || {}).cfg });
  return `${head("Skills", "Everything Claude Code can load as a skill on this computer: yours, this project's and every plugin's, LFG's included.")}
    ${unlocked ? "" : `<div class="callout">Read-only. To change skills, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("skillspage", [["all", "All skills", null, () => '<div id="skills-box"><div class="loading">Reading skills…</div></div>'], ["lfgedit", "Edit LFG skills", null, settingsSkills]])}</div>`;
};
async function loadFeatures() {
  const box = $("#features-section");
  if (!box) return;
  const d = await api("onboarding");
  state.onboardData = d;
  state.pages = d.pages || NAV.map(p => p[0]);
  const unlocked = state.settings?.unlocked;
  const showAllCb = $("#show-all-pages");
  // Wire show-all-pages toggle
  if (showAllCb) {
    showAllCb.checked = d.show_all || false;
    showAllCb.onchange = async () => {
      showAllCb.disabled = true;
      const r = await save("pages_show_all", { on: showAllCb.checked });
      if (r.ok) applyPages(r);
      showAllCb.disabled = false;
    };
  }
  // Render all 5 feature toggles, none disabled
  box.innerHTML = (d.features || []).map(f =>
    `<label class="row"><input type="checkbox" data-feat="${esc(f.id)}" ${f.enabled ? "checked" : ""} ${!unlocked ? "disabled" : ""}> <div><b>${esc(f.name)}</b><div class="muted small">${esc(f.description)}</div></div></label>`
  ).join("") + '<span class="save-msg ml" id="feat-msg"></span>';
  // Wire feature toggles: save immediately on change
  $$("[data-feat]", box).forEach(cb => {
    cb.onchange = async () => {
      cb.disabled = true;
      const r = await save("feature_toggle", { feature: cb.dataset.feat, enabled: cb.checked });
      saidMsg($("#feat-msg"), r, r.ok ? "Saved." : "");
      if (r.ok) applyPages(r);
      cb.disabled = false;
    };
  });
}

async function loadSkills() {
  const box = $("#skills-box");
  if (!box) return;
  const d = await api("allskills"), un = state.settings.unlocked, S = d.summary;
  const filt = sessionStorage.getItem("lfg.skills.filter") || "all";
  const rows = d.skills.filter(r => filt === "all" || (filt === "collisions" ? r.collides_with.length : filt === "auto" ? r.auto : r.source === filt));
  box.innerHTML = `<div class="cols">${stat("Skills", n(S.total))}${stat("Claude may use on its own", n(S.auto), `about ${compact(S.approx_tokens)} tokens of descriptions in every session`)}${stat("Name clashes", n(S.collisions), "the short name goes to your own skill first")}</div>
    <div class="row mt"><label class="muted small" for="sk-filter">Show</label><select id="sk-filter">${[["all", "All"], ["auto", "Used on its own"], ["collisions", "Name clashes"], ...S.sources.map(x => [x, SRC_LABEL[x] || x])].map(([v, l]) => `<option value="${esc(v)}" ${v === filt ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><span class="save-msg" id="sk-msg"></span></div>
    <div class="box mt">${table(rows, [
      { k: "invoke", label: "Type", html: r => `<code class="nowrap">${esc(r.invoke)}</code>${r.shadowed ? ' <span class="tag" title="A skill of yours has the same short name">use full name</span>' : ""}` },
      { k: "source", label: "From", html: r => `${esc(SRC_LABEL[r.source] || r.source)}${r.plugin ? `<div class="sub">${esc(r.plugin)}${r.enabled === false ? " · off" : ""}</div>` : ""}` },
      { k: "auto", label: "Claude uses it on its own", sort: r => (r.auto ? 1 : 0), html: r => r.editable ? `<label class="row"><input type="checkbox" data-sk-auto="${esc(r.id)}" ${r.auto ? "checked" : ""} ${un ? "" : "disabled"}> ${r.auto ? "yes" : "only when typed"}</label>` : (r.auto ? "yes" : "only when typed") },
      { k: "description", label: "What it does", html: r => `<span title="${esc(r.description)}">${esc(r.description.slice(0, 140))}${r.description.length > 140 ? "…" : ""}</span>${r.collides_with.length ? `<div class="sub">same name as ${r.collides_with.map(x => `<code>${esc(x)}</code>`).join(", ")}</div>` : ""}` },
      { k: "chars", label: "Size", num: true },
    ], { onRow: r => showSkillText(r.id), emptyTitle: "No skills here" })}</div>`;
  mountTables(box);
  $("#sk-filter", box).onchange = e => { sessionStorage.setItem("lfg.skills.filter", e.target.value); loadSkills(); };
  $$("[data-sk-auto]", box).forEach(c => {
    c.onclick = e => e.stopPropagation();
    c.onchange = async () => {
      const r = await save("skill_auto", { id: c.dataset.skAuto, auto: c.checked });
      saidMsg($("#sk-msg"), r, r.ok ? "Saved." : "");
      if (!r.ok) c.checked = !c.checked;
    };
  });
}
async function showSkillText(id) {
  const d = await api("skilltext", { id });
  if (d.available === false) return;
  const fm = frontMatter(d.text);
  openDrawer(d.invoke, `${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}${d.lfg_name ? '<p class="small">Change it under <b>Edit LFG skills</b>.</p>' : ""}<div class="md">${md(fm.body)}</div>`);
};

/* Help: how LFG works in three steps, every command grouped by what it's for (read from the plugin, so it's
   always current), and a few answers. */
const HELP_GROUPS = [["Build something", ["lfg", "plan", "build", "spike", "wizard"]], ["Fix a problem", ["fix", "why", "health"]],
  ["Understand the code", ["explain", "explain5", "impact", "map", "research"]], ["Review and ship", ["review-coach", "check", "secure", "pentest", "suggest-tests", "grill", "ship"]],
  ["Remember and hand off", ["note", "learn", "handoff", "inbox"]], ["Not sure", ["which"]]];
PAGES.help = async () => {
  const d = await api("guide");
  const first = t => { const x = String(t || "").replace(/\s+/g, " ").trim(), m = /^(.{20,220}?[.!?])(\s|$)/.exec(x); return m ? m[1] : x.length <= 200 ? x : x.slice(0, x.lastIndexOf(" ", 190)) + "…"; };
  const all = (d.skills || []).map(x => ({ cmd: x.name, key: x.name.replace(/^\/lfg:/, ""), what: first(x.description) }));
  const placed = new Set(), groups = HELP_GROUPS.map(([g, ks]) => [g, ks.map(k => all.find(x => x.key === k)).filter(Boolean)]);
  groups.forEach(([, xs]) => xs.forEach(x => placed.add(x.key)));
  const rest = all.filter(x => !placed.has(x.key)); if (rest.length) groups.push(["More", rest]);
  const step = (n, ico, title, body) => `<div class="box hp-step"><span class="hp-n">${n}</span>${icon(ico)}<b>${title}</b><p>${body}</p></div>`;
  const qa = (q, a) => `<details class="hp-q"><summary>${q}</summary><p>${a}</p></details>`;
  return `${head("Help", "LFG takes a change from idea to pull request inside Claude Code. You describe it, review what comes back, and ship.")}
    ${section("Get started", `<div class="hp-steps">
      ${step(1, "sessions", "Describe the change", `Open <a href="#sessions">Studio</a> and write what you want, or type <code>/lfg:lfg</code> and a sentence in Claude Code.`)}
      ${step(2, "review", "Review the result", `LFG plans, builds, tests and reviews it, and stops to ask you at each checkpoint. Follow along in <a href="#runs">Runs</a>.`)}
      ${step(3, "runs", "Ship it", `<code>/lfg:ship</code> gets the pull request ready. LFG never commits, pushes or merges; you do.`)}</div>`)}
    ${section("What you can ask for", `<input type="search" id="hp-find" class="hp-find" placeholder="Search commands" autocomplete="off">
      ${groups.filter(([, xs]) => xs.length).map(([g, xs]) => `<div class="hp-grp"><h3>${esc(g)}</h3><div class="box"><ul class="list">${xs.map(x => `<li class="click hp-sk" tabindex="0" data-copy-cmd="${esc(x.cmd)}" data-find="${esc((x.cmd + " " + x.what).toLowerCase())}" title="Click to copy"><code>${esc(x.cmd)}</code><span class="grow">${esc(x.what)}</span></li>`).join("")}</ul></div></div>`).join("")}`, "click one to copy it")}
    ${section("Questions", `<div class="box pad">
      ${qa("Which command should I use?", "Type <code>/lfg:which</code> and describe your situation; it picks one for you. For a guided first run, use <code>/lfg:wizard</code>.")}
      ${qa("Where does my work go?", "Everything stays on this computer: LFG keeps its notes in <code>~/.lfg</code> and changes files only in your project. It never commits, pushes, merges or deploys.")}
      ${qa("How much does it cost?", `<a href="#usage">Usage</a> shows what Claude Code spent, by day, model and project, and what Headroom saved.`)}
      ${qa("Can I hide pages I don't use?", `Yes: <a href="#onboarding">choose which pages you see</a>.`)}
      ${qa("How do I get updates?", `The bottom of the sidebar shows your LFG version and tells you when a new one is out; <a href="#settings">Settings</a> can check now.`)}</div>`)}`;
};
function wireHelp(root) {
  const f = $("#hp-find", root);
  if (f) f.oninput = () => { const q = f.value.trim().toLowerCase(); $$(".hp-sk", root).forEach(li => { li.hidden = !!q && !q.split(/\s+/).every(w => li.dataset.find.includes(w)); }); $$(".hp-grp", root).forEach(g => { g.hidden = !$$(".hp-sk", g).some(li => !li.hidden); }); };
  $$("[data-copy-cmd]", root).forEach(li => li.onclick = async () => { await navigator.clipboard.writeText(li.dataset.copyCmd + " "); const c = $("code", li), t = c.textContent; c.textContent = "Copied"; setTimeout(() => { c.textContent = t; }, 1000); });
}

// ------------------------------------------------------------------ shell
const NAV_GROUPS = [["Your work", ["todos", "runs", "issues", "review", "checks"]], ["This project", ["code", "insights", "docs", "knowledge"]], ["LFG", ["usage", "skills", "integrations", "settings", "help"]]];
/* 24px line icons, drawn for these pages (stroke = currentColor) */
const ICON = {
  home: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  runs: "M5 4l14 8-14 8z",
  todos: "M4 6.5l1.5 1.5L8 5.5M4 12.5l1.5 1.5L8 11.5M4 18.5l1.5 1.5L8 17.5M11 7h9M11 13h9M11 19h9",
  sessions: "M4 5h16v14H4zM7.5 10l2.5 2-2.5 2M12 15h4",
  issues: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  checks: "M12 3l8 3v6c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V6zM9 12l2 2 4-4",
  review: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14",
  docs: "M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h6",
  plus: "M12 5v14M5 12h14",
  insights: "M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.6.5 1 1.2 1.1 2h5c.1-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z",
  stack: "M12 3l9 4.5-9 4.5-9-4.5zM3 12l9 4.5 9-4.5M3 16.5l9 4.5 9-4.5",
  chev: "M6 9l6 6 6-6",
  folder: "M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2h8.5A1.5 1.5 0 0 1 21 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  knowledge: "M4 5.5C6.5 4 9.5 4 12 6c2.5-2 5.5-2 8-.5V19c-2.5-1.5-5.5-1.5-8 .5-2.5-2-5.5-2-8-.5zM12 6v13.5",
  usage: "M4 20V10M10 20V4M16 20v-6M2 20h20",
  skills: "M13 2 4 14h7l-1 8 9-12h-7z",
  integrations: "M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  compress: "M4 9h16M4 15h16M10 4l2 3 2-3M10 20l2-3 2 3",
  mic: "M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01",
  lock: "M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4",
  box: "M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10",
  branch: "M6 3v12M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
  "chevron-down": "M6 9l6 6 6-6",
  "chevron-up": "M6 15l6-6 6 6",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.3M12 17h.01",
  panel: "M4 4h16v16H4zM9.5 4v16",
  clip: "M20.5 11.5l-8.3 8.3a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  rewind: "M3 12a9 9 0 1 0 2.6-6.4M3 4v5h5",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  download: "M12 4v11M7 10l5 5 5-5M5 20h14",
  terminal: "M4 5h16v14H4zM7.5 10l2.5 2-2.5 2M12 15h4",
};
const icon = (k, cls = "ico") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON[k] || ""}"/></svg>`;
function renderNav(active) {
  // Filter nav groups by visible pages from onboarding; always include active page
  const visible = new Set(state.pages || NAV.map(p => p[0]));
  visible.add(active);  // always show the active page even if hidden
  $("#nav").innerHTML = navSessions(active) + NAV_GROUPS.map(([g, ks]) => {
    const shown = ks.filter(k => visible.has(k));
    return shown.length ? `<div class="nav-grp">${esc(g)}</div>${shown.map(k => `<a class="${k === active ? "on" : ""}" href="#${k}" title="${esc(TITLES[k])}"${k === active ? ' aria-current="page"' : ""}>${icon(k)}<span>${esc(TITLES[k])}</span></a>`).join("")}` : "";
  }).filter(Boolean).join("");
}
/* The Sessions accordion at the top of the sidebar: new session, the ones live here (and whether they need you),
   your recent ones, and the full list. Open or closed is remembered. */
function navSessions(active) {
  const open = localStorage.getItem("lfg.nav.sessions") !== "0";
  const list = (state.navSess || []).filter(x => x.source !== "background");
  const cur = active === "sessions" ? (location.hash.split("/")[1] || "") : "";  // "" = new, "all" = the list
  const live = list.filter(x => ssLive(x.state)).slice(0, 5), recent = list.filter(x => !ssLive(x.state)).slice(0, Math.max(0, 5 - live.length));
  const dot = st => st === "needs-you" ? '<span class="ns-dot warn" title="Needs you"></span>' : ssLive(st) ? `<span class="ns-dot${st === "idle" ? "" : " on"}" title="${st === "idle" ? "Waiting for you" : "Working"}"></span>` : "";
  const when = t => { const m = (Date.now() - new Date(t || 0)) / 6e4; return m < 60 ? `${Math.max(1, Math.round(m))}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`; };
  const row = x => `<a class="ns-item${x.id === cur ? " on" : ""}" href="#sessions/${esc(x.id)}" title="${esc(x.title)}">${dot(x.state)}<span class="ns-t">${esc(x.title)}</span><span class="ns-w">${ssLive(x.state) ? "" : when(x.updated)}</span></a>`;
  return `<div class="ns${open ? " open" : ""}"><div class="ns-head"><a class="${active === "sessions" && !cur ? "on" : ""}" href="#sessions" title="Studio: Claude Code sessions, here">${icon("sessions")}<span>Studio</span>${live.length ? `<span class="ns-n${live.some(x => x.state === "needs-you") ? " warn" : ""}">${live.length}</span>` : ""}</a>
    <button class="ns-btn" data-ns-new title="New session" aria-label="New session">+</button><button class="ns-btn ns-tog" data-ns-toggle aria-expanded="${open}" aria-label="Show Studio sessions">${icon("chev")}</button></div>
    <div class="ns-body">${live.map(row).join("")}${recent.map(row).join("")}${list.length ? `<a class="ns-all${cur === "all" ? " on" : ""}" href="#sessions/all">All sessions</a>` : '<span class="ns-empty">No sessions yet</span>'}</div></div>`;
}
async function loadNavSessions() {
  if (!state.repo) return;
  try { const d = await api("sessions"); state.navSess = d.sessions || []; } catch (e) { return; }
  if (state.linearWs === undefined) { try { state.linearWs = ((await api("todos")).linear || {}).workspace || ""; } catch (e) { state.linearWs = ""; } }
  renderNav((location.hash.slice(1) || "home").split("/")[0]);
}
/* the sidebar folds to an icon rail (the button left of the breadcrumb, or Cmd/Ctrl+\\); remembered */
function setRail(on) {
  document.body.classList.toggle("rail", on); localStorage.setItem("lfg.side", on ? "rail" : "");
  const b = $("#side-tog"); if (b) { b.setAttribute("aria-label", on ? "Expand sidebar" : "Collapse sidebar"); b.title = `${on ? "Expand" : "Collapse"} sidebar (${/Mac/.test(navigator.platform) ? "⌘" : "Ctrl+"}\\)`; b.setAttribute("aria-expanded", String(!on)); }
}
setRail(localStorage.getItem("lfg.side") === "rail");
document.addEventListener("click", e => { if (e.target.closest("#side-tog")) setRail(!document.body.classList.contains("rail")); });
document.addEventListener("keydown", e => { if (e.key === "\\" && (e.metaKey || e.ctrlKey) && !e.altKey) { e.preventDefault(); setRail(!document.body.classList.contains("rail")); } });
document.addEventListener("click", e => { if (e.target.closest("[data-stop]")) e.stopPropagation(); }, true);  // a link in a clickable row opens only itself
document.addEventListener("click", e => {
  const t = e.target.closest("[data-ns-toggle], [data-ns-new]");
  if (!t) return;
  e.preventDefault();
  if (t.hasAttribute("data-ns-new")) { state.ssFresh = true; if (location.hash === "#sessions") route(); else location.hash = "#sessions"; return; }
  const box = t.closest(".ns"), open = !box.classList.contains("open");
  box.classList.toggle("open", open); t.setAttribute("aria-expanded", open); localStorage.setItem("lfg.nav.sessions", open ? "1" : "0");
});
function applyPages(d) {
  state.pages = d.pages || NAV.map(p => p[0]);
  const current = (location.hash.slice(1) || "home").split("/")[0];
  renderNav(current);
}
/* Breadcrumb in the top bar: project / page / item. Pages that open an item call crumbs() again with it. */
function crumbs(page, item, itemHref) {
  const parts = [`<span class="crumb-proj">${esc(repoName() || "LFG")}</span>`, `<a href="#${page}">${icon(page)}${esc(TITLES[page] || page)}</a>`];
  if (item) parts.push(itemHref ? `<a href="${itemHref}">${esc(item)}</a>` : `<span>${esc(item)}</span>`);
  $("#crumbs").innerHTML = parts.join('<span class="sep">/</span>');
}
/* code map: build/update from the dashboard (the same background job the hooks start) */
const mapBtn = (st, cls = "btn small") => st === "syncing" ? "" : st === "missing" ? `<button class="${cls} primary" data-map-build="update">Build now</button>`
  : st === "fresh" ? `<button class="${cls}" data-map-build="update" title="Re-check the code for changes">Refresh</button>` : `<button class="${cls}" data-map-build="update">Update now</button>`;
let mapTimer = null, mapWatching = false;
async function buildMap(what, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Starting…"; }
  const r = await save("graphs_build", { repo: state.repo, what });
  if (!r.ok) { if (btn) { btn.disabled = false; btn.textContent = "Try again"; btn.title = r.why || ""; } alert(r.why || "Couldn't start it."); return; }
  if (what === "docs") { if (btn) btn.textContent = "Started: docs update in the background"; return; }
  mapWatching = true;
  setTimeout(mapStatus, 1500);
}
function wireMap(root) {
  $$("[data-map-build]", root).forEach(b => b.onclick = e => {
    e.preventDefault();
    if (b.dataset.mapBuild === "rebuild" && !confirm("Rebuild the code map from scratch? It runs in the background and can take a few minutes on a big project.")) return;
    buildMap(b.dataset.mapBuild, b);
  });
}
async function mapStatus() {
  const el = $("#map-status");
  clearTimeout(mapTimer);
  if (!state.repo) { el.innerHTML = ""; return; }
  try {
    const g = await api("graphs");
    const [text, t] = say(g.status);
    el.innerHTML = `<span class="map-line">${dot(t)}<span class="label">Code map: ${esc((text || "unknown").toLowerCase())}</span></span>${mapBtn(g.status, "btn tiny")}`;
    el.title = `Code map: ${(text || "unknown").toLowerCase()}. Agents read this map instead of whole files.`;
    wireMap(el);
    if (g.status === "syncing") { mapWatching = true; mapTimer = setTimeout(mapStatus, 4000); }
    else if (mapWatching) {
      mapWatching = false;
      if ((location.hash.slice(1) || "").split("/")[0] === "code") { state.cache = {}; route(); }
    }
  } catch (e) { el.innerHTML = ""; }
}
let renderSeq = 0;
/* Re-draw the current page in place: no loading placeholder, same scroll position, open sections stay open. For
   controls that change one thing on the page (the Usage range); route() is for going to a page. */
function softRoute() { return route({ soft: true }); }
async function route(opts) {
  const soft = !!(opts && opts.soft);
  let [page, ...rest] = (location.hash.slice(1) || "lfg").split("/");
  page = { home: "sessions", overview: "sessions", reviews: "checks", security: "checks", architecture: "code", health: "code", brain: "knowledge", tools: "settings" }[page] || page;
  const key = PAGES[page] ? page : "sessions";
  document.body.classList.toggle("bare", BARE.includes(key));
  wireTourButton(key);
  const arg = rest.join("/");
  renderNav(key);
  crumbs(key);
  document.title = `${TITLES[key]} · LFG`;
  const seq = ++renderSeq, view = $("#view"), y = window.scrollY;
  view.classList.toggle("wide", (key === "review" && !!arg) || key === "sessions");
  view.classList.toggle("studio", key === "sessions");
  $("#update-banner").hidden = key === "help";  // Help has no update banner; the sidebar shows the version  // fills the window; its own parts scroll
  view.classList.toggle("welcome", key === "onboarding");  // the review screens are two panes: use the width
  const open = soft ? $$("details[open]", view).map((d, i) => d.id || "i" + i) : [];
  if (!soft) view.innerHTML = '<div class="skeleton" style="height:60px;width:40%"></div><div class="skeleton mt"></div><div class="skeleton mt" style="height:220px"></div>';
  let html;
  try { html = await PAGES[key](decodeURIComponent(arg)); } catch (e) { html = unavailable({ why: "Couldn't load this page: " + e.message }); }
  if (seq !== renderSeq) return;
  view.innerHTML = html;
  mountTables(view); mountTabs(view); wire(view);
  $$("[data-href]", view).forEach(li => li.onclick = () => (location.hash = li.dataset.href));
  if (key === "onboarding") drawJourney(view);
  if (state.gh && state.gh.starred) $$("[data-gh-star]", view).forEach(b => (b.textContent = "★ Starred, thank you"));
  if (state.pendingTour && state.pendingTour.startsWith("page-")) { const t = state.pendingTour; state.pendingTour = null; setTimeout(() => startTour(t), 400); }
  if (key === "insights") wireInsights(view);
  if (key === "knowledge") wireKnowledgeAdd(view);
  if (key === "docs") wireDocs();
  if (key === "review") wireReview(view);
  if (key === "todos") wireTodos(view);
  if (key === "lfg") wireLanding(view);
  if (key === "help") wireHelp(view);
  if (key === "sessions") wireSessions(view);
  if (key === "runs" && !arg) wireRuns(view);
  if (key === "checks") { $$('[data-tabs="checks"] .tab', view).forEach(t => t.addEventListener("click", () => setTimeout(() => wireSonar(view), 0))); wireSonar(view); }
  if (key === "usage") { wireUsage(view); loadHeadroom(); }
  if (soft) {
    $$("details", view).forEach((d, i) => { if (open.includes(d.id || "i" + i)) d.open = true; });
    window.scrollTo(0, y);
  } else if (!arg) window.scrollTo(0, 0);
}
function wireDocs() {
  const body = $("#doc-body");
  wireDocEditor(body);
  $$("[data-doclink]", body).forEach(a => a.onclick = e => {
    e.preventDefault();
    const base = body.dataset.path.split("/").slice(0, -1);
    const target = a.dataset.doclink.split("#")[0];
    const parts = [...base];
    for (const p of target.split("/")) { if (p === "..") parts.pop(); else if (p && p !== ".") parts.push(p); }
    location.hash = `#docs/${body.dataset.src}/${encodeURIComponent(parts.join("/"))}`;
  });
  const f = $("#doc-filter");
  if (f) f.oninput = () => {
    const q = f.value.toLowerCase();
    $$(".doc-nav a").forEach(a => (a.style.display = !q || a.textContent.toLowerCase().includes(q) ? "" : "none"));
    $$(".doc-folder").forEach(dt => {
      const hit = $$("a", dt).some(a => a.style.display !== "none") || dt.querySelector("summary").textContent.toLowerCase().includes(q);
      dt.style.display = !q || hit ? "" : "none";
      if (q && hit) { dt.dataset.wasOpen ??= dt.open ? "1" : ""; dt.open = true; } else if (!q && "wasOpen" in dt.dataset) { dt.open = !!dt.dataset.wasOpen; delete dt.dataset.wasOpen; }
    });
  };
  const on = $(".doc-nav a.on");
  if (on) on.scrollIntoView({ block: "nearest" });
}
/* Sessions: Claude Code, run from here. Every session for the project, wherever it was started (here, a terminal,
   the desktop app, LFG's own background runs), read from Claude Code's own transcripts; any of them can be continued
   here. A live session shows what Claude does as readable cards, and asks for your OK with buttons. */
const SS_SRC = { lfg: ["LFG", "on"], terminal: ["Terminal", ""], desktop: ["Desktop app", ""], background: ["Background", "faded"] };
const SS_STATE = { "needs-you": ["Needs you", "warn"], working: ["Working", "ok"], starting: ["Starting", "ok"], idle: ["Waiting for you", "on"], ended: ["Ended", ""], saved: ["", ""] };
const SS_MODES = [["default", "Ask first", "Asks before edits and commands"], ["acceptEdits", "Accept edits", "Edits files, asks before commands"], ["plan", "Plan only", "Reads and plans, changes nothing"]];
const ssLive = st => ["working", "needs-you", "starting", "idle"].includes(st);
const money = v => v == null ? "" : v < 0.01 ? "<$0.01" : usd(v);
let ssPoll = null;

PAGES.sessions = async arg => {
  if (arg === "all") {  // every session for the project, and the worktrees they work in
    const [list, where] = await Promise.all([api("sessions"), api("session_where")]);
    state.sess = { list, d: null, id: null, where };
    state.navSess = list.sessions || [];
    crumbs("sessions", "All sessions", "#sessions/all");
    return `<div class="ss-page">${ssWorktrees(where)}${ssAll(list)}</div>`;
  }
  if (!arg) {  // a new session: the same screen as any session, empty, with the composer at the bottom
    const [sug, where] = await Promise.all([api("session_suggest"), api("session_where")]);
    state.sess = { d: null, id: null, sug, where };
    crumbs("sessions", "New session", "#sessions");
    return `<div class="ss-one">${ssNew(sug)}</div>`;
  }
  const d = await api("session", { id: arg });
  state.sess = { d, id: arg };
  crumbs("sessions", d && d.available !== false ? d.title : null, `#sessions/${arg}`);
  return d.available === false ? unavailable(d) : `<div class="ss-one">${ssDetail(d)}</div>`;
};

/* tags: one look tells you what a session is about and where it stands */
function ssTagList(x, full) {  // full: the session's own header, where tags can be links (a row is already one)
  const out = [], link = (cls, href, text, title) => full && href ? `<a class="tg ${cls}" href="${esc(href)}" target="_blank" rel="noopener noreferrer"${title ? ` title="${esc(title)}"` : ""}>${text}</a>` : `<span class="tg ${cls}"${title ? ` title="${esc(title)}"` : ""}>${text}</span>`;
  const [st, tone] = SS_STATE[x.state] || ["", ""]; if (st) out.push(`<span class="tg ${tone}">${st}</span>`);
  if (x.pr) out.push(link(x.pr.state === "MERGED" ? "merged" : x.pr.state === "CLOSED" ? "bad" : "on", x.pr.url, `PR #${x.pr.number}${x.pr.state === "MERGED" ? " · merged" : x.pr.state === "CLOSED" ? " · closed" : ""}`, "Pull request for this branch"));
  (x.issues || []).forEach(k => out.push(link("", state.linearWs ? `https://linear.app/${state.linearWs}/issue/${k}` : "", esc(k), "Linear issue")));
  if (x.branch && x.branch !== "HEAD") out.push(`<span class="brtag" title="Branch">${esc(x.branch)}</span>`);
  (x.skills || []).slice(0, full ? 6 : 2).forEach(k => out.push(`<span class="tg sk">/${esc(k.replace(/^\//, ""))}</span>`));
  const files = Array.isArray(x.files) ? x.files.length : x.files;
  if (files) out.push(`<span class="tg" title="${Array.isArray(x.files) ? esc(x.files.join("\n")) : "Files Claude changed"}">${plural(files, "file")} changed</span>`);
  if (x.worktree_name) out.push(`<span class="tg wt" title="Works in this worktree">${icon("folder")}${esc(x.worktree_name)}</span>`);
  const [src, stone] = SS_SRC[x.source] || ["", ""]; if (src) out.push(`<span class="tg ${stone}">${src}</span>`);
  return out.join("");
}

function ssNew(sug) {
  const list = (sug && sug.suggestions || []).slice(0, 4);
  return `<header class="ss-head"><div class="grow"><h1 class="ss-title">New session</h1>
      <div class="ss-tags"><span class="tg">${esc(repoName())}</span><span class="brtag" id="ss-branch" title="The branch Claude will work on"></span><span class="tg wt" id="ss-wt-tag" hidden></span></div></div></header>
    <div class="ss-conv ss-empty">${list.length ? `<div class="ss-quick"><span class="muted small">Suggestions</span>${list.map((x, i) => `<button class="chip ss-sug ${x.tone || ""}" data-sug="${i}" title="${esc(x.title)}"><span class="ss-sug-k">${esc(x.skill)}</span>${esc(x.title.length > 56 ? x.title.slice(0, 54) + "…" : x.title)}</button>`).join("")}</div>` : ""}</div>
    ${ssComposer({ isNew: true })}`;
}

function ssAll(list) {
  const f = state.ssFilter || "mine", all = list.sessions || [];
  const pick = all.filter(s => f === "all" || (f === "background" ? s.source === "background" : s.source !== "background"));
  const day = t => { const d = (Date.now() - new Date(t || 0)) / 864e5; return d < 1 ? "Today" : d < 7 ? "This week" : d < 31 ? "This month" : "Earlier"; };
  const groups = {}; pick.forEach(s => (groups[ssLive(s.state) ? "Live here" : day(s.updated)] = groups[ssLive(s.state) ? "Live here" : day(s.updated)] || []).push(s));
  const row = s => `<a class="ss-row" href="#sessions/${esc(s.id)}" data-title="${esc((s.title + " " + (s.branch || "") + " " + (s.skills || []).join(" ") + " " + (s.issues || []).join(" ")).toLowerCase())}">
      <span class="grow"><span class="ss-row-t">${esc(s.title)}</span><span class="ss-tags">${ssTagList(s)}</span></span>
      <span class="ss-row-m"><span>${ago(s.updated)}</span>${s.cost ? `<span class="ss-row-c">${money(s.cost)}</span>` : ""}</span></a>`;
  const chip = (k, l, n) => `<button class="pill${f === k ? " on" : ""}" data-ss-filter="${k}">${l} <span class="muted">${n}</span></button>`;
  return `<section class="ss-allbox"><div class="ss-all-h"><h1>All sessions</h1><a class="btn primary small" href="#sessions" data-ss-newbtn>New session</a><input type="search" id="ss-find" placeholder="Search by title, branch, skill or issue" autocomplete="off">
      <span class="seg">${chip("mine", "Yours", all.filter(s => s.source !== "background").length)}${chip("background", "Background", all.filter(s => s.source === "background").length)}${chip("all", "All", all.length)}</span></div>
    <div class="ss-scrollarea">${["Live here", "Today", "This week", "This month", "Earlier"].filter(g => groups[g]).map(g => `<div class="ss-grp">${g}</div><div class="box ss-list">${groups[g].map(row).join("")}</div>`).join("") || empty("No sessions yet", "Start one from New session. Sessions from your terminal and the desktop app show up here too.")}</div></section>`;
}

function ssComposer(o) {
  const mode = o.mode || localStorage.getItem("lfg.ss.mode") || "default";
  const seg = (name, opts, cur) => `<span class="seg" role="radiogroup" data-seg="${name}">${opts.map(([k, l, tip]) => `<button type="button" role="radio" aria-checked="${k === cur}" class="pill${k === cur ? " on" : ""}" data-v="${k}" title="${esc(tip)}">${l}</button>`).join("")}</span>`;
  const fork = o.fork ? `<div class="ss-forking">${icon("branch")}<span class="grow">New session from ${o.fork.at ? `before <b>“${esc(o.fork.label)}”</b>` : "this whole conversation"}. This one stays as it is.</span><button class="btn small" data-fork-x>Cancel</button></div>` : "";
  return `<div class="ss-comp" id="ss-comp">
    <div class="ss-ac" id="ss-ac" hidden></div>${fork}
    <div class="ss-att" id="ss-att" hidden></div>
    <textarea id="ss-text" rows="1" placeholder="${o.fork ? "What should the new session do?" : o.isNew ? "Describe the task. / for skills, @ for files and folders" : o.saved ? "Write to continue this session here" : "Reply to Claude. / for skills, @ for files"}"></textarea>
    <div class="ss-comp-b"><button type="button" class="icon-btn ss-clip" id="ss-attach" title="Attach files or images. You can also drop them here or paste a screenshot.">${icon("clip")}</button><input type="file" id="ss-file" multiple hidden>
      ${o.isNew ? ssWherePicker() : ""}${o.isNew || o.live ? seg("mode", SS_MODES, mode) : ""}
      <span class="grow"></span><button class="btn primary small" id="ss-send">${o.fork ? "Start fork" : o.isNew ? "Start" : o.saved ? "Continue here" : "Send"}</button></div></div>`;
}

/* Where a new session works: this checkout, a worktree, an existing branch in a worktree of its own, or a new
   worktree forked from a branch. The dashboard's branch picker chooses the default. */
function ssWherePicker() {
  const w = state.sess.where || {}, cur = w.branch || "", picked = state.branch && state.branch !== "-" ? state.branch : "";
  const wts = (w.worktrees || []).filter(x => x.kind === "lfg" || x.kind === "yours");
  const opts = [["here", `Here · ${cur}`]];
  wts.forEach(x => opts.push([`wt:${x.path}`, `Worktree · ${x.branch || x.name}`]));
  if (picked && picked !== cur && !wts.some(x => x.branch === picked)) opts.push([`br:${picked}`, `New worktree · ${picked}`]);
  opts.push(["new", "New worktree, new branch…"]);
  const pw = wts.find(x => x.branch === picked), def = picked && picked !== cur ? (pw ? `wt:${pw.path}` : `br:${picked}`) : "here";
  const branches = (w.branches || []).slice().sort((a, b) => (b === cur) - (a === cur) || (b === w.default) - (a === w.default) || a.localeCompare(b));
  return `<select id="ss-where" class="ss-sel" aria-label="Where Claude works" title="Where Claude works: this checkout, a worktree, or a new one">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === def ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
    <span class="ss-newwt" hidden><input type="text" id="ss-wt-name" placeholder="lfg/short-name" autocomplete="off" aria-label="New branch name"><select id="ss-wt-base" class="ss-sel" aria-label="Fork it from" title="Fork it from">${branches.map(b => `<option value="${esc(b)}"${b === (picked || cur) ? " selected" : ""}>from ${esc(b)}</option>`).join("")}</select></span>`;
}
/* the branch the new session will work on, as the picker and the sidebar's branch say */
function ssTarget(root) {
  const w = state.sess.where || {}, v = ($("#ss-where", root) || {}).value || "here";
  if (v === "here") return [w.branch || "", ""];
  if (v.startsWith("wt:")) { const x = (w.worktrees || []).find(t => t.path === v.slice(3)); return [x ? x.branch : "", x ? `worktree ${x.name}` : "worktree"]; }
  if (v.startsWith("br:")) return [v.slice(3), "new worktree"];
  const n = ($("#ss-wt-name", root) || {}).value || "";
  return [n.trim() || "new branch", `new worktree, from ${($("#ss-wt-base", root) || {}).value || ""}`];
}
function ssWhereValue(root) {
  const v = ($("#ss-where", root) || {}).value || "here";
  if (v === "here") return { kind: "here" };
  if (v.startsWith("wt:")) return { kind: "worktree", path: v.slice(3) };
  if (v.startsWith("br:")) return { kind: "branch", branch: v.slice(3) };
  return { kind: "new", branch: $("#ss-wt-name", root).value.trim(), base: $("#ss-wt-base", root).value };
}

/* Worktrees: where each stands against the branch it was forked from, and merging it back (committed work only) */
function ssWorktrees(w) {
  const rows = (w && w.worktrees || []).filter(x => x.kind === "lfg" || x.kind === "yours");
  if (!rows.length) return "";
  const byBase = {}; rows.forEach(x => { if (x.base) (byBase[x.base] = byBase[x.base] || []).push(x); });
  const row = x => {
    const can = !x.dirty && x.ahead > 0, why = x.dirty ? `${plural(x.dirty, "uncommitted change")}: commit them in the worktree first` : !x.ahead ? `Nothing to merge into ${x.base}` : `Merge ${plural(x.ahead, "commit")} into ${x.base}`;
    return `<div class="wt-row" data-wt="${esc(x.name)}"><span class="wt-ic">${icon("folder")}</span><span class="grow"><span class="wt-t"><b>${esc(x.name)}</b>${x.kind === "lfg" ? '<span class="tg on">LFG</span>' : '<span class="tg">yours</span>'}</span>
      <span class="ss-tags"><span class="brtag">${esc(x.branch || "detached")}</span>${x.base ? `<span class="muted small">→ ${esc(x.base)}</span>` : ""}${x.ahead ? `<span class="tg ok">${x.ahead} ahead</span>` : ""}${x.behind ? `<span class="tg">${x.behind} behind</span>` : ""}${x.dirty ? `<span class="tg warn">${x.dirty} uncommitted</span>` : ""}${x.sessions ? `<span class="tg">${plural(x.sessions, "session")}</span>` : ""}</span></span>
      <span class="wt-a"><button class="btn small" data-wt-session="${esc(x.path)}">New session here</button>${x.base ? `<button class="btn small" data-wt-merge${can ? "" : " disabled"} title="${esc(why)}">Merge into ${esc(x.base)}</button>` : ""}${x.kind === "lfg" && x.base ? `<button class="btn small" data-wt-merge data-remove${can || (!x.dirty && !x.ahead) ? "" : " disabled"} title="${esc(can ? `Merge into ${x.base}, then remove the worktree and its branch` : !x.dirty ? "Nothing to merge: remove the worktree and its branch" : why)}">${can ? "Merge and remove" : "Remove"}</button>` : ""}</span></div>`;
  };
  const bulk = Object.entries(byBase).filter(([, xs]) => xs.filter(x => x.kind === "lfg").length > 1).map(([b, xs]) => `<div class="wt-bulk"><span class="grow">${plural(xs.filter(x => x.kind === "lfg").length, "LFG worktree")} forked from <b>${esc(b)}</b>. Merge them all back and remove them, here or in a terminal: <code>lfg worktree merge --all --into ${esc(b)} --remove</code></span><button class="btn small" data-wt-all="${esc(b)}">Merge all into ${esc(b)}</button></div>`).join("");
  return `<section class="wt-box"><div class="ss-all-h"><h1>Worktrees</h1><span class="muted small">Branches checked out in their own folders. Only committed work is merged; LFG never commits for you.</span></div>
    <div class="wt-scroll"><div class="box wt-list">${rows.map(row).join("")}</div>${bulk}</div></section>`;
}

/* tools as one readable line each; the input and output open on click */
const TOOL_ICON = { Bash: "code", Read: "docs", Edit: "docs", MultiEdit: "docs", Write: "docs", Grep: "code", Glob: "code", Skill: "skills", Agent: "runs", Task: "runs", WebFetch: "issues", WebSearch: "issues", TodoWrite: "todos", AskUserQuestion: "review" };
const base = p => String(p || "").split("/").pop();
const mcpName = n => { const [, srv, tool] = String(n).split("__"); return [String(srv || "").replace(/^plugin_[^_]+_/, ""), String(tool || "").replace(/_tool$/, "").replace(/_/g, " ")]; };
function toolLine(t) {
  const i = t.input || {}, n = t.name || "?";
  if (n === "Bash") return [`Ran`, `<code>${esc(String(i.command || "").split("\n")[0].slice(0, 140))}</code>`, i.description];
  if (n === "Read") return ["Read", `<code>${esc(base(i.file_path))}</code>`, i.offset ? `from line ${i.offset}` : ""];
  if (n === "Edit" || n === "MultiEdit") return ["Edited", `<code>${esc(base(i.file_path))}</code>`, ""];
  if (n === "Write") return ["Wrote", `<code>${esc(base(i.file_path))}</code>`, `${String(i.content || "").split("\n").length} lines`];
  if (n === "Grep") return ["Searched for", `<code>${esc(i.pattern || "")}</code>`, i.path ? `in ${base(i.path)}` : ""];
  if (n === "Glob") return ["Listed", `<code>${esc(i.pattern || "")}</code>`, ""];
  if (n === "Skill") return ["Used skill", `<b>${esc(i.skill || i.name || "")}</b>`, ""];
  if (n === "Agent" || n === "Task") return ["Sent a subagent", esc(i.description || i.subagent_type || ""), ""];
  if (n === "WebFetch") return ["Fetched", `<code>${esc(i.url || "")}</code>`, ""];
  if (n === "WebSearch") return ["Searched the web for", esc(i.query || ""), ""];
  if (n === "TodoWrite") return ["Updated its to-do list", "", `${(i.todos || []).length} items`];
  if (/^mcp__/.test(n)) { const [srv, tool] = mcpName(n); return ["Asked", `<b>${esc(srv)}</b>: ${esc(tool)}`, ""]; }
  return [esc(n), "", ""];
}
function toolBody(t) {
  const i = t.input || {};
  let inp = "";
  if ((t.name === "Edit" || t.name === "MultiEdit") && (i.old_string != null || i.edits)) {
    const edits = i.edits || [{ old_string: i.old_string, new_string: i.new_string }];
    inp = `<div class="muted small">${esc(i.file_path || "")}</div>` + edits.slice(0, 4).map(e => `<div class="ss-diff">${String(e.old_string || "").split("\n").slice(0, 12).map(l => `<div class="d-del">- ${esc(l)}</div>`).join("")}${String(e.new_string || "").split("\n").slice(0, 12).map(l => `<div class="d-add">+ ${esc(l)}</div>`).join("")}</div>`).join("");
  } else if (t.name === "Bash") inp = `<pre class="ss-pre">$ ${esc(i.command || "")}</pre>`;
  else if (Object.keys(i).length) inp = `<pre class="ss-pre">${esc(JSON.stringify(i, null, 2).slice(0, 4000))}</pre>`;
  const out = t.result != null && t.result !== "" ? `<pre class="ss-pre${t.error ? " bad" : ""}">${esc(String(t.result).slice(0, 6000))}${String(t.result).length > 6000 ? "\n…" : ""}</pre>` : "";
  return inp + out;
}
function ssItems(items, live) {
  let html = "", group = [];
  const flush = last => {
    if (!group.length) return;
    const names = {}; group.forEach(t => { const k = /^mcp__/.test(t.name) ? mcpName(t.name)[0] : t.name; names[k] = (names[k] || 0) + 1; });
    const running = live && last && group.some(t => t.result == null);
    const one = t => { const [verb, what, note] = toolLine(t); return `<details class="ss-tool${t.error ? " bad" : ""}"><summary>${icon(TOOL_ICON[t.name] || (/^mcp__/.test(t.name) ? "integrations" : "code"))}<span class="grow"><span class="ss-verb">${verb}</span> ${what}${note ? ` <span class="muted small">${esc(note)}</span>` : ""}</span>${t.result == null ? (running ? '<span class="spin"></span>' : "") : t.error ? '<span class="tg bad">error</span>' : ""}</summary><div class="ss-tool-b">${toolBody(t)}</div></details>`; };
    html += group.length <= 3 ? `<div class="ss-tools">${group.map(one).join("")}</div>`
      : `<details class="ss-steps"${running ? " open" : ""}><summary><span class="grow">${plural(group.length, "step")} · ${Object.entries(names).map(([k, v]) => `${esc(k)}${v > 1 ? ` ×${v}` : ""}`).join(", ")}</span>${running ? '<span class="spin"></span>' : ""}</summary><div class="ss-tools">${group.map(one).join("")}</div></details>`;
    group = [];
  };
  items.forEach((it, i) => {
    if (it.k === "tool") { group.push(it); return; }
    flush(false);
    if (it.k === "me") html += `<div class="ss-me" data-i="${i}">${(it.images || []).length ? `<div class="ss-imgs">${it.images.map(m => `<button class="ss-img" data-img="${esc(m.u)}:${m.i}" title="Show larger"></button>`).join("")}</div>` : ""}${ssMeText(it) ? `<div class="ss-bub">${ssMeText(it)}</div>` : ""}${ssMsgActions(it, i)}</div>`;
    else if (it.k === "skill") html += `<div class="ss-me" data-i="${i}"><div class="ss-bub skill">${icon("skills")}/${esc(it.name.replace(/^\//, ""))}${it.args ? ` <span>${esc(it.args)}</span>` : ""}</div>${ssMsgActions(it, i)}</div>`;
    else if (it.k === "ai") html += `<div class="ss-ai" data-i="${i}"><span class="ss-ai-av">${icon("sessions")}</span><div class="md">${md(it.text)}</div><div class="ss-msg-a"><button class="ss-ma" data-ss-copy="${i}" title="Copy this answer">${icon("copy")}Copy</button></div></div>`;
    else if (it.k === "note") html += `<div class="ss-note">${esc(it.text)}</div>`;
  });
  flush(true);
  return html;
}
/* what you sent: uploaded files show as chips, the [Image #n] markers as the images themselves */
function ssMeText(it) {
  let t = esc(it.text || "");
  if ((it.images || []).length) t = t.replace(/\[Image #\d+\]\s?/g, "");
  t = t.replace(/@(\/\S*?\/\.lfg\/uploads\/\d{8}\/[0-9a-f]{8}-(\S+))/g, (_m, path, name) => `<span class="ss-file" title="${path}">${icon("docs")}${name}</span>`);
  return t.trim();
}
/* each of your messages: Rewind to before it, Fork from before it (a new session), Copy (as in Claude Code) */
function ssMsgActions(it, i) {
  const rw = it.u ? `<button class="ss-ma" data-rw="${esc(it.u)}" title="Undo the conversation from here, the code Claude changed since, or both">${icon("rewind")}Rewind</button>` : "";
  const fk = it.u && it.p ? `<button class="ss-ma" data-fork="${i}" title="A new session with the conversation up to here; this one stays as it is">${icon("branch")}Fork</button>` : "";
  return `<div class="ss-msg-a">${rw}${fk}<button class="ss-ma" data-ss-copy="${i}" title="Copy">${icon("copy")}Copy</button></div>`;
}
const ssItemText = it => it.k === "skill" ? `/${it.name.replace(/^\//, "")}${it.args ? " " + it.args : ""}` : it.k === "tool" ? `${it.name} ${JSON.stringify(it.input || {})}` : (it.text || "").replace(/\[Image #\d+\]\s?/g, "");
function ssMarkdown(d) {  // Export: the conversation as Markdown, like /export
  const out = [`# ${d.title}`, "", [d.branch && `Branch: ${d.branch}`, d.updated && `Updated: ${new Date(d.updated).toLocaleString()}`, `Session: ${d.id}`].filter(Boolean).join(" · "), ""];
  (d.items || []).forEach(it => {
    if (it.k === "me" || it.k === "skill") out.push(`## You`, "", ssItemText(it), "");
    else if (it.k === "ai") out.push(`## Claude`, "", it.text, "");
    else if (it.k === "tool") { const [verb, what] = toolLine(it); out.push(`- ${verb} ${what.replace(/<[^>]+>/g, "")}${it.error ? " (error)" : ""}`); }
    else if (it.k === "note") out.push("", `*${it.text}*`, "");
  });
  return out.join("\n").replace(/\n{3,}/g, "\n\n");
}
function ssDownload(name, text) {
  const a = document.createElement("a"), url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
  a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
async function ssImages(root) {  // images in messages come from the transcript, one request each, kept for the page
  state.ssImg = state.ssImg || {};
  for (const b of $$(".ss-img[data-img]", root)) {
    if (b.firstChild) continue;
    const key = b.dataset.img, [u, i] = key.split(":");
    if (!state.ssImg[key]) { const r = await api("session_image", { id: state.sess.id, u, i }).catch(() => null); if (!r || !r.src) continue; state.ssImg[key] = r.src; }
    const img = new Image(); img.alt = "Image you sent"; img.src = state.ssImg[key]; b.append(img);
  }
}
/* how full the context window is (live sessions; from Claude Code, no API call) */
function ssCtxHtml(c) {
  if (!c || c.percent == null) return "";
  const tip = [`${(c.used || 0).toLocaleString()} of ${(c.max || 0).toLocaleString()} tokens`, ...(c.parts || []).map(p => `${p.name}: ${p.tokens.toLocaleString()}`), c.auto_compact_at ? `Compacts by itself near ${c.auto_compact_at.toLocaleString()}` : "", "Compact it from the ⋯ menu"].filter(Boolean).join("\n");
  return `<span class="ss-ctx${c.percent >= 70 ? " warn" : ""}" title="${esc(tip)}"><i style="--p:${Math.min(100, c.percent)}%"></i>${c.percent}% context</span>`;
}
function ssPending(d) {
  return (d.pending || []).map(p => {
    const t = { name: p.tool, input: p.input }, [verb, what] = toolLine(t), label = /^mcp__/.test(p.tool) ? mcpName(p.tool).join(": ") : p.tool;
    return `<div class="ss-ask" data-req="${esc(p.id)}"><div class="ss-ask-h">${icon("checks")}<span class="grow">Claude wants to <b>${verb.toLowerCase()}</b> ${what}</span></div>
      ${p.description ? `<div class="muted small">${esc(p.description)}</div>` : ""}<div class="ss-tool-b">${toolBody(t)}</div>
      <div class="ss-ask-a"><button class="btn primary small" data-decide="once">Allow once</button>${p.can_remember ? `<button class="btn small" data-decide="always" title="Saved in your Claude Code settings, like choosing it in a terminal">Always allow ${esc(label)}</button>` : ""}<button class="btn small" data-decide="session">Allow for this session</button><button class="btn small bad" data-decide="deny">Deny</button></div></div>`;
  }).join("");
}
function ssFollowups(d) {
  if (d.state !== "idle" || d.pending && d.pending.length) return "";
  const out = [];
  if ((d.files || []).length) { out.push(["/lfg:check", "Check these changes", "/lfg:check the changes from this session"]); out.push(["/lfg:review-coach", "Review the changes", "/lfg:review-coach review the changes from this session"]); }
  if (d.pr && d.pr.state === "OPEN" && (d.files || []).length) out.push(["/lfg:ship", `Get PR #${d.pr.number} ready`, `/lfg:ship PR #${d.pr.number}`]);
  out.push(["", "Summarize what changed", "Summarize what you changed in this session and anything left to do, in a few bullets."]);
  return `<div class="ss-follow"><span class="muted small">Next</span>${out.map(([k, l, p]) => `<button class="chip" data-follow="${esc(p)}">${k ? `<span class="ss-sug-k">${esc(k)}</span>` : ""}${esc(l)}</button>`).join("")}</div>`;
}
function ssConv(d) {
  const live = ssLive(d.state);
  return `${ssItems(d.items || [], live)}${(d.queued || []).map(q => `<div class="ss-me"><div class="ss-bub queued">${esc(q)}<span class="muted small"> · goes in when Claude is ready</span></div></div>`).join("")}
    ${ssPending(d)}${d.state === "working" || d.state === "starting" ? `<div class="ss-working"><span class="ss-pulse"></span> Claude is working… <button class="btn small" data-ss-interrupt>Stop</button></div>` : ""}
    ${d.error ? `<div class="callout bad small">${fmtWhy(d.error)}</div>` : ""}${ssFollowups(d)}${!(d.items || []).length && !live ? empty("Nothing to show", "This session has no messages yet.") : ""}`;
}
function ssHead(d) {
  const model = String(d.model || "").replace(/^claude-/, "").replace(/-(\d)-(\d)$/, " $1.$2").replace(/^./, c => c.toUpperCase());
  return `<div class="grow"><h1 class="ss-title" title="Click to rename" data-ss-rename>${esc(d.title)}</h1>
      <div class="ss-tags">${ssTagList(d, true)}${model ? `<span class="tg">${esc(model)}</span>` : ""}${d.via === "headroom" ? '<span class="tg on">via Headroom</span>' : ""}</div></div>
    <div class="ss-head-a">${ssLive(d.state) ? ssCtxHtml((state.ssCtx || {})[d.id]) : ""}${d.cost ? `<span class="ss-cost" title="What this session has cost so far">${money(d.cost)}</span>` : ""}${ssLive(d.state) ? `<button class="btn small" data-ss-end title="End the Claude Code process; you can continue the session later">End</button>` : ""}
      <button class="icon-btn ss-more" data-ss-more aria-haspopup="menu" aria-expanded="false" title="More">${icon("more")}</button>
      <div class="ss-menu" role="menu" hidden>
        <button role="menuitem" data-menu="fork">${icon("branch")}Fork session</button>
        <button role="menuitem" data-menu="compact">${icon("compress")}Compact conversation</button>
        <hr><button role="menuitem" data-menu="export">${icon("download")}Export as Markdown</button>
        <button role="menuitem" data-menu="resume">${icon("terminal")}Copy terminal command</button>
        <button role="menuitem" data-menu="rename">${icon("docs")}Rename</button></div></div>`;
}
function ssDetail(d) {
  const live = ssLive(d.state), fork = state.ssFork && state.ssFork.sid === d.id ? state.ssFork : null;
  return `<header class="ss-head" id="ss-head">${ssHead(d)}</header>
    <div class="ss-conv${d.state === "working" || d.state === "starting" || (d.pending || []).length ? " ss-busy" : ""}" id="ss-conv">${ssConv(d)}</div>
    ${ssComposer({ live, saved: !live, mode: d.mode, fork })}`;
}

/* a file for a message: big images are scaled down first (to 2000px and under ~3.5 MB, as Claude Code does) */
async function ssPrepFile(f) {
  let blob = f, type = f.type || "";
  if (/^image\/(png|jpeg|webp)$/.test(type)) {
    const img = await createImageBitmap(f).catch(() => null);
    if (img && (Math.max(img.width, img.height) > 2000 || f.size > 3.5e6)) {
      const k = Math.min(1, 2000 / Math.max(img.width, img.height)), c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      blob = await new Promise(ok => c.toBlob(ok, "image/jpeg", 0.88)); type = "image/jpeg";
    }
  }
  if (blob.size > 20 * 1024 * 1024) throw new Error("files can be up to 20 MB");
  const url = await new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result)); r.onerror = () => no(new Error("couldn't read it")); r.readAsDataURL(blob); });
  return { type, data: url.slice(url.indexOf(",") + 1), thumb: /^image\/(png|jpeg|gif|webp)$/.test(type) ? url : "" };
}

/* the composer: / for skills, @ for files and folders, ↑↓ to pick, Enter or Tab to take, Escape to close */
const SK_GROUP = { plugin: "LFG and plugins", project: "This project", personal: "Your skills", builtin: "Claude Code" };
async function ssSkills() {
  if (!state.ssSkillList) {
    const d = await api("allskills");
    state.ssSkillList = (d.skills || []).filter(x => x.invoke).map(x => ({ v: x.invoke, d: x.description || "", g: SK_GROUP[x.source] || "Other", lfg: /^\/lfg:/.test(x.invoke) }))
      .sort((a, b) => (b.lfg - a.lfg) || a.g.localeCompare(b.g) || a.v.localeCompare(b.v));
  }
  return state.ssSkillList;
}
function ssAutocomplete(ta, box) {
  let items = [], at = 0, tok = null, timer = null, total = 0;
  const close = () => { box.hidden = true; items = []; tok = null; };
  const paint = () => {
    if (!tok) return close();
    box.hidden = false;
    const head = tok.kind === "/" ? `<b>Skills</b><span>${items.length}${items.length === 1 ? " skill" : " skills"} · type to filter</span>` : `<b>Files and folders</b><span>${total > items.length ? `${items.length} of ${total} · keep typing to narrow` : `${items.length} found`}</span>`;
    let group = "";
    box.innerHTML = `<div class="ss-ac-h">${head}<span class="grow"></span><span class="ss-keys"><kbd>↑</kbd><kbd>↓</kbd> choose <kbd>↵</kbd> add <kbd>esc</kbd> close</span></div><div class="ss-ac-l">${items.length ? items.map((x, i) => {
      const g = x.g && x.g !== group ? (group = x.g, `<div class="ss-ac-g">${esc(x.g)}</div>`) : "";
      const isDir = tok.kind === "@" && x.v.endsWith("/"), name = tok.kind === "@" ? x.v.replace(/\/$/, "").split("/").pop() + (isDir ? "/" : "") : x.v, dir = tok.kind === "@" ? x.v.replace(/\/$/, "").split("/").slice(0, -1).join("/") : "";
      return `${g}<button type="button" class="ss-ac-i${i === at ? " on" : ""}" data-i="${i}">${tok.kind === "@" ? `<span class="ss-ac-ic">${icon(isDir ? "folder" : "docs")}</span>` : ""}<span class="ss-ac-t"><b>${esc(name)}</b>${tok.kind === "@" ? (dir ? `<span>${esc(dir)}</span>` : "") : x.d ? `<span>${esc(x.d.slice(0, 110))}</span>` : ""}</span></button>`;
    }).join("") : `<div class="ss-ac-none">${tok.kind === "/" ? "No skill matches that." : "No file or folder matches that."}</div>`}</div>`;
    $$(".ss-ac-i", box).forEach(b => b.onmousedown = e => { e.preventDefault(); take(+b.dataset.i); });
    const on = $(".ss-ac-i.on", box); if (on) on.scrollIntoView({ block: "nearest" });
  };
  const take = i => {
    const x = items[i]; if (!x || !tok) return;
    const before = ta.value.slice(0, tok.start), after = ta.value.slice(ta.selectionStart);
    const ins = (tok.kind === "@" ? "@" + x.v : x.v) + (tok.kind === "@" && x.v.endsWith("/") ? "" : " ");
    ta.value = before + ins + after; ta.selectionStart = ta.selectionEnd = before.length + ins.length; ta.focus();
    if (tok.kind === "@" && x.v.endsWith("/")) { update(); return; }  // a folder: keep going inside it, or press space
    close(); ta.dispatchEvent(new Event("input"));
  };
  const update = async () => {
    const upto = ta.value.slice(0, ta.selectionStart), m = /(^|\s)([/@])([^\s]*)$/.exec(upto);
    if (!m) return close();
    const mine = tok = { kind: m[2], start: upto.length - m[3].length - 1, q: m[3].toLowerCase() };
    if (mine.kind === "/") {
      if (mine.q.includes("/")) return close();  // a path like /tmp/x, not a skill
      const found = (await ssSkills()).filter(x => (x.v + " " + x.d).toLowerCase().includes(mine.q));
      if (tok !== mine) return;  // the text moved on while the list loaded
      items = found; total = found.length; at = 0; return paint();
    }
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await api("session_files", { q: mine.q });
      if (tok !== mine) return;
      items = (r.files || []).map(f => ({ v: f })); total = r.total || items.length; at = 0; paint();
    }, 120);
  };
  ta.addEventListener("input", update);
  ta.addEventListener("click", update);
  ta.addEventListener("keydown", e => {
    if (box.hidden || !items.length) { if (!box.hidden && e.key === "Escape") { e.preventDefault(); close(); } return; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); at = (at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; $$(".ss-ac-i", box).forEach((b, i) => b.classList.toggle("on", i === at)); $(".ss-ac-i.on", box).scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); e.stopImmediatePropagation(); take(at); }
    else if (e.key === "Escape") { e.preventDefault(); close(); }
  }, true);
  box.addEventListener("mousedown", e => e.preventDefault());  // scrolling or clicking the list keeps the cursor in the text
  ta.addEventListener("blur", () => setTimeout(close, 150));
}

/* Studio screens fill the window exactly: the page never scrolls, their own parts do */
function ssFit(root) {
  const box = $(".ss-one, .ss-page", root), view = $("#view");
  if (!box) return;
  window.scrollTo(0, 0);
  const pad = parseFloat(getComputedStyle(view).paddingBottom) || 0;
  box.style.setProperty("--ss-h", Math.max(360, Math.floor(window.innerHeight - box.getBoundingClientRect().top - pad - 2)) + "px");
}
window.addEventListener("resize", () => { if ((location.hash.slice(1) || "").split("/")[0] === "sessions") ssFit(document); });

function wireSessions(root) {
  clearTimeout(ssPoll);
  ssFit(root);
  const S = state.sess || {}, d = S.d;
  const go = async (what, body, btn, busy) => { const was = btn && btn.textContent; if (btn) { btn.disabled = true; if (busy) btn.textContent = busy; } const r = await save(what, Object.assign({ repo: state.repo }, body)); if (!r.ok) { if (btn) { btn.disabled = false; btn.textContent = was; } alert(String(r.why || "That didn't work.").replace(/`/g, "")); } return r; };
  // the list: filter and search
  $$("[data-ss-filter]", root).forEach(b => b.onclick = () => { state.ssFilter = b.dataset.ssFilter; route({ soft: true }); });
  const find = $("#ss-find", root);
  if (find) find.oninput = () => { const q = find.value.trim().toLowerCase(); $$(".ss-row", root).forEach(a => { a.hidden = !!q && !q.split(/\s+/).every(w => a.dataset.title.includes(w)); }); };
  // the composer
  const ta = $("#ss-text", root), send = $("#ss-send", root), ac = $("#ss-ac", root);
  $$("[data-seg]", root).forEach(seg => $$("button", seg).forEach(b => b.onclick = () => {
    $$("button", seg).forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-checked", x === b); });
    localStorage.setItem("lfg.ss." + seg.dataset.seg, b.dataset.v);
    if (seg.dataset.seg === "mode" && S.id && d && ssLive(d.state)) go("sess_mode", { id: S.id, mode: b.dataset.v });
  }));
  const segVal = k => { const b = $(`[data-seg="${k}"] button.on`, root); return b ? b.dataset.v : undefined; };
  if (ta) {
    ssAutocomplete(ta, ac);
    ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && ac.hidden) { e.preventDefault(); send.click(); } });
    ta.addEventListener("input", () => { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 280) + "px"; });
    if (state.ssPrefill) { ta.value = state.ssPrefill; state.ssPrefill = ""; ta.dispatchEvent(new Event("input")); state.ssFresh = true; }
    if (!S.id || ssLive(d && d.state) || state.ssFresh) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
    state.ssFresh = false;
  }
  // attachments: the paperclip, drag and drop onto the composer, or a pasted screenshot
  const att = [], attBox = $("#ss-att", root), comp = $("#ss-comp", root), fileIn = $("#ss-file", root);
  const paintAtt = () => {
    attBox.hidden = !att.length;
    attBox.innerHTML = att.map((a, i) => `<span class="ss-chip${a.path ? "" : " up"}" title="${esc(a.name)}${a.path ? "" : " (adding…)"}">${a.thumb ? `<img src="${a.thumb}" alt="">` : icon("docs")}<span>${esc(a.name)}</span><button type="button" data-att-x="${i}" aria-label="Remove ${esc(a.name)}">&times;</button></span>`).join("");
    $$("[data-att-x]", attBox).forEach(b => b.onclick = () => { att.splice(+b.dataset.attX, 1); paintAtt(); });
  };
  const addFiles = async files => {
    for (const f of Array.from(files || [])) {
      if (att.length >= 10) { alert("Attach up to 10 files at a time."); break; }
      const a = { name: f.name || "pasted-image.png" }; att.push(a); paintAtt();
      try {
        const x = await ssPrepFile(f); a.thumb = x.thumb;  paintAtt();
        const r = await save("sess_upload", { repo: state.repo, name: a.name, type: x.type, data: x.data });
        if (!r.ok) throw new Error(r.why || "couldn't attach it");
        Object.assign(a, { path: r.path, type: r.type, image: r.image });
      } catch (e) { att.splice(att.indexOf(a), 1); alert(`${a.name}: ${String(e.message || e).replace(/`/g, "")}`); }
      paintAtt();
    }
  };
  if (comp && ta) {
    $("#ss-attach", root).onclick = () => fileIn.click();
    fileIn.onchange = () => { addFiles(fileIn.files); fileIn.value = ""; };
    let depth = 0;
    const hasFiles = e => Array.from((e.dataTransfer || {}).types || []).includes("Files");
    comp.addEventListener("dragenter", e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; comp.classList.add("drop"); });
    comp.addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
    comp.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; comp.classList.remove("drop"); } });
    comp.addEventListener("drop", e => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; comp.classList.remove("drop"); addFiles(e.dataTransfer.files); });
    ta.addEventListener("paste", e => { const fs = Array.from((e.clipboardData || {}).files || []); if (fs.length) { e.preventDefault(); addFiles(fs); } });
  }
  const attached = () => att.filter(a => a.path).map(a => ({ path: a.path, type: a.type || "" }));
  $$("[data-sug]", root).forEach(b => b.onclick = () => { const x = S.sug.suggestions[+b.dataset.sug]; ta.value = x.prompt; ta.dispatchEvent(new Event("input")); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); });
  const clearComposer = () => { ta.value = ""; ta.style.height = "auto"; att.length = 0; paintAtt(); };
  if (send) send.onclick = async () => {
    const text = ta.value.trim(), files = attached();
    if (att.some(a => !a.path)) return;  // still uploading
    if (!text && !files.length) return ta.focus();
    const fork = S.id && state.ssFork && state.ssFork.sid === S.id ? state.ssFork : null;
    if (fork) {
      const r = await go("sess_fork", { id: S.id, at: fork.at || "", text, attachments: files }, send, "Forking…");
      if (r.ok) { state.ssFork = null; clearComposer(); loadNavSessions(); location.hash = "#sessions/" + r.id; }
      return;
    }
    if (!S.id) {
      const where = ssWhereValue(root);
      if (where.kind === "new" && !where.branch) { const n = $("#ss-wt-name", root); n.focus(); n.placeholder = "Name the new branch"; n.classList.add("need"); return; }
      const r = await go("sess_start", { text, mode: segVal("mode"), where, attachments: files }, send, where.kind === "here" || where.kind === "worktree" ? "Starting…" : "Making the worktree…");
      if (r.ok) { clearComposer(); loadNavSessions(); location.hash = "#sessions/" + r.id; }
      return;
    }
    if (!ssLive(d.state)) { const r = await go("sess_resume", { id: S.id }, send, "Starting…"); if (!r.ok) return; }
    const r = await go("sess_say", { id: S.id, text, attachments: files }, send, "Sending…");
    if (r.ok) { clearComposer(); send.disabled = false; send.textContent = "Send"; refresh(); }
  };
  const fx = $("[data-fork-x]", root); if (fx) fx.onclick = () => { state.ssFork = null; route({ soft: true }); };
  const wsel = $("#ss-where", root);
  const tag = () => { const [b, wt] = ssTarget(root), t = $("#ss-branch", root), w = $("#ss-wt-tag", root); if (t) t.textContent = b; if (w) { w.hidden = !wt; w.innerHTML = wt ? `${icon("folder")}${esc(wt)}` : ""; } };
  if (wsel) {
    const show = () => { $(".ss-newwt", root).hidden = wsel.value !== "new"; tag(); };
    wsel.onchange = () => { show(); if (wsel.value === "new") $("#ss-wt-name", root).focus(); };
    $("#ss-wt-name", root).oninput = tag; $("#ss-wt-base", root).onchange = tag;
    show();
  }
  if (!S.id && $("#ss-branch", root)) {  // the checked-out branch can change under us: keep it current
    const tick = async () => {
      if (location.hash !== "#sessions") return;
      const w = await api("session_where").catch(() => null);
      if (w && w.branch !== (state.sess.where || {}).branch) { state.sess.where = w; const o = $('#ss-where option[value="here"]'); if (o) o.textContent = `Here · ${w.branch}`; tag(); }
      ssPoll = setTimeout(tick, 5000);
    };
    ssPoll = setTimeout(tick, 5000);
  }
  // worktrees: new session there, merge back, merge all
  $$("[data-wt-session]", root).forEach(b => b.onclick = () => { state.ssStartIn = b.dataset.wtSession; location.hash = "#sessions"; });
  if (state.ssStartIn && wsel) { const o = $(`#ss-where option[value="wt:${CSS.escape(state.ssStartIn)}"]`, root); if (o) { wsel.value = o.value; wsel.onchange(); } state.ssStartIn = null; }
  const merge = async (body, btn, label) => {
    let r = await go(body.into ? "wt_merge_all" : "wt_merge", body, btn, "Merging…");
    if (r.ok && r.needs_merge_commit) {
      if (!confirm(r.why + "\n\nThis creates a merge commit on the base branch.")) { route({ soft: true }); return; }
      r = await go(body.into ? "wt_merge_all" : "wt_merge", Object.assign({ merge_commit: true }, body), btn, "Merging…");
    }
    if (r.ok) { const done = r.done || [r]; alert(done.length ? done.map(x => `${x.name}: ${x.commits ? `${x.commits} commit${x.commits === 1 ? "" : "s"} into ${x.into} (${x.how})` : "nothing to merge"}${x.removed ? ", removed" : ""}`).join("\n") : "Nothing to merge."); }
    route({ soft: true });
  };
  $$("[data-wt-merge]", root).forEach(b => b.onclick = () => {
    const row = b.closest("[data-wt]"), name = row.dataset.wt, rm = b.hasAttribute("data-remove");
    if (!confirm(rm ? `${b.textContent} ${name}?\n\nOnly committed work is merged. The worktree folder and its branch (once merged) are removed.` : `Merge ${name} into its base branch?\n\nOnly committed work is merged.`)) return;
    merge({ name, remove: rm }, b);
  });
  $$("[data-wt-all]", root).forEach(b => b.onclick = () => { if (confirm(`Merge every LFG worktree forked from ${b.dataset.wtAll} into it, then remove them?\n\nIt stops at the first one that can't merge (uncommitted changes or conflicts).`)) merge({ into: b.dataset.wtAll }, b); });
  if (!d || d.available === false) return;
  // one session: answers, follow-ups, stop, end, rename, live updates
  const conv = $("#ss-conv", root), head = $("#ss-head", root);
  const wireConv = () => {
    $$(".ss-ask", conv).forEach(card => $$("[data-decide]", card).forEach(b => b.onclick = async () => { const r = await go("sess_decide", { id: S.id, request: card.dataset.req, decision: b.dataset.decide }, b); if (r.ok) refresh(); }));
    const stop = $("[data-ss-interrupt]", conv); if (stop) stop.onclick = () => go("sess_interrupt", { id: S.id }, stop, "Stopping…");
    $$("[data-follow]", conv).forEach(b => b.onclick = () => { ta.value = b.dataset.follow; send.click(); });
    $$("[data-ss-copy]", conv).forEach(b => b.onclick = async () => { await navigator.clipboard.writeText(ssItemText(d.items[+b.dataset.ssCopy])); const t = b.innerHTML; b.textContent = "Copied"; setTimeout(() => { b.innerHTML = t; }, 1200); });
    $$("[data-fork]", conv).forEach(b => b.onclick = () => {
      const it = d.items[+b.dataset.fork];
      state.ssFork = { sid: S.id, at: it.p || "", label: ssItemText(it).slice(0, 60) };
      state.ssPrefill = ssItemText(it); route({ soft: true });
    });
    $$("[data-rw]", conv).forEach(b => b.onclick = () => ssRewind(b));
    $$(".ss-img", conv).forEach(b => b.onclick = () => b.classList.toggle("big"));
    ssImages(conv);
  };
  // Rewind: like Claude Code's, to before one of your messages: the conversation, the code, or both
  const ssRewind = async b => {
    $$(".ss-rw", conv).forEach(x => x.remove());
    const msg = b.closest(".ss-me"), u = b.dataset.rw;
    const box = document.createElement("div"); box.className = "ss-rw";
    box.innerHTML = `<div class="ss-rw-h"><b>Rewind to before this message</b><span class="muted small" data-rw-prev>Checking which files would change…</span></div><div class="ss-rw-files" hidden></div>
      <div class="ss-rw-a"><button class="btn small primary" data-rw-go="both">Code and conversation</button><button class="btn small" data-rw-go="chat">Conversation only</button><button class="btn small" data-rw-go="code">Code only</button><button class="btn small" data-rw-x>Cancel</button></div>`;
    msg.append(box); box.scrollIntoView({ block: "nearest" });
    $("[data-rw-x]", box).onclick = () => box.remove();
    const codeBtns = $$('[data-rw-go="both"], [data-rw-go="code"]', box);
    const p = await save("sess_rewind_preview", { repo: state.repo, id: S.id, message: u }), prev = $("[data-rw-prev]", box);
    if (!p.ok || !p.can) { prev.textContent = p.ok ? `The code can't be rewound: ${p.why || "no saved copy of the files from then"}.` : String(p.why || "Couldn't check the files.").replace(/`/g, ""); codeBtns.forEach(x => x.disabled = true); $('[data-rw-go="chat"]', box).classList.add("primary"); }
    else if (!p.files.length) { prev.textContent = "No file changes since then; only the conversation goes back."; codeBtns.forEach(x => x.disabled = true); $('[data-rw-go="chat"]', box).classList.add("primary"); }
    else { prev.textContent = `Puts back ${plural(p.files.length, "file")} (+${p.insertions} −${p.deletions}).`; const fl = $(".ss-rw-files", box); fl.hidden = false; fl.textContent = p.files.join("\n"); }
    $$("[data-rw-go]", box).forEach(x => x.onclick = async () => {
      const what = x.dataset.rwGo;
      if (what !== "chat" && !confirm(`Put ${plural(p.files.length, "file")} back to how they were before this message? Changes made since, by Claude or by you, are lost.`)) return;
      const r = await go("sess_rewind", { id: S.id, message: u, what }, x, "Rewinding…");
      if (!r.ok) return;
      if (r.prefill) state.ssPrefill = r.prefill;
      loadNavSessions(); route({ soft: true });
    });
  };
  const wireHead = () => {
    const end = $("[data-ss-end]", head); if (end) end.onclick = async () => { if (confirm("End this session? Claude Code stops; you can continue the session later.")) { await go("sess_end", { id: S.id }, end); loadNavSessions(); route({ soft: true }); } };
    const rename = async () => { const t = prompt("Name this session", d.title); if (t && t.trim()) { await go("sess_rename", { id: S.id, title: t }); loadNavSessions(); route({ soft: true }); } };
    const ttl = $("[data-ss-rename]", head); if (ttl) ttl.onclick = rename;
    const more = $("[data-ss-more]", head), menu = $(".ss-menu", head);
    const close = () => { menu.hidden = true; more.setAttribute("aria-expanded", "false"); document.removeEventListener("click", outside, true); };
    const outside = e => { if (!e.target.closest(".ss-menu, [data-ss-more]")) close(); };
    more.onclick = () => { const open = menu.hidden; menu.hidden = !open; more.setAttribute("aria-expanded", open); if (open) document.addEventListener("click", outside, true); else close(); };
    $$("[data-menu]", menu).forEach(b => b.onclick = async () => {
      close();
      const k = b.dataset.menu;
      if (k === "rename") return rename();
      if (k === "export") return ssDownload(`${(d.title || "session").replace(/[^\w.-]+/g, "-").slice(0, 60)}.md`, ssMarkdown(d));
      if (k === "resume") { await navigator.clipboard.writeText(`claude --resume ${S.id}`); return alert(`Copied: claude --resume ${S.id}\n\nRun it in this project's folder to carry on in a terminal.`); }
      if (k === "fork") { state.ssFork = { sid: S.id, at: "", label: "" }; route({ soft: true }); return; }
      if (k === "compact") {
        if (!confirm("Compact this conversation? Claude Code summarizes it to free up context, as /compact does in a terminal.")) return;
        if (!ssLive(d.state)) { const r = await go("sess_resume", { id: S.id }); if (!r.ok) return; }
        const r = await go("sess_compact", { id: S.id }); if (r.ok) refresh();
      }
    });
  };
  const loadCtx = async () => {  // how full the context is, once Claude is idle
    if (!ssLive(d.state) || d.state === "working") return;
    const c = await api("session_context", { id: S.id }).catch(() => null);
    if (!c || c.percent == null) return;
    (state.ssCtx = state.ssCtx || {})[S.id] = c;
    const a = $(".ss-head-a", head), old = $(".ss-ctx", a);
    if (old) old.outerHTML = ssCtxHtml(c); else a.insertAdjacentHTML("afterbegin", ssCtxHtml(c));
  };
  wireConv(); wireHead(); loadCtx();
  const atBottom = () => conv.scrollTop + conv.clientHeight >= conv.scrollHeight - 120;
  conv.scrollTop = conv.scrollHeight;
  let sig = "";
  const sigOf = n => JSON.stringify([n.items.length, n.state, (n.pending || []).length, (n.queued || []).length, n.error, n.cost, (n.items[n.items.length - 1] || {}).result != null]);
  sig = sigOf(d);
  async function refresh() {
    clearTimeout(ssPoll);
    if (!/^#sessions\//.test(location.hash) || state.sess.id !== S.id) return;
    const n = await api("session", { id: S.id });
    if (!n || n.available === false) return;
    const nsig = sigOf(n);
    if (nsig !== sig) {
      const stick = atBottom(), was = d.state;
      sig = nsig; state.sess.d = n; Object.assign(d, n);
      conv.innerHTML = ssConv(n); head.innerHTML = ssHead(n); wireConv(); wireHead();
      conv.classList.toggle("ss-busy", n.state === "working" || n.state === "starting" || !!(n.pending || []).length);
      if (n.state === "idle" && was !== "idle") loadCtx();
      if (send) { const want = ssLive(n.state) ? "Send" : "Continue here"; if (!send.disabled && send.textContent !== want) send.textContent = want; }
      if (stick) conv.scrollTop = conv.scrollHeight;
    }
    if (ssLive(n.state)) ssPoll = setTimeout(refresh, n.state === "idle" ? 4000 : 1200);
  }
  if (ssLive(d.state)) ssPoll = setTimeout(refresh, 1200);
}

/* Notifications: every long job (an AI review or answer, a fix run, a Linear ticket, a scan, the checks) is announced
   when it finishes, by `lfg ui` itself, even with its page closed. They show as toasts, in the bell's list and, when
   this tab is in the background and you allowed it, as system notifications. A click opens the page. */
const NOTES = { last: "", seen: localStorage.getItem("lfg.notes.seen") || "", events: [] };
const NOTE_ICON = { review: "review", diff: "review", fix: "runs", linear: "todos", checks: "checks", sonar: "checks" };
async function openNote(ev) {
  closeBell();
  if (ev.repo && ev.repo !== state.repo && state.repos.some(r => r.id === ev.repo)) {
    state.repo = ev.repo; localStorage.setItem("lfg.repo", ev.repo);
    const sel = $("#repo"); if (sel) sel.value = ev.repo;
    await loadBranches();
  }
  if (ev.href && location.hash !== ev.href) location.hash = ev.href; else route();
}
function noteHtml(ev, cls) {
  const proj = ev.repo && ev.repo !== state.repo ? `<span class="brtag">${esc(repoName(ev.repo))}</span>` : "";
  return `<a href="${esc(ev.href || "#")}" class="${cls}${ev.ok ? "" : " bad"}${ev.id > NOTES.seen ? " new" : ""}" data-note="${esc(ev.id)}"><span class="note-ico">${icon(NOTE_ICON[ev.kind] || "home")}</span><span class="grow"><b>${esc(ev.title)}</b>${ev.body ? `<span class="note-b">${esc(ev.body)}</span>` : ""}<span class="note-m">${proj}${ago(ev.ts)}</span></span></a>`;
}
function paintBell() {
  const unread = NOTES.events.filter(e => e.id > NOTES.seen).length, n = $("#bell-n");
  n.hidden = !unread; n.textContent = unread > 9 ? "9+" : unread;
  const pop = $("#bell-pop");
  if (pop.hidden) return;
  const perm = NOTES.desktop === "terminal-notifier" ? `<span class="muted small">When this tab isn't in front, you also get a macOS notification; click it to come back here.</span>`
    : NOTES.desktop === "osascript" ? `<span class="muted small">When this tab isn't in front, you also get a macOS notification. Install terminal-notifier (<code>brew install terminal-notifier</code>) to make it open the page on click.</span>`
    : !("Notification" in window) ? "" : Notification.permission === "granted" ? `<span class="muted small">System notifications are on when this tab is in the background.</span>`
    : Notification.permission === "denied" ? `<span class="muted small">System notifications are blocked for this page in your browser's settings.</span>`
    : `<button class="btn small" id="note-perm">Notify me when this tab is in the background</button>`;
  pop.innerHTML = `<div class="bell-h"><b>Notifications</b><span class="grow"></span>${unread ? `<a href="#" class="small" id="note-read">Mark all read</a>` : ""}</div>
    <div class="bell-list">${NOTES.events.slice(0, 30).map(e => noteHtml(e, "note")).join("") || '<p class="muted small bell-empty">Nothing yet. When the AI finishes a review, an answer or a fix run, or a scan or check is done, it shows up here.</p>'}</div>
    <div class="bell-f">${perm}</div>`;
  $$("[data-note]", pop).forEach(a => a.onclick = e => { e.preventDefault(); openNote(NOTES.events.find(x => x.id === a.dataset.note)); });
  const rd = $("#note-read", pop); if (rd) rd.onclick = e => { e.preventDefault(); markSeen(); };
  const pm = $("#note-perm", pop); if (pm) pm.onclick = async () => { await Notification.requestPermission(); paintBell(); };
}
function markSeen() { NOTES.seen = NOTES.events[0] ? NOTES.events[0].id : NOTES.seen; localStorage.setItem("lfg.notes.seen", NOTES.seen); paintBell(); }
function closeBell() { const pop = $("#bell-pop"); if (!pop.hidden) { pop.hidden = true; $("#bell").setAttribute("aria-expanded", "false"); markSeen(); } }
function toast(ev) {
  const box = $("#toasts"), el = document.createElement("div");
  el.innerHTML = `${noteHtml(ev, "toast")}<button class="toast-x" aria-label="Dismiss">&times;</button>`;
  const t = el.firstChild, x = el.lastChild;
  const wrap = document.createElement("div"); wrap.className = "toast-wrap"; wrap.append(t, x); box.prepend(wrap);
  t.onclick = e => { e.preventDefault(); wrap.remove(); openNote(ev); };
  x.onclick = () => wrap.remove();
  setTimeout(() => wrap.remove(), 9000);
  while (box.children.length > 4) box.lastChild.remove();
}
function systemNote(ev) {  // the browser's own notification, only when `lfg ui` can't post macOS ones itself
  if (NOTES.desktop || !document.hidden || !("Notification" in window) || Notification.permission !== "granted") return;
  const n = new Notification(`LFG · ${ev.title}`, { body: [ev.body, ev.repo && repoName(ev.repo)].filter(Boolean).join("\n"), tag: ev.id });
  n.onclick = () => { window.focus(); n.close(); openNote(ev); };
}
const inFront = () => document.visibilityState === "visible" && document.hasFocus();
async function pollNotes(first) {
  let d;
  try { d = await api("notifications", Object.assign({ visible: inFront() ? "1" : "0" }, NOTES.last ? { since: NOTES.last } : {})); } catch (e) { return; }
  if (!d || !d.events) return;
  NOTES.desktop = d.desktop || "";
  const sb = $("#top-sess-n"), ss = d.sessions || {};
  const sk = JSON.stringify(ss); if (sk !== NOTES.sessKey || Date.now() - (NOTES.sessAt || 0) > 30000) { NOTES.sessKey = sk; NOTES.sessAt = Date.now(); loadNavSessions(); }
  if (sb) { sb.hidden = !ss.live; sb.textContent = ss.needs_you ? `${ss.needs_you} need you` : `${ss.live} live`; sb.classList.toggle("warn", !!ss.needs_you); }
  if (!first) d.events.slice().reverse().forEach(ev => { toast(ev); systemNote(ev); });
  NOTES.events = d.events.concat(NOTES.events).slice(0, 50);
  NOTES.last = d.latest || NOTES.last;
  paintBell();
}
function mountBell() {
  const b = $("#bell"), pop = $("#bell-pop");
  b.onclick = e => { e.stopPropagation(); if (pop.hidden) { pop.hidden = false; b.setAttribute("aria-expanded", "true"); paintBell(); } else closeBell(); };
  document.addEventListener("click", e => { if (!pop.hidden && !e.target.closest(".bell")) closeBell(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeBell(); });
  pollNotes(true);
  setInterval(() => pollNotes(false), 5000);
  // tell `lfg ui` at once when this tab goes to the back (or comes forward), so macOS notifications start right away
  ["visibilitychange", "blur", "focus"].forEach(ev => (ev === "visibilitychange" ? document : window).addEventListener(ev, () => pollNotes(false)));
}

/* Bottom of the sidebar: the LFG version, a tag when a newer one is out, and a button to check now */
function drawSideVersion(u, checking) {
  const box = $("#side-ver");
  if (!box || !u) return;
  const tip = u.error && !u.upstream ? `Couldn't reach GitHub: ${u.error}` : u.checked_at ? `Checked ${ago(u.checked_at)}` : "Not checked yet";
  box.innerHTML = `<span class="side-ver-n" title="LFG runs only on this computer">LFG v${esc(u.current)}</span>
    ${u.update_available ? `<a class="tag blue side-upd" href="#settings" title="In your LFG clone run ${esc(u.command)}">${esc(u.upstream)} available</a>` : `<span class="side-ok" title="${esc(tip)}">${u.checked_at ? "up to date" : ""}</span>`}
    <button class="icon-btn side-chk${checking ? " spinning" : ""}" id="side-chk" title="Check for updates · ${esc(tip)}" aria-label="Check for updates"${checking ? " disabled" : ""}><svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg></button>`;
  $("#side-chk", box).onclick = async () => {
    drawSideVersion(u, true);
    const r = await save("updates_check", {});
    drawSideVersion(r.ok === false ? u : r, false);
  };
}
async function sideVersion() { try { drawSideVersion(await api("updates")); } catch (e) { /* offline: leave the name */ } }
async function init() {
  const brand = $(".brand"); if (brand) brand.innerHTML = logoSvg(20);
  sideVersion();
  api("github").then(g => { state.gh = g; if (g && g.starred) $$("[data-gh-star]").forEach(b => (b.textContent = "★ Starred, thank you")); }).catch(() => {});
  if (location.hash.startsWith("#unlock=")) {  // from `lfg ui`: keep the edit key, drop it from the URL
    localStorage.setItem("lfg.editKey", decodeURIComponent(location.hash.slice(8)));
    history.replaceState(null, "", location.pathname);
  }
  $("#drawer-close").onclick = closeDrawer;
  const linked = new URLSearchParams(location.search).get("repo");  // opened from a macOS notification
  if (linked) { state.repo = linked; localStorage.setItem("lfg.repo", linked); history.replaceState(null, "", location.pathname + location.hash); }
  mountBell();
  setTimeout(loadNavSessions, 300);
  $("#drawer").onclick = e => { if (e.target.id === "drawer") closeDrawer(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  try { state.rules = await api("rules"); } catch (e) { state.rules = null; }
  mountRuleTips();
  // Fetch features BEFORE first route, set pages
  let d = null;
  try { d = await api("features"); } catch (e) { d = null; }
  if (d) {
    state.pages = d.pages || NAV.map(p => p[0]);
    if (d.show_all) state.pages = NAV.map(p => p[0]);
  }
  // Redirect to onboarding only when: !complete AND hash empty AND no welcomeShown
  let welcomeShown = null;
  try { welcomeShown = sessionStorage.getItem("lfg.welcomeShown"); } catch (e) { /* ignore */ }
  const hashEmpty = !location.hash || location.hash === "#";
  if (d && !d.complete && hashEmpty && !welcomeShown) {
    try { sessionStorage.setItem("lfg.welcomeShown", "1"); } catch (e) { /* ignore */ }
    location.hash = "#onboarding";
  }
  const r = await api("repos");
  state.repos = r.repos || [];
  if (!state.repos.some(x => x.id === state.repo)) state.repo = state.repos[0] ? state.repos[0].id : "";
  $("#repo").innerHTML = state.repos.map(x => `<option value="${esc(x.id)}" title="${esc(x.root || x.id)}" ${x.id === state.repo ? "selected" : ""}>${esc(x.name || x.id)}</option>`).join("") || "<option>no projects yet</option>";
  $("#repo").onchange = async () => { state.repo = $("#repo").value; localStorage.setItem("lfg.repo", state.repo); state.navSess = []; await loadBranches(); refresh(); loadNavSessions(); };
  $("#branch").onchange = () => { state.branch = $("#branch").value; localStorage.setItem(branchPref(), state.branch); refresh(); };
  window.onhashchange = route;
  await loadBranches();
  mapStatus();
  route();
  offerTours();
  checkUpdates();
}
async function loadBranches() {
  /* runs and checks are tagged with the branch they ran on; the code map is one per project */
  const sel = $("#branch");
  let B = null;
  try { B = state.repo ? await api("branches", { branch: "" }) : null; } catch (e) { B = null; }
  B = B || { branches: [], unrecorded: 0 };
  const known = new Set(B.branches.map(b => b.name).concat(B.unrecorded ? ["-"] : []));
  state.branch = localStorage.getItem(branchPref()) || "";
  if (!known.has(state.branch)) state.branch = "";
  const opt = (v, label) => `<option value="${esc(v)}" ${v === state.branch ? "selected" : ""}>${esc(label)}</option>`;
  sel.innerHTML = opt("", "All branches") + B.branches.map(b => opt(b.name, b.name + (b.state === "current" ? " (checked out)" : b.state === "deleted" ? " (deleted)" : ""))).join("") + (B.unrecorded ? opt("-", "Older runs (branch unknown)") : "");
  sel.disabled = !state.repo;
  sel.hidden = !B.branches.length && !B.unrecorded;
  sel.title = "Show runs and checks from one branch. The code map always follows the checked-out branch.";
}
function refresh() { state.cache = {}; mapStatus(); route(); }
init();
