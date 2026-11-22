/* Süre biçimleri: çalışırken 0:07, bitince "34,6 sn" / "2 dk 14 sn" */
function fmtClock(ms) { const t = Math.floor(ms / 1000); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; }
function fmtDone(sec) {
  sec = +sec || 0;
  return sec < 60 ? `${sec.toFixed(1).replace(".", ",")} sn` : `${Math.floor(sec / 60)} dk ${Math.round(sec % 60)} sn`;
}
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = {
  sites: [], selected: new Set(), results: [], job: null, es: null,
  total: 0, started: 0, timer: null,
  statuses: new Set(["Claimed"]), view: "table", previews: {},
};

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- site list ---------------- */
async function loadSites() {
  $("#siteList").innerHTML = '<div class="muted pad">Yükleniyor…</div>';
  const p = new URLSearchParams({ source: $("#source").value, json: $("#customJson").value, ignore_exclusions: $("#ignoreExcl").checked ? 1 : 0 });
  try {
    const r = await fetch("/api/sites?" + p);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error);
    state.sites = d;
    renderSites();
  } catch (e) {
    $("#siteList").innerHTML = `<div class="pad" style="color:var(--danger)">${esc(e.message)}</div>`;
  }
}
function visibleSites() {
  const q = $("#siteFilter").value.trim().toLowerCase();
  const nsfw = $("#nsfw").checked;
  return state.sites.filter(s => (nsfw || !s.nsfw || state.selected.has(s.name)) && (!q || s.name.toLowerCase().includes(q)));
}
function renderSites() {
  const list = visibleSites();
  const base = state.sites.filter(s => $("#nsfw").checked || !s.nsfw).length;
  $("#siteCount").textContent = base;
  $("#siteList").innerHTML = list.length ? list.map(s => `
    <label class="site-item"><input type="checkbox" value="${esc(s.name)}" ${state.selected.has(s.name) ? "checked" : ""}>
      ${esc(s.name)} ${s.nsfw ? '<span class="tag">NSFW</span>' : ""}</label>`).join("")
    : '<div class="muted pad">Eşleşen site yok.</div>';
  $("#selCount").textContent = state.selected.size ? `${state.selected.size} seçili` : "hepsi taranır";
}
$("#siteList").addEventListener("change", e => {
  if (e.target.type !== "checkbox") return;
  e.target.checked ? state.selected.add(e.target.value) : state.selected.delete(e.target.value);
  $("#selCount").textContent = state.selected.size ? `${state.selected.size} seçili` : "hepsi taranır";
});
$("#siteFilter").oninput = renderSites;
$("#nsfw").onchange = renderSites;
$("#selAll").onclick = () => { visibleSites().forEach(s => state.selected.add(s.name)); renderSites(); };
$("#selNone").onclick = () => { state.selected.clear(); renderSites(); };
$("#source").onchange = () => { $("#customJsonWrap").hidden = $("#source").value !== "custom"; if ($("#source").value !== "custom") loadSites(); };
$("#customJson").onchange = loadSites;
$("#ignoreExcl").onchange = loadSites;

/* ---------------- search ---------------- */
$("#searchForm").onsubmit = async e => {
  e.preventDefault();
  if (state.es) return;
  if (!collectNames().length) { $("#usernames").focus(); return toast("En az bir kullanıcı adı ekleyin"); }
  const body = {
    usernames: collectNames().join(" "),
    sites: [...state.selected],
    nsfw: $("#nsfw").checked,
    ignore_exclusions: $("#ignoreExcl").checked,
    timeout: +$("#timeout").value,
    source: $("#source").value,
    json: $("#customJson").value,
    proxy: $("#proxy").value,
  };
  $("#startBtn").disabled = true;
  $("#statusLine").textContent = "Başlatılıyor…";
  const r = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const d = await r.json();
  if (!r.ok) { $("#startBtn").disabled = false; $("#statusLine").textContent = d.error; toast(d.error); return; }

  closeDrawer();
  state.job = d.job; state.results = []; state.previews = {}; state.total = d.total; state.started = Date.now();
  $("#stTotal").textContent = d.total;
  $("#userFilter").innerHTML = '<option value="">Tüm adlar</option>' + d.usernames.map(u => `<option>${esc(u)}</option>`).join("");
  $("#userFilter").hidden = d.usernames.length < 2;
  $("#stopBtn").disabled = false;
  $("#bar").classList.add("running"); $("#sMeter").classList.add("running"); $("#sClock").classList.add("running");
  $("#stTime").textContent = "0:00";
  setExports(false);
  render();
  state.timer = setInterval(() => ($("#stTime").textContent = fmtClock(Date.now() - state.started)), 250);
  $("#statusLine").textContent = `${d.usernames.join(", ")} · ${d.site_count} site`;

  const es = new EventSource(`/api/stream/${d.job}`);
  state.es = es;
  let pending = false;
  es.onmessage = ev => {
    const m = JSON.parse(ev.data);
    const later = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; render(); }); } };
    if (m.type === "result") {
      state.results[m.data.i] = m.data;
      later();
      $("#statusLine").textContent = `[${m.data.username}] ${m.data.site} → ${m.data.status}`;
    } else if (m.type === "preview") {
      const r = state.results[m.data.i];
      if (r) r.verified = m.data.ok;
      state.previews[m.data.url] = m.data;
      if (m.data.ok && m.data.image) new Image().src = m.data.image;   // görseli önceden yükle
      if (preview.url === m.data.url) renderPreview(r, m.data);
      later();
    } else if (m.type === "verifying") {
      $("#statusLine").textContent = `Profiller açılıp doğrulanıyor (${m.data} kaldı)…`;
    } else if (m.type === "username") {
      $("#statusLine").textContent = `Kullanıcı: ${m.data}`;
    } else if (m.type === "error") {
      toast("Hata: " + m.data);
    } else if (m.type === "done") {
      finish(m.data);
    }
  };
  es.onerror = () => { if (state.es) finish({ cancelled: true }); };
};

function finish(info) {
  state.es?.close(); state.es = null;
  clearInterval(state.timer);
  $("#startBtn").disabled = false; $("#stopBtn").disabled = true;
  $("#bar").classList.remove("running"); $("#sMeter").classList.remove("running"); $("#sClock").classList.remove("running");
  $("#stTime").textContent = fmtDone(info.elapsed ?? (Date.now() - state.started) / 1000);
  const found = state.results.filter(r => eff(r) === "Claimed").length;
  $("#statusLine").textContent = `${info.cancelled ? "Durduruldu" : "Tamamlandı"} · ${found} hesap bulundu · ${state.results.length} kontrol${info.elapsed ? ` · ${info.elapsed} sn` : ""}`;
  setExports(state.results.length > 0);
  render();
}
$("#stopBtn").onclick = () => state.job && fetch(`/api/stop/${state.job}`, { method: "POST" });

/* ---------------- filters & render ---------------- */
$$("#statusChips .chip").forEach(c => c.onclick = () => {
  const s = c.dataset.status;
  state.statuses.has(s) ? state.statuses.delete(s) : state.statuses.add(s);
  c.classList.toggle("active");
  render();
});
$("#resFilter").oninput = render;
$("#userFilter").onchange = render;
$("#sortBy").onchange = render;
$$(".view-toggle button").forEach(b => b.onclick = () => {
  $$(".view-toggle button").forEach(x => x.classList.toggle("active", x === b));
  state.view = b.dataset.view; render();
});

// Bulunan ama açılınca olumsuz dönen profiller "Unverified" sayılır ve Bulundu'da gösterilmez.
const eff = r => (r.status === "Claimed" && r.verified === false ? "Unverified" : r.status);

function filtered() {
  const q = $("#resFilter").value.trim().toLowerCase();
  const u = $("#userFilter").value;
  let rows = state.results.filter(r => r && state.statuses.has(eff(r)) && (!u || r.username === u) &&
    (!q || r.site.toLowerCase().includes(q) || r.url.toLowerCase().includes(q)));
  const sort = $("#sortBy").value;
  const order = { Claimed: 0, Unverified: 1, Unknown: 2, WAF: 3, Illegal: 4, Available: 5 };
  if (sort === "site") rows.sort((a, b) => a.site.localeCompare(b.site));
  else if (sort === "time") rows.sort((a, b) => (a.time_ms ?? 1e9) - (b.time_ms ?? 1e9));
  else if (sort === "status") rows.sort((a, b) => order[eff(a)] - order[eff(b)] || a.site.localeCompare(b.site));
  return rows;
}

const LABEL = { Claimed: "", Unverified: "açılmadı", Available: "yok", Unknown: "hata", WAF: "WAF", Illegal: "geçersiz" };
const label = r => (r.status === "Claimed" && r.verified === undefined ? "kontrol…" : LABEL[eff(r)]);
function favicon(home) {
  try { return `<img class="fav" loading="lazy" src="${new URL(home).origin}/favicon.ico" onerror="this.style.visibility='hidden'" alt="">`; }
  catch { return ""; }
}

function render() {
  const R = state.results.filter(Boolean);
  const count = s => R.filter(r => eff(r) === s).length;
  $("#stFound").textContent = count("Claimed");
  $("#stAvail").textContent = count("Available");
  $("#stErr").textContent = count("Unknown") + count("WAF") + count("Illegal");
  $("#stDone").textContent = R.length;
  $("#bar").style.width = state.total ? `${(R.length / state.total) * 100}%` : "0";
  $$("#statusChips .chip").forEach(c => {
    const n = count(c.dataset.status);
    c.innerHTML = c.innerHTML.replace(/<span class="n">.*<\/span>/, "") + `<span class="n">${n}</span>`;
  });

  const rows = filtered();
  const box = $("#results");
  const multi = state.results.some(r => r.username !== state.results[0]?.username);
  if (!rows.length) {
    box.className = "results";
    box.innerHTML = `<div class="empty">${R.length ? "Bu filtrede sonuç yok." : ""}</div>`;
    return;
  }
  if (state.view === "grid") {
    box.className = "results grid-view";
    box.innerHTML = rows.map(r => `
      <a class="tile" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">
        <div class="head"><span>${favicon(r.home)}${esc(r.site)}</span><span class="pill ${r.status}">${LABEL[r.status]}</span></div>
        <div class="u">${esc(r.url)}</div>
        <div class="muted" style="font-size:11px">${multi ? `<span class="user-tag">@${esc(r.username)}</span> · ` : ""}${r.time_ms ?? "–"} ms</div>
      </a>`).join("");
  } else {
    box.className = "results";
    box.innerHTML = `<table><thead><tr><th>Site</th>${multi ? "<th>Kullanıcı</th>" : ""}<th>Profil URL</th><th>Durum</th><th class="hide-sm">Süre</th></tr></thead><tbody>
      ${rows.map(r => `<tr data-i="${r.i}" class="${r.url === preview.url ? "sel" : ""}">
        <td>${favicon(r.home)}${esc(r.site)}</td>
        ${multi ? `<td class="user-tag">${esc(r.username)}</td>` : ""}
        <td class="url"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url)}</a></td>
        <td><span class="pill ${eff(r)}">${label(r)}</span>${r.context && r.status !== "Claimed" && r.status !== "Available" ? `<span class="ctx">${esc(r.context)}</span>` : ""}${eff(r) === "Unverified" ? `<span class="ctx">${esc(state.previews[r.url]?.error || "")}</span>` : ""}</td>
        <td class="t hide-sm">${r.time_ms ?? "–"} ms</td></tr>`).join("")}
      </tbody></table>`;
  }
}

/* ---------------- exports ---------------- */
function setExports(on) {
  $$("[data-export]").forEach(b => (b.disabled = !on));
  $("#copyBtn").disabled = $("#openAllBtn").disabled = !on;
}
$$("[data-export]").forEach(b => b.onclick = () => {
  location.href = `/api/export/${state.job}.${b.dataset.export}?found=${$("#exportFound").checked ? 1 : 0}`;
});
const foundUrls = () => filtered().filter(r => eff(r) === "Claimed").map(r => r.url);
$("#copyBtn").onclick = async () => {
  const urls = foundUrls();
  try { await navigator.clipboard.writeText(urls.join("\n")); toast(`${urls.length} link kopyalandı`); }
  catch { toast("Panoya kopyalanamadı"); }
};
$("#openAllBtn").onclick = () => {
  const urls = foundUrls();
  if (!urls.length) return toast("Açılacak link yok");
  if (urls.length > 15 && !confirm(`${urls.length} sekme açılacak. Devam?`)) return;
  urls.forEach(u => window.open(u, "_blank", "noopener"));
};

/* ---------------- username list ---------------- */
const names = [];
function addNames(list) {
  let added = 0;
  for (let n of list) {
    n = n.trim().replace(/^@/, "");
    if (!n || n.startsWith("#") || names.includes(n)) continue;
    names.push(n); added++;
  }
  renderTags();
  return added;
}
function renderTags() {
  $("#tagList").innerHTML = names.map((n, i) =>
    `<span class="tag">${esc(n)}<button type="button" data-rm="${i}" aria-label="${esc(n)} kaldır">×</button></span>`).join("");
  $("#clearTags").hidden = names.length < 2;
  $("#usernames").placeholder = names.length ? "bir ad daha ekle" : "kullanıcı adı";
}
function addFromInput() {
  const v = $("#usernames").value;
  if (!v.trim()) return false;
  addNames(v.split(/[\s,;]+/));
  $("#usernames").value = "";
  $("#usernames").focus();
  return true;
}
// Aranacak adlar: listedekiler + kutuda yazılı kalanlar
function collectNames() {
  const pending = $("#usernames").value.split(/[\s,;]+/).map(s => s.trim().replace(/^@/, "")).filter(Boolean);
  return [...new Set([...names, ...pending])];
}
$("#addBtn").onclick = addFromInput;
$("#usernames").addEventListener("keydown", e => {
  // Enter: kutu doluysa listeye ekler; kutu boşsa aramayı başlatır
  if (e.key === "Enter" && $("#usernames").value.trim() && (names.length || e.shiftKey)) { e.preventDefault(); addFromInput(); }
  if (e.key === "Backspace" && !$("#usernames").value && names.length) { names.pop(); renderTags(); }
});
$("#tagList").onclick = e => {
  const i = e.target.dataset.rm;
  if (i !== undefined) { names.splice(+i, 1); renderTags(); }
};
$("#clearTags").onclick = () => { names.length = 0; renderTags(); };
$("#fileInput").onchange = async e => {
  const f = e.target.files[0];
  if (!f) return;
  const text = await f.text();
  const n = addNames(text.split(/[\r\n,;\t]+/).map(l => l.trim().split(/\s+/)[0] || ""));
  toast(`${f.name}: ${n} ad eklendi`);
  e.target.value = "";
};

/* ---------------- profile preview ---------------- */
const preview = { url: null, ctrl: null };
function openDrawer() { $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#scrim").hidden = false; }
function closeDrawer() {
  $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true;
  preview.url = null; preview.ctrl?.abort(); $$("tbody tr.sel").forEach(t => t.classList.remove("sel"));
}
$("#pvClose").onclick = closeDrawer;
$("#scrim").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape" && preview.url) closeDrawer(); });

$("#results").addEventListener("click", e => {
  if (e.target.closest("a")) return;          // link kendi sekmesinde açılsın
  const tr = e.target.closest("tr[data-i]");
  if (tr) showPreview(state.results[+tr.dataset.i]);
});

async function showPreview(r) {
  preview.url = r.url;
  $$("tbody tr").forEach(t => t.classList.toggle("sel", +t.dataset.i === r.i));
  $("#pvSite").innerHTML = `${favicon(r.home)}${esc(r.site)}`;
  openDrawer();
  preview.ctrl?.abort();
  // Arka planda zaten açıldıysa anında göster.
  const cached = state.previews[r.url];
  if (cached) return renderPreview(r, cached);
  $("#pvBody").innerHTML = `<div class="pv-skel"></div><div class="pv-loading">${esc(r.url)} okunuyor…</div>`;
  // Doğrulaması sürüyorsa sonucu SSE getirecek; ayrıca istek atma.
  if (state.es && r.status === "Claimed" && r.verified === undefined) return;
  preview.ctrl = new AbortController();
  let d;
  try {
    d = await (await fetch("/api/preview?url=" + encodeURIComponent(r.url), { signal: preview.ctrl.signal })).json();
  } catch (err) {
    if (err.name === "AbortError") return;
    d = { error: err.message };
  }
  state.previews[r.url] = d;
  if (preview.url === r.url) renderPreview(r, d);
}

function renderPreview(r, d) {
  if (!r || preview.url !== r.url) return;
  const meta = [
    ["kullanıcı", r.username],
    ["yanıt", d.http_status ? `HTTP ${d.http_status}` : "–"],
    ["süre", r.time_ms != null ? `${r.time_ms} ms` : "–"],
    d.final_url && d.final_url !== r.url ? ["yönlendi", d.final_url] : null,
    d.type ? ["tür", d.type] : null,
  ].filter(Boolean);
  $("#pvBody").innerHTML = `
    ${d.image && d.ok !== false ? `<img class="pv-img" src="${esc(d.image)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
    ${d.error ? `<p class="pv-desc">Sayfa okunamadı: ${esc(d.error)}</p>` : `
      <h3 class="pv-title">${esc(d.title || "Başlık yok")}</h3>
      <p class="pv-desc">${esc(d.description || "Açıklama bulunamadı.")}</p>`}
    <div class="pv-meta">${meta.map(([k, v]) => `<span>${k}</span><span>${esc(v)}</span>`).join("")}</div>
    <a class="pv-open" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">Profili aç ↗</a>`;
}

loadSites();
