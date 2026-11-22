/* Vaka yönetimi (23), bağlantı grafiği (24), araç zincirleme (25), rapor (26), ayarlar (27).
   app.js ve tools.js'teki yardımcıları kullanır. */

/* ======================================================================
   Varlık çıkarma: bir sonuçtaki e-posta, telefon, IP, alan adı, kullanıcı adı, görsel, adres
   ====================================================================== */
const FREE_MAIL = /^(gmail|googlemail|hotmail|outlook|live|yahoo|icloud|me|yandex|proton(mail)?|mail|gmx|aol|msn|windowslive)\./i;
const BIG_SITES = /(^|\.)(google|facebook|instagram|twitter|x|tiktok|youtube|linkedin|github|reddit|t\.me|telegram|wikipedia|apple|microsoft|amazon|gravatar|keybase|archive)\.\w+$/i;
const USER_TOOLS = new Set(["sherlock", "maigret", "whatsmyname", "blackbird", "social-analyzer", "nexfil", "user-scanner", "socialscan"]);
const DOMAIN_TOOLS = new Set(["theharvester", "whois", "crtsh", "subfinder", "dnstwist", "site-intel", "recon-ng", "spiderfoot"]);

function isPublicIPv4(ip) {
  const p = ip.split(".").map(Number);
  if (p.length !== 4 || p.some(n => n > 255)) return false;
  return !(p[0] === 10 || p[0] === 127 || p[0] === 0 || (p[0] === 192 && p[1] === 168) || (p[0] === 172 && p[1] >= 16 && p[1] <= 31) || (p[0] === 169 && p[1] === 254) || p[0] >= 224);
}

function entitiesOf(r, tool) {
  if (!r) return [];
  const out = [];
  const add = (type, value) => { value = String(value || "").trim(); if (value && !out.some(e => e.type === type && e.value.toLowerCase() === value.toLowerCase())) out.push({ type, value }); };
  const metaVals = Object.values(r.meta || {}).join(" ");
  const text = `${r.title || ""} ${r.detail || ""} ${metaVals}`;
  for (const m of text.matchAll(/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g)) if (!/noreply|\.(png|jpg|gif)$/i.test(m[0])) add("email", m[0]);
  for (const m of text.matchAll(/(?:\+|00)\d[\d\s()-]{9,16}\d|\b0\d{3}[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b/g)) {
    const digits = m[0].replace(/\D/g, "");
    if (/^\+0|^000|\d{4}-\d{2}-\d{2}|\d{2}:\d{2}/.test(m[0].trim())) continue;   // saat dilimi / tarih damgası, telefon değil
    if (digits.length >= 10 && digits.length <= 15) add("phone", m[0].replace(/\s+/g, " ").trim());
  }
  for (const m of text.matchAll(/\b(?:\d{1,3}\.){3}\d{1,3}\b/g)) if (isPublicIPv4(m[0])) add("ip", m[0]);
  if (r.kind === "username") add("username", r.title);
  // Ad soyad: sonuçların "Ad / fullname / name" alanlarından ya da "Commit'teki ad: …" başlıklarından
  const looksLikeName = v => /^[\p{L}][\p{L}'’.-]+(\s+[\p{L}][\p{L}'’.-]+){1,3}$/u.test(v) && v.length <= 60;
  const nameVals = [r.meta?.["Ad"], r.meta?.["Ad Soyad"], r.meta?.fullname, r.meta?.name, (r.title.match(/^Commit'teki ad: (.+)$/) || [])[1]];
  if (r.kind === "person") nameVals.push(r.title);
  for (const v of nameVals) if (v && looksLikeName(String(v).trim())) add("name", String(v).trim());
  if (r.username) add("username", r.username);                       // Sherlock satırı
  let url = null;
  try { url = r.url && /^https?:/.test(r.url) ? new URL(r.url) : null; } catch {}
  if (url && !/google\.com\/search|bing\.com\/search|duckduckgo|yandex\.\w+\/search|web\.archive\.org|maps/.test(url.href)) {
    const host = url.hostname.replace(/^www\./, "");
    const path = url.pathname.replace(/\/+$/, "");
    if (USER_TOOLS.has(tool) || r.username) {
      const seg = path.split("/").filter(Boolean).pop();
      if (seg && /^@?[\w.-]{2,40}$/.test(seg) && !/\.(php|html?)$/.test(seg)) add("username", seg.replace(/^@/, ""));
    }
    if ((DOMAIN_TOOLS.has(tool) || !path || path === "") && !BIG_SITES.test(host)) add("domain", host);
    add("url", url.href);
  }
  for (const e of out.filter(e => e.type === "email")) {
    const d = e.value.split("@")[1];
    if (!FREE_MAIL.test(d + ".")) add("domain", d);
  }
  if (r.image && /^https?:/.test(r.image)) add("image", r.image);
  else if (r.image && r.image.startsWith("/")) add("image", location.origin + r.image);
  if (r.kind === "gps" && r.lat != null) add("coords", `${r.lat},${r.lon}`);
  return out;
}

const CHAIN = {
  email: [["holehe", "Holehe", { email: "$" }], ["email-accounts", "E-posta hesap kontrolü", { email: "$" }], ["email-verify", "E-posta doğrulayıcı", { email: "$" }],
          ["hibp", "HIBP sızıntıları", { email: "$" }], ["h8mail", "h8mail", { email: "$" }], ["ghunt", "GHunt", { email: "$" }, v => /@gmail\.com$/i.test(v)],
          ["user-scanner", "user-scanner", { target: "$" }], ["blackbird", "Blackbird", { target: "$" }], ["dorks", "Google dorkları", { value: "$", kind: "email" }]],
  phone: [["phonenumbers", "Numara çözümleyici", { number: "$" }], ["ignorant", "Ignorant", { number: "$" }], ["phoneinfoga", "PhoneInfoga", { number: "$" }],
          ["phone-search", "Numara varyasyon araması", { number: "$" }]],
  ip: [["ipgeo", "IP konum sorgusu", { target: "$" }], ["shodan", "Shodan", { target: "$" }]],
  domain: [["whois", "WHOIS / DNS", { domain: "$" }], ["crtsh", "Sertifika kayıtları", { domain: "$" }], ["subfinder", "subfinder + httpx", { domain: "$" }],
           ["site-intel", "Site izleyici analizi", { url: "$" }], ["wayback", "Wayback (site)", { url: "$", mode: "domain" }],
           ["theharvester", "theHarvester", { domain: "$" }], ["dnstwist", "Sahte alan adları", { domain: "$" }], ["doc-meta", "Belge meta verisi", { domain: "$" }],
           ["ipgeo", "IP konumu", { target: "$" }], ["dorks", "Google dorkları", { value: "$", kind: "domain" }]],
  username: [["sherlock", "Sherlock", null], ["maigret", "Maigret", { username: "$" }], ["whatsmyname", "WhatsMyName", { username: "$" }],
             ["user-scanner", "user-scanner", { target: "$" }], ["nexfil", "Nexfil", { username: "$" }], ["github", "GitHub profili", { username: "$" }],
             ["social-activity", "Reddit / HN / Keybase", { username: "$" }], ["telegram", "Telegram", { username: "$" }],
             ["instaloader", "Instagram (Instaloader)", { username: "$" }], ["dorks", "Google dorkları", { value: "$", kind: "username" }]],
  image: [["geofusion", "Konum bulucu", { url: "$" }], ["exiftool", "ExifTool", { url: "$" }], ["reverse-image", "Ters görsel arama", { url: "$" }, v => !v.startsWith(location.origin)],
          ["geolocate", "Görsel konum tahmini", { url: "$" }], ["ela", "Sahtecilik analizi (ELA)", { url: "$" }]],
  url: [["wayback", "Wayback (bu sayfa)", { url: "$", mode: "page" }], ["site-intel", "Site izleyici analizi", { url: "$" }],
        ["video", "Video analizi", { url: "$" }, v => /youtu|tiktok|vimeo|instagram\.com\/(reel|p)\/|x\.com\/.+\/status|twitter\.com\/.+\/status|dailymotion|twitch/i.test(v)]],
  coords: [["ipgeo", "", null, () => false]],
  name: [["namesearch", "İsim araştırma", { name: "$" }], ["dorks", "Google dorkları", { value: "$", kind: "name" }]],
};
const ENT_LABEL = { name: "Ad soyad", email: "E-posta", phone: "Telefon", ip: "IP", domain: "Alan adı", username: "Kullanıcı adı", image: "Görsel", url: "Adres", coords: "Konum" };

function chainActions(r, tool) {
  return entitiesOf(r, tool).map(e => ({
    ...e, actions: (CHAIN[e.type] || []).filter(([id, , , ok]) => id !== tool && (!ok || ok(e.value)) && (id === "sherlock" || T.registry.some(t => t.id === id))),
  })).filter(e => e.actions.length);
}

function chainListHTML(r, tool) {
  const groups = chainActions(r, tool);
  if (!groups.length) return "";
  return `<div class="chain-list"><div class="chain-h">Bununla devam et</div>${groups.map(g => `
    <div class="chain-group"><span class="chain-ent">${ENT_LABEL[g.type]}: <b>${esc(g.value.length > 60 ? g.value.slice(0, 57) + "…" : g.value)}</b></span>
      <div class="chain-btns">${g.actions.map(([id, label, f]) => `<button type="button" class="chain-btn" data-run="${id}" data-fields='${esc(JSON.stringify(fill(f, g.value)))}'>${esc(label)}</button>`).join("")}</div></div>`).join("")}
    <button type="button" class="chain-btn save" data-savecur="1">+ Vakaya ekle</button></div>`;
}
const fill = (f, v) => f ? Object.fromEntries(Object.entries(f).map(([k, x]) => [k, x === "$" ? v : x])) : { __sherlock: v };

let chainCtx = null;
function openChainMenu(btn, r, tool) {
  const menu = $("#chainMenu");
  chainCtx = { r, tool };
  menu.innerHTML = chainListHTML(r, tool) || '<div class="chain-h">Bu sonuçtan çıkarılabilen bir değer yok.</div>';
  menu.hidden = false;
  const b = btn.getBoundingClientRect();
  const w = Math.min(360, innerWidth - 24);
  menu.style.width = w + "px";
  menu.style.left = Math.max(12, Math.min(b.right - w, innerWidth - w - 12)) + "px";
  const below = b.bottom + 6 + menu.offsetHeight < innerHeight;
  menu.style.top = (below ? b.bottom + 6 : Math.max(12, b.top - menu.offsetHeight - 6)) + "px";
}
document.addEventListener("click", e => {
  const run = e.target.closest("[data-run]");
  if (run) {
    e.preventDefault();
    $("#chainMenu").hidden = true;
    const fields = JSON.parse(run.dataset.fields);
    if (run.dataset.run === "sherlock") return sendToSherlock([fields.__sherlock]);
    return runTool(run.dataset.run, fields);
  }
  if (e.target.closest("[data-savecur]")) {
    $("#chainMenu").hidden = true;
    const ctx = chainCtx || drawerCtx;
    if (ctx) saveToCase(ctx.tool, ctx.tool === "sherlock" ? state.job : T.job, [ctx.r]);
    return;
  }
  if (!e.target.closest("#chainMenu") && !e.target.closest("[data-chain]")) $("#chainMenu").hidden = true;
});
addEventListener("keydown", e => { if (e.key === "Escape") $("#chainMenu").hidden = true; });

/* Bir aracı açıp alanlarını doldurup çalıştırır. */
function runTool(id, fields) {
  closeDrawer();
  selectTool(id);
  const tool = T.registry.find(t => t.id === id);
  if (!tool) return;
  for (const [k, v] of Object.entries(fields)) {
    const el = $("#tMain").name === k && !$("#tMain").hidden ? $("#tMain") : $(`#f_${k}`);
    if (el) el.type === "checkbox" ? (el.checked = !!v) : (el.value = v);
  }
  if (T.es) return toast("Bu araç zaten çalışıyor");
  $("#toolForm").requestSubmit();
}
function sendToSherlock(list) {
  closeDrawer();
  selectTool("sherlock");
  if (state.es) return toast("Sherlock şu an çalışıyor; adlar listeye eklendi");
  const n = addNames(list);
  toast(`${n || list.length} ad Sherlock listesine eklendi`);
  if (list.length === 1) $("#searchForm").requestSubmit();
}

/* Sherlock çekmecesine zincirleme listesi ekle */
let drawerCtx = null;
const _renderPreview = renderPreview;
renderPreview = function (r, d) {
  _renderPreview(r, d);
  if (!r || preview.url !== r.url) return;
  const row = { ...r, image: d && d.ok !== false ? d.image : "", detail: d?.description || "" };
  drawerCtx = { r: row, tool: "sherlock" };
  $("#pvBody").insertAdjacentHTML("beforeend", chainListHTML(row, "sherlock"));
};
const _showToolDetail = showToolDetail;
showToolDetail = async function (r) { drawerCtx = { r, tool: T.current }; return _showToolDetail(r); };

/* ======================================================================
   Vakalar
   ====================================================================== */
const C = { current: null, currentName: "", open: null, graph: null, notesTimer: null };
try { const s = JSON.parse(localStorage.getItem("osint-case") || "null"); if (s) { C.current = s.id; C.currentName = s.name; } } catch {}
function setCurrentCase(id, name) {
  C.current = id; C.currentName = name || "";
  try { localStorage.setItem("osint-case", JSON.stringify(id ? { id, name } : null)); } catch {}
  $("#caseChipName").textContent = id ? name : "Seçilmedi";
  $("#caseChip").classList.toggle("on", !!id);
}
setCurrentCase(C.current, C.currentName);
$("#caseChip").onclick = () => { selectTool("cases"); if (C.current) openCase(C.current); };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

async function ensureCase(suggest) {
  if (C.current) {
    try { await api(`/api/cases/${C.current}`); return C.current; } catch { setCurrentCase(null); }
  }
  const c = await api("/api/cases", { method: "POST", body: { name: suggest || "Yeni vaka" } });
  setCurrentCase(c.id, c.name);
  toast(`"${c.name}" vakası oluşturuldu ve aktif yapıldı`);
  return c.id;
}

/* tool: araç kimliği; job: iş kimliği; rows: sonuç nesneleri */
async function saveToCase(tool, job, rows) {
  rows = rows.filter(Boolean);
  if (!rows.length) return toast("Kaydedilecek sonuç yok");
  try {
    let n;
    if (tool === "sherlock") {
      const q = [...new Set(rows.map(r => r.username))].join(", ");
      const cid = await ensureCase(q);
      const items = rows.map(r => {
        const pv = state.previews[r.url] || {};
        return { title: r.site, url: r.url, status: "found", tags: "Sherlock", image: pv.ok !== false ? pv.image || "" : "",
                 detail: pv.ok !== false ? (pv.title || "") : "", meta: { "Kullanıcı adı": r.username, "Yanıt süresi": r.time_ms ? `${r.time_ms} ms` : "" } };
      });
      ({ added: n } = await api(`/api/cases/${cid}/items`, { method: "POST", body: { tool: "sherlock", query: q, items } }));
    } else {
      const cid = await ensureCase($("#tMain").value || T.registry.find(t => t.id === tool)?.title);
      ({ added: n } = await api(`/api/cases/${cid}/items`, { method: "POST", body: { job, indices: rows.map(r => r.i) } }));
    }
    toast(n ? `${n} bulgu "${C.currentName}" vakasına eklendi` : "Bunlar vakada zaten var");
  } catch (e) { toast("Kaydedilemedi: " + e.message); }
}
$("#tSaveCase").onclick = () => saveToCase(T.current, T.job, T.results.filter(r => (r.status === "found" || r.status === "maybe") && r.kind !== "histogram"));
$("#sSaveCase").onclick = () => saveToCase("sherlock", state.job, state.results.filter(r => r && eff(r) === "Claimed"));
const _finish = finish;
finish = function (info) { _finish(info); $("#sSaveCase").disabled = !state.results.some(r => r && eff(r) === "Claimed"); };

async function openCases() {
  if (C.open) return openCase(C.open);
  $("#casesList").hidden = false; $("#caseDetail").hidden = true;
  const list = await api("/api/cases");
  $("#caseCards").innerHTML = list.length ? list.map(c => `
    <button type="button" class="case-card ${c.id === C.current ? "on" : ""}" data-case="${c.id}">
      <b>${esc(c.name)}</b><span>${c.n} bulgu · ${new Date(c.updated * 1000).toLocaleString("tr-TR", { dateStyle: "medium", timeStyle: "short" })}</span>
      ${c.id === C.current ? '<i class="case-on">aktif</i>' : ""}</button>`).join("")
    : '<div class="empty">Henüz vaka yok. Yukarıdan bir tane oluşturun ya da herhangi bir araçta "Vakaya kaydet"e basın.</div>';
}
$("#caseCards").onclick = e => { const b = e.target.closest("[data-case]"); if (b) openCase(+b.dataset.case); };
$("#newCaseForm").onsubmit = async e => {
  e.preventDefault();
  const c = await api("/api/cases", { method: "POST", body: { name: $("#newCaseName").value } });
  $("#newCaseName").value = "";
  setCurrentCase(c.id, c.name);
  openCase(c.id);
};
$("#caseBack").onclick = () => { C.open = null; openCases(); };

let caseData = null;
async function openCase(id) {
  C.open = id;
  try { caseData = await api(`/api/cases/${id}`); } catch { C.open = null; return openCases(); }
  $("#casesList").hidden = true; $("#caseDetail").hidden = false;
  $("#caseName").value = caseData.name;
  $("#caseNotes").value = caseData.notes || "";
  $("#caseReport").href = `/case/${id}/report?lang=${typeof LANG === "string" ? LANG : "tr"}`;
  $("#caseActivate").textContent = C.current === id ? "Aktif vaka ✓" : "Aktif vaka yap";
  $("#caseActivate").disabled = C.current === id;
  const tools = new Set(caseData.items.map(i => i.tool));
  $("#caseMeta").textContent = `${caseData.items.length} bulgu · ${tools.size} araç · oluşturma ${new Date(caseData.created * 1000).toLocaleDateString("tr-TR")}`;
  await loadEvidence();
  showCaseTab(C.tab || "items");
}
$("#caseName").onchange = async () => {
  const c = await api(`/api/cases/${C.open}`, { method: "PATCH", body: { name: $("#caseName").value } });
  if (C.current === C.open) setCurrentCase(c.id, c.name);
};
$("#caseActivate").onclick = () => { setCurrentCase(caseData.id, caseData.name); openCase(caseData.id); toast("Aktif vaka değişti"); };
$("#caseDelete").onclick = async () => {
  if (!confirm(`"${caseData.name}" vakası ve içindeki ${caseData.items.length} bulgu kalıcı olarak silinecek. Emin misiniz?`)) return;
  await api(`/api/cases/${C.open}`, { method: "DELETE" });
  if (C.current === C.open) setCurrentCase(null);
  C.open = null; openCases(); toast("Vaka silindi");
};
$("#caseNotes").oninput = () => {
  clearTimeout(C.notesTimer);
  $("#notesSaved").textContent = "Kaydediliyor…";
  C.notesTimer = setTimeout(async () => {
    await api(`/api/cases/${C.open}`, { method: "PATCH", body: { notes: $("#caseNotes").value } });
    $("#notesSaved").textContent = "Kaydedildi " + new Date().toLocaleTimeString("tr-TR");
  }, 700);
};
$$("#caseTabs .chip").forEach(c => c.onclick = () => showCaseTab(c.dataset.ctab));
$("#caseFilter").oninput = () => renderCaseItems();

function showCaseTab(tab) {
  C.tab = tab;
  $$("#caseTabs .chip").forEach(c => c.classList.toggle("active", c.dataset.ctab === tab));
  $("#caseItems").hidden = tab !== "items";
  $("#caseGraphWrap").hidden = tab !== "graph";
  $("#caseNotesWrap").hidden = tab !== "notes";
  $("#caseTimelineWrap").hidden = tab !== "timeline";
  $("#caseWatchWrap").hidden = tab !== "watch";
  $("#caseFilter").parentElement.hidden = tab !== "items";
  if (tab === "items") renderCaseItems();
  if (tab === "graph") renderGraph();
  if (tab === "timeline") renderTimeline();
  if (tab === "watch") renderWatch();
}

const toolTitle = id => id === "sherlock" ? "Sherlock" : (T.registry.find(t => t.id === id)?.title || id);
function renderCaseItems() {
  const q = $("#caseFilter").value.trim().toLowerCase();
  const items = caseData.items.filter(i => !q || `${i.title} ${i.url} ${i.detail} ${i.note} ${i.tags} ${JSON.stringify(i.meta)}`.toLowerCase().includes(q));
  if (!items.length) {
    $("#caseItems").innerHTML = `<div class="empty">${caseData.items.length ? "Aramaya uyan bulgu yok." : "Bu vakada henüz bulgu yok. Herhangi bir aracın sonuçlarında + ya da “Bulunanları vakaya kaydet” düğmesini kullanın."}</div>`;
    return;
  }
  const groups = {};
  items.forEach(i => (groups[`${i.tool}\u0000${i.query}`] ||= []).push(i));
  $("#caseItems").innerHTML = Object.entries(groups).map(([k, list]) => {
    const [tool, query] = k.split("\u0000");
    return `<section class="case-group"><h3>${esc(toolTitle(tool))} <span class="muted">· ${esc(query)}</span> <span class="n">${list.length}</span></h3>
      <div class="rlist">${list.map(i => `
        <div class="ritem case-item" data-item="${i.id}">
          <div class="thumb">${i.image ? `<img src="${esc(i.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'dot ${i.status}'}))">` : `<i class="dot ${i.status}"></i>`}</div>
          <div>
            <div class="t1">${esc(i.title)}</div>
            ${i.url ? `<div class="t2"><a href="${esc(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.url)}</a></div>` : ""}
            ${i.detail ? `<div class="t3">${esc(i.detail)}</div>` : ""}
            ${evidenceBadge(i)}
            <input class="item-note" data-note="${i.id}" value="${esc(i.note || "")}" placeholder="not ekle…">
          </div>
          <div class="ractions"><span class="tag2">${esc(i.tags || "")}</span>
            ${i.url && /^https?:/.test(i.url) ? `<button type="button" class="rbtn" data-evid="${i.id}" title="Kanıt olarak arşivle (ekran görüntüsü + HTML + SHA-256)">⎙</button>` : ""}
            <button type="button" class="rbtn" data-cchain="${i.id}" title="Bununla devam et">→</button>
            <button type="button" class="rbtn" data-del="${i.id}" title="Vakadan çıkar">×</button></div>
        </div>`).join("")}</div></section>`;
  }).join("");
}
$("#caseItems").addEventListener("click", async e => {
  const ev = e.target.closest("[data-evid]");
  if (ev) {
    ev.disabled = true; ev.textContent = "…";
    try {
      const rec = await api(`/api/items/${ev.dataset.evid}/evidence`, { method: "POST" });
      toast(rec.error && !rec.png_sha256 && !rec.html_sha256 ? "Arşivlenemedi: " + rec.error : "Kanıt arşivlendi");
    } catch (err) { toast("Arşivlenemedi: " + err.message); }
    await loadEvidence(); return renderCaseItems();
  }
  const del = e.target.closest("[data-del]");
  if (del) {
    await api(`/api/items/${del.dataset.del}`, { method: "DELETE" });
    caseData.items = caseData.items.filter(i => i.id !== +del.dataset.del);
    return renderCaseItems();
  }
  const ch = e.target.closest("[data-cchain]");
  if (ch) {
    const it = caseData.items.find(i => i.id === +ch.dataset.cchain);
    return openChainMenu(ch, it, it.tool);
  }
});
$("#caseItems").addEventListener("change", async e => {
  const n = e.target.closest("[data-note]");
  if (!n) return;
  await api(`/api/items/${n.dataset.note}`, { method: "PATCH", body: { note: n.value } });
  caseData.items.find(i => i.id === +n.dataset.note).note = n.value;
  toast("Not kaydedildi");
});

/* ======================================================================
   Bağlantı grafiği (vis-network)
   ====================================================================== */
const ENT_COLOR = { name: "#b7791f", email: "#c0392b", phone: "#8e44ad", ip: "#d35400", domain: "#2471a3", username: "#2f6f3e", query: "#1c1b19", item: "#7f8c8d", image: "#16a085", case: "#1c1b19" };
function buildGraph(c) {
  const nodes = new Map(), edges = [];
  const node = (id, o) => { if (!nodes.has(id)) nodes.set(id, { id, ...o }); return id; };
  const entId = e => `${e.type}:${e.value.toLowerCase()}`;
  const root = node("case", { label: c.name, shape: "box", color: { background: ENT_COLOR.case, border: ENT_COLOR.case }, font: { color: "#fff", size: 16 }, margin: 10 });
  const queries = {};
  for (const it of c.items) {
    if (it.status === "notfound" || it.status === "error") continue;
    // sorgu düğümü (aranan değer) — e-posta / alan adı vb. ise o varlıkla birleşir
    const qe = entitiesOf({ title: it.query, kind: it.tool === "namesearch" ? "person"
      : USER_TOOLS.has(it.tool) && !/[@.\s]/.test(it.query) ? "username" : "" }, "")[0];
    const qid = qe && qe.type !== "url" ? entId(qe) : `q:${it.query}`;
    if (!queries[qid]) {
      node(qid, { label: it.query, group: qe?.type || "query", shape: "dot", size: 16, color: ENT_COLOR[qe?.type] || ENT_COLOR.query, font: { size: 14, bold: true } });
      edges.push({ from: root, to: qid, dashes: true });
      queries[qid] = true;
    }
    const iid = `item:${it.id}`;
    const img = it.image && !it.image.startsWith("data:") ? it.image : null;
    node(iid, { label: it.title.length > 38 ? it.title.slice(0, 36) + "…" : it.title, title: `${toolTitle(it.tool)}\n${it.url || ""}\n${it.detail || ""}`,
                shape: img ? "circularImage" : "dot", image: img || undefined, size: img ? 18 : 8, color: ENT_COLOR.item, url: it.url, brokenImage: undefined });
    edges.push({ from: qid, to: iid, label: toolTitle(it.tool), font: { size: 9, color: "#999", strokeWidth: 0 }, arrows: "to" });
    for (const e of entitiesOf(it, it.tool)) {
      if (e.type === "url" || e.type === "image" || e.type === "coords") continue;
      const eid = entId(e);
      if (eid === qid) continue;
      node(eid, { label: e.value, group: e.type, shape: "dot", size: 11, color: ENT_COLOR[e.type], font: { size: 12 } });
      edges.push({ from: iid, to: eid, color: { color: ENT_COLOR[e.type], opacity: .5 } });
    }
  }
  return { nodes: [...nodes.values()], edges };
}
function renderGraph() {
  const el = $("#caseGraph");
  $("#graphLegend").innerHTML = Object.entries({ name: "Ad soyad", username: "Kullanıcı adı", email: "E-posta", phone: "Telefon", domain: "Alan adı", ip: "IP", item: "Bulgu" })
    .map(([k, l]) => `<span><i style="background:${ENT_COLOR[k]}"></i>${l}</span>`).join("");
  if (!window.vis) { el.innerHTML = '<div class="empty">Grafik kütüphanesi yüklenemedi (internet bağlantısı gerekir).</div>'; return; }
  const g = buildGraph(caseData);
  if (g.nodes.length < 2) { el.innerHTML = '<div class="empty">Grafik için vakada bulgu olmalı.</div>'; return; }
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  C.graph?.destroy();
  el.innerHTML = "";
  C.graph = new vis.Network(el, { nodes: new vis.DataSet(g.nodes), edges: new vis.DataSet(g.edges) }, {
    nodes: { font: { color: dark ? "#e8e6e1" : "#1c1b19", face: "IBM Plex Sans" }, borderWidth: 1 },
    edges: { color: { color: dark ? "#3a3936" : "#d3cfc6" }, smooth: { type: "continuous" }, width: 1 },
    physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -60, springLength: 90 }, stabilization: { iterations: 200 } },
    interaction: { hover: true, tooltipDelay: 150 },
  });
  C.graph.on("doubleClick", p => {
    const n = g.nodes.find(x => x.id === p.nodes[0]);
    if (n?.url) window.open(n.url, "_blank", "noopener");
  });
}

/* ======================================================================
   Ayarlar: anahtarlar kalıcıdır (settings.json); yazıldıktan sonra gizlenir, göz simgesiyle görünür.
   ====================================================================== */
const EYE = '<svg viewBox="0 0 24 24"><path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/></svg>';
const EYE_OFF = '<svg viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 5.6A9.7 9.7 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-3 3.8M6.6 6.6C4 8.3 2.5 12 2.5 12s3.5 6.5 9.5 6.5a9 9 0 0 0 4.3-1.1M9.9 9.9a2.8 2.8 0 0 0 4.2 4.2"/></svg>';
const SAVED = {};

async function refreshKeyStatus() {
  try {
    const d = await api("/api/settings");
    T.keys = d.keys; T.toolKeys = d.tool_keys;
    renderNav();
    return d;
  } catch { return null; }
}

async function loadSettings() {
  const d = await refreshKeyStatus();
  if (!d) return;
  d.settings.forEach(s => (SAVED[s.key] = s.value));
  $("#settingsForm").innerHTML = d.settings.map(s => `
    <div class="set-row" data-row="${s.key}">
      <label for="s_${s.key}"><b>${esc(s.label)}</b><span>${esc(s.help)}</span>
        ${s.used_by ? `<em>Kullanan: ${esc(s.used_by)}</em>` : ""}</label>
      <div class="set-col">
        <div class="set-input ${s.set ? "is-set" : ""}">
          <input id="s_${s.key}" name="${s.key}" type="${s.secret ? "password" : "text"}" autocomplete="off" spellcheck="false"
                 data-secret="${s.secret ? 1 : 0}" value="${esc(s.value)}" placeholder="${s.secret ? "anahtarı yapıştırın" : "boş"}">
          ${s.secret ? `<button type="button" class="eye" data-eye="${s.key}" title="Göster / gizle" aria-label="Göster / gizle">${EYE}</button>` : ""}
          <span class="set-ok" title="Kayıtlı">✓</span>
        </div>
        <div class="set-btns">
          ${s.url ? `<a class="get-key" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${s.key === "instagram_sessionid" ? "Instagram'ı aç" : s.key === "h8mail_keys" ? "Desteklenen servisler" : "Anahtar al"} ↗</a>` : ""}
          ${s.set ? `<button type="button" class="text" data-clear="${s.key}">Sil</button>` : ""}
        </div>
      </div>
    </div>`).join("") + `<div class="set-save"><button type="submit">Kaydet</button><span class="note" id="setNote">Değişiklikler alandan çıkınca da kendiliğinden kaydedilir.</span></div>`;
  $("#settingsStatus").innerHTML = `
    <h3>Oturum gerektiren araçlar</h3>
    <div class="set-stat"><b>GHunt</b>${d.status.ghunt ? '<span class="ok">✓ Google oturumu açık</span>'
      : `<span class="warn-t">Oturum yok</span> — terminalde bir kez çalıştırın: <code id="ghuntCmd">tools/ghunt/bin/ghunt login</code>
         <button type="button" class="text" id="copyGhunt">Kopyala</button>`}</div>
    <div class="set-stat"><b>Görsel konum tahmini</b>${d.keys.anthropic_api_key
      ? `<span class="ok">✓ Anthropic anahtarı ${d.status.anthropic_env && !SAVED.anthropic_api_key ? "(ortam değişkeninden)" : "kayıtlı"}</span>` : '<span class="warn-t">Anahtar yok</span>'}</div>`;
  $("#copyGhunt")?.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText("tools/ghunt/bin/ghunt login"); toast("Komut kopyalandı"); } catch { toast("Kopyalanamadı"); }
  });
}

async function saveSettings(keys) {
  const body = {};
  for (const k of keys) {
    const el = $(`#s_${k}`);
    if (!el) continue;
    const v = el.value.trim();
    if (v !== (SAVED[k] || "")) body[k] = v;
  }
  if (!Object.keys(body).length) return false;
  await api("/api/settings", { method: "POST", body });
  Object.assign(SAVED, body);
  for (const k of Object.keys(body)) {
    const row = $(`[data-row="${k}"] .set-input`);
    row?.classList.toggle("is-set", !!body[k]);
    const el = $(`#s_${k}`);
    if (el?.dataset.secret === "1") { el.type = "password"; $(`[data-eye="${k}"]`).innerHTML = EYE; }
  }
  await refreshKeyStatus();
  return true;
}
$("#settingsForm").onsubmit = async e => {
  e.preventDefault();
  const changed = await saveSettings($$("#settingsForm input").map(i => i.name));
  toast(changed ? "Ayarlar kaydedildi" : "Değişiklik yok");
  loadSettings();
};
// Alandan çıkınca kaydet ve gizle
$("#settingsForm").addEventListener("focusout", async e => {
  const i = e.target.closest("input[name]");
  if (!i || e.relatedTarget?.dataset?.eye === i.name) return;
  if (await saveSettings([i.name])) toast("Kaydedildi");
  if (i.dataset.secret === "1") { i.type = "password"; const b = $(`[data-eye="${i.name}"]`); if (b) b.innerHTML = EYE; }
});
$("#settingsForm").addEventListener("click", async e => {
  const eye = e.target.closest("[data-eye]");
  if (eye) {
    const i = $(`#s_${eye.dataset.eye}`);
    const show = i.type === "password";
    i.type = show ? "text" : "password";
    eye.innerHTML = show ? EYE_OFF : EYE;
    return;
  }
  const c = e.target.closest("[data-clear]");
  if (!c) return;
  if (!confirm("Bu kayıtlı değer silinsin mi?")) return;
  await api("/api/settings", { method: "POST", body: { [c.dataset.clear]: "" } });
  toast("Silindi");
  loadSettings();
});
refreshKeyStatus();


/* ---------------- kanıt arşivi ---------------- */
C.evidence = {};
async function loadEvidence() {
  try {
    const d = await api(`/api/cases/${C.open}/evidence`);
    C.evidence = {};
    d.items.forEach(e => (C.evidence[e.item_id] ||= []).push(e));
    C.chrome = d.chrome;
    const j = d.job;
    $("#caseArchiveAll").textContent = j && j.done < j.total ? `Arşivleniyor ${j.done}/${j.total}…` : "Kanıtları arşivle";
    return j;
  } catch { return null; }
}
function evidenceBadge(i) {
  const list = C.evidence?.[i.id];
  if (!list?.length) return "";
  const e = list[list.length - 1];
  const ok = e.png_sha256 || e.html_sha256;
  const when = new Date(e.captured_at).toLocaleString(LANG === "en" ? "en-GB" : "tr-TR");
  return `<div class="ev-badge ${ok ? "" : "bad"}">
    ${e.has_png ? `<a href="/api/evidence/${e.id}/png" target="_blank" rel="noopener"><img src="/api/evidence/${e.id}/png" alt="" loading="lazy"></a>` : ""}
    <div><b>${ok ? "Kanıt arşivlendi" : "Arşivlenemedi"}</b> · ${esc(when)}${e.http_status ? ` · HTTP ${e.http_status}` : ""}
      ${e.png_sha256 ? `<div class="mono">PNG SHA-256 ${esc(e.png_sha256.slice(0, 16))}…</div>` : ""}
      ${e.html_sha256 ? `<div class="mono">HTML SHA-256 ${esc(e.html_sha256.slice(0, 16))}…</div>` : ""}
      ${e.error ? `<div class="muted">${esc(e.error)}</div>` : ""}
      <div class="ev-links">${e.has_html ? `<a href="/api/evidence/${e.id}/html">HTML</a>` : ""} <a href="/api/evidence/${e.id}/manifest">manifest.json</a></div>
    </div></div>`;
}
$("#caseArchiveAll").onclick = async () => {
  try {
    const s = await api(`/api/cases/${C.open}/evidence`, { method: "POST" });
    if (!s.total) return toast("Arşivlenecek yeni bağlantı yok");
    if (!C.chrome) toast("Chrome / Chromium bulunamadı: yalnızca HTML ve başlıklar arşivlenecek");
    const tick = async () => {
      const j = await loadEvidence();
      if (C.tab === "items") renderCaseItems();
      if (j && j.done < j.total) setTimeout(tick, 2000); else toast("Arşivleme bitti");
    };
    tick();
  } catch (err) { toast("Arşivlenemedi: " + err.message); }
};

/* ---------------- zaman çizelgesi ---------------- */
async function renderTimeline() {
  const box = $("#caseTimeline");
  box.innerHTML = '<div class="empty">Yükleniyor…</div>';
  let ev = [];
  try { ev = (await api(`/api/cases/${C.open}/timeline`)).events; } catch {}
  if (!ev.length) { box.innerHTML = '<div class="empty">Bu vakada tarih içeren bulgu yok.</div>'; return; }
  const years = {};
  ev.forEach(e => (years[e.date.slice(0, 4)] ||= []).push(e));
  box.innerHTML = Object.entries(years).map(([y, list]) => `
    <section class="tl-year"><h3>${esc(y)} <span class="n">${list.length}</span></h3>
      ${list.map(e => `<div class="tl-row k-${e.kind}">
        <span class="tl-date mono">${esc(e.precision === "year" ? e.date.slice(0, 4) : e.date)}</span>
        <span class="tl-dot"></span>
        <div><span class="tl-label">${esc(e.label)}</span>
          <div class="t1">${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.title)}</a>` : esc(e.title)}</div>
          ${e.tool && !["evidence", "watch"].includes(e.tool) ? `<span class="muted">${esc(toolTitle(e.tool))}</span>` : ""}</div>
      </div>`).join("")}</section>`).join("");
}

/* ---------------- izleme ---------------- */
async function renderWatch() {
  let d;
  try { d = await api(`/api/cases/${C.open}/watch`); } catch { return; }
  const w = d.watch;
  $("#watchEnabled").checked = !!w.enabled;
  $("#watchInterval").value = String(Math.round(w.interval_h || 24));
  const fmt = t => t ? new Date(t * 1000).toLocaleString(LANG === "en" ? "en-GB" : "tr-TR") : "–";
  $("#watchStatus").textContent = w.running ? "Taranıyor…" : `Son tarama: ${fmt(w.last_run)}${w.enabled ? ` · sonraki: ${fmt(w.next_run)}` : ""}${w.last_error ? ` · hata: ${w.last_error}` : ""}`;
  $("#watchQueries").textContent = d.queries.length ? `İzlenen değerler: ${d.queries.join(", ")}` : "Vakada izlenecek arama değeri yok; önce bulgu kaydedin.";
  $("#watchChanges").innerHTML = d.changes.length ? `<div class="rlist">${d.changes.map(c => `
    <div class="ritem ch-row ${c.seen ? "" : "unseen"}"><div class="thumb"><i class="dot ${/kayboldu/.test(c.kind) ? "error" : /Yeni/.test(c.kind) ? "found" : "maybe"}"></i></div>
      <div><div class="t1">${esc(c.kind)} · ${esc(c.title)}</div>
        ${c.url ? `<div class="t2"><a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.url)}</a></div>` : ""}
        ${c.detail ? `<div class="t3">${esc(c.detail)}</div>` : ""}</div>
      <div class="ractions"><span class="tag2">${esc(fmt(c.ts))}</span></div></div>`).join("")}</div>`
    : '<div class="empty">Henüz değişiklik kaydı yok. İlk tarama mevcut durumu kaydeder; sonraki taramalar farkları burada gösterir.</div>';
  if (w.running) setTimeout(() => C.tab === "watch" && renderWatch(), 4000);
  if (d.changes.some(c => !c.seen)) api(`/api/cases/${C.open}/changes/seen`, { method: "POST" }).then(refreshWatchBadge);
}
async function saveWatch() {
  await api(`/api/cases/${C.open}/watch`, { method: "POST", body: { enabled: $("#watchEnabled").checked, interval_h: +$("#watchInterval").value } });
  toast($("#watchEnabled").checked ? "İzleme açıldı" : "İzleme kapatıldı");
  renderWatch();
}
$("#watchEnabled").onchange = saveWatch;
$("#watchInterval").onchange = () => $("#watchEnabled").checked && saveWatch();
$("#watchRunNow").onclick = async () => {
  await api(`/api/cases/${C.open}/watch/run?lang=${LANG}`, { method: "POST" });
  toast("Tarama başladı; birkaç dakika sürebilir");
  renderWatch();
};
async function refreshWatchBadge() {
  try {
    const u = await api("/api/watch/unseen");
    C.watchN = Object.values(u).reduce((a, b) => a + b, 0);
    paintWatchBadge();
  } catch {}
}
function paintWatchBadge() {
  const item = document.querySelector('.nav-item[data-tool="cases"]');
  item?.querySelector(".watch-n")?.remove();
  if (C.watchN && item) item.insertAdjacentHTML("beforeend", `<span class="watch-n" title="İzlemede yeni değişiklik">${C.watchN}</span>`);
}
setInterval(refreshWatchBadge, 60000);
setTimeout(refreshWatchBadge, 1500);
