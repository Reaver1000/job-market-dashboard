/* Job Market Snapshot: pure logic + browser rendering.
   The pure functions run in the browser and under Node (for tests).
   Data: latest.csv from the job-market-dashboard GitHub repo. */

// ---------------- pure logic ----------------

const REGION_RULES = [
  ["United States", /united states|\busa\b|u\.s\.|\bamerica\b|new york|san francisco|los angeles|chicago|boston|austin|seattle|denver|atlanta|dallas|miami|philadelphia|phoenix|houston|washington/i],
  ["Canada", /canada|toronto|vancouver|montreal|ottawa|calgary/i],
  ["United Kingdom", /united kingdom|\buk\b|\bengland\b|scotland|wales|london|manchester|birmingham|\bleeds\b|bristol|edinburgh|glasgow/i],
  ["Germany", /germany|deutschland|berlin|munich|m\u00fcnchen|hamburg|frankfurt|cologne|k\u00f6ln|leipzig|stuttgart|d\u00fcsseldorf|dusseldorf|dresden|nuremberg|heidelberg/i],
  ["Europe (other)", /france|paris|netherlands|amsterdam|spain|madrid|barcelona|italy|milan|rome|poland|warsaw|ireland|dublin|austria|vienna|switzerland|zurich|belgium|brussels|sweden|stockholm|denmark|copenhagen|finland|helsinki|norway|oslo|portugal|lisbon|czech|prague|\beurope\b/i],
  ["EMEA", /emea/i],
  ["APAC", /apac|asia|singapore|japan|tokyo|india|australia|sydney|china|beijing|shanghai|hong kong|korea|taiwan|new zealand|vietnam|thailand|indonesia|philippines|malaysia/i],
  ["LATAM", /latam|brazil|mexico|argentina|colombia|chile|peru/i],
  ["Africa", /africa|nigeria|kenya|egypt|ghana/i],
];

const JUNIOR_RE = /junior|graduate|entry/i;
const SENIOR_RE = /senior|\bsr\.?\b|lead|principal|staff|head of|director|\bvp\b|chief/i;

function parseCSV(text) {
  const rows = [];
  let row = [], field = "", inQ = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; } else { inQ = false; }
      } else { field += c; }
    } else if (c === '"') { inQ = true; }
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") {
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else if (c !== "\r") { field += c; }
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const header = rows.shift();
  return rows.map(r => {
    const o = {};
    header.forEach((h, i) => { o[h] = r[i] !== undefined ? r[i] : ""; });
    return o;
  });
}

function regionOf(loc) {
  const s = " " + (loc || "") + " ";
  for (const [label, re] of REGION_RULES) {
    if (re.test(s)) return label;
  }
  if (/remote|anywhere|worldwide|global/i.test(s)) return "Remote (unspecified)";
  return "Unrecognised";
}

function seniorityOf(title) {
  const t = title || "";
  if (JUNIOR_RE.test(t)) return "Junior/entry-titled";
  if (SENIOR_RE.test(t)) return "Senior-titled";
  return "Neither stated";
}

function derive(rows) {
  return rows.map(r => {
    const title = r.title || "";
    const postedRaw = (r.posted || "").trim();
    return {
      title,
      company: r.company || "",
      location: r.location || "",
      remote: parseInt(r.remote, 10) === 1 ? 1 : 0,
      posted: postedRaw && /^\d{4}-\d{2}-\d{2}$/.test(postedRaw) ? postedRaw : null,
      source: r.source || "",
      url: r.url || "",
      junior: JUNIOR_RE.test(title) ? 1 : 0,
      region: regionOf(r.location || ""),
      seniority: seniorityOf(title),
    };
  });
}

function applyFilters(rows, f) {
  return rows.filter(r =>
    (!f.sources.length || f.sources.includes(r.source)) &&
    (!f.remoteOnly || r.remote === 1) &&
    (!f.juniorOnly || r.junior === 1) &&
    (!f.excludeUS || r.region !== "United States") &&
    (!f.search || r.title.toLowerCase().includes(f.search.toLowerCase()))
  );
}

function countBy(rows, key) {
  const m = new Map();
  for (const r of rows) m.set(r[key], (m.get(r[key]) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

function aggregate(rows, windowDays) {
  const total = rows.length;
  const kpi = { total };
  if (!total) return { kpi, perDay: [], regions: [], remoteRegions: [], juniorRegions: [], seniority: [], companies: [], sources: [], remoteShare: [] };

  let remoteN = 0, juniorN = 0, jrRemote = 0, nonUsRemote = 0;
  const companies = new Set();
  for (const r of rows) {
    if (r.remote) remoteN++;
    if (r.junior) juniorN++;
    if (r.remote && r.junior) jrRemote++;
    if (r.remote && r.region !== "United States" && r.region !== "Unrecognised") nonUsRemote++;
    companies.add(r.company);
  }
  kpi.remote = remoteN;
  kpi.remotePct = (100 * remoteN / total).toFixed(1);
  kpi.junior = juniorN;
  kpi.juniorPct = (100 * juniorN / total).toFixed(1);
  kpi.juniorRemote = jrRemote;
  kpi.nonUsRemote = nonUsRemote;
  kpi.companies = companies.size;

  const dayMap = new Map();
  let maxDay = null;
  for (const r of rows) {
    if (!r.posted) continue;
    const d = dayMap.get(r.posted) || { total: 0, remote: 0, junior: 0 };
    d.total++; if (r.remote) d.remote++; if (r.junior) d.junior++;
    dayMap.set(r.posted, d);
    if (!maxDay || r.posted > maxDay) maxDay = r.posted;
  }
  let perDay = [...dayMap.entries()].map(([day, v]) => ({ day, ...v })).sort((a, b) => a.day < b.day ? -1 : 1);
  if (windowDays > 0 && maxDay) {
    const cutoff = new Date(maxDay + "T00:00:00Z");
    cutoff.setUTCDate(cutoff.getUTCDate() - (windowDays - 1));
    const cut = cutoff.toISOString().slice(0, 10);
    perDay = perDay.filter(p => p.day >= cut);
  }

  return {
    kpi,
    perDay,
    regions: countBy(rows, "region"),
    remoteRegions: countBy(rows.filter(r => r.remote === 1), "region"),
    juniorRegions: countBy(rows.filter(r => r.junior === 1), "region"),
    seniority: countBy(rows, "seniority"),
    companies: countBy(rows, "company").slice(0, 15),
    sources: countBy(rows, "source").slice(0, 15),
    remoteShare: (() => {
      const m = new Map();
      for (const r of rows) {
        const v = m.get(r.source) || { total: 0, remote: 0 };
        v.total++; if (r.remote) v.remote++;
        m.set(r.source, v);
      }
      return [...m.entries()]
        .filter(([, v]) => v.total >= 30)
        .map(([src, v]) => [src, Math.round(1000 * v.remote / v.total) / 10])
        .sort((a, b) => b[1] - a[1]);
    })(),
  };
}

// ---------------- browser bootstrap ----------------

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const DATA_URL = "https://raw.githubusercontent.com/Reaver1000/job-market-dashboard/main/data/latest.csv";
  const PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"];

  let ROWS = [];
  let charts = [];
  const state = {
    sources: [], remoteOnly: false, juniorOnly: false, excludeUS: false,
    search: "", windowDays: 30,
  };

  const $ = (id) => document.getElementById(id);

  async function init() {
    setStatus("loading the latest sweep...");
    let text = null, err = null;
    for (let i = 0; i < 5; i++) {
      try {
        const res = await fetch(DATA_URL, { cache: "no-store" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        text = await res.text();
        break;
      } catch (e) { err = e; await new Promise(r => setTimeout(r, 3000)); }
    }
    if (text === null) { setStatus("could not load the snapshot: " + (err && err.message), true); return; }
    ROWS = derive(parseCSV(text));
    setStatus("");
    buildFilters();
    render();
  }

  function setStatus(msg, isErr) {
    const el = $("status");
    el.textContent = msg || "";
    el.style.color = isErr ? "#e15759" : "#8899aa";
  }

  function buildFilters() {
    const all = countBy(ROWS, "source");
    const box = $("sourceBox");
    const top = all.slice(0, 10).map(e => e[0]);
    state.sources = top;
    all.forEach(([src, n]) => {
      const label = document.createElement("label");
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = top.includes(src);
      cb.addEventListener("change", () => {
        if (cb.checked) state.sources.push(src);
        else state.sources = state.sources.filter(s => s !== src);
        render();
      });
      label.appendChild(cb);
      label.appendChild(document.createTextNode(" " + src + " (" + n + ")"));
      box.appendChild(label);
    });

    $("remoteOnly").addEventListener("change", e => { state.remoteOnly = e.target.checked; render(); });
    $("juniorOnly").addEventListener("change", e => { state.juniorOnly = e.target.checked; render(); });
    $("excludeUS").addEventListener("change", e => { state.excludeUS = e.target.checked; render(); });
    $("search").addEventListener("input", e => { state.search = e.target.value.trim(); render(); });
    $("window").addEventListener("change", e => {
      state.windowDays = e.target.value === "all" ? 0 : parseInt(e.target.value, 10);
      render();
    });
  }

  function chart(canvasId, config) {
    const ctx = $(canvasId).getContext("2d");
    charts.push(new window.Chart(ctx, config));
  }

  function render() {
    charts.forEach(c => c.destroy());
    charts = [];
    const rows = applyFilters(ROWS, state);
    const a = aggregate(rows, state.windowDays);

    $("kTotal").textContent = a.kpi.total.toLocaleString();
    $("kRemote").textContent = a.kpi.remote.toLocaleString();
    $("kRemotePct").textContent = a.kpi.remotePct + "%";
    $("kJunior").textContent = a.kpi.junior.toLocaleString();
    $("kJuniorPct").textContent = a.kpi.juniorPct + "%";
    $("kJrRemote").textContent = a.kpi.juniorRemote.toLocaleString();
    $("kNonUsRemote").textContent = a.kpi.nonUsRemote.toLocaleString();
    $("kCompanies").textContent = a.kpi.companies.toLocaleString();
    $("countNote").textContent =
      a.kpi.total.toLocaleString() + " postings in view";

    const labels = a.perDay.map(p => p.day);
    chart("cPerDay", {
      type: "line",
      data: {
        labels,
        datasets: [
          { label: "total", data: a.perDay.map(p => p.total), borderColor: "#4e79a7", backgroundColor: "#4e79a733", fill: true, tension: 0.25, pointRadius: 2 },
          { label: "remote", data: a.perDay.map(p => p.remote), borderColor: "#f28e2b", tension: 0.25, pointRadius: 2 },
          { label: "junior", data: a.perDay.map(p => p.junior), borderColor: "#e15759", tension: 0.25, pointRadius: 2 },
        ],
      },
      options: { plugins: { legend: { labels: { color: "#aab6c2" } } }, scales: SCALES },
    });

    doughnut("cRegions", a.regions, "All postings by region");
    doughnut("cRemoteRegions", a.remoteRegions, "Remote postings by region");
    doughnut("cJuniorRegions", a.juniorRegions, "Junior/entry postings by region");
    doughnut("cSeniority", a.seniority, "Titles by seniority signal");

    bar("cCompanies", a.companies, "Top companies", true);
    bar("cSources", a.sources, "Roles by source", true);
    bar("cRemoteShare", a.remoteShare, "Remote share by source, % (min 30 postings)", false);
  }

  const SCALES = {
    x: { ticks: { color: "#8899aa", maxTicksLimit: 14 }, grid: { color: "#232a33" } },
    y: { ticks: { color: "#8899aa" }, grid: { color: "#232a33" }, beginAtZero: true },
  };

  function doughnut(id, entries, title) {
    if (!entries.length) { return; }
    chart(id, {
      type: "doughnut",
      data: {
        labels: entries.map(e => e[0]),
        datasets: [{
          data: entries.map(e => e[1]),
          backgroundColor: PALETTE.concat(["#556677", "#334455", "#667788"]),
          borderColor: "#12161c",
        }],
      },
      options: {
        cutout: "45%",
        plugins: {
          title: { display: true, text: title, color: "#ccd5de", font: { size: 13 } },
          legend: { position: "right", labels: { color: "#aab6c2", boxWidth: 12 } },
        },
      },
    });
  }

  function bar(id, entries, title, horizontal) {
    if (!entries.length) { return; }
    chart(id, {
      type: "bar",
      data: {
        labels: entries.map(e => e[0]),
        datasets: [{ data: entries.map(e => e[1]), backgroundColor: "#4e79a7", borderRadius: 3 }],
      },
      options: {
        indexAxis: horizontal ? "y" : "x",
        plugins: {
          title: { display: true, text: title, color: "#ccd5de", font: { size: 13 } },
          legend: { display: false },
        },
        scales: horizontal
          ? { x: SCALES.y, y: { ...SCALES.x, ticks: { ...SCALES.x.ticks, autoSkip: false, color: "#aab6c2" } } }
          : SCALES,
      },
    });
  }

  document.addEventListener("DOMContentLoaded", init);
}

// Node export for tests
if (typeof module !== "undefined" && module.exports) {
  module.exports = { parseCSV, regionOf, seniorityOf, derive, applyFilters, aggregate, countBy };
}
