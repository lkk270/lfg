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
  const q = new URLSearchParams({ repo: state.repo, ...(state.branch ? { branch: state.branch } : {}), ...(state.fresh ? { fresh: "1" } : {}), ...params });
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

/* simple bar chart: data=[{label, values:[...]}], series=[[name,color]] */
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
      out += `<${ordered ? "ol" : "ul"}>${buf.map(b => `<li>${inline(b, link)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`; continue;
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
document.addEventListener("keydown", openKnow);

function wire(root) {
  $$("[data-run-file]", root).forEach(a => a.onclick = async e => {
    e.preventDefault();
    const [run, f] = JSON.parse(a.dataset.runFile);
    const d = await api("file", { run, f });
    openDrawer(a.textContent, renderFile(f, d.text));
  });
  $$("[data-view]", root).forEach(b => b.onclick = async () => {
    const box = document.getElementById(b.dataset.target);
    box.innerHTML = '<div class="loading">Opening… large repos can take a minute the first time.</div>';
    const d = await api("view", { kind: b.dataset.view });
    box.innerHTML = d.src ? `<iframe class="viewer mt" src="${esc(d.src)}" title="${esc(b.textContent)}" referrerpolicy="no-referrer"></iframe>` : empty("Not made yet", fmtWhy(d.message));
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
  if ($("[data-checks-running]", root)) setTimeout(() => { if (document.body.contains(root) && $("[data-checks-running]", root)) { state.cache = {}; route(); } }, 10000);
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
async function isUnlocked() {
  if (!editKey()) return false;
  try {
    const r = await fetch("/api/unlocked", { headers: { "X-LFG": "1", "X-LFG-Key": editKey() } });
    return r.ok && (await r.json()).ok;
  } catch (e) { return false; }
}
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
  if (f.type === "bool") return `<input type="checkbox" id="${id}" data-cfg="${esc(f.key)}" ${v ? "checked" : ""} ${dis}>`;
  if (f.type === "choice") return `<select id="${id}" data-cfg="${esc(f.key)}" ${dis}>${f.options.map(o => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  if (f.type === "int") return `<input type="number" id="${id}" data-cfg="${esc(f.key)}" min="${f.min}" max="${f.max}" value="${esc(v)}" ${dis}>`;
  const val = Array.isArray(v) ? v.join(", ") : v ?? "";
  return `<input type="text" id="${id}" data-cfg="${esc(f.key)}" value="${esc(val)}" ${dis}>`;
}
function settingsGeneral() {
  const { cfg, unlocked } = state.settings;
  return `<div>${cfg.fields.map(f => `<label class="set-row" for="cfg-${esc(f.key)}"><div><div class="set-label">${esc(f.label)}</div><div class="set-help">${esc(f.help || "")}</div></div><div class="set-input">${fieldInput(f, !unlocked)}</div></label>`).join("")}</div>
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
    <div class="set-section"><h4>Safety rules</h4><p class="muted">What every LFG session must follow. LFG enforces these in code. To lift a block so Claude does it only when you ask, use <a href="#prefs">Preferences → Safety rules</a>.</p>
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
  box.innerHTML = `<p><b>Add a rule</b></p><p class="muted small">Give it a short name (lowercase, dashes) and write it in Markdown. Agents read it with <code>lfg rule &lt;name&gt;</code>. New sessions are told to follow it, and sessions already open are told with your next message to them.</p>
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
  const packRows = d.packs.map(p => `<li>${dot(p.on ? (p.missing.length ? "warn" : "ok") : "")}<div class="grow"><div class="title">${esc(p.title)}</div><div class="meta">${esc(p.about)}${p.on && p.missing.length ? ` · missing: ${esc(p.missing.map(m => m.split(":")[1]).join(", "))}` : ""}</div>${job(p.name)}</div>
    ${p.name === "core" ? '<span class="muted small">always on</span>' : p.on && !p.missing.length ? `<button class="btn small" data-cc="pack_remove" data-name="${esc(p.name)}" ${dis}>Turn off</button>` : `<button class="btn small" data-cc="pack_add" data-name="${esc(p.name)}" ${dis || ((d.jobs[p.name] || {}).status === "running" ? "disabled" : "")}>${p.on ? "Install missing" : "Add"}</button>`}</li>`).join("");
  const hrOpts = [["off", "Off"], ["repos", "Only repos where LFG is on"], ["everywhere", "Every Claude Code session"]];
  const hrBlocked = hr.cloud_provider ? `Not available: Claude Code uses ${esc(hr.cloud_provider)} here.` : !hr.installed ? "Add the Headroom pack first." : "";
  const changes = d.changes.length ? `<div class="box"><ul class="list">${d.changes.slice().reverse().map(c => `<li><span class="muted nowrap">#${c.id}</span><div class="grow"><div class="title">${fmtWhy(c.text)}</div><div class="meta">${esc(c.why)} · ${ago(c.ts)}</div></div><button class="btn small" data-cc="change_undo" data-id="${c.id}" ${dis}>Undo</button></li>`).join("")}</ul></div>`
    : `<div class="box calm">${dot("ok")}LFG has changed nothing outside ~/.lfg.</div>`;
  const legacy = d.legacy.length ? `<div class="set-section"><h4>Left over from an older LFG</h4><p class="muted">Older versions changed Claude Code for every session. Each fix below removes exactly what LFG added.</p>
    <div class="box"><ul class="list">${d.legacy.map(l => `<li>${dot("warn")}<div class="grow"><div class="title">${esc(l.title)}</div><div class="meta">${esc(l.fix)}</div></div>${l.default ? `<button class="btn small" data-cc="legacy_fix" data-id="${esc(l.id)}" ${dis}>Fix</button>` : ""}</li>`).join("")}</ul></div></div>` : "";
  box.innerHTML = `<p class="muted">What LFG does to Claude Code, and where. Everything here is recorded and can be undone; nothing outside the repos you pick is touched.</p>
    <span class="save-msg" id="cc-msg"></span>${legacy}
    <div class="set-section"><h4>Where LFG is on</h4><p class="muted">In other repos Claude Code works exactly as if LFG weren't installed: no skills, hooks or MCP servers.</p>
      <label class="row"><input type="checkbox" data-cc="everywhere" ${R.everywhere ? "checked" : ""} ${dis}> Turn LFG on in every repo <span class="muted small">(not recommended)</span></label>
      <div class="box mt">${repoRows ? `<ul class="list">${repoRows}</ul>` : empty("No repos yet", "Run <code>lfg enable</code> in a repo, or open one in Claude Code after enabling it.")}</div></div>
    <div class="set-section"><h4>Feature packs</h4><p class="muted">Core is all LFG needs. The rest install their tools only when you add them. Tools stay installed when you turn a pack off.</p>
      <div class="box"><ul class="list">${packRows}</ul></div></div>
    <div class="set-section"><h4>Safety</h4>
      <div class="box pad"><div class="row">${dot("ok")}<div class="grow"><b>Guard</b><div class="meta">On in every LFG repo: blocks commits, pushes, secret reads and the rest of the 18 rules (Settings → Rules). Recently blocked: ${d.blocked.length ? d.blocked.slice(0, 3).map(b => `rule ${esc(b.rule)} (${esc(b.tool)})`).join(", ") : "nothing"}.</div></div></div>
      <label class="row mt"><input type="checkbox" data-cc="hardened" ${d.hardened ? "checked" : ""} ${dis}><span><b>Hardened mode</b><span class="meta"> · also add Claude Code deny rules (git commit/push, secret files…) to each LFG repo's <code>.claude/settings.local.json</code>, never to your user settings</span></span></label></div></div>
    <div class="set-section"><h4>Headroom (context compression)</h4><p class="muted">A local proxy that shrinks what Claude Code sends. ${hr.live ? `Running, forwarding to ${esc(hr.upstream)}.` : hr.scope !== "off" ? `<span class="row" style="gap:8px">${dot("bad")}<span>Not running, and Claude Code is pointed at it, so terminal sessions can't reach Claude. Run <code>lfg headroom restart</code> in a terminal.</span></span>` : "Not running."}</p>
      <div class="row"><select id="cc-hr" ${dis || (hrBlocked && hr.scope === "off" ? "disabled" : "")}>${hrOpts.map(([v, l]) => `<option value="${v}" ${v === hr.scope ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><button class="btn" data-cc="headroom" ${dis}>Apply</button><span class="muted small">${esc(hrBlocked)}</span></div></div>
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
  $$("[data-cc]", box).forEach(el => {
    const act = el.dataset.cc, ev = el.type === "checkbox" ? "onchange" : "onclick";
    el[ev] = async () => {
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
  clearTimeout(ccTimer);
  if (Object.values(d.jobs).some(j => j.status === "running")) ccTimer = setTimeout(() => { if (document.body.contains(box)) loadClaudeCode(); }, 2000);
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
  if ($("#mylib-box", root)) loadMyLibrary();
  if ($("#ollama-box", root)) loadOllama();
  if ($("#storage-box", root)) loadStorage();
  if ($("#tools-box", root)) loadTools();
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

// ------------------------------------------------------------------ pages
const NAV = [["prefs", "Preferences"], ["home", "Home"], ["sessions", "Sessions"], ["environment", "Environment"], ["runs", "Runs"], ["issues", "Issues"], ["checks", "Checks"], ["prs", "PR reviews"], ["code", "Code"], ["docs", "Docs"],
  ["knowledge", "Knowledge"], ["usage", "Usage"], ["skills", "Skills"], ["settings", "Settings"], ["help", "Help"]];
const TITLES = Object.fromEntries(NAV);
const PAGES = {};

async function cachedRuns() {
  const key = "runs:" + state.repo;
  if (!state.cache[key]) state.cache[key] = await api("runs");
  return state.cache[key];
}

/* What a run is doing, in one line: "Step 5 of 10 · next: run the checks" */
function runLine(r, stages) {
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

PAGES.home = async () => {
  const d = await api("overview");
  if (d.available === false) return unavailable(d, "No project yet");
  const all = await cachedRuns();
  const stages = all.stages, run = d.run, g = d.graphs || {}, t = d.tokens_7d || {}, hr = d.headroom || {};
  // what needs the user
  const attn = [];
  if (run) runAttention(run).forEach(([tn, text]) => attn.push([tn, text, `#runs/${encodeURIComponent(run.run)}`]));
  if (d.security && d.security.blocking && !(run && run.secure === "don't")) attn.push(["bad", `The latest security check found ${plural(d.security.blocking, "problem")}`, "#checks"]);
  if (g.status === "error") attn.push(["bad", "The code map failed to update", "#code"]);
  (d.integrations || []).filter(x => !x.ok && !x.optional).forEach(x => attn.push(["warn", x.problem || `${x.name} needs attention`, "#settings"]));
  if (d.work && d.work.blocked) attn.push(["warn", `${plural(d.work.blocked, "issue")} blocked by other work`, "#issues"]);
  const worst = attn.some(a => a[0] === "bad") ? "bad" : attn.length ? "warn" : "ok";
  const attnBox = attn.length
    ? `<div class="callout ${worst}"><ul class="attn">${attn.map(([tn, text, href]) => `<li>${dot(tn)}<a class="grow" href="${href}">${fmtWhy(text)}</a><span class="go" aria-hidden="true">→</span></li>`).join("")}</ul></div>`
    : `<div class="callout ok">${dot("ok")}Nothing needs you right now.</div>`;
  // the current run
  let now;
  if (run) {
    const p = runPlace(stages, run.stages, run);
    now = `<a class="now" href="#runs/${encodeURIComponent(run.run)}">
      <h2>${esc(runName(run))}</h2>
      ${run.about ? `<p class="about">${txt(run.about)}</p>` : ""}
      <div class="meta">${run.owner ? `Filed under ${esc(run.owner_name)}${run.branch ? ` (branch ${esc(run.branch)})` : ""} · started ${ago(run.created)} · ${n(run.tasks_here_done)} of ${plural(run.tasks_here, "task")} for this repo done` : `${run.branch ? `On branch ${esc(run.branch)} · ` : ""}started ${ago(run.created)}${run.tasks.total ? ` · ${run.tasks.done} of ${plural(run.tasks.total, "task")} done` : ""}`}</div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>
      <div class="next${p.blocked ? " stuck" : ""}">${p.finished ? "All steps done. The commit message is ready for you." : `${p.done} of ${p.total} steps · next: ${esc(NEXT[p.next])}`}</div></a>`;
  } else {
    now = `<div class="box">${empty("Nothing in progress", "Start in Claude Code with <code>/lfg:lfg</code> and a short description of what you want, or <code>/lfg:wizard</code> for a guided run.")}</div>`;
  }
  const recent = all.runs.filter(r => !run || r.run !== run.run).slice(0, 5);
  const recentBox = recent.length ? `<div class="box"><ul class="list">${recent.map(r => `<li class="click" data-href="#runs/${encodeURIComponent(r.run)}"><div class="grow"><div class="title">${esc(runName(r))}</div>${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="meta">${esc(runLine(r, stages))}</div></div><span class="muted small nowrap">${ago(r.created)}</span></li>`).join("")}</ul></div>` : "";
  const used = (t.input || 0) + (t.output || 0) + (t.cache_read || 0) + (t.cache_write || 0);
  const cached = pct(t.cache_read || 0, used - (t.output || 0));
  const saved = hr.available && hr.lifetime && hr.lifetime.tokens_saved;
  return `${head(repoName() || "Home", `${run ? "What LFG is doing in this project" : "Nothing in progress in this project"}${state.branch ? `, on ${esc(state.branch === "-" ? "unrecorded branches" : state.branch)}` : ""}.`)}
    ${section(run ? "Working on" : "Current work", now)}
    ${section("Needs your attention", attnBox)}
    ${recent.length ? section("Earlier runs", recentBox, `<a href="#runs">See all ${n(all.runs.length)}</a>`) : ""}
    ${section("This week", `<div class="cols">${(d.spend || {}).available ? stat("AI cost", usd(d.spend["7d"]), `${compact(used)} tokens, all projects${saved ? ` · ${compact(saved)} saved by compression` : ""}`) : stat("AI tokens", compact(used), `all projects, last 7 days · ${cached}% from cache${saved ? ` · ${compact(saved)} saved by compression` : ""}`)}${stat("Code map", say(g.status)[0] || "Unknown", `${g.status === "missing" ? "not built yet" : g.synced_at ? `updated ${ago(g.synced_at)}` : ""} ${mapBtn(g.status)}`)}${d.work && !d.work.why ? stat("Issues ready to start", n(d.work.ready), d.work.blocked ? `${n(d.work.blocked)} blocked` : "none blocked") : d.work ? stat("Issues", "Not available", fmtWhy(d.work.why)) : ""}</div>`)}`;
};

PAGES.runs = async arg => {
  if (arg) return runDetail(arg);
  const d = await cachedRuns();
  if (d.available === false) return unavailable(d);
  return `${head("Runs", "Each run is one piece of work LFG took from idea to a commit you can review. Click one to see where it is.")}
    <div class="box">${table(d.runs, [
      { k: "slug", label: "Work", html: r => `${esc(runName(r))}${r.current ? ' <span class="tag">current</span>' : ""}${r.about ? `<div class="about clamp">${txt(r.about)}</div>` : ""}<div class="sub">${r.owner ? `filed under ${esc(r.owner_name)} · ${plural(r.tasks_here, "task")} for this repo, ${n(r.tasks_here_done)} done` : r.branch ? `branch ${esc(r.branch)}` : ""}</div>`, sort: r => runName(r) },
      { k: "progress", label: "Where it is", html: r => esc(runLine(r, d.stages)), sort: r => r.progress },
      { k: "attn", label: "Status", html: r => { const a = runAttention(r); return a.length ? `<span class="st">${dot(a[0][0])}${esc(a[0][1])}</span>` : `<span class="st">${dot("ok")}On track</span>`; }, sort: r => runAttention(r).length },
      { k: "created", label: "Started", html: r => `<span class="nowrap">${ago(r.created)}</span>` },
    ], { onRow: r => (location.hash = "#runs/" + encodeURIComponent(r.run)), emptyTitle: "No runs yet", emptyBody: "Start one in Claude Code with <code>/lfg:lfg</code> and what you want built." })}</div>`;
};

const FILE_NAMES = { "01-brief.md": "The idea, written up", "02-design.md": "The plan", "tasks.json": "Task list", "04-qa.md": "Test report",
  "ready.json": "Check results", "05-secure.json": "Security check", "05-pentest.json": "Security test", "06-review.json": "Code review",
  "07-shipcheck.json": "Ship check", "COMMIT_MSG.md": "Commit message", "PR_BODY.md": "Pull request text", "progress.md": "Progress notes" };
const fileName = f => FILE_NAMES[f] || (/^03-build-(.+)\.md$/.test(f) ? `Build notes · ${f.slice(9, -3)}` : null);
/* documents in pipeline order: brief, plan, tasks, build notes, tests, checks, security, review, ship, packet, notes */
const FILE_ORDER = ["01-brief.md", "02-design.md", "tasks.json", "03-build-", "04-qa.md", "ready.json", "05-secure.json", "05-pentest.json",
  "06-review.json", "07-shipcheck.json", "COMMIT_MSG.md", "PR_BODY.md", "progress.md"];
const fileRank = f => { const i = FILE_ORDER.findIndex(x => f === x || (x.endsWith("-") && f.startsWith(x))); return i < 0 ? 99 : i; };

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
  return `${head(runName(d), `${d.owner_name ? `Filed under ${esc(d.owner_name)} · ` : ""}${d.branch ? `On branch ${esc(d.branch)} · ` : ""}started ${ago(d.created)}`, '<a class="back" href="#runs">← All runs</a>')}
    ${d.about ? `<p class="about lead">${txt(d.about)}</p>` : ""}
    <div class="panel"><div class="row"><b>${p.finished ? "All steps done" : `${p.done} of ${p.total} steps done`}</b><span class="muted${p.blocked ? " stuck-text" : ""}">${p.finished ? "· the commit message is ready for you to review" : `· next: ${esc(NEXT[p.next])}`}</span></div>
      <div class="progress${p.blocked ? " stuck" : p.finished ? " done" : ""}"><span style="width:${pct(p.done, p.total)}%"></span></div>${steps}</div>
    ${attn.length ? section("Needs your attention", `<div class="callout ${attn.some(a => a[0] === "bad") ? "bad" : "warn"}"><ul class="attn">${attn.map(([tn, text]) => `<li>${dot(tn)}<span class="grow">${esc(text)}</span></li>`).join("")}</ul></div>`) : ""}
    ${tasks ? section("Tasks", tasks, `${d.tasks.done} of ${d.tasks.total} done · click one for its steps`) : ""}
    ${checks ? section("Checks", d.ready === "stale" && d.checks.length ? `<p class="muted small">These ran ${ago(d.checked_at)}, before the latest work on this run, so they may no longer hold. Run <code>/lfg:check</code> for a fresh result.</p>${checks}` : checks, d.ready === "stale" ? "out of date" : "click a failed one to see why") : d.owner_name ? section("Checks", `<p class="muted small">This run's checks run in ${esc(d.owner_name)}, on its code, so they aren't shown here.</p>`) : ""}
    ${files.length ? section("Documents", `<div class="box"><ul class="list">${files.map(f => `<li><a href="#" class="grow" data-run-file='${esc(JSON.stringify([f.run, f.name]))}'>${esc(f.label)}</a><span class="muted small nowrap" title="${esc(f.mtime)}">${ago(f.mtime.replace(" ", "T"))}</span></li>`).join("")}</ul></div>`) : ""}`;
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

PAGES.checks = async () => {
  const [r, s] = await Promise.all([api("reviews"), api("security")]);
  const last = s.secure[0], ship = s.shipcheck[0], rev = r.verdicts[0];
  const open = r.findings.filter(f => !f.feedback);
  const sum = `<div class="cols">${stat("Latest code review", rev ? say(rev.verdict)[0] : "None yet", rev ? plural(rev.findings, "finding") : "run <code>/lfg:expert</code>")}${stat("Latest security check", last ? say(last.verdict)[0] : "None yet", last ? (last.blocking ? `${plural(last.blocking, "problem")} to fix` : "nothing blocking") : "run <code>/lfg:secure</code>")}${stat("Latest ship check", ship ? (ship.pass ? "Passed" : "Failed") : "None yet", ship ? `${ship.ok} of ${ship.total} checks passed${(ship.manual || []).length ? ` · ${ship.manual.length} for you to do` : ""}` : "run <code>/lfg:ship</code>")}</div>`;
  const sevSort = { blocker: 0, critical: 0, high: 1, major: 1, medium: 2, minor: 3, low: 3, nit: 4 };
  return `${head("Checks", "What the code reviews and security checks found, and the actions LFG stopped to keep your work safe.")}
    ${sum}
    <div class="section">${tabs("checks", [
      ["review", "Review findings", r.findings.length, () => `<div class="box">${table(r.findings, [
        { k: "severity", label: "How serious", html: x => st(x.severity), sort: x => -(sevSort[String(x.severity).toLowerCase()] ?? 5) },
        { k: "message", label: "Finding", html: x => `${txt(x.title || x.finding || x.message || x.id)}${x.fix ? `<div class="sub clamp">What to do: ${txt(x.fix)}</div>` : ""}${x.file ? `<div class="sub mono">${esc(x.file)}${x.line ? ":" + esc(x.line) : ""}</div>` : ""}<div class="sub">from <a href="#runs/${encodeURIComponent(x.run)}">${esc(runName({ slug: String(x.run || "").slice(14) }))}</a></div>` },
        { k: "feedback", label: "Your call", html: x => st(x.feedback, "not decided") }], { onRow: x => openDrawer("Review finding", `<div class="readable">${findingCard(x)}</div>`), emptyTitle: "No findings", emptyBody: "Run <code>/lfg:expert</code> on a change." })}</div>${open.length ? `<p class="muted small">Record your call with <code>lfg feedback add &lt;id&gt; accept|reject</code>.</p>` : ""}`],
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
      ["stopped", "Stopped actions", r.blocked.length, () => `<p class="muted">Actions an agent tried that break a rule, so LFG stopped them. Nothing here needs you; it shows the guard working.</p><div class="box">${table(r.blocked, [{ k: "why", label: "What was stopped", html: x => esc(x.why || x.tool) }, { k: "rule", label: "Rule", html: x => `rule ${esc(x.rule)}` }, { k: "ts", label: "When", html: x => `<span class="nowrap">${ago(x.ts)}</span>` }])}</div>`],
    ])}</div>`;
};

PAGES.code = async () => {
  const [c, a] = await Promise.all([api("code"), api("architecture")]);
  const g = await api("graphs");
  const [gText, gTone] = say(g.status);
  const mapRow = `<div class="box pad row">${dot(gTone)}<div class="grow"><b>${esc(repoName())} code map: ${esc((gText || "unknown").toLowerCase())}</b><div class="meta">${g.status === "syncing" ? "Building in the background. This page updates when it's done." : g.synced_at ? `Updated ${ago(g.synced_at)}${g.seconds ? ` in ${Math.round(g.seconds)}s` : ""}.` : "Not built yet."}${g.error ? ` Last error: ${esc(String(g.error).slice(0, 200))}` : ""}</div></div>
    ${mapBtn(g.status)}${g.status !== "missing" && g.status !== "syncing" ? '<button class="btn small" data-map-build="rebuild">Rebuild from scratch</button><button class="btn small" data-map-build="docs" title="Wikis, call flows and playbooks">Refresh docs</button>' : ""}</div>`;
  if (c.available === false && a.available === false) return `${head("Code", "LFG keeps a map of this project so agents read only the parts that matter.")}${mapRow}
    ${g.status === "syncing" ? "" : empty("No code map yet", "Build it now. It runs in the background on this computer and usually takes a minute or two.")}`;
  let summary = "";
  if (c.available !== false) {
    const cov = pct(c.coverage.tested, c.coverage.tested + c.coverage.untested);
    summary = `${n(c.nodes.File)} code files, ${n((c.nodes.Function || 0) + (c.nodes.Class || 0))} functions and classes; code-review-graph links ${cov}% of them to a test.`;
  }
  const risky = c.available !== false ? (c.hotspots || []).slice(0, 10) : [];
  const areas = a.available !== false ? a.community_list.slice(0, 12) : [];
  const notes = a.available !== false ? a.rationale : [];
  return `${head("Code", `LFG keeps a map of this project so agents read only the parts that matter. ${summary}`)}
    ${mapRow}
    ${risky.length ? section("Where changes are riskiest", `<div class="box">${table(risky, [
      { k: "symbol", label: "Code", html: r => `${esc(r.symbol)}<div class="sub">${esc(r.file)}</div>` },
      { k: "callers", label: "Used by", num: true, html: r => plural(r.callers, "place") },
      { k: "coverage", label: "Tested", html: r => (r.coverage === "tested" ? `${dot("ok")} Yes` : `${dot("warn")} No`) }], { filter: false })}</div>`, "used in many places, so a change here reaches far") : ""}
    ${areas.length ? section("Main parts of the code", `<div class="box"><ul class="list">${areas.map(x => `<li><div class="grow"><div class="title">${esc(x.name)}</div><div class="meta">${esc((x.files || []).slice(0, 3).join(" · "))}</div></div></li>`).join("")}</ul></div>`) : ""}
    ${notes.length ? section("Why the code is the way it is", `<div class="box">${table(notes, [{ k: "note", label: "Explanation" }, { k: "file", label: "Where", html: r => `<span class="small muted mono nowrap">${esc(r.file + (r.line ? ":" + r.line : ""))}</span>` }])}</div>`, `docstrings and WHY / NOTE / HACK comments${a.rationale_total > notes.length ? `, first ${notes.length} of ${n(a.rationale_total)}` : ""}`) : ""}
    ${section("Explore", `<div class="row"><button class="btn" data-view="architecture" data-target="explore">Map of the code</button><button class="btn" data-view="callflow" data-target="explore">How calls flow</button><button class="btn" data-view="code" data-target="explore">Detailed code graph</button><button class="btn" data-view="health" data-target="explore">Health report</button></div><div id="explore"></div>`)}`;
};

const DOC_SHOWN = 12;
PAGES.docs = async arg => {
  const d = await api("docs");
  if (d.available === false) return unavailable(d);
  const parts = (arg || "").split("/");
  let src = parts[0], path = decodeURIComponent(parts.slice(1).join("/"));
  const first = d.groups.find(g => g.items.length);
  if (!src && first) { src = first.id; path = first.items[0].path; }
  const nav = d.groups.filter(g => g.items.length).map(g => `<div class="grp"><span>${esc(g.title)}</span><span>${g.items.length}</span></div>
    <div data-grp="${esc(g.id)}">${g.items.map((it, i) => `<a href="#docs/${esc(g.id)}/${encodeURIComponent(it.path)}" class="${g.id === src && it.path === path ? "on" : ""}${i >= DOC_SHOWN && !(g.id === src && it.path === path) ? " extra" : ""}" title="${esc(it.title)}">${esc(it.title)}</a>`).join("")}${g.items.length > DOC_SHOWN ? `<a href="#" class="more" data-doc-more>Show all ${g.items.length}</a>` : ""}</div>`).join("");
  let body = empty("No docs yet", "LFG writes them from the code map automatically. They'll appear after the next update.");
  if (src && path) {
    const doc = await api("doc", { src, path });
    body = doc.text === "not found" ? empty("Document not found", "") : `<div class="md">${md(doc.text, true)}</div>`;
  }
  return `${head("Docs", "Guides and runbooks written from the code, kept up to date as it changes.")}
    <div class="docs"><div class="box doc-nav"><div class="table-tools"><input type="search" id="doc-filter" placeholder="Search docs…"></div>${nav}</div>
    <div class="box" id="doc-body" data-src="${esc(src || "")}" data-path="${esc(path || "")}">${body}</div></div>`;
};

/* Knowledge: what LFG has saved, each item with a repo, a feature and a topic, fuzzy search and Ask. */
const KINDS = {
  decision: ["Decisions", "Choices made while building something, and why: \"the queue auto-starts and can be cancelled\". Kept so nobody re-argues them. Usually about one repo and one feature."],
  learning: ["Lessons", "Things found out the hard way: gotchas, root causes, how to run or deploy something. The kind of thing you'd tell a teammate before they start."],
  rule: ["Rules", "Always/never rules and things that must stay true, which agents check their work against."],
  note: ["Your notes", "Personal notes and preferences in second-brain, not tied to a repo. How you like to work, ideas, questions."],
};
const TOPIC = { setup: "Setup and environment", gotcha: "Gotcha", incident_review: "Incident review", retro: "Retro", hindsight: "Hindsight" };
/* Fuzzy match: every word of the query must appear, as a substring or as letters in order, in the item's text. */
function fuzzy(q, text) {
  if (!q) return 1;
  const t = text.toLowerCase();
  let score = 0;
  for (const w of q.toLowerCase().split(/\s+/).filter(Boolean)) {
    if (t.includes(w)) { score += 2; continue; }
    let i = 0;
    for (const c of t) if (c === w[i]) i++;
    if (i === w.length) score += 1; else return 0;
  }
  return score;
}
PAGES.knowledge = async () => {
  const [k, b, unlocked] = await Promise.all([api("knowledge"), api("brain"), isUnlocked()]);
  const K = k.available === false ? { decisions: [], principles: [], invariants: [], unheld: [], gaps: [], learnings: [] } : k;
  const B = b.available === false ? { notes: [], preferences: [] } : b;
  const unheld = new Set((K.unheld || []).map(r => r.slug));
  const part = (label, v) => v ? `<h3>${label}</h3><div class="md">${md(String(v))}</div>` : "";
  const sheet = (title, tags, body) => [title, `<div class="readable"><p>${tags}</p>${body}</div>`];
  const note = r => sheet(r.name || words(r.slug), `${r.kind ? `<span class="tag">${esc(words(r.kind))}</span>` : ""} ${r.when ? `<span class="muted small">${ago(r.when)}</span>` : ""}`,
    `${r.content ? `<div class="md">${md(String(r.content))}</div>` : '<p class="muted">No text was saved with this note.</p>'}${r.tags && String(r.tags) !== "[]" ? `<p class="muted small">Tags: ${esc(String(r.tags).replace(/[[\]']/g, ""))}</p>` : ""}`);
  const dec = r => sheet(r.title, `${st(r.status)} <span class="muted small">${ago(r.createdAt)}</span>`, `${part("Why it came up", r.context)}${part("What was decided", r.decision)}${part("What follows from it", r.consequences)}`);
  const lrn = r => sheet(r.title, `${r.learningKind ? `<span class="tag">${esc(words(r.learningKind))}</span>` : ""} <span class="muted small">${ago(r.createdAt)}</span>`, r.body ? `<div class="md">${md(String(r.body))}</div>` : '<p class="muted">No text was saved with this lesson.</p>');
  const rule = r => sheet(r.text, `<span class="tag">${esc(r.kind)}</span> ${st(r.s)}`, `${part("Why", r.why)}${part("Do this instead", r.alt)}${part("Checked by", r.guard)}${part("Where it comes from", r.spec)}`);
  const items = [
    ...K.decisions.map(r => ({ ...r, kind: "decision", text: [r.decision, r.context].filter(Boolean).join(" "), when: r.createdAt, detail: () => dec(r) })),
    ...K.learnings.map(r => ({ ...r, kind: "learning", text: r.body || "", when: r.createdAt, detail: () => lrn(r) })),
    ...K.principles.map(p => ({ slug: p.slug, kind: "rule", title: (p.polarity === "forbids" ? "Never: " : "Always: ") + p.statement, text: p.rationale || "", status: p.status,
      detail: () => rule({ text: p.statement, why: p.rationale, s: p.status, kind: p.polarity === "forbids" ? "Never" : "Always", alt: p.correctAlternative, spec: p.specRef }) })),
    ...K.invariants.map(i => ({ slug: i.slug, kind: "rule", title: "Must stay true: " + i.statement, text: "", status: unheld.has(i.slug) ? "unheld" : i.status,
      detail: () => rule({ text: i.statement, s: unheld.has(i.slug) ? "unheld" : i.status, kind: "Must stay true", guard: i.guardRef, spec: i.specRef }) })),
    ...[...B.notes].map(n => ({ slug: n.slug, kind: "note", title: n.name || words(n.slug), text: String(n.content || ""), when: n.createdAt, topic: n.kind, detail: () => note({ ...n, when: n.createdAt }) })),
  ];
  state.knowledge = items;
  const F = state.kf || (state.kf = { q: "", kind: "", repo: "", feature: "", topic: "" });
  const opts = key => [...new Set(items.map(i => i[key]).filter(Boolean))].sort();
  const shown = items.map(i => [i, fuzzy(F.q, [i.title, i.text, i.repo, i.feature, (i.tickets || []).join(" "), TOPIC[i.topic] || i.topic].join(" "))])
    .filter(([i, s]) => s && (!F.kind || i.kind === F.kind) && (!F.repo || i.repo === F.repo) && (!F.feature || i.feature === F.feature) && (!F.topic || i.topic === F.topic))
    .sort((a, b) => b[1] - a[1] || String(b[0].when || "").localeCompare(String(a[0].when || ""))).map(([i]) => i);
  const sel = (key, label, values, names = {}) => `<label class="small muted">${label} <select data-kf="${key}"><option value="">All</option>${values.map(v => `<option value="${esc(v)}" ${F[key] === v ? "selected" : ""}>${esc(names[v] || v)}</option>`).join("")}</select></label>`;
  const guessed = (i, f) => (i.guessed || []).includes(f) ? ' title="Filled in by LFG from the ticket it came from; set your own with Tag"' : "";
  const KN = state.know = shown.slice(0, 300).map(i => i.detail);
  const line = (i, n) => `<li class="sess"><div class="grow click" data-kn="${n}" tabindex="0"><div class="title">${esc(i.title || "")}</div>
      ${i.text ? `<div class="meta clamp">${esc(i.text.slice(0, 400))}</div>` : ""}
      <div class="meta"><span class="tag">${esc(KINDS[i.kind][0].replace(/s$/, ""))}</span>${i.repo ? ` <span class="tag"${guessed(i, "repo")}>${esc(i.repo)}</span>` : ""}${i.feature ? ` <span class="tag"${guessed(i, "feature")}>${esc(i.feature.slice(0, 48))}</span>` : ""}${i.topic && TOPIC[i.topic] ? ` <span class="tag"${guessed(i, "topic")}>${esc(TOPIC[i.topic])}</span>` : ""}${(i.tickets || []).length ? ` · ${esc(i.tickets.join(", "))}` : ""}${i.when ? ` · ${ago(i.when)}` : ""}${i.status && i.status !== "accepted" && i.status !== "active" ? ` · ${st(i.status)}` : ""}</div></div>
      ${["decision", "learning"].includes(i.kind) ? `<button class="btn small" data-ktag="${esc(i.slug)}" ${unlocked ? "" : "disabled"}>Tag</button>` : ""}</li>`;
  const missing = [k, b].filter(x => x.available === false).map(x => `<div class="callout warn">${fmtWhy(x.why)}</div>`).join("");
  return `${head("Knowledge", "What Claude has saved while working with you. Agents read it before they start, so they don't repeat old mistakes or re-argue settled choices.")}
    ${missing}
    <div class="cols">${Object.entries(KINDS).map(([kk, [t, about]]) => `<a href="#" class="box pad stat-link ${F.kind === kk ? "on" : ""}" data-kkind="${kk}"><div class="k" style="margin-top:0">${t} · ${items.filter(i => i.kind === kk).length}</div><p class="muted small">${about}</p></a>`).join("")}</div>
    <div class="panel mt"><div class="row"><input type="text" id="k-ask" class="grow" placeholder="Ask: how do I run atomus-local-mcp locally? what did we decide about the run queue?"><button class="btn primary" id="k-askgo" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to ask\""}>Ask</button></div><div id="k-answer"></div></div>
    <div class="table-tools mt"><input type="search" id="k-find" placeholder="Search everything (typos are fine)…" value="${esc(F.q)}">${sel("repo", "Repo", opts("repo"))}${sel("feature", "Feature", opts("feature"))}${sel("topic", "Topic", Object.keys(TOPIC).filter(t => items.some(i => i.topic === t)), TOPIC)}<span class="count">${plural(shown.length, "item")}</span></div>
    ${shown.length ? `<ul class="items box">${shown.slice(0, 300).map(line).join("")}</ul>` : empty("Nothing matches", "Try fewer words, or clear a filter.")}
    <p class="muted small">Repo and feature come from the ticket each item was saved under; a hover on a tag says when LFG filled it in. Tag sets your own, which always wins. To save something, tell Claude "remember that…" or use <code>/lfg:note</code>; things every session must know, like how to reach prod, belong in your CLAUDE.md instead.</p>`;
};
function wireKnowledge(root) {
  const F = state.kf;
  const find = $("#k-find", root);
  let t;
  if (find) find.oninput = () => { clearTimeout(t); t = setTimeout(() => { F.q = find.value; route().then(() => { const f = $("#k-find"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 200); };
  $$("[data-kf]", root).forEach(s => s.onchange = () => { F[s.dataset.kf] = s.value; route(); });
  $$("[data-kkind]", root).forEach(a => a.onclick = e => { e.preventDefault(); F.kind = F.kind === a.dataset.kkind ? "" : a.dataset.kkind; route(); });
  const go = $("#k-askgo", root), q = $("#k-ask", root);
  const ask = async () => {
    if (!q.value.trim()) return q.focus();
    go.disabled = true; go.textContent = "Asking…";
    const r = await save("knowledge_ask", { question: q.value });
    go.disabled = false; go.textContent = "Ask";
    const box = $("#k-answer");
    if (!r.ok) { box.innerHTML = `<p class="bad-tx small">${esc(r.why || "")}</p>`; return; }
    const by = Object.fromEntries((state.knowledge || []).map(i => [i.slug, i]));
    box.innerHTML = `<p class="mt">${esc(r.answer)}</p>${(r.slugs || []).length ? `<div class="k">From</div><ul class="list">${r.slugs.map(sl => `<li>${esc((by[sl] || {}).title || sl)} <span class="muted small">${esc(KINDS[(by[sl] || {}).kind]?.[0] || "")}</span></li>`).join("")}</ul>` : ""}`;
  };
  if (go) go.onclick = ask;
  if (q) q.onkeydown = e => { if (e.key === "Enter") ask(); };
  $$("[data-ktag]", root).forEach(b => b.onclick = () => {
    const i = (state.knowledge || []).find(x => x.slug === b.dataset.ktag) || {};
    const opts = key => [...new Set((state.knowledge || []).map(x => x[key]).filter(Boolean))].sort();
    openDrawer("Tag: " + (i.title || i.slug), `<div class="readable"><p class="muted">Stored in LFG only; the saved item itself doesn't change. Leave a box empty to go back to what LFG filled in.</p>
      <label class="k">Repo</label><input type="text" id="kt-repo" class="wide" list="kt-repos" value="${esc(i.repo || "")}"><datalist id="kt-repos">${opts("repo").map(v => `<option value="${esc(v)}">`).join("")}</datalist>
      <label class="k">Feature</label><input type="text" id="kt-feature" class="wide" list="kt-features" value="${esc(i.feature || "")}"><datalist id="kt-features">${opts("feature").map(v => `<option value="${esc(v)}">`).join("")}</datalist>
      ${i.kind === "learning" ? `<label class="k">Topic</label><select id="kt-topic"><option value="">(LFG's guess)</option>${Object.entries(TOPIC).map(([v, l]) => `<option value="${v}" ${i.topic === v && !(i.guessed || []).includes("topic") ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>` : ""}
      <div class="set-actions"><button class="btn primary" id="kt-save">Save</button><span class="save-msg" id="kt-msg"></span></div></div>`);
    $("#kt-save").onclick = async () => {
      const body = { slug: i.slug, repo: $("#kt-repo").value, feature: $("#kt-feature").value };
      if ($("#kt-topic")) body.topic = $("#kt-topic").value;
      const r = await save("knowledge_tag", body);
      saidMsg($("#kt-msg"), r, "Saved.");
      if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400);
    };
  });
}
/* Preferences: your rules for Claude. Defaults here; one session's changes from Sessions → Rules. */
function prefControls(P, values, defaults, scope, unlocked) {
  const groups = {};
  for (const p of P.catalog) if (!p.shown_if || values[p.shown_if[0]] === p.shown_if[1]) (groups[p.group] = groups[p.group] || []).push(p);
  const changed = p => scope && values[p.id] !== defaults[p.id];
  const ctl = p => {
    const v = values[p.id], dis = unlocked ? "" : "disabled";
    const told = t => t ? `<details class="told"><summary>What Claude is told</summary><p class="small mono">${esc(t)}</p></details>` : "";
    if (p.kind === "number") return `<label class="row"><input type="number" class="num" min="${p.min || 0}" max="${p.max || ""}" value="${esc(v)}" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' ${dis}> <span>${esc(p.unit || "")}</span></label>${p.about ? `<p class="small">${esc(p.about)}</p>` : ""}`;
    if (p.kind === "switch") return `<label class="row"><input type="checkbox" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' ${v ? "checked" : ""} ${dis}> <span>${v ? "On" : "Off"}</span></label>${p.about ? `<p class="small">${esc(p.about)}</p>` : ""}${told(v ? p.text : p.off_text)}`;
    return `<div class="opts">${p.options.map(o => `<label class="opt ${o.value === v ? "on" : ""}"><input type="radio" name="pref-${esc(p.id)}${scope ? "-" + esc(scope) : ""}" data-pref='${esc(JSON.stringify([p.id, scope || ""]))}' value="${esc(o.value)}" ${o.value === v ? "checked" : ""} ${dis}><span><b>${esc(o.label)}</b>${o.about ? `<span class="small muted">${esc(o.about)}</span>` : ""}</span></label>`).join("")}</div>${told((p.options.find(o => o.value === v) || {}).text)}`;
  };
  return Object.entries(groups).map(([g, ps]) => section(g, `<div class="pref-grid">${ps.map(p => `<div class="box pad pref ${changed(p) ? "changed" : ""}"><div class="row"><b class="grow">${esc(p.title)}</b>${p.enforce ? '<span class="tag" title="LFG checks every command against it, so Claude can\'t break it even by mistake">blocked if broken</span>' : '<span class="tag" title="Claude is told to follow it; nothing checks it">Claude is asked</span>'}${changed(p) ? ' <span class="tag warn">this session</span>' : ""}${p.custom && !scope && unlocked ? ` <a href="#" class="small" data-pref-rm="${esc(p.id)}">Remove</a>` : ""}</div>${ctl(p)}</div>`).join("")}</div>`)).join("");
}
function prefToast(msg, bad) {
  let t = $("#pref-toast");
  if (!t) { t = document.createElement("div"); t.id = "pref-toast"; document.body.appendChild(t); }
  t.className = bad ? "bad" : "";
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), 5000);
}
function wirePrefs(root, after) {
  $$("[data-pref]", root).forEach(el => el.onchange = async () => {
    const [id, session] = JSON.parse(el.dataset.pref);
    const value = el.type === "checkbox" ? el.checked : el.type === "number" ? Number(el.value) : el.value;
    const r = await save("pref_set", { id, value, session: session || null });
    if (!r.ok) { prefToast("Not saved: " + (r.why || "error"), true); after(); return; }
    prefToast(session ? "Saved for this session. It takes effect with your next message there." : "Saved. New sessions start with it; open sessions pick it up with your next message.");
    await after();
    const card = $(`[data-pref^='["${id}"']`)?.closest(".pref");
    if (card) { card.classList.add("just-saved"); setTimeout(() => card.classList.remove("just-saved"), 1600); }
  });
  $$("[data-pref-rm]", root).forEach(a => a.onclick = async e => { e.preventDefault(); const r = await save("pref_remove", { id: a.dataset.prefRm }); if (r.ok) after(); });
}
PAGES.prefs = async () => {
  const [P, unlocked] = await Promise.all([api("prefs"), isUnlocked()]);
  const I = P.installed || {};
  const on = I.hooks && I.import;
  const banner = on ? "" : `<div class="callout warn">${dot("warn")}<span><b>Your rules aren't switched on yet.</b> This adds three small hooks to <code>~/.claude/settings.json</code> (one gives each session its rules, one checks commands before they run) and one line to your CLAUDE.md that reads the rules file. Both are backed up and listed under Settings → Claude Code, where they can be undone.</span> <button class="btn small primary" id="prefs-install" ${unlocked ? "" : "disabled"}>Switch on</button></div>`;
  return `${head("Preferences", "Your rules for Claude. These are the defaults every new session starts with; Sessions → Rules changes them for one session. Enforced rules are checked before every command, so Claude keeps them even by mistake; the rest are instructions.")}
    ${banner}
    ${on ? `<div class="callout ok">${dot("ok")}<span><b>Changes apply to sessions already open, no restart needed.</b> Enforced rules are checked on the very next command; open sessions are told about any change with your next message to them.</span></div>` : ""}
    ${unlocked ? "" : `<div class="callout">Read-only. Run <code>lfg ui</code> in your terminal to change your rules here.</div>`}
    ${prefControls(P, P.defaults, P.defaults, null, unlocked)}
    <div class="box pad mt"><div class="k" style="margin-top:0">When a change takes effect</div>
      <ul class="small"><li><b>Enforced rules</b> apply at once, in every session, open or new: the next command is checked against them.</li>
      <li><b>Instructions</b> reach new sessions when they start, and sessions already open with your next message in them. Nothing to restart.</li>
      <li>Claude can make a session stricter, never looser. Loosening is yours: here, or <code>! lfg prefs set &lt;id&gt; &lt;value&gt; --by-user</code> in Claude Code.</li></ul>
      <p class="muted small">Your defaults are written to <code>${esc(P.file)}</code>, which your CLAUDE.md reads.</p></div>`;
};
function wirePrefsPage(root) {
  const b = $("#prefs-install", root);
  if (b) b.onclick = async () => { b.disabled = true; const r = await save("prefs_install", {}); if (!r.ok) { b.disabled = false; return alertMsg(b, r); } softRoute(); };
  wirePrefs(root, softRoute);
}
async function sessionRules(sid) {
  const s = (state.sessions.sessions || []).find(x => x.id === sid) || {};
  const draw = async () => {
    const [P, unlocked] = await Promise.all([api("prefs", { session: sid }), isUnlocked()]);
    const n = Object.keys(P.overrides || {}).length;
    openDrawer(`Rules: ${s.name || sid}`, `<div class="readable"><p class="muted">Starts from your defaults (Preferences). What you change here is for this session only and reaches it with your next message.${n ? ` <b>${plural(n, "rule")} differ${n === 1 ? "s" : ""} from your defaults.</b> <button class="btn small" id="sr-reset">Back to defaults</button>` : ""}</p>
      ${(P.installed || {}).hooks ? "" : `<div class="callout warn">Your rules aren't switched on yet, so a session can't get its own. Switch them on under Preferences.</div>`}
      ${prefControls(P, P.values, P.defaults, sid, unlocked)}</div>`);
    wirePrefs($("#drawer-body"), draw);
    const r = $("#sr-reset");
    if (r) r.onclick = async () => { await save("pref_clear", { session: sid }); draw(); };
  };
  draw();
}
/* Sessions: every Claude Code session on this machine, grouped repo → ticket/branch (or your folder). */
PAGES.sessions = async () => {
  const [d, unlocked] = await Promise.all([api("sessions", state.showHidden ? { hidden: "1" } : {}), isUnlocked()]);
  state.sessions = d;
  const q = (state.sessionFind || "").toLowerCase();
  const hit = s => !q || [s.name, s.repo, s.worktree, s.branch, s.ticket, s.folder, s.first, s.cwd].join(" ").toLowerCase().includes(q);
  const rows = d.sessions.filter(hit);
  const byRepo = new Map();
  for (const s of rows) {
    const repo = s.folder ? "Your groups" : s.repo || "Other";
    if (!byRepo.has(repo)) byRepo.set(repo, new Map());
    const g = byRepo.get(repo);
    if (!g.has(s.group)) g.set(s.group, []);
    g.get(s.group).push(s);
  }
  const line = s => `<li class="sess" data-sid="${esc(s.id)}"><div class="grow"><div class="title">${esc(s.name)}${s.named ? "" : ' <span class="tag" title="You haven\'t named it (/rename in Claude Code, or Rename here); this name is made up from its ticket, branch and first message">not named</span>'}</div>
      <div class="meta">${ago(s.modified)} · ${plural(s.prompts, "message")}${s.worktree ? ` · worktree <span class="mono">${esc(s.worktree)}</span>` : ""}${s.branch && s.group !== s.branch ? ` · <span class="mono">${esc(s.branch)}</span>` : ""}${s.app ? " · desktop app" : ""}${s.cost != null ? ` · ${usd(s.cost)}` : ""}${s.folder_exists ? "" : ` · <span class="bad-tx">its folder is gone</span>`}</div></div>
      <button class="btn small primary" data-copy="${esc(s.resume)}" title="${esc(s.resume)}">Copy resume command</button>
      <button class="btn small" data-sess-rules="${esc(s.id)}">Rules</button>
      <button class="btn small" data-sess-name="${esc(s.id)}" ${unlocked ? "" : "disabled"}>Rename</button>
      ${s.folder ? `<span class="tag" title="Your group">${esc(s.folder)} <a href="#" data-sess-ungroup="${esc(s.id)}" title="Take it out of this group" aria-label="Take it out of ${esc(s.folder)}">✕</a></span>` : ""}
      <button class="btn small" data-sess-folder="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Group sessions your own way, e.g. one feature across repos. Only LFG stores this; nothing on disk moves.">${s.folder ? "Change group" : "Group…"}</button>
      <button class="btn small" data-sess-hide='${esc(JSON.stringify([s.id, !s.hidden]))}' ${unlocked ? "" : "disabled"}>${s.hidden ? "Show again" : "Hide"}</button>
      <button class="btn small" data-sess-trash="${esc(s.id)}" ${unlocked ? "" : "disabled"} title="Move this session's file to the Trash">Delete</button></li>`;
  const groups = [...byRepo].map(([repo, g]) => section(repo, [...g].map(([name, ss]) => `<details class="item" ${q || byRepo.size === 1 || ss.some(s => Date.now() - Date.parse(s.modified) < 3 * 864e5) ? "open" : ""}><summary><span class="grow"><b>${esc(name)}</b></span><span class="muted small nowrap">${plural(ss.length, "session")} · ${ago(ss[0].modified)}</span>${repo !== "Your groups" && unlocked ? ` <button class="btn small" data-sess-done='${esc(JSON.stringify([repo, name]))}' title="Hide these sessions and clean up their worktrees">Done with this</button>` : ""}</summary><ul class="items sess-list">${ss.map(line).join("")}</ul></details>`).join(""), plural([...g.values()].flat().length, "session")));
  const lock = unlocked ? "" : `<div class="callout warn">Rename, groups and delete are locked. Run <code>lfg ui --unlock</code> in your terminal to change them here. Copy works either way.</div>`;
  return `${head("Sessions", "Every Claude Code session on this machine, whichever folder you started it in. Copy a resume command and paste it in any terminal: it opens the right folder and picks the session back up.")}
    ${lock}
    <div class="table-tools"><input type="search" id="sess-find" placeholder="Search names, tickets, branches, repos…" value="${esc(state.sessionFind || "")}"><span class="count">${plural(rows.length, "session")}${q ? ` of ${d.sessions.length}` : ""}</span>${d.hidden_count ? `<label class="small"><input type="checkbox" id="sess-hidden" ${state.showHidden ? "checked" : ""}> Show ${plural(d.hidden_count, "hidden session")}</label>` : ""}</div>
    ${rows.length ? groups.join("") : empty("No sessions match", q ? "Try a ticket number, a branch or a repo name." : "No Claude Code sessions found in " + esc(d.projects_dir))}`;
};
function wireSessions(root) {
  const find = $("#sess-find", root);
  if (find) {
    let t;
    find.oninput = () => { clearTimeout(t); t = setTimeout(() => { state.sessionFind = find.value; route().then(() => { const f = $("#sess-find"); if (f) { f.focus(); f.setSelectionRange(f.value.length, f.value.length); } }); }, 250); };
  }
  $$("[data-copy]", root).forEach(b => b.onclick = async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    setTimeout(() => (b.textContent = "Copy resume command"), 1500);
  });
  const setGroup = async (sid, folder, msgEl) => {
    const r = await save("session_folder", { id: sid, folder });
    if (msgEl) saidMsg(msgEl, r, folder ? `Added to ${folder}.` : "Taken out.");
    if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400);
    return r;
  };
  const ask = (sid, kind) => {
    const s = (state.sessions.sessions || []).find(x => x.id === sid) || {};
    const groups = state.sessions.folders || [];
    if (kind === "name") {
      openDrawer("Rename session", `<div class="readable"><p>Shown in LFG only; Claude Code's own title is left alone. Leave it empty to go back to the automatic name: <i>${esc(s.auto_name || "")}</i>.</p>
        <input type="text" id="sess-val" class="wide" value="${esc(s.name !== s.auto_name ? s.name : "")}" placeholder="${esc(s.auto_name || "")}">
        <div class="set-actions"><button class="btn primary" id="sess-save">Save</button><span class="save-msg" id="sess-msg"></span></div></div>`);
      const go = async () => { const r = await save("session_name", { id: sid, name: $("#sess-val").value }); saidMsg($("#sess-msg"), r, "Saved."); if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 400); };
      $("#sess-save").onclick = go;
      $("#sess-val").onkeydown = e => { if (e.key === "Enter") go(); };
      $("#sess-val").focus();
      return;
    }
    openDrawer("Put this session in a group", `<div class="readable">
      <p>Groups are your own way of sorting sessions, for example one feature that spans several repos. They live in LFG only: no file or folder on disk moves, and <code>/resume</code> is unchanged. A session is in at most one group.</p>
      ${s.folder ? `<p>Now in <b>${esc(s.folder)}</b>. <button class="btn small" id="grp-out">Take it out</button></p>` : ""}
      ${groups.filter(g => g !== s.folder).length ? `<div class="k">Your groups</div><div class="row wrap">${groups.filter(g => g !== s.folder).map(g => `<button class="btn small" data-grp="${esc(g)}">${esc(g)}</button>`).join("")}</div>` : ""}
      <div class="k">New group</div>
      <div class="row"><input type="text" id="grp-new" class="grow" placeholder="e.g. ATO-4162 rollout" maxlength="80"><button class="btn primary" id="grp-make">Create and add</button></div>
      <span class="save-msg" id="sess-msg"></span></div>`);
    $$("[data-grp]").forEach(b => b.onclick = () => setGroup(sid, b.dataset.grp, $("#sess-msg")));
    const out = $("#grp-out");
    if (out) out.onclick = () => setGroup(sid, "", $("#sess-msg"));
    const make = () => {
      const v = $("#grp-new").value.trim();
      if (v.length < 2) { $("#sess-msg").textContent = "Give the group a name of at least 2 characters."; return; }
      setGroup(sid, v, $("#sess-msg"));
    };
    $("#grp-make").onclick = make;
    $("#grp-new").onkeydown = e => { if (e.key === "Enter") make(); };
  };
  $$("[data-sess-ungroup]", root).forEach(a => a.onclick = e => { e.preventDefault(); setGroup(a.dataset.sessUngroup, ""); });
  const hid = $("#sess-hidden", root);
  if (hid) hid.onchange = () => { state.showHidden = hid.checked; route(); };
  $$("[data-sess-hide]", root).forEach(b => b.onclick = async () => {
    const [id, on] = JSON.parse(b.dataset.sessHide);
    b.disabled = true;
    const r = await save("session_hide", { ids: [id], on });
    if (!r.ok) { b.disabled = false; return alertMsg(b, r); }
    route();
  });
  $$("[data-sess-trash]", root).forEach(b => b.onclick = () => {
    const s = (state.sessions.sessions || []).find(x => x.id === b.dataset.sessTrash) || {};
    openDrawer("Delete this session?", `<div class="readable"><p><b>${esc(s.name)}</b></p><p>Its file goes to the macOS Trash, so you can still get it back from there. It disappears from <code>/resume</code>. If you only want it out of this list, use Hide instead.</p>
      <div class="set-actions"><button class="btn primary" id="sess-trash-go">Move to Trash</button><span class="save-msg" id="sess-trash-msg"></span></div></div>`);
    $("#sess-trash-go").onclick = async () => {
      const r = await save("session_trash", { id: s.id });
      saidMsg($("#sess-trash-msg"), r, "Moved to the Trash.");
      if (r.ok) setTimeout(() => { closeDrawer(); route(); }, 700);
    };
  });
  $$("[data-sess-done]", root).forEach(b => b.onclick = async e => {
    e.preventDefault(); e.stopPropagation();
    const [repo, group] = JSON.parse(b.dataset.sessDone);
    openDrawer(`Done with ${group}`, '<div class="skeleton"></div>');
    const d = await api("sessiondone", { repo, group });
    const wts = d.worktrees || [];
    const wtRow = w => `<li><label class="row"><input type="checkbox" data-wt="${esc(w.path)}" ${w.safe ? "checked" : "disabled"}><span class="grow"><span class="mono small">${esc(w.path)}</span><div class="meta">${w.safe ? `nothing would be lost${w.branch ? `; the branch <span class="mono">${esc(w.branch)}</span> is kept` : ""}` : `<span class="bad-tx">kept: ${esc(w.why)}</span>`}</div>${(w.dirty || []).length ? `<pre class="small">${esc(w.dirty.join("\n"))}</pre>` : ""}${(w.unpushed || []).length ? `<pre class="small">${esc(w.unpushed.join("\n"))}</pre>` : ""}</span></label></li>`;
    openDrawer(`Done with ${group}`, `<div class="readable">
      <label class="row"><input type="checkbox" id="done-hide" checked><span>Hide its ${plural(d.sessions.length, "session")} from this page. Their files stay, so <code>/resume</code> still works, and "Show hidden" brings them back.</span></label>
      ${wts.length ? `<div class="k">Worktrees these sessions used</div><p class="muted small">Only ones with nothing uncommitted or unpushed can be deleted. Files git ignores there (node_modules, copied .env files) go with them.</p><ul class="items box">${wts.map(wtRow).join("")}</ul>` : `<p class="muted">None of these sessions ran in a worktree.</p>`}
      <div class="set-actions"><button class="btn primary" id="done-go">Clean up</button><span class="save-msg" id="done-msg"></span></div></div>`);
    $("#done-go").onclick = async () => {
      const go = $("#done-go"), msg = $("#done-msg"), out = [];
      go.disabled = true;
      if ($("#done-hide").checked && d.sessions.length) {
        const r = await save("session_hide", { ids: d.sessions, on: true });
        out.push(r.ok ? `hid ${plural(d.sessions.length, "session")}` : `couldn't hide: ${r.why}`);
      }
      for (const box of $$("[data-wt]:checked")) {
        const r = await save("worktree_remove", { path: box.dataset.wt });
        out.push(r.ok ? `deleted ${box.dataset.wt.split("/").pop()}` : r.why);
      }
      msg.textContent = out.join(" · ") || "Nothing selected.";
      setTimeout(() => { closeDrawer(); route(); }, 1600);
    };
  });
  $$("[data-sess-name]", root).forEach(b => b.onclick = () => ask(b.dataset.sessName, "name"));
  $$("[data-sess-rules]", root).forEach(b => b.onclick = () => sessionRules(b.dataset.sessRules));
  $$("[data-sess-folder]", root).forEach(b => b.onclick = () => ask(b.dataset.sessFolder, "folder"));
}
/* Environment: every repo and worktree on this machine, and what LFG runs in the background. */
const MB = b => b == null ? "?" : b >= 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.round(b / 1e6) + " MB";
PAGES.environment = async () => {
  const [d, unlocked] = await Promise.all([api("environment"), isUnlocked()]);
  if (d.pending) {
    setTimeout(() => { if ((location.hash.slice(1) || "").startsWith("environment")) route(); }, 2500);
    return `${head("Environment", "Every repo and worktree on this computer, and what LFG runs in the background.")}<div class="loading">Looking at every repo and worktree… (about 10 seconds)</div>`;
  }
  if (d.available === false) return unavailable(d);
  state.env = d;
  const S = d.services || {};
  const svc = section("Running in the background", `<ul class="items box">${(S.rows || []).map(r => `<li class="sess"><div class="grow">${dot(r.ok ? "ok" : "bad")}<b>${esc(r.name)}</b> <span class="muted small">${esc(r.detail)}</span></div>${r.ok ? "" : `<button class="btn small" data-copy="${esc(r.fix)}">Copy fix</button>`}</li>`).join("")}${(S.disk || []).map(x => `<li class="sess"><div class="grow muted small">${esc(x.what)}</div><span class="small">${MB(x.bytes)}</span></li>`).join("")}</ul>`);
  const all = d.repos.flatMap(r => r.worktrees.filter(w => !w.main).map(w => Object.assign({ repo: r.name, root: r.root }, w)));
  const old = all.filter(w => w.safe_to_delete && Date.now() - Date.parse(w.last_session || w.touched || 0) > 14 * 864e5);
  const status = w => w.missing ? `<span class="muted">folder already gone</span>` : [w.dirty ? `<span class="bad-tx">${plural(w.dirty, "uncommitted file")}</span>` : "", w.unpushed ? `<span class="bad-tx">${plural(w.unpushed, "commit")} not pushed</span>` : "", !w.dirty && !w.unpushed ? "nothing unsaved" : ""].filter(Boolean).join(" · ");
  const wtLine = w => `<li class="sess"><div class="grow"><div class="title">${esc(w.branch || (w.detached ? "detached at " + w.head : w.head))}${w.ticket && !(w.branch || "").toUpperCase().includes(w.ticket) ? ` <span class="tag">${esc(w.ticket)}</span>` : ""}${w.main ? ' <span class="tag">main checkout</span>' : ""}</div>
      <div class="meta mono">${esc(w.path)}</div>
      <div class="meta">${status(w)}${w.last_session ? ` · last session ${ago(w.last_session)}` : w.touched ? ` · touched ${ago(w.touched)}` : ""}${w.sessions ? ` · ${plural(w.sessions, "session")}` : ""}${w.last_subject ? ` · <span title="${esc(w.last_commit || "")}">${esc(w.last_subject.slice(0, 70))}</span>` : ""}</div></div>
      ${w.missing ? "" : `<button class="btn small" data-copy="cd ${esc(w.path)}">Copy cd</button>`}
      ${w.main || w.missing ? "" : `<button class="btn small" data-wt-del="${esc(w.path)}" ${unlocked && w.safe_to_delete ? "" : "disabled"} title="${w.safe_to_delete ? "Delete this worktree; the branch is kept" : "Has unsaved work, so it can't be deleted from here"}">Delete</button>`}</li>`;
  const repos = d.repos.filter(r => r.worktrees.length > 1 || r.worktrees.some(w => w.dirty || w.unpushed)).map(r => {
    const wt = r.worktrees.filter(w => !w.main), gone = wt.filter(w => w.missing).length;
    const sub = `${plural(wt.length, "worktree")}${gone ? ` · ${gone} already gone` : ""}${r.enabled ? " · LFG on" : ""}`;
    return `<details class="item" ${wt.some(w => w.dirty || w.unpushed) || wt.length <= 5 ? "open" : ""}><summary><span class="grow"><b>${esc(r.name)}</b> <span class="muted small">${sub}</span></span>${gone && unlocked ? `<button class="btn small" data-wt-prune="${esc(r.root)}" title="Forget worktrees whose folders were deleted by hand. No files are touched.">Forget ${gone} gone</button>` : ""}</summary><ul class="items sess-list">${r.worktrees.map(wtLine).join("")}</ul></details>`;
  }).join("");
  const quiet = d.repos.filter(r => r.worktrees.length <= 1 && !r.worktrees.some(w => w.dirty || w.unpushed)).map(r => r.name);
  const lock = unlocked ? "" : `<div class="callout warn">Delete is locked. Run <code>lfg ui</code> in your terminal to open this page unlocked. Copy works either way.</div>`;
  return `${head("Environment", `Every repo and worktree on this computer (${plural(all.length, "worktree")} in ${plural(d.repos.length, "repo")}), and what LFG runs in the background. Checked ${ago(d.checked_at)}.`)}
    ${lock}${svc}
    ${old.length && unlocked ? `<div class="callout">${plural(old.length, "worktree")} have nothing unsaved and no session or change in the last 14 days. <button class="btn small primary" id="wt-old">Review and delete…</button></div>` : ""}
    ${section("Repos and worktrees", repos || empty("No worktrees", "None of your repos has a second worktree."), "worktrees with unsaved work first open")}
    ${quiet.length ? `<p class="muted small">No worktrees and nothing unsaved: ${esc(quiet.join(", "))}.</p>` : ""}`;
};
function wireEnvironment(root) {
  $$("[data-copy]", root).forEach(b => b.onclick = async () => {
    const was = b.textContent;
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    setTimeout(() => (b.textContent = was), 1500);
  });
  const del = async paths => {
    const out = [];
    for (const p of paths) { const r = await save("worktree_remove", { path: p }); out.push(r.ok ? null : `${p.split("/").pop()}: ${r.why}`); }
    return out.filter(Boolean);
  };
  $$("[data-wt-del]", root).forEach(b => b.onclick = () => {
    const p = b.dataset.wtDel;
    openDrawer("Delete this worktree?", `<div class="readable"><p class="mono small">${esc(p)}</p><p>The folder goes, including files git ignores there (node_modules, a copied .env). The branch stays, so you can check it out again any time. LFG checks again just before deleting and refuses if anything is unsaved.</p>
      <div class="set-actions"><button class="btn primary" id="wt-go">Delete worktree</button><span class="save-msg" id="wt-msg"></span></div></div>`);
    $("#wt-go").onclick = async () => { $("#wt-go").disabled = true; const bad = await del([p]); $("#wt-msg").textContent = bad.length ? bad[0] : "Deleted."; if (!bad.length) setTimeout(() => { closeDrawer(); route(); }, 600); };
  });
  $$("[data-wt-prune]", root).forEach(b => b.onclick = async e => {
    e.preventDefault(); e.stopPropagation(); b.disabled = true;
    const r = await save("worktree_prune", { root: b.dataset.wtPrune });
    if (!r.ok) { b.disabled = false; return alertMsg(b, r); }
    route();
  });
  const oldBtn = $("#wt-old", root);
  if (oldBtn) oldBtn.onclick = () => {
    const all = state.env.repos.flatMap(r => r.worktrees.filter(w => !w.main && w.safe_to_delete && Date.now() - Date.parse(w.last_session || w.touched || 0) > 14 * 864e5).map(w => Object.assign({ repo: r.name }, w)));
    openDrawer(`Delete ${plural(all.length, "old worktree")}?`, `<div class="readable"><p>Each has nothing uncommitted and nothing unpushed, and hasn't been used in 14 days. Branches are kept. Untick any you want to keep.</p>
      <ul class="items box">${all.map(w => `<li><label class="row"><input type="checkbox" data-old="${esc(w.path)}" checked><span class="grow"><b>${esc(w.repo)}</b> · ${esc(w.branch || w.head)}<div class="meta mono small">${esc(w.path)} · ${ago(w.last_session || w.touched)}</div></span></label></li>`).join("")}</ul>
      <div class="set-actions"><button class="btn primary" id="old-go">Delete ticked</button><span class="save-msg" id="old-msg"></span></div></div>`);
    $("#old-go").onclick = async () => {
      const go = $("#old-go"), msg = $("#old-msg"), paths = $$("[data-old]:checked").map(x => x.dataset.old);
      go.disabled = true; msg.textContent = `Deleting ${paths.length}…`;
      const bad = await del(paths);
      msg.textContent = bad.length ? `Deleted ${paths.length - bad.length}; kept ${bad.length}: ${bad.join("; ")}` : `Deleted ${paths.length}.`;
      setTimeout(() => { closeDrawer(); route(); }, bad.length ? 5000 : 900);
    };
  };
}
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
PAGES.usage = async () => {
  const [d, H] = await Promise.all([api("usage", { days: UR.days > 30 ? 90 : 30 }), api("headroom", { days: UR.days > 30 ? 90 : 30 })]);
  const hrDay = Object.fromEntries((((H || {}).when || {}).days || []).map(x => [x.day, x]));
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (d.days || []).filter(x => x.day >= since).map(x => ({ ...x, hr_saved: (hrDay[x.day] || {}).saved || 0, hr_usd: (hrDay[x.day] || {}).usd || 0 }));
  const hrPending = H && H.pending;
  const rangeUsd = days.reduce((a, x) => a + (x.usd || 0), 0), hrUsd = days.reduce((a, x) => a + (x.hr_usd || 0), 0);
  const revUsd = days.reduce((a, x) => a + (x.review_usd || 0), 0), revs = (d.reviews || []).filter(r => r.last >= since);
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
    <div class="cols">${stat(`Cost, last ${UR.days} days`, usd(rangeUsd), "the work priced at Anthropic's API rates, from every session's log; on a subscription you pay your plan, not this")}${stat("Cost today", usd(sp.today || 0), "since midnight")}${stat(`PR reviews, last ${UR.days} days`, usd(revUsd), revs.length ? `${pct(revUsd, rangeUsd)}% of the cost, ${plural(revs.length, "review session")}` : "no review sessions")}${stat(`Saved by Headroom, last ${UR.days} days`, hrTokens ? usd(hrUsd) : "—", hrTokens ? `${compact(hrTokens)} tokens removed, by Headroom's count` : hrPending ? "checking…" : "nothing recorded")}</div>
    <div class="cols">${stat(`Tokens sent, last ${UR.days} days`, compact(t.input + t.cache_read + t.cache_write), `${hit}% reused from cache, which costs about a tenth as much`)}${stat(`Tokens written, last ${UR.days} days`, compact(t.output), "Claude's replies")}</div>
    ${section(UR.measure === "usd" ? `Cost per ${UR.by}` : `Tokens per ${UR.by}`, `<div class="box pad" id="usage-main">${chart}<div id="usage-detail"></div></div>`, UR.measure === "usd"
      ? `the solid bar is what that ${UR.by}'s work cost at Anthropic's API prices; the dashed part on top is what Headroom saved, so the whole bar is what it would have cost without Headroom${hrPending ? " (Headroom's numbers are still loading)" : ""}. Hover for numbers, click for the breakdown by model.`
      : `solid: what was sent (new text, and text reused from cache, hidden until you click its key) and what Claude wrote back. Dashed on top: what Headroom removed before sending, so the whole bar is what would have been sent without it${hrPending ? " (Headroom's numbers are still loading)" : ""}.`)}
    ${(d.models || []).length ? section("By model", `<div class="box">${table(d.models, [{ k: "model", label: "Model" }, { k: "input", label: "Sent", num: true, html: r => compact((r.input || 0) + (r.cache_read || 0) + (r.cache_write || 0)) }, { k: "output", label: "Written", num: true, html: r => compact(r.output) }, { k: "usd", label: "Cost", num: true, html: r => r.usd != null ? usd(r.usd) : "" }], { filter: false })}</div>`, "last " + (d.days || []).length + " days") : ""}
    ${revs.length ? section("PR reviews", `<div class="box">${table(revs, [{ k: "pr", label: "PR", html: r => esc(r.pr) }, { k: "last", label: "Last used", html: r => `<span class="nowrap">${esc(r.last)}</span>` }, { k: "tokens", label: "Tokens", num: true, html: r => compact(r.tokens) }, { k: "usd", label: "Cost", num: true, html: r => usd(r.usd) }], { filter: false, sort: "last" })}</div>`, "sessions that started with /review-pr, /lfg:review or the dashboard's Review button, with their subagents") : ""}
    <div id="hr-detail"><div class="loading">Reading Headroom's logs…</div></div>
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
  const W = d.when || {}, X = d.where || {};
  const since = new Date(Date.now() - (UR.days - 1) * 864e5).toISOString().slice(0, 10);
  const days = (W.days || []).filter(x => x.day >= since);
  const rows = bucket(days, UR.by, rs => addRows(rs, ["saved", "calls", "usd", "before"]));
  const status = d.routed ? `<span class="row" style="gap:8px">${dot(d.live ? "ok" : "bad")}<span>${d.live ? "On: every Claude Code session goes through it." : "Every terminal session goes through it, but it isn't running right now, so they can't reach Claude. Run <code>lfg headroom restart</code> in a terminal."}</span></span>` : d.live ? `<span class="row" style="gap:8px">${dot("warn")}<span>Running, but Claude Code doesn't go through it.</span></span>` : `<span class="row" style="gap:8px">${dot("")}<span>Off.</span></span>`;
  const hours = (W.today_by_hour || []).filter(h => h.calls).sort((a, b) => b.calls - a.calls).slice(0, 3);
  box.innerHTML = section("Saved by Headroom", `<p class="muted">Headroom is a small program on this computer that every request from Claude Code passes through on its way to Anthropic. It removes repeated and unneeded text first, so less is sent and billed.</p>
    <p>${status}</p>
    ${rows.length ? `<p class="muted small">In this range: ${compact(rows.reduce((a, x) => a + (x.saved || 0), 0))} tokens removed from ${n(rows.reduce((a, x) => a + (x.calls || 0), 0))} requests, about ${usd(rows.reduce((a, x) => a + (x.usd || 0), 0))} by Headroom's count. It's the dashed part of the chart above.${hours.length ? ` Busiest today: ${hours.map(h => `${h.hour}:00 (${n(h.calls)} requests)`).join(", ")}.` : ""}</p>` : ""}
    ${(X.sessions || []).length ? `<div class="k">Where it saved the most, since ${ago(X.since)}</div>
      <p class="muted small">Headroom's request log only keeps the last few hours. Requests are matched to a session by their token counts: ${n(X.matched)} of ${n(X.requests)} matched one session exactly.</p>
      <div class="box">${table(X.repos, [{ k: "repo", label: "Repo" }, { k: "sessions", label: "Sessions", num: true }, { k: "calls", label: "Requests", num: true }, { k: "saved", label: "Tokens removed", num: true, html: r => compact(r.saved) }], { filter: false })}</div>
      <div class="box mt">${table(X.sessions, [{ k: "name", label: "Session", html: r => `${esc(r.name)}<div class="sub">${esc(r.repo)}${r.group ? " · " + esc(r.group) : ""} · last ${ago(r.last)}</div>` }, { k: "calls", label: "Requests", num: true }, { k: "saved", label: "Tokens removed", num: true, html: r => compact(r.saved) }, { k: "percent", label: "Smaller by", num: true, html: r => r.percent + "%" }], { filter: false, sort: "saved" })}</div>` : ""}`);
  mountTables(box);
  wireICharts(box);
}
PAGES.settings = async () => {
  const [cfg, sk, cm, unlocked] = await Promise.all([api("settings"), api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = { cfg, sk, cm, unlocked };
  return `${head("Settings", unlocked ? "Changes are checked, refused if they look like a password or key, and backed up." : "")}
    ${unlocked ? "" : `<div class="callout">Read-only. To make changes, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("settings", [["claudecode", "Claude Code", null, settingsClaudeCode], ["general", "General", null, settingsGeneral], ["tools", "Connections", null, settingsTools], ["ollama", "Local AI models", null, settingsOllama], ["storage", "Disk space", null, settingsStorage], ["rules", "Rules", null, settingsRules], ["claudemd", "Your instructions", null, settingsClaude]])}</div>`;
};

// ------------------------------------------------------------------ skills: every skill Claude Code loads, from every source
const SRC_LABEL = { personal: "Yours", "personal command": "Your command", project: "This project", plugin: "Plugin" };
PAGES.skills = async () => {
  const [sk, cm, unlocked] = await Promise.all([api("skills"), api("claudemd"), isUnlocked()]);
  state.settings = Object.assign(state.settings || {}, { sk, cm, unlocked, cfg: (state.settings || {}).cfg });
  return `${head("Skills", "Everything Claude Code can load as a skill on this computer: yours, this project's and every plugin's, LFG's included.")}
    ${unlocked ? "" : `<div class="callout">Read-only. To change skills, run <code>lfg ui</code> in your own terminal; it opens this page unlocked.</div>`}
    <div class="section">${tabs("skillspage", [["all", "All skills", null, () => '<div id="skills-box"><div class="loading">Reading skills…</div></div>'], ["mine", "Your skills & references", null, () => '<div id="mylib-box"><div class="loading">Reading ~/.claude…</div></div>'], ["lfgedit", "Edit LFG skills", null, settingsSkills]])}</div>`;
};
async function loadSkills() {
  const box = $("#skills-box");
  if (!box) return;
  const [d, G] = await Promise.all([api("allskills"), api("skillgroups")]), un = state.settings.unlocked, S = d.summary;
  const groupOf = Object.fromEntries(Object.entries(G).flatMap(([g, ids]) => ids.map(i => [i, g])));
  d.skills.forEach(r => (r.group = groupOf[r.id] || ""));
  state.skillGroups = Object.keys(G).sort();
  const filt = sessionStorage.getItem("lfg.skills.filter") || "all";
  const rows = d.skills.filter(r => filt === "all" || (filt.startsWith("group:") ? r.group === filt.slice(6) : filt === "collisions" ? r.collides_with.length : filt === "auto" ? r.auto : r.source === filt));
  box.innerHTML = `<div class="cols">${stat("Skills", n(S.total))}${stat("Claude may use on its own", n(S.auto), `about ${compact(S.approx_tokens)} tokens of descriptions in every session`)}${stat("Name clashes", n(S.collisions), "the short name goes to your own skill first")}</div>
    <div class="row mt"><label class="muted small" for="sk-filter">Show</label><select id="sk-filter">${[["all", "All"], ["auto", "Used on its own"], ["collisions", "Name clashes"], ...S.sources.map(x => [x, SRC_LABEL[x] || x]), ...state.skillGroups.map(g => ["group:" + g, "Group: " + g])].map(([v, l]) => `<option value="${esc(v)}" ${v === filt ? "selected" : ""}>${esc(l)}</option>`).join("")}</select><span class="save-msg" id="sk-msg"></span></div>
    <div class="box mt">${table(rows, [
      { k: "invoke", label: "Type", html: r => `<code class="nowrap">${esc(r.invoke)}</code>${r.shadowed ? ' <span class="tag" title="A skill of yours has the same short name">use full name</span>' : ""}` },
      { k: "source", label: "From", html: r => `${esc(SRC_LABEL[r.source] || r.source)}${r.plugin ? `<div class="sub">${esc(r.plugin)}${r.enabled === false ? " · off" : ""}</div>` : ""}` },
      { k: "auto", label: "Claude uses it on its own", sort: r => (r.auto ? 1 : 0), html: r => r.editable ? `<label class="row"><input type="checkbox" data-sk-auto="${esc(r.id)}" ${r.auto ? "checked" : ""} ${un ? "" : "disabled"}> ${r.auto ? "yes" : "only when typed"}</label>` : (r.auto ? "yes" : "only when typed") },
      { k: "description", label: "What it does", html: r => `<span title="${esc(r.description)}">${esc(r.description.slice(0, 140))}${r.description.length > 140 ? "…" : ""}</span>${r.collides_with.length ? `<div class="sub">same name as ${r.collides_with.map(x => `<code>${esc(x)}</code>`).join(", ")}</div>` : ""}` },
      { k: "group", label: "Group", html: r => `${r.group ? `<span class="tag">${esc(r.group)}</span> ` : ""}<button class="btn small" data-sk-group="${esc(r.id)}" ${un ? "" : "disabled"}>${r.group ? "Change" : "Group…"}</button>` },
      { k: "chars", label: "Size", num: true },
    ], { onRow: r => showSkillText(r.id), emptyTitle: "No skills here" })}</div>`;
  mountTables(box);
  $("#sk-filter", box).onchange = e => { sessionStorage.setItem("lfg.skills.filter", e.target.value); loadSkills(); };
  $$("[data-sk-group]", box).forEach(b => b.onclick = e => {
    e.stopPropagation();
    const id = b.dataset.skGroup, cur = (d.skills.find(x => x.id === id) || {}).group || "";
    const set = async g => { const r = await save("skill_group", { id, group: g }); saidMsg($("#skg-msg"), r, "Saved."); if (r.ok) setTimeout(() => { closeDrawer(); loadSkills(); }, 400); };
    openDrawer(`Group ${(d.skills.find(x => x.id === id) || {}).invoke || id}`, `<div class="readable"><p>Groups sort skills your own way, for example your <code>/review-pr</code> with <code>/lfg:review</code>. They live in LFG only and change nothing about the skills.</p>
      ${cur ? `<p>Now in <b>${esc(cur)}</b>. <button class="btn small" id="skg-out">Take it out</button></p>` : ""}
      ${state.skillGroups.filter(g => g !== cur).length ? `<div class="k">Your groups</div><div class="row wrap">${state.skillGroups.filter(g => g !== cur).map(g => `<button class="btn small" data-skg="${esc(g)}">${esc(g)}</button>`).join("")}</div>` : ""}
      <div class="k">New group</div><div class="row"><input type="text" id="skg-new" class="grow" placeholder="e.g. PR reviews" maxlength="60"><button class="btn primary" id="skg-make">Create and add</button></div><span class="save-msg" id="skg-msg"></span></div>`);
    $$("[data-skg]").forEach(x => x.onclick = () => set(x.dataset.skg));
    if ($("#skg-out")) $("#skg-out").onclick = () => set("");
    const make = () => { const v = $("#skg-new").value.trim(); if (v.length < 2) { $("#skg-msg").textContent = "Give the group a name of at least 2 characters."; return; } set(v); };
    $("#skg-make").onclick = make;
    $("#skg-new").onkeydown = e => { if (e.key === "Enter") make(); };
  });
  $$("[data-sk-auto]", box).forEach(c => {
    c.onclick = e => e.stopPropagation();
    c.onchange = async () => {
      const r = await save("skill_auto", { id: c.dataset.skAuto, auto: c.checked });
      saidMsg($("#sk-msg"), r, r.ok ? "Saved." : "");
      if (!r.ok) c.checked = !c.checked;
    };
  });
}
async function loadMyLibrary(pick) {
  const box = $("#mylib-box");
  if (!box) return;
  const d = await api("mylibrary"), un = state.settings.unlocked;
  const fileLink = (f, label) => `<a href="#" data-myfile="${esc(f.path)}" title="${esc(f.path)}">${esc(label)}${(f.used_by || []).length ? `<span class="tag" title="Mentioned by ${esc(f.used_by.join(", "))}">${f.used_by.length}</span>` : ""}</a>`;
  const skills = d.skills.map(s => `<div class="nav-grp">/${esc(s.name)}</div>${s.files.map(f => fileLink(f, f.rel)).join("")}`).join("");
  const shared = d.shared.map(g => `<div class="nav-grp">${esc(g.name)}</div>${g.files.map(f => fileLink(f, f.rel)).join("")}`).join("");
  box.innerHTML = `<p class="muted">Your own skills in <code>~/.claude/skills</code>, and the shared files they read: <code>~/.claude/skills/shared</code> and <code>~/.claude/references</code>. The number on a shared file is how many of your skills mention it. ${un ? "Saving keeps a copy of the old version in <code>~/.lfg/backups/personal/</code>." : "Unlock editing (run <code>lfg ui</code>) to change them."}</p>
    <div class="skill-edit"><nav>${shared ? `<div class="nav-grp"><b>Shared</b></div>${shared}` : ""}<div class="nav-grp"><b>Your skills</b></div>${skills}</nav>
    <div class="grow"><div id="myfile-editor">${empty("Pick a file to read or change it", "New Claude Code sessions use what you save.")}</div></div></div>`;
  $$("[data-myfile]", box).forEach(a => a.onclick = e => { e.preventDefault(); $$("[data-myfile]", box).forEach(x => x.classList.toggle("on", x === a)); showMyFile(a.dataset.myfile, d); });
  if (pick) { const a = $(`[data-myfile="${CSS.escape(pick)}"]`, box); if (a) a.click(); }
}
async function showMyFile(path, lib) {
  const ed = $("#myfile-editor"), un = state.settings.unlocked;
  const d = await api("myfile", { path });
  if (d.available === false) { ed.innerHTML = unavailable(d); return; }
  const f = [...lib.skills, ...lib.shared].flatMap(g => g.files).find(x => x.path === path) || {};
  const isMd = /\.md$/i.test(path);
  ed.innerHTML = `<div class="row"><span class="mono small grow">${esc(path.replace(/^\/Users\/[^/]+/, "~"))}</span>${un ? '<button class="btn small" id="myf-edit">Edit</button>' : ""}</div>
    ${(f.used_by || []).length ? `<p class="muted small">Mentioned by ${f.used_by.map(n => `<code>/${esc(n)}</code>`).join(", ")}: changing it changes how they work.</p>` : ""}
    <div id="myf-read" class="box pad ${isMd ? "md" : ""}">${isMd ? md(frontMatter(d.text).body) : `<pre>${esc(d.text)}</pre>`}</div>
    <div id="myf-write" hidden><textarea class="editor" id="myf-text" spellcheck="false">${esc(d.text)}</textarea>
      <div class="set-actions"><button class="btn primary" id="myf-save">Save</button><button class="btn" id="myf-cancel">Cancel</button><span class="save-msg" id="myf-msg"></span></div></div>`;
  if (!un) return;
  $("#myf-edit").onclick = () => { $("#myf-read").hidden = true; $("#myf-write").hidden = false; $("#myf-edit").hidden = true; };
  $("#myf-cancel").onclick = () => showMyFile(path, lib);
  $("#myf-save").onclick = async () => {
    const r = await save("my_file", { path, text: $("#myf-text").value });
    saidMsg($("#myf-msg"), r, r.ok ? (r.note || "Saved.") : "");
    if (r.ok) setTimeout(() => loadMyLibrary(path), 900);
  };
}
async function showSkillText(id) {
  const d = await api("skilltext", { id });
  if (d.available === false) return;
  const fm = frontMatter(d.text);
  openDrawer(d.invoke, `${fm.meta.description ? `<p class="muted">${txt(fm.meta.description)}</p>` : ""}${d.lfg_name ? '<p class="small">Change it under <b>Edit LFG skills</b>.</p>' : ""}<div class="md">${md(fm.body)}</div>`);
};

PAGES.help = async () => {
  const d = await api("guide");
  return `${head("Help", `New here? Type <code>/lfg:wizard</code> in Claude Code for a guided run, or <code>/lfg:which</code> if you're not sure what to do next. LFG ${esc(d.version)}.`)}
    ${tabs("help", [
      ["guide", "Guide", null, () => d.has_guide ? `<iframe class="viewer" src="/guide/guide.html" title="LFG guide" referrerpolicy="no-referrer"></iframe>` : empty("The guide isn't installed", "Re-run <code>bootstrap.sh</code>.")],
      ["skills", "What you can ask for", d.skills.length, () => `<div class="box">${table(d.skills, [{ k: "name", label: "Command", html: r => `<code>/${esc(r.name)}</code>` }, { k: "description", label: "What it does" }])}</div>`],
    ])}`;
};

// ------------------------------------------------------------------ shell
// ------------------------------------------------------------------ PR reviews (lfg review)
/* Reviews of other people's PRs: the queue GitHub asks you to review, each saved review, and the buttons to run a
   review, decide each finding and post. Every button needs the edit key; posting is only ever a person's click. */
const prRef = r => `${r.repo}#${r.number}`;
const prHash = r => `#prs/${r.repo}/${r.number}`;
const PRIOR = { fixed: ["Fixed", "ok"], replied: ["Answered, still open", "warn"], withdrawn: ["Withdrawn", ""],
  "resolved-unchanged": ["Resolved but not fixed", "bad"], ignored: ["Not addressed", "bad"], open: ["Still open", "warn"] };
const SINCE = { new: "in the new commits", missed: "missed last time" };
const ORIGIN = { exposed: "existing bug this PR now reaches", "pre-existing": "was already there" };
function jobLine(j) {
  if (!j) return "";
  if (j.status === "running") return `<span class="st">${dot("on")}Reviewing… started ${ago(j.started)}</span>`;
  if (j.status === "failed") return `<span class="st" title="${esc(j.log || "")}">${dot("bad")}${esc(j.why || "The last review failed")}</span> <button class="btn small" data-pr-import='${esc(JSON.stringify([`${j.repo}#${j.number}`, "log"]))}' title="Look in that run's log for a review and save it">Save from log</button>`;
  return "";
}
function tallyLine(r) {
  const t = r.tally || {};
  if (r.posted) return `<span class="st">${dot("ok")}Posted: ${esc({ APPROVE: "approved", REQUEST_CHANGES: "changes requested", COMMENT: "comments" }[r.posted.event] || r.posted.event)}</span>`;
  if (t.pending) return `<span class="st">${dot("warn")}${plural(t.pending, "finding")} to decide</span>`;
  return `<span class="st">${dot("on")}Ready to post</span>`;
}
async function prStart(pr, btn) {
  const fresh = btn.dataset.fresh === "1";
  btn.disabled = true; btn.textContent = "Starting…";
  const d = await save("review_run", { pr, fresh });
  if (!d.ok) { btn.disabled = false; btn.textContent = "Try again"; btn.title = d.why || ""; return; }
  btn.textContent = d.started ? "Started" : "Already running";
  setTimeout(softRoute, 1200);
}
/* Where a PR stands on GitHub, as a tag: Approved / Changes requested / Needs review / Merged / Closed. */
const GH_DECISION = { APPROVED: ["Approved", "ok"], CHANGES_REQUESTED: ["Changes requested", "bad"], REVIEW_REQUIRED: ["Needs review", "warn"] };
function ghTag(g) {
  if (!g || g.available === false) return "";
  if (g.state === "MERGED") return '<span class="tag ok">Merged</span>';
  if (g.state === "CLOSED") return '<span class="tag">Closed</span>';
  const [t, tn] = GH_DECISION[g.decision] || ["No reviews yet", ""];
  const mine = (g.reviewers || []).find(r => r.who === g.me);
  const fails = (g.checks || {}).FAILURE || 0;
  return `<span class="tag ${tn}">${esc(t)}</span>${mine ? ` <span class="tag">you: ${esc(({ APPROVED: "approved", CHANGES_REQUESTED: "asked for changes", COMMENTED: "commented", DISMISSED: "dismissed" })[mine.state] || mine.state.toLowerCase())}</span>` : ""}${fails ? ` <span class="tag bad">${plural(fails, "check")} failing</span>` : ""}${g.draft ? ' <span class="tag">draft</span>' : ""}`;
}
function ghPanel(g) {
  if (!g || g.available === false) return g && g.why ? `<p class="muted small">Couldn't ask GitHub: ${esc(g.why)}</p>` : "";
  const word = { APPROVED: "approved", CHANGES_REQUESTED: "asked for changes", COMMENTED: "commented", DISMISSED: "dismissed" };
  const checks = Object.entries(g.checks || {}).map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ");
  return `<div class="pr-status small"><div class="tags">${ghTag(g)}</div><div class="muted">${(g.reviewers || []).map(r => `${esc(r.who)} ${esc(word[r.state] || r.state.toLowerCase())} ${ago(r.at)}`).join(" · ") || "nobody has reviewed yet"}${(g.waiting_on || []).length ? ` · waiting on ${esc(g.waiting_on.join(", "))}` : ""}${checks ? ` · checks: ${esc(checks)}` : ""}</div></div>`;
}
PAGES.prs = async arg => {
  if (arg) return prDetail(arg);
  const [d, unlocked] = await Promise.all([api("prreviews"), isUnlocked()]);
  const lock = unlocked ? "" : `<div class="callout warn">Buttons are locked. Run <code>lfg ui --unlock</code> in your terminal to review and post from here.</div>`;
  const qcols = [
    { k: "title", label: "Pull request", html: x => `${esc(x.title)}<div class="sub mono">${esc(prRef(x))} · by ${esc(x.author)}</div><div class="sub">${ghTag(x.gh)}</div>${x.job ? `<div class="sub">${jobLine(x.job)}</div>` : ""}` },
    { k: "updated", label: "Updated", html: x => `<span class="nowrap">${ago(x.updated)}</span>` },
    { k: "act", label: "", html: x => (x.job && x.job.status === "running") ? "" : `<button class="btn small${x.passes ? "" : " primary"}" data-pr-start="${esc(prRef(x))}" ${unlocked ? "" : "disabled"}>${x.passes ? "Re-review" : "Review"}</button> <button class="btn small" data-pr-sessions="${esc(prRef(x))}" ${unlocked ? "" : "disabled"} title="Bring in a review you did in a Claude Code session">Import</button>${x.passes ? ` <a class="small" href="${esc(prHash(x))}">Open</a>` : ""}` },
  ];
  const rcols = [
    { k: "title", label: "Review", html: x => `${esc(x.title || prRef(x))}<div class="sub mono">${esc(prRef(x))} · by ${esc(x.author || "")}${x.ticket ? ` · ${esc(x.ticket)}` : ""}</div>${x.gh ? `<div class="sub">${ghTag(x.gh)}</div>` : ""}` },
    { k: "state", label: "Where it is", html: x => `${tallyLine(x)}${x.job ? `<div class="sub">${jobLine(x.job)}</div>` : ""}`, sort: x => (x.posted ? 2 : (x.tally || {}).pending ? 0 : 1) },
    { k: "score", label: "Score", num: true },
    { k: "passes", label: "Reviews", num: true },
    { k: "updated", label: "Updated", html: x => `<span class="nowrap">${ago(x.updated)}</span>` },
  ];
  return `${head("PR reviews", "Pull requests waiting on your review, and the reviews you've run. Run one, decide what to keep, then post it to GitHub. Reviews run on your own Claude Code login.")}
    ${lock}
    ${section("Waiting on you", d.queue_why ? unavailable({ why: d.queue_why }, "Couldn't ask GitHub") : `<div class="box">${table(d.queue, qcols, { emptyTitle: "Nothing waiting", emptyBody: "No open PRs ask for your review." })}</div>`, "open PRs where GitHub lists you as a reviewer")}
    ${section("Your reviews", `<div class="box">${table(d.reviews, rcols, { onRow: x => (location.hash = prHash(x)), sort: "updated", emptyTitle: "No reviews yet", emptyBody: "Press Review above, or run <code>/lfg:review &lt;PR&gt;</code> in Claude Code." })}</div>`)}`;
};
function prFinding(f, pr, unlocked, live) {
  const where = f.file ? `${f.file}${f.line ? ":" + f.line : ""}` : "the PR as a whole";
  const tags = [f.since !== "first" && SINCE[f.since], ORIGIN[f.origin]].filter(Boolean).map(t => `<span class="tag">${esc(t)}</span>`).join("");
  const posted = f.comment_url ? `<a class="small" href="${esc(f.comment_url)}" target="_blank" rel="noopener noreferrer">Posted ↗</a>` : "";
  const can = unlocked && live && !f.comment_id;
  const btn = (status, text) => `<button class="btn small${f.status === status ? " primary" : ""}" data-pr-mark='${esc(JSON.stringify([pr, f.id, status]))}' ${can ? "" : "disabled"}>${text}</button>`;
  return `<div class="card pr-finding ${esc(f.status)}" id="f-${esc(f.id)}"><div class="row">${st(f.severity === "nitpick" ? "nit" : f.severity)}${tags}<span class="grow"></span><span class="muted small mono">${esc(f.id)}</span></div>
    <div class="title">${txt(f.title || f.issue)}</div>
    ${f.issue && f.title ? `<p>${txt(f.issue)}</p>` : ""}${f.fix ? `<p><b>Fix:</b> ${txt(f.fix)}</p>` : ""}
    <div class="muted small mono">${esc(where)}</div>
    ${f.detail ? `<details class="more"><summary>What the review checked</summary><div class="md">${md(f.detail)}</div></details>` : ""}
    <div class="k">Comment the author will read</div>
    <div class="pr-body md" data-pr-body="${esc(f.id)}">${md(f.body)}</div>
    <div class="pr-edit" data-pr-editbox="${esc(f.id)}" hidden>
      <div class="row"><input type="text" class="grow" data-pr-ask="${esc(f.id)}" placeholder="Ask Claude to change it: shorter, softer, add an example…"><button class="btn small" data-pr-askgo='${esc(JSON.stringify([pr, f.id]))}'>Ask Claude</button></div>
      <textarea class="editor small">${esc(f.body)}</textarea>
      <div class="set-actions"><button class="btn small primary" data-pr-editsave='${esc(JSON.stringify([pr, f.id]))}'>Save comment</button><button class="btn small" data-pr-editcancel="${esc(f.id)}">Cancel</button><span class="save-msg"></span></div></div>
    <div class="row mt">${posted || `${btn("keep", "Keep")}${btn("drop", "Drop")}<button class="btn small" data-pr-edit="${esc(f.id)}" ${can ? "" : "disabled"}>Edit comment</button>`}</div></div>`;
}
async function prDetail(arg) {
  const m = /^([\w.-]+\/[\w.-]+)\/(\d+)$/.exec(arg);
  if (!m) return unavailable({ why: "Not a PR address." });
  const pr = `${m[1]}#${m[2]}`;
  const [d, unlocked] = await Promise.all([api("prreview", { pr }), isUnlocked()]);
  if (d.available === false) return unavailable(d);
  const rec = d.record, j = d.job;
  crumbs("prs", pr);
  const running = j && j.status === "running";
  if (running) setTimeout(() => { if (location.hash === `#prs/${arg}`) softRoute(); }, 4000);
  const back = '<a class="back" href="#prs">← All reviews</a>';
  const kindOf = j && (j.fresh ? "new review" : j.re_review ? "re-review" : "review");
  const jobBox = j && j.status === "running" ? `<div class="callout">${dot("on")}<b>${esc(kindOf[0].toUpperCase() + kindOf.slice(1))} running</b>, started ${ago(j.started)}. It shows up below as a new tab when it's done; this updates by itself.${(j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`
    : j && j.status === "failed" ? `<div class="callout bad">${jobLine(j)}${(j.steps || []).length ? `<ul class="mono small pr-steps">${j.steps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>` : "";
  const can = unlocked && !running;
  const actions = `<div class="row wrap pr-actions">${rec ? `<button class="btn primary" data-pr-start="${esc(pr)}" ${can ? "" : "disabled"} title="Check what happened to your posted comments, review only the new commits, then look once more for anything missed">Re-review</button><button class="btn" data-pr-start="${esc(pr)}" data-fresh="1" ${can ? "" : "disabled"} title="Review the whole PR again from scratch, ignoring earlier reviews">New full review</button>` : `<button class="btn primary" data-pr-start="${esc(pr)}" ${can ? "" : "disabled"}>Review</button>`}<button class="btn" data-pr-sessions="${esc(pr)}" ${can ? "" : "disabled"} title="Bring in a review you did in a Claude Code session">Import</button></div>`;
  const sess = (d.sessions || []).length ? section("Your sessions about this PR", `<ul class="items box">${d.sessions.map(x => `<li class="sess"><div class="grow"><div class="title">${esc(x.title)}</div><div class="meta">${ago(x.modified)} · ${esc(x.cwd || "")}${x.has_json ? " · review ready to import" : ""}</div></div><button class="btn small" data-pr-importpath='${esc(JSON.stringify([pr, x.path]))}' ${unlocked ? "" : "disabled"}>Import as a review</button></li>`).join("")}</ul>`, "e.g. a /review-pr you ran yourself") : "";
  if (!rec) return `${head(pr, "Not reviewed yet.", back)}${ghPanel(d.gh)}${jobBox}${actions}${sess}`;
  const passes = rec.passes, last = passes[passes.length - 1];
  const key = "lfg.prpass." + pr;
  let pick = Number(sessionStorage.getItem(key)) || last.n;
  if (state.prSeen && state.prSeen[pr] && state.prSeen[pr] < last.n) pick = last.n;  // a new review just landed
  (state.prSeen || (state.prSeen = {}))[pr] = last.n;
  const p = passes.find(x => x.n === pick) || last;
  const live = p === last && !p.posted;
  const byId = Object.fromEntries(passes.flatMap(x => x.findings).map(f => [f.id, f]));
  const label = x => `Review ${x.n}${x.kind === "re-review" ? " · re-review" : ""}`;
  const passTabs = `<div class="tabs pr-passes">${passes.slice().reverse().map(x => `<button class="tab ${x.n === p.n ? "on" : ""}" data-pr-pass='${esc(JSON.stringify([pr, x.n]))}'>${esc(label(x))}<span class="n">${x.posted ? "posted" : ago(x.ts)}</span></button>`).join("")}</div>`;
  const prior = (p.prior || []).length ? section("Earlier comments", `<div class="box items">${p.prior.map(x => { const [t, tn] = PRIOR[x.state] || [x.state, ""]; const f = byId[x.id] || {}; return `<details class="item"><summary>${dot(tn)}<span class="grow">${txt(f.title || x.id)}</span><span class="muted small nowrap">${esc(t)}</span></summary><div class="item-body">${x.note ? `<p>${txt(x.note)}</p>` : ""}${f.comment_url ? `<a class="small" href="${esc(f.comment_url)}" target="_blank" rel="noopener noreferrer">The comment on GitHub ↗</a>` : ""}</div></details>`; }).join("")}</div>`, "what happened to what you posted last time") : "";
  const order = { blocker: 0, major: 1, minor: 2, nitpick: 3, note: 4 };
  const fs = [...p.findings].sort((a, b) => (order[a.severity] ?? 5) - (order[b.severity] ?? 5));
  const pending = p.findings.filter(f => f.status === "pending").length;
  const kept = p.findings.filter(f => f.status === "keep").length;
  const postBar = live ? `<div class="panel"><div class="k" style="margin-top:0">Post to GitHub</div>
      <textarea class="editor small" id="pr-post-body" placeholder="Optional: a note above the comments"></textarea>
      <div class="row mt">${[["request-changes", "Request changes"], ["approve", "Approve"], ["comment", "Comment only"]].map(([e, l]) => `<button class="btn${e === "request-changes" ? " primary" : ""}" data-pr-preview='${esc(JSON.stringify([pr, e]))}' ${unlocked && !pending ? "" : "disabled"}>${l}…</button>`).join("")}
      <span class="muted small" id="pr-post-hint">${pending ? `Decide ${plural(pending, "more finding")} first.` : `${plural(kept, "kept finding")} will be posted. You'll see exactly what goes out before it does.`}</span></div></div>`
    : p.posted ? `<div class="callout ok">${dot("ok")}Posted ${ago(p.posted.ts)}. <a href="${esc(p.posted.url)}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a></div>`
    : `<p class="muted small">An older review. Only the newest one can be posted or discarded.</p>`;
  const discard = live && unlocked ? `<button class="btn small" data-pr-discard='${esc(JSON.stringify([pr, p.n]))}' title="Throw this review away; nothing was posted">Discard this review</button>` : "";
  return `${head(rec.title || pr, `<span class="mono">${esc(pr)}</span> by ${esc(rec.author || "")}${rec.ticket ? ` · ${esc(rec.ticket)}` : ""} · <a href="${esc(rec.url)}" target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>`, back)}
    ${ghPanel(d.gh)}
    ${jobBox}
    ${actions}
    ${passTabs}
    <div class="pr-pass-body">
      <div class="panel"><div class="row"><b>${esc(label(p))}</b><span class="muted">${ago(p.ts)} · at commit <span class="mono">${esc(p.head_sha.slice(0, 8))}</span>${p.score != null ? ` · score ${esc(p.score)}` : ""}${p.imported_from ? " · imported from a session" : ""}</span><span class="grow"></span>${discard}</div>
        ${p.summary ? `<p>${txt(p.summary)}</p>` : ""}
        ${(p.approach_notes || []).length ? `<div class="k">Approach notes (not posted)</div><ul>${p.approach_notes.map(x => `<li>${txt(x)}</li>`).join("")}</ul>` : ""}</div>
      ${prior}
      ${section("Findings", fs.length ? fs.map(f => prFinding(f, pr, unlocked, live)).join("") : empty("Nothing found", "This review found nothing to comment on."), `<span id="pr-tally">${plural(p.findings.length, "finding")} · ${kept} kept · ${pending} to decide</span>`)}
      ${postBar}
    </div>
    ${sess}`;
}
async function prImport(pr, path, btn) {
  btn.disabled = true; btn.textContent = path === "log" ? "Saving…" : "Importing…";
  const d = await save("review_import", { pr, path });
  if (!d.ok) { btn.disabled = false; btn.textContent = "Try again"; alertMsg(btn, d); return; }
  btn.textContent = `Saved ${plural(d.findings, "finding")}`;
  setTimeout(() => { closeDrawer(); const h = `#prs/${pr.replace("#", "/")}`; if (location.hash === h) softRoute(); else location.hash = h; }, 900);
}
async function prSessions(pr) {
  openDrawer(`Import a review of ${pr}`, '<div class="skeleton"></div>');
  const d = await save("review_sessions", { pr });
  const ss = (d.ok && d.sessions) || [];
  const rows = ss.map(s => `<li><div class="grow"><div class="title">${esc(s.title)}</div><div class="meta">${ago(s.modified)} · ${esc(s.cwd || "")}${s.has_json ? " · review ready to import" : " · Claude turns the review into findings (one short call)"}</div></div><button class="btn small" data-pr-importpath='${esc(JSON.stringify([pr, s.path]))}'>Import</button></li>`).join("");
  openDrawer(`Import a review of ${pr}`, `<div class="readable"><p>Your Claude Code sessions from the last 30 days that mention this PR, newest first. Importing adds it as a new review you can keep, drop and post like any other.</p>
    ${!d.ok ? unavailable(d) : ss.length ? `<ul class="items box">${rows}</ul>` : empty("No sessions found", "None of your sessions in the last 30 days mention this PR.")}</div>`);
  $$("[data-pr-importpath]").forEach(b => b.onclick = () => { const [p, path] = JSON.parse(b.dataset.prImportpath); prImport(p, path, b); });
}
function wirePrs(root) {
  $$("[data-pr-start]", root).forEach(b => b.onclick = e => { e.stopPropagation(); prStart(b.dataset.prStart, b); });
  $$("[data-pr-sessions]", root).forEach(b => b.onclick = e => { e.stopPropagation(); prSessions(b.dataset.prSessions); });
  $$("[data-pr-import]", root).forEach(b => b.onclick = e => { e.stopPropagation(); const [pr, path] = JSON.parse(b.dataset.prImport); prImport(pr, path, b); });
  $$("[data-pr-mark]", root).forEach(b => b.onclick = async () => {
    const [pr, id, status] = JSON.parse(b.dataset.prMark);
    b.disabled = true;
    const d = await save("review_mark", { pr, ids: [id], status });
    if (!d.ok) { b.disabled = false; b.title = d.why || ""; alertMsg(b, d); return; }
    softRoute();
  });
  $$("[data-pr-edit]", root).forEach(b => b.onclick = () => {
    $(`[data-pr-editbox="${b.dataset.prEdit}"]`, root).hidden = false;
    $(`[data-pr-body="${b.dataset.prEdit}"]`, root).hidden = true;
  });
  $$("[data-pr-editcancel]", root).forEach(b => b.onclick = () => {
    $(`[data-pr-editbox="${b.dataset.prEditcancel}"]`, root).hidden = true;
    $(`[data-pr-body="${b.dataset.prEditcancel}"]`, root).hidden = false;
  });
  $$("[data-pr-importpath]", root).forEach(b => b.onclick = () => { const [p, path] = JSON.parse(b.dataset.prImportpath); prImport(p, path, b); });
  $$("[data-pr-pass]", root).forEach(b => b.onclick = () => { const [pr, n] = JSON.parse(b.dataset.prPass); sessionStorage.setItem("lfg.prpass." + pr, n); softRoute(); });
  $$("[data-pr-discard]", root).forEach(b => b.onclick = () => {
    const [pr, n] = JSON.parse(b.dataset.prDiscard);
    openDrawer(`Discard review ${n}?`, `<div class="readable"><p>Its findings and your keep/drop choices go. Nothing was posted, so GitHub isn't touched. Earlier reviews stay.</p><div class="set-actions"><button class="btn primary" id="pr-disc-go">Discard</button><span class="save-msg" id="pr-disc-msg"></span></div></div>`);
    $("#pr-disc-go").onclick = async () => {
      const r = await save("review_discard", { pr, pass: n });
      saidMsg($("#pr-disc-msg"), r, "Discarded.");
      if (r.ok) { sessionStorage.removeItem("lfg.prpass." + pr); setTimeout(() => { closeDrawer(); softRoute(); }, 500); }
    };
  });
  $$("[data-pr-askgo]", root).forEach(b => {
    const [pr, id] = JSON.parse(b.dataset.prAskgo), box = b.closest(".pr-edit"), input = $("[data-pr-ask]", box);
    const go = async () => {
      if (!input.value.trim()) return input.focus();
      b.disabled = true; b.textContent = "Asking…";
      const d = await save("review_rewrite", { pr, id, instruction: input.value });
      b.disabled = false; b.textContent = "Ask Claude";
      if (!d.ok) return alertMsg(b, d);
      $("textarea", box).value = d.body;
      input.value = "";
      input.placeholder = "Changed below. Ask again, edit it yourself, or Save comment.";
    };
    b.onclick = go;
    input.onkeydown = e => { if (e.key === "Enter") go(); };
  });
  $$("[data-pr-editsave]", root).forEach(b => b.onclick = async () => {
    const [pr, id] = JSON.parse(b.dataset.prEditsave), box = b.closest(".pr-edit");
    const text = $("textarea", box).value;
    const d = await save("review_mark", { pr, ids: [id], body: text });
    if (!d.ok) return saidMsg($(".save-msg", box), d);
    const shown = $(`[data-pr-body="${id}"]`, root);
    shown.innerHTML = md(text);
    shown.hidden = false;
    box.hidden = true;
    saidMsg($(".save-msg", box), d, "");
  });
  $$("[data-pr-preview]", root).forEach(b => b.onclick = async () => {
    const [pr, event] = JSON.parse(b.dataset.prPreview), body = ($("#pr-post-body") || {}).value || "";
    const d = await save("review_post", { pr, event, body, dry_run: true });
    if (!d.ok) return alertMsg(b, d);
    const verb = { APPROVE: "Approve", REQUEST_CHANGES: "Request changes", COMMENT: "Comment" }[d.event];
    openDrawer(`${verb}: what will be posted`, `<div class="readable">
      <p>${plural(d.comments.length, "comment")} on lines of code${d.in_body.length ? `, and ${plural(d.in_body.length, "finding")} in the review text because GitHub can't attach ${d.in_body.length === 1 ? "it" : "them"} to a changed line` : ""}.</p>
      ${d.body ? `<div class="k">Review text</div><div class="box pad md">${md(d.body)}</div>` : ""}
      ${d.comments.map(c => `<div class="card"><div class="muted small mono">${esc(c.path)}:${esc(c.line)}</div><div class="md">${md(c.body)}</div></div>`).join("")}
      <div class="set-actions"><button class="btn primary" id="pr-post-go">${verb} on GitHub</button><span class="save-msg" id="pr-post-msg"></span></div></div>`);
    $("#pr-post-go").onclick = async () => {
      const go = $("#pr-post-go");
      go.disabled = true; go.textContent = "Posting…";
      const r = await save("review_post", { pr, event: event, body });
      saidMsg($("#pr-post-msg"), r, "Posted.");
      if (r.ok) { go.textContent = "Posted"; setTimeout(() => { closeDrawer(); softRoute(); }, 900); } else { go.disabled = false; go.textContent = "Try again"; }
    };
  });
}
function alertMsg(el, d) {
  let m = el.parentNode.querySelector(".save-msg");
  if (!m) { m = document.createElement("span"); m.className = "save-msg"; el.parentNode.appendChild(m); }
  saidMsg(m, d);
}

const NAV_GROUPS = [["Your work", ["home", "sessions", "environment", "runs", "issues", "checks", "prs"]], ["This project", ["code", "docs", "knowledge"]], ["LFG", ["prefs", "usage", "skills", "settings", "help"]]];
/* 24px line icons, drawn for these pages (stroke = currentColor) */
const ICON = {
  home: "M3 10.5 12 3l9 7.5M5 9v11h5v-6h4v6h5V9",
  sessions: "M4 5h16v11H8l-4 4zM8 9h8M8 12h5",
  environment: "M4 5h16v5H4zM4 14h16v5H4zM7 7.5h.01M7 16.5h.01",
  prefs: "M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4",
  runs: "M5 4l14 8-14 8z",
  issues: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z",
  checks: "M12 3l8 3v6c0 5-3.4 8.3-8 9-4.6-.7-8-4-8-9V6zM9 12l2 2 4-4",
  prs: "M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM6 7v10M6 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17V9a3 3 0 0 0-3-3h-4M13 3.5 10.5 6 13 8.5",
  code: "M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 5l-3 14",
  docs: "M14 3H6v18h12V7zM14 3v4h4M9 12h6M9 16h6",
  knowledge: "M4 5.5C6.5 4 9.5 4 12 6c2.5-2 5.5-2 8-.5V19c-2.5-1.5-5.5-1.5-8 .5-2.5-2-5.5-2-8-.5zM12 6v13.5",
  usage: "M4 20V10M10 20V4M16 20v-6M2 20h20",
  skills: "M13 2 4 14h7l-1 8 9-12h-7z",
  settings: "M4 7h9M17 7h3M4 17h3M11 17h9M15 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM9 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.4v.3M12 17h.01",
};
const icon = (k, cls = "ico") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${ICON[k] || ""}"/></svg>`;
function renderNav(active) {
  $("#nav").innerHTML = NAV_GROUPS.map(([g, ks]) => `<div class="nav-grp">${esc(g)}</div>${ks.map(k => `<a class="${k === active ? "on" : ""}" href="#${k}"${k === active ? ' aria-current="page"' : ""}>${icon(k)}<span>${esc(TITLES[k])}</span></a>`).join("")}`).join("");
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
    el.innerHTML = `<span class="map-line">${dot(t)}<span class="label">${esc(repoName())} code map: ${esc((text || "unknown").toLowerCase())}</span></span>${mapBtn(g.status, "btn tiny")}`;
    el.title = `The code map of ${repoName()} (the project picked above): an index of its functions and what calls what, which LFG's agents read instead of whole files. ${text || "Unknown"}. Each project has its own.`;
    wireMap(el);
    if (g.status === "syncing") { mapWatching = true; mapTimer = setTimeout(mapStatus, 4000); }
    else if (mapWatching) {
      mapWatching = false;
      if (["home", "code"].includes((location.hash.slice(1) || "home").split("/")[0])) { state.cache = {}; route(); }
    }
  } catch (e) { el.innerHTML = ""; }
}
let renderSeq = 0;
/* Re-draw the current page in place: no loading placeholder, same scroll position, open sections stay open. For
   buttons that change one thing on the page (Keep, Save comment, Review); route() is for going to a page. */
function softRoute() { return route({ soft: true }); }
async function route(opts) {
  const soft = !!(opts && opts.soft);
  let [page, ...rest] = (location.hash.slice(1) || "home").split("/");
  page = { overview: "home", reviews: "checks", security: "checks", architecture: "code", health: "code", brain: "knowledge", tools: "settings" }[page] || page;
  const key = PAGES[page] ? page : "home";
  const arg = rest.join("/");
  renderNav(key);
  crumbs(key);
  document.title = `${TITLES[key]} · LFG`;
  const seq = ++renderSeq, view = $("#view"), y = window.scrollY;
  const open = soft ? $$("details[open]", view).map((d, i) => d.id || "i" + i) : [];
  if (!soft) view.innerHTML = '<div class="skeleton" style="height:60px;width:40%"></div><div class="skeleton mt"></div><div class="skeleton mt" style="height:220px"></div>';
  let html;
  try { html = await PAGES[key](decodeURIComponent(arg)); } catch (e) { html = unavailable({ why: "Couldn't load this page: " + e.message }); }
  if (seq !== renderSeq) return;
  view.innerHTML = html;
  mountTables(view); mountTabs(view); wire(view);
  $$("[data-href]", view).forEach(li => li.onclick = () => (location.hash = li.dataset.href));
  if (key === "docs") wireDocs();
  if (key === "prs") wirePrs(view);
  if (key === "sessions") wireSessions(view);
  if (key === "knowledge") wireKnowledge(view);
  if (key === "prefs") wirePrefsPage(view);
  if (key === "environment") wireEnvironment(view);
  if (key === "usage") { wireUsage(view); loadHeadroom(); }
  const rf = $("#refreshed");
  if (rf) rf.textContent = "Updated " + new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (soft) {
    $$("details", view).forEach((d, i) => { if (open.includes(d.id || "i" + i)) d.open = true; });
    window.scrollTo(0, y);
  } else if (!arg) window.scrollTo(0, 0);
}
function wireDocs() {
  const body = $("#doc-body");
  $$("[data-doclink]", body).forEach(a => a.onclick = e => {
    e.preventDefault();
    const base = body.dataset.path.split("/").slice(0, -1);
    const target = a.dataset.doclink.split("#")[0];
    const parts = [...base];
    for (const p of target.split("/")) { if (p === "..") parts.pop(); else if (p && p !== ".") parts.push(p); }
    location.hash = `#docs/${body.dataset.src}/${encodeURIComponent(parts.join("/"))}`;
  });
  const f = $("#doc-filter");
  if (f) f.oninput = () => { const q = f.value.toLowerCase(); $(".doc-nav").classList.toggle("searching", !!q); $$(".doc-nav a:not(.more)").forEach(a => (a.style.display = !q || a.textContent.toLowerCase().includes(q) ? "" : "none")); };
  $$("[data-doc-more]").forEach(m => m.onclick = e => { e.preventDefault(); m.parentNode.classList.add("all"); });
  const on = $(".doc-nav a.on");
  if (on) on.scrollIntoView({ block: "nearest" });
}
async function init() {
  if (location.hash.startsWith("#unlock=")) {  // from `lfg ui`: keep the edit key, drop it from the URL
    localStorage.setItem("lfg.editKey", decodeURIComponent(location.hash.slice(8)));
    history.replaceState(null, "", location.pathname);
  }
  $("#drawer-close").onclick = closeDrawer;
  $("#drawer").onclick = e => { if (e.target.id === "drawer") closeDrawer(); };
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  try { state.rules = await api("rules"); } catch (e) { state.rules = null; }
  mountRuleTips();
  const r = await api("repos");
  state.repos = r.repos || [];
  if (!state.repos.some(x => x.id === state.repo)) state.repo = state.repos[0] ? state.repos[0].id : "";
  $("#repo").innerHTML = state.repos.map(x => `<option value="${esc(x.id)}" title="${esc(x.root || x.id)}" ${x.id === state.repo ? "selected" : ""}>${esc(x.name || x.id)}</option>`).join("") || "<option>no projects yet</option>";
  $("#repo").onchange = async () => { state.repo = $("#repo").value; localStorage.setItem("lfg.repo", state.repo); await loadBranches(); refresh(); };
  $("#refresh").onclick = refresh;
  checkUpdate();
  $("#branch").onchange = () => { state.branch = $("#branch").value; localStorage.setItem(branchPref(), state.branch); refresh(); };
  window.onhashchange = route;
  await loadBranches();
  mapStatus();
  route();
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
/* "Update ready": newer LFG in your fork or the original project. Checked on load, every minute and when the tab
   comes back; the server caches for a minute, so a new merge shows within about two. */
const UPDATE_FROM = { upstream: "the original LFG", origin: "your fork" };
let updateRecheck = 0;
async function checkUpdate(fresh) {
  const box = $("#update-banner");
  if (!box) return;
  let d;
  try { d = await api("update", fresh === true ? { fresh: "1" } : {}); } catch (e) { return; }
  /* an answer older than the cache means the server only just started a new check: ask again once it's done */
  if (d.checked_at && Date.now() - Date.parse(d.checked_at) > 70e3 && Date.now() - updateRecheck > 30e3) {
    updateRecheck = Date.now();
    setTimeout(checkUpdate, 5000);
  }
  const j = d.job;
  if (j && j.status === "running") {
    box.hidden = false;
    box.className = "callout";
    box.innerHTML = `${dot("on")}Updating LFG… ${esc((j.steps || []).slice(-1)[0] || "")}`;
    setTimeout(checkUpdate, 3000);
    return;
  }
  const F = d.fix;
  if (F && F.status === "running") {
    box.hidden = false;
    box.className = "callout";
    box.innerHTML = fixingMsg(F);
    watchUpdate();
    return;
  }
  const R = d.remotes || {}, H = d.held;
  const named = r => `${UPDATE_FROM[r]}${(R[r] || {}).name ? ` (${R[r].name})` : ""}`;
  if (H && H.state !== "ready") {
    /* a merge that conflicted, or code whose tests failed: it waits on its own branch until it's fixed and committed */
    box.hidden = false;
    box.className = "callout bad";
    const ver = $("#lfg-version");
    if (ver) ver.textContent = "Update stopped";
    const what = H.state === "tests" ? "LFG's tests fail on the new code"
      : `the changes from ${esc(named("upstream"))} ${H.state === "conflict" ? `conflict with yours in ${plural(H.files.length, "file")}` : "are merged but not committed yet"}`;
    const tried = F && F.status === "failed" && F.branch === H.branch ? `<span class="muted small pre-wrap">Claude tried ${ago(F.ended)} and stopped: ${esc(F.why || "")}</span>` : "";
    const unlocked = await isUnlocked();
    box.innerHTML = `${dot("bad")}<span><b>LFG update stopped:</b> ${what}. Nothing changed on main and nothing was installed; it's on <code>${esc(H.branch)}</code> in <code>${esc(H.worktree)}</code>.</span>
      ${H.files.length ? `<details class="more inline"><summary>${H.state === "conflict" ? "Conflicting files" : "Changed files"}</summary><ul>${H.files.map(f => `<li class="mono small">${esc(f)}</li>`).join("")}</ul></details>` : ""}
      ${H.output ? `<details class="more inline"><summary>Test output</summary><pre class="raw mono small">${esc(H.output)}</pre></details>` : ""}
      ${tried}
      <button class="btn small primary" id="update-fix" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to fix from here\""}>${tried ? "Try again with Claude" : "Fix with Claude"}</button>
      <button class="btn small" data-copy="${esc(H.prompt)}" title="${esc(H.prompt)}">Copy fix for Claude</button>
      <span class="muted small">Fix with Claude runs Claude Code on that branch by itself, then runs the update again; it never touches main. Or paste the fix into Claude Code yourself and press Update once it's committed.</span>`;
    $$("[data-copy]", box).forEach(b => b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; } catch (e) { window.prompt("Copy this:", b.dataset.copy); }
    });
    const fx = $("#update-fix");
    if (fx) fx.onclick = async () => {
      fx.disabled = true; fx.textContent = "Starting…";
      const r = await save("update_fix", {});
      if (!r.ok) { fx.disabled = false; fx.textContent = "Try again"; return alertMsg(fx, r); }
      watchUpdate();
    };
    return;
  }
  const seen = localStorage.getItem("lfg.update.seen") === (j && j.ended);
  if (j && j.status === "done" && !seen && !(d.available && d.ready) && Date.now() - Date.parse(j.ended) < 15 * 60e3) {
    box.hidden = false;
    box.className = "callout ok";
    box.innerHTML = `${dot("ok")}<span><b>LFG updated ${ago(j.ended)}</b>: tests passed and it's installed${(j.changes || []).length ? `, ${plural(j.changes.length, "change")}: ${esc(j.changes.map(c => c.replace(/^\S+ /, "")).slice(0, 3).join("; "))}${j.changes.length > 3 ? "…" : ""}` : ""}. This page runs the new version. <b>Start a new Claude Code session</b> for new or changed skills; sessions already open keep the old ones.</span> <button class="btn small" id="update-ok">OK</button>`;
    $("#update-ok").onclick = () => { localStorage.setItem("lfg.update.seen", j.ended); box.hidden = true; };
    return;
  }
  if (j && j.status === "failed" && !seen && !(d.available && d.ready && Date.parse(j.ended) < Date.now() - 60e3)) {
    box.hidden = false;
    box.className = "callout bad";
    box.innerHTML = `${dot("bad")}The update didn't go through: <span class="pre-wrap">${esc(j.why || "")}</span> <button class="btn small" id="update-ok">OK</button>`;
    $("#update-ok").onclick = () => { localStorage.setItem("lfg.update.seen", j.ended); box.hidden = true; };
    return;
  }
  const ver = $("#lfg-version");
  if (ver && d.available) ver.textContent = d.ready ? "Update ready" : "LFG up to date";
  if (d.pending) { setTimeout(checkUpdate, 3000); return; }
  if (!d.available || !d.ready) { box.hidden = true; return; }
  const src = d.sources || [], parts = src.map(r => src.length === 1 ? plural(R[r].new, "change") : `${plural(R[r].new, "change")} from ${named(r)}`);
  if (d.not_installed) parts.push(`${plural(d.not_installed, "change")} in your checkout not installed yet`);
  if (H) parts.push(`the merge on ${H.branch}, fixed and committed`);
  const from = src.length === 2 ? "from both the original LFG and your fork" : src.length ? `from ${named(src[0])}` : "";
  const li = c => `<li class="mono small">${esc(c)}</li>`, group = (title, cs) => cs.length ? `<li><b>${esc(title)}</b><ul>${cs.map(li).join("")}</ul></li>` : "";
  const list = src.map(r => group(`From ${named(r)}`, R[r].commits || [])).concat(group("In your checkout, not installed yet", d.not_installed_commits || []));
  const blocked = d.current_branch && d.current_branch !== "main" ? `Switch ${esc(d.source)} to main first.` : d.dirty ? `${esc(d.source)} has uncommitted changes; commit or stash them first.` : "";
  const unlocked = await isUnlocked();
  box.hidden = false;
  box.className = "callout warn";
  box.innerHTML = `${dot("warn")}<b>LFG update ready${from ? ` ${esc(from)}` : ""}:</b> ${esc(parts.join(", "))}. <details class="more inline"><summary>What's in it</summary><ul>${list.join("")}</ul></details>
    ${blocked ? `<span class="muted small">${blocked}</span>` : `<button class="btn small primary" id="update-go" ${unlocked ? "" : "disabled title=\"Open the dashboard with lfg ui to update from here\""}>Update</button><span class="muted small"> Tests run first; if they fail nothing changes.</span>`}`;
  const go = $("#update-go");
  if (go) go.onclick = async () => {
    go.disabled = true; go.textContent = "Starting…";
    const r = await save("update_apply", {});
    if (!r.ok) { go.disabled = false; go.textContent = "Try again"; return alertMsg(go, r); }
    watchUpdate();
  };
}
const fixingMsg = F => `${dot("on")}Claude is fixing the stopped update${F.branch ? ` on <code>${esc(F.branch)}</code>` : ""}, started ${ago(F.started)}. Once it commits a fix, the update runs again by itself.`;
let watching = false;  /* one watcher at a time: the banner re-checks every minute and would start another */
async function watchUpdate() {
  if (watching) return;
  watching = true;
  try { await watchLoop(); } finally { watching = false; }
}
async function watchLoop() {
  const box = $("#update-banner");
  for (;;) {
    await new Promise(r => setTimeout(r, 2500));
    let d;
    try { d = await api("update", { t: Date.now() }); } catch (e) { continue; }
    const j = d.job || {}, F = d.fix || {};
    box.hidden = false;
    if (j.status === "running") { box.className = "callout"; box.innerHTML = `${dot("on")}Updating LFG… ${esc((j.steps || []).slice(-1)[0] || "")}`; continue; }
    if (F.status === "running") { box.className = "callout"; box.innerHTML = fixingMsg(F); continue; }
    if (j.status === "done") {
      box.innerHTML = `${dot("on")}Installed. Reloading the dashboard on the new version…`;
      await save("ui_restart", {});
      for (let i = 0; i < 40; i++) {
        await new Promise(r => setTimeout(r, 750));
        try { const r = await fetch("/api/unlocked", { headers: { "X-LFG": "1" } }); if (r.status) { location.reload(); return; } } catch (e) { /* restarting */ }
      }
      return;
    }
    return checkUpdate(true);
  }
}
setInterval(checkUpdate, 60 * 1000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) checkUpdate(); });
window.addEventListener("focus", () => checkUpdate());
function refresh() { state.cache = {}; state.fresh = true; mapStatus(); checkUpdate(true); route().finally(() => { state.fresh = false; }); }
/* Pages whose data changes without you (GitHub, running jobs) reload every 10 minutes, unless you're typing or a
   drawer is open, so nothing you're in the middle of is thrown away. */
const AUTO_REFRESH = ["home", "sessions", "environment", "prs", "checks", "runs", "issues"];
setInterval(() => {
  const page = (location.hash.slice(1) || "home").split("/")[0];
  const busy = document.hidden || document.querySelector("#drawer:not([hidden])") ||
    ["TEXTAREA", "INPUT", "SELECT"].includes((document.activeElement || {}).tagName);
  if (AUTO_REFRESH.includes(page) && !busy) refresh();
}, 10 * 60 * 1000);
init();
