/* Akıllı arama: tek giriş → türü algıla → o veriyi kabul eden tüm araçları birlikte çalıştır → birleşik rapor.
   Arka uçtaki mevcut araçlar (/api/tool/<id>, /api/search) olduğu gibi kullanılır. */

const U_TYPES = { username: "Kullanıcı adı", email: "E-posta", phone: "Telefon", name: "Ad soyad", domain: "Alan adı",
                  ip: "IP adresi", url: "Bağlantı", image: "Görsel" };

/* [araç, alanlar ($ = girilen değer), varsayılan: true | false | koşul] — ağır / yavaş araçlar varsayılan kapalı */
const U_MAP = {
  username: [["sherlock", null, true], ["maigret", { username: "$", top: 500, timeout: 10 }, true], ["whatsmyname", { username: "$" }, true],
             ["user-scanner", { target: "$" }, true], ["blackbird", { target: "$" }, true], ["socialscan", { query: "$" }, true],
             ["github", { username: "$" }, true], ["social-activity", { username: "$" }, true], ["telegram", { username: "$" }, true],
             ["nexfil", { username: "$" }, false], ["social-analyzer", { username: "$" }, false], ["instaloader", { username: "$" }, false],
             ["dorks", { value: "$", kind: "username" }, false]],
  email: [["holehe", { email: "$" }, true], ["email-accounts", { email: "$" }, true], ["email-verify", { email: "$" }, true],
          ["user-scanner", { target: "$" }, true], ["blackbird", { target: "$" }, true], ["socialscan", { query: "$" }, true],
          ["hibp", { email: "$" }, "key:hibp_api_key"], ["ghunt", { email: "$" }, "gmail"], ["h8mail", { email: "$" }, false],
          ["dorks", { value: "$", kind: "email" }, false]],
  phone: [["phonenumbers", { number: "$" }, true], ["ignorant", { number: "$" }, true], ["phoneinfoga", { number: "$" }, true],
          ["phone-search", { number: "$" }, true], ["dorks", { value: "$", kind: "phone" }, false]],
  name: [["namesearch", { name: "$" }, true], ["variants", { first: "$" }, true], ["dorks", { value: "$", kind: "name" }, false]],
  domain: [["whois", { domain: "$" }, true], ["crtsh", { domain: "$" }, true], ["site-intel", { url: "$" }, true], ["ipgeo", { target: "$" }, true],
           ["shodan", { target: "$" }, true], ["wayback", { url: "$", mode: "domain", limit: 300 }, true], ["theharvester", { domain: "$" }, false],
           ["subfinder", { domain: "$" }, false], ["dnstwist", { domain: "$" }, false], ["doc-meta", { domain: "$" }, false],
           ["recon-ng", { target: "$", kind: "domain" }, false], ["spiderfoot", { target: "$", minutes: 5 }, false],
           ["dorks", { value: "$", kind: "domain" }, false]],
  ip: [["ipgeo", { target: "$" }, true], ["shodan", { target: "$" }, true]],
  url: [["wayback", { url: "$", mode: "page" }, true], ["site-intel", { url: "$" }, true], ["video", { url: "$", frames: "off" }, "video"],
        ["geofusion", { url: "$" }, "imageurl"], ["exiftool", { url: "$" }, "imageurl"], ["reverse-image", { url: "$" }, "imageurl"]],
  image: [["geofusion", {}, true], ["exiftool", {}, true], ["ela", {}, false]],
};
const IMG_RX = /\.(jpe?g|png|webp|gif|heic|tiff?|bmp)(\?|$)/i;
const VIDEO_RX = /youtu\.?be|tiktok\.com|vimeo\.com|instagram\.com\/(reel|p)\/|(x|twitter)\.com\/.+\/status|dailymotion|twitch\.tv/i;
const SEARCH_HOSTS = /(^|\.)(google|bing|duckduckgo|yandex|baidu|sogou)\.[a-z.]+$|web\.archive\.org|wa\.me|lens\.google|tineye\.com|suncalc|overpass|mapillary/i;

const U = { type: null, value: "", file: null, tasks: [], running: false, started: 0, timer: null, tab: "merged",
            selected: new Set(), localPart: false, profileHandle: false, extraType: null };

const U_TLDS = new Set("com net org info biz io dev app co edu gov mil int xyz site online tech store shop blog me tv cc ai cloud page live news media agency digital link club pro name mobi asia eu".split(" "));
function detectType(v) {
  v = v.trim();
  if (!v) return null;
  if (/^[\w.+-]+@[\w-]+(\.[\w-]+)+$/.test(v)) return "email";
  if (/^https?:\/\//i.test(v)) return "url";
  if (/^(\d{1,3}\.){3}\d{1,3}$/.test(v)) return "ip";
  if (/^\+?[\d\s()-]{10,18}$/.test(v) && v.replace(/\D/g, "").length >= 10) return "phone";
  if (/^[\p{L}][\p{L}'’.-]*(\s+[\p{L}][\p{L}'’.-]*){1,3}$/u.test(v)) return "name";
  const host = v.replace(/^www\./i, "").toLowerCase();
  if (/^([a-z0-9-]+\.)+[a-z]{2,}$/.test(host)) {
    const tld = host.split(".").pop();
    if (tld.length === 2 || U_TLDS.has(tld)) return "domain";
  }
  return "username";
}

/* E-postanın @ öncesi ya da profil bağlantısındaki kullanıcı adı: ek girdi olarak kullanıcı adı araçlarına da gider */
function secondaryValues() {
  const out = [];
  if (U.type === "email" && U.localPart) out.push(["username", U.value.split("@")[0]]);
  if (U.type === "url" && U.profileHandle) {
    const acc = typeof entitiesOf === "function" ? entitiesOf({ title: "", url: U.value, username: "" }, "sherlock").find(e => e.type === "username") : null;
    if (acc) out.push(["username", acc.value]);
  }
  return out;
}
function profileHandleOf(url) {
  try {
    const u = new URL(url);
    const seg = u.pathname.split("/").filter(Boolean);
    if (/(instagram|x|twitter|tiktok|github|gitlab|facebook|threads|youtube|reddit|medium|t)\.(com|me)$/i.test(u.hostname.replace(/^www\./, "")) && seg.length >= 1) {
      const h = seg[0] === "user" || seg[0] === "u" ? seg[1] : seg[0];
      return (h || "").replace(/^@/, "");
    }
  } catch {}
  return "";
}

function evalDefault(d, val) {
  if (d === true || d === false) return d;
  if (d.startsWith("key:")) return !!T.keys?.[d.slice(4)];
  if (d === "gmail") return /@gmail\.com$/i.test(val) && !!T.keys?.ghunt_login;
  if (d === "video") return VIDEO_RX.test(val);
  if (d === "imageurl") return IMG_RX.test(val);
  return false;
}
const toolTitleU = id => id === "sherlock" ? "Sherlock" : (T.registry.find(t => t.id === id)?.title || id);

/* Çalışacak araç listesi (birincil tür + ek girdiler) */
function plannedTools() {
  const list = [];
  const add = (type, val, isExtra) => {
    for (const [id, fields, def] of U_MAP[type] || []) {
      if (id !== "sherlock" && !T.registry.some(t => t.id === id)) continue;
      const key = `${id}|${val}`;
      if (list.some(x => x.key === key)) continue;
      list.push({ key, id, fields, val, type, extra: isExtra, def: evalDefault(def, val) && !(isExtra && !["sherlock", "maigret", "whatsmyname", "github", "socialscan"].includes(id)) });
    }
  };
  if (U.file) add("image", U.file.name, false);
  else if (U.type) add(U.type, U.value, false);
  for (const [t, v] of secondaryValues()) add(t, v, true);
  return list;
}

function renderTypeBar() {
  $("#uTypes").innerHTML = (U.file ? ["image"] : Object.keys(U_TYPES).filter(t => t !== "image")).map(t =>
    `<button type="button" class="chip ${U.type === t || (U.file && t === "image") ? "active" : ""}" data-utype="${t}">${U_TYPES[t]}</button>`).join("");
  const ex = [];
  if (U.type === "email" && !U.file) ex.push(`<label class="check small"><input type="checkbox" id="uLocal" ${U.localPart ? "checked" : ""}> “${esc(U.value.split("@")[0])}” kısmını kullanıcı adı olarak da ara (Sherlock, Maigret, WhatsMyName, GitHub…)</label>`);
  if (U.type === "url" && profileHandleOf(U.value)) ex.push(`<label class="check small"><input type="checkbox" id="uHandle" ${U.profileHandle ? "checked" : ""}> Bağlantıdaki “${esc(profileHandleOf(U.value))}” kullanıcı adını başka sitelerde de ara</label>`);
  $("#uExtra").innerHTML = ex.join("");
  $("#uLocal")?.addEventListener("change", e => { U.localPart = e.target.checked; renderToolList(); });
  $("#uHandle")?.addEventListener("change", e => { U.profileHandle = e.target.checked; renderToolList(); });
  renderToolList();
}

let uToolChoice = {};          // kullanıcının araç seçimleri (key → bool)
function renderToolList() {
  const tools = plannedTools();
  $("#uToolList").innerHTML = tools.length ? tools.map(t => {
    const checked = t.key in uToolChoice ? uToolChoice[t.key] : t.def;
    const k = T.toolKeys?.[t.id];
    const needKey = k && k.required && !T.keys?.[k.key];
    return `<label class="u-tool ${needKey ? "needkey" : ""}"><input type="checkbox" data-ukey="${esc(t.key)}" ${checked && !needKey ? "checked" : ""} ${needKey ? "disabled" : ""}>
      ${svg(T.registry.find(r => r.id === t.id)?.icon || "fingerprint")}<span>${esc(toolTitleU(t.id))}${t.extra ? ` <em>· ${esc(t.val)}</em>` : ""}</span>
      ${needKey ? '<small>anahtar gerekli</small>' : ""}</label>`;
  }).join("") : '<div class="muted pad">Önce bir değer yazın.</div>';
  const n = tools.filter(t => (t.key in uToolChoice ? uToolChoice[t.key] : t.def)).length;
  $("#uToolCount").textContent = tools.length ? `(${n} / ${tools.length} seçili)` : "";
}
$("#uToolList").addEventListener("change", e => {
  const k = e.target.dataset.ukey;
  if (k) { uToolChoice[k] = e.target.checked; renderToolList(); }
});

$("#uInput").addEventListener("input", () => {
  U.value = $("#uInput").value.trim();
  if (U.file && U.value) clearFile();
  U.type = detectType(U.value);
  uToolChoice = {};
  renderTypeBar();
});
$("#uTypes").addEventListener("click", e => {
  const b = e.target.closest("[data-utype]");
  if (!b || U.file) return;
  U.type = b.dataset.utype;
  uToolChoice = {};
  renderTypeBar();
});
function clearFile() { U.file = null; $("#uFile").value = ""; $("#uFileName").textContent = ""; }
$("#uFile").addEventListener("change", e => {
  U.file = e.target.files[0] || null;
  $("#uFileName").textContent = U.file ? U.file.name : "";
  if (U.file) { $("#uInput").value = ""; U.value = ""; U.type = "image"; }
  uToolChoice = {};
  renderTypeBar();
});

/* ---------------- çalıştırma ---------------- */
const U_CONCURRENCY = 4;
$("#uForm").onsubmit = e => {
  e.preventDefault();
  if (U.running) return;
  if (!U.value && !U.file) return $("#uInput").focus();
  const chosen = plannedTools().filter(t => (t.key in uToolChoice ? uToolChoice[t.key] : t.def));
  if (!chosen.length) return toast("En az bir araç seçin");
  U.tasks = chosen.map(t => ({ ...t, title: toolTitleU(t.id), status: "queued", results: [], raw: [], logs: [], error: null, job: null, t0: 0, elapsed: 0 }));
  U.selected = new Set();
  U.running = true;
  U.started = Date.now();
  U.query = U.value || U.file?.name;
  $("#uRun").disabled = true; $("#uStop").disabled = false;
  $("#uMeter").classList.add("running", "indeterminate"); $("#uClock").classList.add("running");
  $("#uBarRow").hidden = false; $("#uSelBar").hidden = false;
  U.timer = setInterval(() => ($("#uTime").textContent = fmtClock(Date.now() - U.started)), 250);
  renderUnified();
  pump();
};
$("#uStop").onclick = () => {
  for (const t of U.tasks) {
    if (t.status === "running" && t.job) fetch(`/api/stop/${t.job}`, { method: "POST" });
    if (t.status === "queued") t.status = "skipped";
  }
};
function pump() {
  const active = U.tasks.filter(t => t.status === "running").length;
  for (const t of U.tasks.filter(t => t.status === "queued").slice(0, Math.max(0, U_CONCURRENCY - active))) startTask(t);
  if (!U.tasks.some(t => t.status === "queued" || t.status === "running")) finishUnified();
}

async function startTask(t) {
  t.status = "running"; t.t0 = Date.now();
  renderProgress();
  try {
    let r;
    if (t.id === "sherlock") {
      r = await fetch("/api/search", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ usernames: t.val, sites: [], nsfw: false, timeout: 20, source: "remote" }) });
    } else {
      const fd = new FormData();
      fd.append("_lang", typeof LANG === "string" ? LANG : "tr");
      for (const [k, v] of Object.entries(t.fields)) fd.append(k, v === "$" ? t.val : v);
      if (t.id === "variants") {            // "Emre Tuna Ulaş" → ad: Emre Tuna, soyad: Ulaş
        const parts = t.val.split(/\s+/);
        fd.set("first", parts.slice(0, -1).join(" ")); fd.set("last", parts.at(-1));
      }
      if (t.type === "image" && U.file) fd.append("file", U.file);
      r = await fetch(`/api/tool/${t.id}`, { method: "POST", body: fd });
    }
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
    t.job = d.job;
    await new Promise(res => {
      const es = new EventSource(`/api/stream/${d.job}`);
      let pending = false;
      es.onmessage = ev => {
        const m = JSON.parse(ev.data);
        if (m.type === "result") {
          if (t.id === "sherlock") { t.raw.push(m.data); if (m.data.status === "Claimed") t.results.push(sherlockRow(m.data)); }
          else t.results.push(m.data);
          if (!pending) { pending = true; setTimeout(() => { pending = false; renderUnified(); }, 400); }
        } else if (m.type === "preview" && t.id === "sherlock") {
          const raw = t.raw[m.data.i]; if (raw) raw.verified = m.data.ok;
          const row = t.results.find(x => x.url === m.data.url);
          if (row) {
            if (m.data.ok === false) t.results.splice(t.results.indexOf(row), 1);   // açılmayan profil: sonuçlardan çıkar
            else { row.verified = true; if (m.data.image) row.image = m.data.image; if (m.data.title) row.detail ||= m.data.title; }
            if (!pending) { pending = true; setTimeout(() => { pending = false; renderUnified(); }, 400); }
          }
        } else if (m.type === "log") {
          t.logs.push(m.data);
        } else if (m.type === "error") {
          t.error = m.data;
        } else if (m.type === "done") {
          es.close(); res();
        }
      };
      es.onerror = () => { es.close(); res(); };
    });
    t.status = t.error ? "error" : "done";
  } catch (err) {
    t.status = "error"; t.error = err.message;
  }
  t.elapsed = (Date.now() - t.t0) / 1000;
  renderUnified();
  pump();
}
function sherlockRow(r) {
  return { i: r.i, title: r.site, url: r.url, status: "found", detail: "", image: "", tags: "Sherlock", meta: { "Kullanıcı adı": r.username } };
}
function finishUnified() {
  if (!U.running) return;
  U.running = false;
  clearInterval(U.timer);
  $("#uRun").disabled = false; $("#uStop").disabled = true;
  $("#uMeter").classList.remove("running", "indeterminate"); $("#uClock").classList.remove("running");
  $("#uTime").textContent = fmtDone((Date.now() - U.started) / 1000);
  const m = merged();
  $("#uStatus").textContent = `Tamamlandı · ${U.tasks.length} araç · ${m.items.length} farklı bulgu · ${m.items.filter(x => x.tools.length > 1).length} tanesi birden çok araçta`;
  renderUnified();
}

/* ---------------- birleştirme ---------------- */
function normUrl(u) {
  try {
    const x = new URL(u);
    return (x.hostname.replace(/^(www|m|mobile)\./, "") + x.pathname.replace(/\/+$/, "")).toLowerCase();
  } catch { return ""; }
}
function baseDomain(host) {
  const p = host.toLowerCase().replace(/^www\./, "").split(".");
  const n = p.length > 2 && /^(co|com|org|net|gov|edu|ac)$/.test(p.at(-2)) ? 3 : 2;
  return p.slice(-n).join(".");
}
function merged() {
  const map = new Map(), info = [];
  for (const t of U.tasks) {
    for (const r of t.results) {
      if (["histogram", "figure", "person", "personas", "geofusion", "photo", "thumb", "clean"].includes(r.kind)) continue;
      if (r.kind === "warn") { info.push({ t, r }); continue; }
      if (r.status === "notfound" || r.status === "error") continue;      // ayrıntılı görünümde duruyor
      let host = "";
      try { host = new URL(r.url).hostname; } catch {}
      const isProfile = r.url && (r.status === "found" || r.status === "maybe") && !SEARCH_HOSTS.test(host);
      if (!isProfile) { info.push({ t, r }); continue; }
      // E-posta kontrollerinde her araç aynı site için farklı adres verir (ana sayfa, giriş sayfası…): siteye göre birleştir
      const k = t.type === "email" ? "e:" + baseDomain(host) : normUrl(r.url);
      const cur = map.get(k);
      if (cur) {
        if (!cur.tools.includes(t.title)) cur.tools.push(t.title);
        cur.refs.push({ t, r });
        if (!cur.image && r.image) cur.image = r.image;
        if (!cur.detail && r.detail) cur.detail = r.detail;
        if (r.status === "found") cur.status = "found";
      } else {
        map.set(k, { key: k, title: r.title, url: r.url, image: r.image || "", detail: r.detail || "", status: r.status,
                     tools: [t.title], refs: [{ t, r }], tags: r.tags || "", meta: r.meta || {} });
      }
    }
  }
  const items = [...map.values()].sort((a, b) => b.tools.length - a.tools.length || (b.status === "found") - (a.status === "found") || !!b.image - !!a.image);
  return { items, info };
}

function renderProgress() {
  const done = U.tasks.filter(t => ["done", "error", "skipped"].includes(t.status)).length;
  $("#uDone").textContent = done; $("#uTotal").textContent = U.tasks.length;
  $("#uBar").style.width = U.tasks.length ? `${(done / U.tasks.length) * 100}%` : "0";
  if (done) $("#uMeter").classList.remove("indeterminate");
  $("#uProgress").innerHTML = U.tasks.map((t, n) => {
    const cnt = t.results.filter(r => r.status === "found" || r.status === "maybe").length;
    const errs = t.results.filter(r => r.status === "error").length;
    const st = { queued: "sırada", running: "çalışıyor", done: `${cnt} bulgu${errs ? ` · ${errs} yanıtsız` : ""} · ${t.elapsed.toFixed(0)} sn`, error: "hata", skipped: "atlandı" }[t.status];
    return `<div class="u-task s-${t.status}" title="${esc(t.error || "")}">
      ${t.status === "running" ? '<i class="spin"></i>' : t.status === "done" ? "✓" : t.status === "error" ? "!" : "·"}
      <b>${esc(t.title)}</b>${t.extra ? `<em>${esc(t.val)}</em>` : ""}<span>${st}</span>
      ${t.status === "done" || t.status === "error" ? `<button type="button" class="text" data-uopen="${n}">aç</button>` : ""}</div>`;
  }).join("");
}

function renderUnified() {
  renderProgress();
  const { items, info } = merged();
  $("#uFound").textContent = items.length;
  $("#uMulti").textContent = items.filter(x => x.tools.length > 1).length;
  $$("#uTabs .chip").forEach(c => {
    const n = c.dataset.utab === "merged" ? items.length : info.length;
    c.innerHTML = c.innerHTML.replace(/<span class="n">.*<\/span>/, "") + `<span class="n">${n}</span>`;
    c.classList.toggle("active", c.dataset.utab === U.tab);
  });
  const q = $("#uFilter").value.trim().toLowerCase();
  if (U.tab === "merged") {
    const list = items.filter(x => !q || `${x.title} ${x.url} ${x.detail} ${x.tools.join(" ")}`.toLowerCase().includes(q));
    U.view = list;
    $("#uResults").innerHTML = list.length ? `<div class="rlist">${list.map((x, n) => `
      <div class="ritem u-item ${U.selected.has(x.key) ? "sel" : ""}" data-uidx="${n}">
        <label class="u-check"><input type="checkbox" data-usel="${esc(x.key)}" ${U.selected.has(x.key) ? "checked" : ""}></label>
        <div class="thumb">${x.image ? `<img src="${esc(x.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'dot ${x.status}'}))">` : `<i class="dot ${x.status}"></i>`}</div>
        <div>
          <div class="t1">${esc(x.title)}</div>
          <div class="t2"><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(x.url.length > 90 ? x.url.slice(0, 88) + "…" : x.url)}</a></div>
          ${x.detail ? `<div class="t3">${esc(x.detail.slice(0, 220))}</div>` : ""}
          <div class="u-tools-found">${x.tools.map(n => `<span>${esc(n)}</span>`).join("")}${x.tools.length > 1 ? `<b>${x.tools.length} araç buldu</b>` : ""}</div>
        </div>
        <div class="ractions">${x.status === "maybe" ? '<span class="tag2">olası</span>' : ""}<button type="button" class="rbtn" data-uchain="${n}" title="Bununla devam et">→</button></div>
      </div>`).join("")}</div>`
      : `<div class="empty">${U.running ? "Araçlar çalışıyor…" : U.tasks.length ? "Hesap / profil bulunamadı; “Bilgiler ve bağlantılar” sekmesine bakın." : ""}</div>`;
  } else {
    const groups = {};
    info.filter(({ r }) => !q || `${r.title} ${r.detail} ${r.url}`.toLowerCase().includes(q)).forEach(x => (groups[x.t.title] ||= []).push(x));
    $("#uResults").innerHTML = Object.entries(groups).map(([tool, list]) => `
      <details class="ns-group" open><summary>${esc(tool)} <span class="n">${list.length}</span></summary>
        <div class="rlist">${list.slice(0, 80).map(({ r }) => `
          <div class="ritem"><div class="thumb"><i class="dot ${r.status}"></i></div>
            <div><div class="t1">${esc(r.title)}</div>
              ${r.url ? `<div class="t2"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url.slice(0, 90))}</a></div>` : ""}
              ${r.detail ? `<div class="t3">${esc(String(r.detail).slice(0, 260))}</div>` : ""}</div>
            <div class="ractions"><span class="tag2">${esc(r.tags || "")}</span></div></div>`).join("")}</div></details>`).join("")
      || '<div class="empty">Bilgi satırı yok.</div>';
  }
  $("#uSelCount").textContent = `${U.selected.size} seçili`;
  $("#uSelAll").checked = U.view?.length > 0 && U.view.every(x => U.selected.has(x.key));
}
$$("#uTabs .chip").forEach(c => c.onclick = () => { U.tab = c.dataset.utab; renderUnified(); });
$("#uFilter").oninput = () => renderUnified();

$("#uResults").addEventListener("change", e => {
  const k = e.target.dataset.usel;
  if (!k) return;
  e.target.checked ? U.selected.add(k) : U.selected.delete(k);
  e.target.closest(".u-item")?.classList.toggle("sel", e.target.checked);
  updateSelBar();
});
function updateSelBar() {
  $("#uSelCount").textContent = `${U.selected.size} seçili`;
  $("#uSelAll").checked = U.view?.length > 0 && U.view.every(x => U.selected.has(x.key));
}
$("#uSelAll").onchange = e => {
  for (const x of U.view || []) e.target.checked ? U.selected.add(x.key) : U.selected.delete(x.key);
  renderUnified();
};
$("#uResults").addEventListener("click", e => {
  const c = e.target.closest("[data-uchain]");
  if (c) {
    const x = U.view[+c.dataset.uchain];
    return openChainMenu(c, { title: x.title, url: x.url, detail: x.detail, image: x.image, meta: x.meta, username: x.meta?.["Kullanıcı adı"] || "" }, "sherlock");
  }
});
$("#uProgress").addEventListener("click", e => {
  const b = e.target.closest("[data-uopen]");
  if (b) openTaskDetail(U.tasks[+b.dataset.uopen]);
});
const selectedItems = () => merged().items.filter(x => U.selected.has(x.key));
$("#uSelCopy").onclick = async () => {
  const urls = selectedItems().map(x => x.url);
  if (!urls.length) return toast("Önce sonuç seçin");
  try { await navigator.clipboard.writeText(urls.join("\n")); toast(`${urls.length} bağlantı kopyalandı`); } catch { toast("Kopyalanamadı"); }
};
$("#uSelSave").onclick = async () => {
  const items = selectedItems();
  if (!items.length) return toast("Önce kaydedilecek sonuçları seçin");
  try {
    const cid = await ensureCase(U.query);
    const { added } = await api(`/api/cases/${cid}/items`, { method: "POST", body: { tool: "unified", query: U.query,
      items: items.map(x => ({ title: x.title, url: x.url, detail: x.detail, image: x.image, status: x.status,
                              tags: x.tools.join(", "), meta: { ...x.meta, "Bulan araçlar": x.tools.join(", ") } })) } });
    toast(added ? `${added} bulgu “${C.currentName}” vakasına eklendi` : "Bunlar vakada zaten var");
  } catch (err) { toast("Kaydedilemedi: " + err.message); }
};

/* Bir aracın tam ekranını (harita, kişi kartları, EXIF…) bu sonuçlarla aç */
function openTaskDetail(t) {
  if (t.id === "sherlock") {
    selectTool("sherlock");
    state.job = t.job; state.results = t.raw.map((r, i) => ({ ...r, i })); state.total = t.raw.length;
    render(); setExports(true); $("#sSaveCase").disabled = false;
    $("#statusLine").textContent = `Akıllı aramadan açıldı · ${t.results.length} hesap`;
    return;
  }
  selectTool(t.id);
  T.results = t.results.slice(); T.logs = t.logs.slice(); T.job = t.job; T.error = t.error;
  const main = $("#tMain");
  if (!main.hidden && t.val) main.value = t.val;
  setToolExports(T.results.length > 0);
  $("#tSaveCase").disabled = !T.results.some(r => r.status === "found" || r.status === "maybe");
  $("#tStatus").textContent = `Akıllı aramadan açıldı · ${T.results.length} sonuç · ${t.elapsed.toFixed(1)} sn`;
  renderTool();
}

renderTypeBar();
$(".start-grid")?.addEventListener("click", e => { const el = e.target.closest("[data-tool]"); if (el) selectTool(el.dataset.tool); });

/* Dil düğmeleri / language switch */
document.querySelectorAll(".lang-switch [data-lang]").forEach(b => {
  b.classList.toggle("active", b.dataset.lang === LANG);
  b.onclick = () => { if (b.dataset.lang !== LANG) setLang(b.dataset.lang); };
});
