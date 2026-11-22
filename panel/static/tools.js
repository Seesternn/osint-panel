/* Sol panel + Sherlock dışındaki araçların ortak ekranı.
   app.js'teki $, $$, esc, toast, favicon, openDrawer, closeDrawer, preview kullanılır. */

const ICONS = {
  idcard: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2.3"/><path d="M5.8 16.2a3.5 3.5 0 0 1 6.4 0M14.5 10h4M14.5 13.5h3"/>',
  crosshair: '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="2"/><path d="M12 2.5v4M12 17.5v4M2.5 12h4M17.5 12h4"/>',
  folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
  radar: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12l6-6"/>',
  git: '<circle cx="6" cy="6" r="2.2"/><circle cx="6" cy="18" r="2.2"/><circle cx="18" cy="8" r="2.2"/><path d="M6 8.2v7.6M18 10.2c0 4-6 3-10.5 6.3"/>',
  activity: '<path d="M3 12h4l2.5-6 5 12 2.5-6H21"/>',
  send: '<path d="M21 3.5L10.5 14M21 3.5l-6.5 17-4-6.5-6.5-4z"/>',
  shuffle: '<path d="M16 3.5h4.5V8M4 20l16.5-16.5M20.5 16v4.5H16M14.5 14.5l6 6M4 4l5 5"/>',
  inbox: '<path d="M3.5 13.5l2.5-8h12l2.5 8v5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5z"/><path d="M3.5 13.5H8l1.5 2.5h5l1.5-2.5h4.5"/>',
  phonesearch: '<rect x="4" y="3" width="10" height="18" rx="2.2"/><path d="M8 17.5h2"/><circle cx="17.5" cy="11.5" r="2.5"/><path d="M19.3 13.3l2 2"/>',
  globe2: '<circle cx="12" cy="10" r="6.5"/><path d="M5.5 10h13M12 3.5c1.8 1.9 2.6 4 2.6 6.5s-.8 4.6-2.6 6.5c-1.8-1.9-2.6-4-2.6-6.5s.8-4.6 2.6-6.5zM8 21h8M12 16.5V21"/>',
  copy: '<rect x="8" y="8" width="12.5" height="12.5" rx="2"/><path d="M16 8V5.5a2 2 0 0 0-2-2H5.5a2 2 0 0 0-2 2V14a2 2 0 0 0 2 2H8"/>',
  layers: '<path d="M12 3.5l9 5-9 5-9-5z"/><path d="M3 13.5l9 5 9-5"/>',
  film: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M7.5 4.5v15M16.5 4.5v15M3.5 9.5h4M3.5 14.5h4M16.5 9.5h4M16.5 14.5h4"/>',
  lock: '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
  network: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5M12 12l-6 5.5M12 12l6 5.5"/>',
  alert: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  code: '<path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5M13.5 5l-3 14"/>',
  eye: '<path d="M2.5 12s3.5-6.5 9.5-6.5 9.5 6.5 9.5 6.5-3.5 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.8"/>',
  search2: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5M8 10.5h5M10.5 8v5"/>',
  file: '<path d="M14 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-10z"/><path d="M14 3.5v5h5M8.5 13h7M8.5 16.5h5"/>',
  spider: '<circle cx="12" cy="12.5" r="3.5"/><path d="M12 9V6M8.6 11l-4.6-3M15.4 11l4.6-3M8.5 13.5h-5M15.5 13.5h5M9 15.5l-4 4M15 15.5l4 4"/>',
  box: '<path d="M12 3l8.5 4.5v9L12 21l-8.5-4.5v-9z"/><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9"/>',
  zap: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  mailcheck: '<path d="M20.5 12V7.5a2 2 0 0 0-2-2h-13a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2H12"/><path d="M4 7l8 6 8-6"/><path d="M15 18l2 2 4-4"/>',
  hash: '<path d="M5 9h14M5 15h14M10 4l-2 16M16 4l-2 16"/>',
  phonecheck: '<rect x="5" y="3" width="10" height="18" rx="2.2"/><path d="M9 17.5h2"/><path d="M16.5 11.5l1.8 1.8 3.2-3.5"/>',
  pin: '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/><path d="M8 7.5h8M8 11h6"/>',
  fingerprint: '<path d="M12 11v3a8 8 0 0 1-1.5 4.7"/><path d="M8.5 9.5a3.5 3.5 0 0 1 7 0V13a12 12 0 0 1-.8 4.3"/><path d="M5.5 12V9.5a6.5 6.5 0 0 1 12.4-2.7"/><path d="M18.5 11v2a15 15 0 0 1-.6 4"/><path d="M8.5 13a10 10 0 0 1-1.6 5.5"/>',
  user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>',
  bird: '<path d="M16 7h.01"/><path d="M3.5 18H11a7 7 0 0 0 7-7V7.5L20.5 6 18 5a3.5 3.5 0 0 0-6.5 1.8L4 18"/><path d="M11 18l-1 3M14 17l1 4"/>',
  gauge: '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/>',
  check: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.3l2.4 2.4 4.6-5"/>',
  mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>',
  shield: '<path d="M12 3.5l7 3v5.5c0 4.4-3 7.6-7 8.5-4-.9-7-4.1-7-8.5V6.5z"/><path d="M12 9v4M12 16h.01"/>',
  google: '<path d="M20 12.2c0 4.6-3.3 7.8-8 7.8a8 8 0 1 1 5.4-13.9"/><path d="M20 12h-7.5"/>',
  phone: '<rect x="7" y="3" width="10" height="18" rx="2.2"/><path d="M11 17.5h2"/>',
  camera: '<rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="3.8"/><path d="M17 7h.01"/>',
  at: '<circle cx="12" cy="12" r="3.5"/><path d="M15.5 12v1.5a2.5 2.5 0 0 0 5 0V12a8.5 8.5 0 1 0-3.5 6.9"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M20.5 16l-5-5-8.5 8.5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6"/><path d="M15 15l5.5 5.5"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.5 2.6 3.5 5.3 3.5 8.5s-1 5.9-3.5 8.5c-2.5-2.6-3.5-5.3-3.5-8.5s1-5.9 3.5-8.5z"/>',
  server: '<rect x="4" y="4" width="16" height="7" rx="1.5"/><rect x="4" y="13" width="16" height="7" rx="1.5"/><path d="M8 7.5h.01M8 16.5h.01"/>',
};
const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.search}</svg>`;

const T = { registry: [], current: null, job: null, es: null, results: [], logs: [], tab: "found", timer: null, started: 0, running: new Set() };

/* ---------------- sol panel ---------------- */
async function loadNav() {
  try { T.registry = await (await fetch("/api/tools?lang=" + (typeof LANG === "string" ? LANG : "tr"))).json(); } catch { T.registry = []; }
  if (!T.registry.some(t => t.id === "sherlock"))
    T.registry.unshift({ id: "sherlock", group: "Kullanıcı adı", title: "Sherlock", icon: "fingerprint", fields: [], about: {} });
  T.registry.unshift({ id: "unified", group: "Çalışma alanı", title: "Akıllı arama", icon: "search", desc: "Tek giriş, tüm uygun araçlar, birleşik rapor", fields: [] },
                     { id: "guide", group: "Çalışma alanı", title: "Rehber", icon: "book", desc: "Araçların ne işe yaradığı", fields: [] },
                     { id: "cases", group: "Çalışma alanı", title: "Vakalar", icon: "folder", desc: "Kaydedilen bulgular, grafik ve rapor", fields: [] },
                     { id: "settings", group: "Çalışma alanı", title: "Ayarlar", icon: "gear", desc: "API anahtarları", fields: [] });
  $("#aboutSherlock .about-body").innerHTML = aboutHTML(T.registry.find(t => t.id === "sherlock"));
  renderGuide();
  renderNav();
  const start = (location.hash || "").slice(1);
  selectTool(T.registry.some(t => t.id === start) ? start : "unified", false);
}
function renderNav() {
  const q = $("#navFilter").value.trim().toLowerCase();
  const groups = {};
  for (const t of T.registry) {
    if (q && !(`${t.title} ${t.group} ${t.desc || ""}`.toLowerCase().includes(q))) continue;
    (groups[t.group] ||= []).push(t);
  }
  $("#navList").innerHTML = sortGroups(groups).map(([g, items]) => `
    <div class="nav-group">${esc(g)}</div>
    ${items.map(t => `<button type="button" class="nav-item ${T.current === t.id ? "active" : ""}" data-tool="${t.id}" title="${esc(t.title)}">
        ${svg(t.icon)}<span>${esc(t.title)}</span>${keyBadge(t.id)}${T.running.has(t.id) ? '<i class="busy"></i>' : ""}</button>`).join("")}`).join("")
    || '<div class="nav-group">Eşleşen araç yok</div>';
  if (typeof paintWatchBadge === "function") paintWatchBadge();
}
const GROUP_ORDER = ["Çalışma alanı", "Kişi", "Kullanıcı adı", "E-posta", "Telefon", "Platform", "Görsel", "Alan adı", "Kripto", "Arama", "Çerçeveler", "Eklentiler"];
const sortGroups = groups => Object.entries(groups).sort(([a], [b]) =>
  (GROUP_ORDER.indexOf(a) + 1 || 99) - (GROUP_ORDER.indexOf(b) + 1 || 99));

/* API anahtarı gerektiren araçlar: anahtar yoksa anahtar simgesi, girildiyse yeşil onay */
const KEY_SVG = '<svg viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="M11 12l8.5-8.5M16 7l2.5 2.5M14 9l2 2"/></svg>';
const KEY_OK_SVG = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" class="fill"/><path d="M8 12.3l2.7 2.7 5.3-5.6" class="tick"/></svg>';
function keyBadge(id) {
  const k = T.toolKeys?.[id];
  if (!k) return "";
  const ok = !!T.keys?.[k.key];
  const cls = ok ? "ok" : k.required ? "need" : "opt";
  const title = ok ? "API anahtarı girildi" : k.required ? "API anahtarı gerekli — Ayarlar'dan ekleyin" : "İsteğe bağlı API anahtarı (anahtarsız da çalışır)";
  return `<i class="kb ${cls}" title="${title}" aria-label="${title}">${ok ? KEY_OK_SVG : KEY_SVG}</i>`;
}
$("#navFilter").oninput = renderNav;
$("#navList").onclick = e => {
  const b = e.target.closest("[data-tool]");
  if (b) { selectTool(b.dataset.tool); closeMobileNav(); }
};
$("#navToggle").onclick = () => {
  if (matchMedia("(max-width: 800px)").matches) return closeMobileNav();
  const c = document.documentElement.classList.toggle("nav-collapsed");
  try { localStorage.setItem("nav-collapsed", c ? "1" : "0"); } catch {}
};
$("#navOpen").onclick = () => { $("#nav").classList.add("mobile-open"); $("#navScrim").hidden = false; };
function closeMobileNav() { $("#nav").classList.remove("mobile-open"); $("#navScrim").hidden = true; }
$("#navScrim").onclick = closeMobileNav;

function selectTool(id, push = true) {
  if (T.current === id) return;
  if (T.es && T.current !== "sherlock") { T.es.close(); T.es = null; T.running.delete(T.current); stopTimer(); }
  T.current = id;
  closeDrawer();
  if (push) history.replaceState(null, "", "#" + id);
  const VIEWS = { unified: "#view-unified", sherlock: "#view-sherlock", guide: "#view-guide", cases: "#view-cases", settings: "#view-settings" };
  $$("main .view").forEach(v => (v.hidden = true));
  $(VIEWS[id] || "#view-tool").hidden = false;
  document.title = (T.registry.find(t => t.id === id)?.title || "OSINT") + " · OSINT Panel";
  if (!VIEWS[id]) showTool(T.registry.find(t => t.id === id));
  if (id === "cases") openCases();
  if (id === "settings") loadSettings();
  if (id === "unified" && typeof renderTypeBar === "function") renderTypeBar();
  renderNav();
  scrollTo(0, 0);
}

/* ---------------- araç ekranı ---------------- */
function showTool(tool) {
  $("#tTitle").textContent = tool.title;
  $("#tDesc").textContent = tool.desc || "";
  const note = $("#tNote");
  note.hidden = !tool.note;
  note.innerHTML = esc(tool.note || "").replace(/`([^`]+)`/g, "<code>$1</code>");
  const need = T.toolKeys?.[tool.id];
  if (need && need.required && !T.keys?.[need.key] && need.key !== "ghunt_login") {
    note.hidden = false;
    note.innerHTML += ` <a class="text-link" href="#settings">Anahtarı Ayarlar'a ekle →</a>`;
  }
  // Ana alan büyük tek satırlık kutudur; metin alanı / dosya ise ana kutu gizlenir ve alan formda tam genişlikte çizilir.
  const main = tool.fields[0];
  const bigMain = main && !["textarea", "file"].includes(main.type);
  const rest = bigMain ? tool.fields.slice(1) : tool.fields;
  const mainEl = $("#tMain");
  mainEl.hidden = !bigMain;
  $("#toolForm .search").classList.toggle("no-main", !bigMain);
  mainEl.name = bigMain ? main.name : "";
  mainEl.type = bigMain && main.type === "email" ? "email" : "text";
  mainEl.placeholder = bigMain ? (main.placeholder || main.label) : "";
  mainEl.required = bigMain && !!main.required;
  mainEl.value = "";
  $("#tFields").innerHTML = rest.map(f => {
    const id = `f_${f.name}`;
    if (f.type === "checkbox") return `<label class="check"><input type="checkbox" name="${f.name}" id="${id}"> ${esc(f.label)}</label>`;
    if (f.type === "select") return `<label class="field"><span class="lbl">${esc(f.label)}</span><select name="${f.name}" id="${id}">
        ${f.options.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></label>`;
    if (f.type === "textarea") return `<label class="field wide"><span class="lbl">${esc(f.label)}</span>
        <textarea name="${f.name}" id="${id}" rows="7" spellcheck="false" placeholder="${esc(f.placeholder || "")}">${esc(f.value ?? "")}</textarea></label>`;
    if (f.type === "file") {
      const isImg = !f.accept;
      const what = isImg ? (f.multiple ? "Fotoğrafları" : "Fotoğrafı") : (f.multiple ? "Dosyaları" : "Dosyayı");
      const hint = isImg ? "JPEG, PNG, HEIC, TIFF, RAW" : (f.accept || "").replaceAll(",", " ").replaceAll(".", "").toUpperCase();
      return `<label class="dropzone" for="${id}" data-what="${what}" data-hint="${esc(hint)}">
        <input type="file" name="${f.name}" id="${id}" ${f.multiple ? "multiple" : ""} accept="${esc(f.accept || "image/*,.heic,.heif,.tif,.tiff,.dng,.cr2,.nef,.arw")}">
        <img class="dz-preview" alt="" hidden>
        <span class="dz-text"><b>${what} buraya sürükle</b> ya da tıklayıp seç<br><small>${esc(hint)}</small></span>
        <button type="button" class="text dz-clear" hidden>Kaldır</button></label>`;
    }
    return `<label class="field"><span class="lbl">${esc(f.label)}</span><input type="${f.type === "number" ? "number" : f.type === "password" ? "password" : "text"}"
        name="${f.name}" id="${id}" value="${esc(f.value ?? "")}" placeholder="${esc(f.placeholder || "")}" ${f.required ? "required" : ""}></label>`;
  }).join("");
  $$("#tFields .dropzone").forEach(initDropzone);
  $("#tAbout .about-body").innerHTML = aboutHTML(tool);
  $("#tAbout").hidden = !tool.about || !tool.about.what;
  $("#tAbout").open = false;
  resetResults();
  mainEl.focus();
}

/* ---------------- sürükle-bırak dosya alanı ---------------- */
function initDropzone(dz) {
  const input = dz.querySelector("input[type=file]");
  const img = dz.querySelector(".dz-preview");
  const clear = dz.querySelector(".dz-clear");
  const show = () => {
    const files = [...input.files];
    const f = files[0];
    dz.classList.toggle("has-file", !!f);
    clear.hidden = !f;
    if (img.src) URL.revokeObjectURL(img.src);
    img.hidden = !(f && f.type.startsWith("image/"));
    if (f) {
      if (!img.hidden) { img.src = URL.createObjectURL(f); img.onerror = () => { img.hidden = true; }; }   // HEIC/RAW önizlenemez
      const size = files.reduce((s, x) => s + x.size, 0);
      dz.querySelector(".dz-text").innerHTML = files.length > 1
        ? `<b>${files.length} dosya seçildi</b><br><small>${files.map(x => esc(x.name)).slice(0, 4).join(", ")}${files.length > 4 ? "…" : ""} · ${(size / 1024).toFixed(0)} KB</small>`
        : `<b>${esc(f.name)}</b><br><small>${(f.size / 1024).toFixed(0)} KB</small>`;
      if (!$("#tMain").hidden && !input.multiple) $("#tMain").value = "";
    } else {
      dz.querySelector(".dz-text").innerHTML = `<b>${dz.dataset.what} buraya sürükle</b> ya da tıklayıp seç<br><small>${esc(dz.dataset.hint)}</small>`;
    }
  };
  input.onchange = show;
  clear.onclick = e => { e.preventDefault(); input.value = ""; show(); };
  ["dragenter", "dragover"].forEach(t => dz.addEventListener(t, e => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(t => dz.addEventListener(t, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", e => {
    e.preventDefault();
    if (!e.dataTransfer.files.length) return;
    const dt = new DataTransfer();
    [...e.dataTransfer.files].slice(0, input.multiple ? 30 : 1).forEach(x => dt.items.add(x));
    input.files = dt.files; show();
    if (!T.es && !input.multiple) $("#toolForm").requestSubmit();
  });
}

/* ---------------- harita ---------------- */
function mapEmbed(lat, lon, zoom = 0.01) {
  const bbox = [lon - zoom * 1.6, lat - zoom, lon + zoom * 1.6, lat + zoom].map(n => n.toFixed(5)).join(",");
  return `<iframe class="map" loading="lazy" referrerpolicy="no-referrer" title="Harita"
    src="https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat},${lon}"></iframe>`;
}

/* ---------------- ExifTool ekranı ---------------- */
const EXIF_ORDER = ["Konum", "Kamera", "Kişi ve telif", "Yazılım ve düzenleme", "Tarih ve saat", "Çekim ayarları", "Görüntü", "Dosya", "Üretici notları", "Teknik ayrıntılar"];
function renderExif() {
  const R = T.results;
  const photo = R.find(r => r.kind === "photo");
  const gps = R.find(r => r.kind === "gps");
  const thumbs = R.filter(r => r.kind === "thumb");
  const warns = R.filter(r => r.kind === "warn");
  const clean = R.find(r => r.kind === "clean");
  const q = $("#tFilter").value.trim().toLowerCase();
  const fields = R.filter(r => r.kind === "field" && (T.tab === "all" || r.status === "found") &&
    (!q || `${r.title} ${r.detail} ${r.tags}`.toLowerCase().includes(q)));
  if (!photo) return T.es ? '<div class="empty">Okunuyor…</div>' : "";
  const groups = {};
  fields.forEach(f => (groups[f.tags] ||= []).push(f));
  return `<div class="exif">
    <div class="exif-top">
      <a class="exif-photo" href="${esc(photo.image)}" target="_blank" rel="noopener"><img src="${esc(photo.image)}" alt="İncelenen fotoğraf" onerror="this.parentNode.classList.add('noimg')"><span>Önizleme yok</span></a>
      <div class="exif-side">
        <dl class="exif-sum">${Object.entries(photo.meta || {}).map(([k, v]) => `<dt>${esc(k)}</dt><dd class="${v === "–" ? "muted" : ""}">${esc(v)}</dd>`).join("")}</dl>
        <div class="exif-actions">
          <a class="text-link" href="${esc(photo.image)}?download=1">Fotoğrafı indir</a>
          ${clean ? `<a class="text-link" href="${esc(clean.url)}?download=1">Meta verisi silinmiş kopyayı indir</a>` : ""}
        </div>
      </div>
    </div>
    ${gps ? `<div class="exif-gps"><div class="exif-gps-head"><b>${esc(gps.title)}</b><span class="mono">${esc(gps.detail)}</span>
        <a class="text-link" href="${esc(gps.url)}" target="_blank" rel="noopener noreferrer">Google Maps'te aç ↗</a></div>${mapEmbed(+gps.lat, +gps.lon, 0.004)}</div>`
      : `<div class="exif-nogps">Fotoğrafta konum (GPS) bilgisi yok.</div>`}
    ${warns.length ? `<div class="exif-warns">${warns.map(w => `<div class="warn"><b>${esc(w.title)}</b><span>${esc(w.detail)}</span></div>`).join("")}</div>` : ""}
    ${thumbs.length ? `<div class="exif-thumbs">${thumbs.map(t => `<figure><img src="${esc(t.image)}" alt=""><figcaption><b>${esc(t.title)}</b>${esc(t.detail)}</figcaption></figure>`).join("")}</div>` : ""}
    <div class="exif-groups">
      ${EXIF_ORDER.filter(g => groups[g]).map(g => `<details class="exif-group" ${["Konum", "Kamera", "Kişi ve telif", "Yazılım ve düzenleme", "Tarih ve saat"].includes(g) || q ? "open" : ""}>
        <summary>${esc(g)} <span class="n">${groups[g].length}</span></summary>
        <table>${groups[g].map(f => `<tr><td>${esc(f.title)}</td><td>${esc(f.detail)}</td></tr>`).join("")}</table></details>`).join("")}
      ${!fields.length ? `<div class="empty">${T.tab === "found" ? "Öne çıkan alan yok. “Tümü” sekmesine bakın." : "Alan bulunamadı."}</div>` : ""}
    </div>
  </div>`;
}

/* ---------------- araç bilgileri ---------------- */
const ABOUT_LABELS = [["what", "Ne yapar"], ["when", "Ne zaman kullanılır"], ["input", "Girdi"], ["output", "Çıktı"], ["tips", "İpucu"]];
function aboutHTML(t) {
  const a = t?.about || {};
  return `<dl class="about-body" style="all:unset;display:contents">${ABOUT_LABELS.filter(([k]) => a[k])
    .map(([k, l]) => `<dt>${l}</dt><dd>${esc(a[k])}</dd>`).join("")}</dl>`;
}
function renderGuide() {
  const groups = {};
  for (const t of T.registry) if (t.group !== "Çalışma alanı") (groups[t.group] ||= []).push(t);
  $("#guideList").innerHTML = sortGroups(groups).map(([g, items]) => `
    <div class="guide-group">${esc(g)}</div>
    ${items.map(t => `<div class="guide-item" data-tool="${t.id}">
      <div class="gi-icon">${svg(t.icon)}</div>
      <div>
        <h3>${esc(t.title)}</h3>
        <p>${esc(t.about?.what || t.desc || "")}</p>
        ${t.about?.when ? `<div class="gi-when"><b>Ne zaman:</b> ${esc(t.about.when)}</div>` : ""}
        ${t.note ? `<div class="gi-need">Gereksinim: ${esc(t.note.replace(/`/g, ""))}</div>` : ""}
      </div></div>`).join("")}`).join("");
}
addEventListener("hashchange", () => {
  const id = location.hash.slice(1);
  if (T.registry.some(t => t.id === id)) selectTool(id, false);
});
$("#guideList").onclick = e => { const el = e.target.closest("[data-tool]"); if (el) selectTool(el.dataset.tool); };

function resetResults() {
  T.results = []; T.logs = []; T.job = null; T.error = null; T.personaState = null;
  $("#tSaveCase").disabled = true;
  $("#tStatus").textContent = "";
  $("#tTime").textContent = "0:00";
  $("#tBar").style.width = "0"; $("#tMeter").classList.remove("indeterminate", "running"); $("#tClock").classList.remove("running");
  $("#tLog").textContent = "";
  setToolExports(false);
  renderTool();
}

$("#toolForm").onsubmit = async e => {
  e.preventDefault();
  const tool = T.registry.find(t => t.id === T.current);
  if (!tool || T.es) return;
  const fd = new FormData($("#toolForm"));
  fd.append("_lang", typeof LANG === "string" ? LANG : "tr");
  const hasFile = [...fd.values()].some(v => v instanceof File && v.size);
  const hasText = [...fd.entries()].some(([k, v]) => typeof v === "string" && v.trim() && !$(`#f_${k}`)?.matches("select,[type=number],[type=checkbox]"));
  if (!$("#tMain").hidden && $("#tMain").required && !$("#tMain").value.trim()) return $("#tMain").focus();
  if (!hasText && !hasFile) return toast("Bir değer girin ya da dosya seçin");
  resetResults();
  $("#tRun").disabled = true; $("#tStop").disabled = false;
  $("#tStatus").textContent = "Başlatılıyor…";
  let r, d;
  try {
    r = await fetch(`/api/tool/${tool.id}`, { method: "POST", body: fd });
    d = await r.json();
  } catch (err) { d = { error: err.message }; }
  if (!r?.ok) { $("#tRun").disabled = false; $("#tStop").disabled = true; $("#tStatus").textContent = ""; return showError(d.error); }

  T.job = d.job; T.started = Date.now();
  T.running.add(tool.id); renderNav();
  $("#tMeter").classList.add("indeterminate", "running"); $("#tClock").classList.add("running");
  T.timer = setInterval(() => ($("#tTime").textContent = fmtClock(Date.now() - T.started)), 250);
  const es = new EventSource(`/api/stream/${d.job}`);
  T.es = es;
  let pending = false;
  const later = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; renderTool(); }); } };
  es.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.type === "result") { T.results.push(m.data); later(); }
    else if (m.type === "log") {
      T.logs.push(m.data);
      // Ham JSON / komut satırlarını durum satırında gösterme; en fazla 4 kez/sn güncelle
      if (!/^[\[{$]/.test(m.data.trim()) && Date.now() - (T.lastStatus || 0) > 250) {
        T.lastStatus = Date.now();
        $("#tStatus").textContent = m.data.replace(/\s+/g, " ").slice(0, 140);
      }
      if (T.tab === "log") { $("#tLog").textContent += m.data + "\n"; }
    } else if (m.type === "progress") {
      const [dn, tot] = m.data;
      $("#tMeter").classList.remove("indeterminate");
      $("#tBar").style.width = `${(dn / tot) * 100}%`;
    } else if (m.type === "error") { showError(m.data); }
    else if (m.type === "done") { finishTool(m.data); }
  };
  es.onerror = () => { if (T.es === es) finishTool({ cancelled: true }); };
};
$("#tStop").onclick = () => T.job && fetch(`/api/stop/${T.job}`, { method: "POST" });

function stopTimer() { clearInterval(T.timer); }
function finishTool(info) {
  T.es?.close(); T.es = null; stopTimer();
  T.running.delete(T.current); renderNav();
  $("#tRun").disabled = false; $("#tStop").disabled = true;
  $("#tMeter").classList.remove("indeterminate", "running"); $("#tClock").classList.remove("running"); $("#tBar").style.width = "100%";
  $("#tTime").textContent = fmtDone(info.elapsed ?? (Date.now() - T.started) / 1000);
  const found = T.results.filter(r => r.status === "found").length;
  if (!$("#tResults .err-box")) {
    $("#tStatus").textContent = `${info.cancelled ? "Durduruldu" : "Tamamlandı"} · ${found} bulundu · ${T.results.length} sonuç${info.elapsed ? ` · ${info.elapsed} sn` : ""}`;
  }
  setToolExports(T.results.length > 0);
  $("#tSaveCase").disabled = !T.results.some(r => r.status === "found" || r.status === "maybe");
  // Yalnızca bilgi türü sonuç varsa (WHOIS, theHarvester…) "Tümü"ne geç.
  if (!T.results.some(r => r.status === "found" || r.status === "maybe") && T.results.length && T.tab === "found") {
    $$("#tTabs .chip").find(c => c.dataset.tab === "all").click();
    return;
  }
  renderTool();
}
function showError(msg) {
  T.error = msg;
  $("#tStatus").textContent = "Hata";
  renderTool();
}

$$("#tTabs .chip").forEach(c => c.onclick = () => {
  T.tab = c.dataset.tab;
  $$("#tTabs .chip").forEach(x => x.classList.toggle("active", x === c));
  renderTool();
});
$("#tFilter").oninput = () => renderTool();

function toolRows() {
  const q = $("#tFilter").value.trim().toLowerCase();
  return T.results.filter(r => (T.tab === "all" || r.status === "found" || r.status === "maybe") &&
    (!q || `${r.title} ${r.url} ${r.detail} ${r.tags}`.toLowerCase().includes(q)));
}

function renderTool() {
  const R = T.results;
  $("#tFound").textContent = R.filter(r => r.status === "found" || r.status === "maybe").length;
  $("#tInfo").textContent = R.filter(r => r.status === "info").length;
  $("#tErr").textContent = R.filter(r => r.status === "error").length;
  $$("#tTabs .chip").forEach(c => {
    const n = c.dataset.tab === "found" ? +$("#tFound").textContent : c.dataset.tab === "all" ? R.length : T.logs.length;
    c.innerHTML = c.innerHTML.replace(/<span class="n">.*<\/span>/, "") + `<span class="n">${n}</span>`;
  });
  const isLog = T.tab === "log";
  $("#tLog").hidden = !isLog;
  $("#tResults").hidden = isLog;
  if (isLog) { $("#tLog").textContent = T.logs.join("\n") || "Henüz çıktı yok."; return; }

  const err = T.error ? `<div class="err-box">${esc(T.error).replace(/tools\/ghunt\/bin\/ghunt login/, "<code>$&</code>")}</div>` : "";
  if (T.current === "exiftool") {
    // Akış sırasında haritanın tekrar tekrar yüklenmemesi için bitince çiz.
    $("#tResults").innerHTML = err + (T.es ? '<div class="empty">Okunuyor…</div>' : renderExif());
    return;
  }
  const rows = toolRows().filter(r => !["figure", "histogram", "warn", "geofusion"].includes(r.kind));
  if (T.current === "namesearch") {
    $("#tResults").innerHTML = err + (T.es ? '<div class="empty">Kaynaklar taranıyor… (Wikidata, haberler, akademik kayıtlar, GitHub, kullanıcı adları)</div>' : renderNameSearch(R));
    return;
  }
  if (T.current === "geofusion" && T.es) {
    // Harita, analiz bitince bir kez çizilir (akış sırasında tekrar tekrar yüklenmesin)
    $("#tResults").innerHTML = err + '<div class="empty">Fotoğraf inceleniyor… EXIF, GeoCLIP ve yazı okuma çalışıyor.</div>';
    return;
  }
  const blocks = renderGeoFusion(R) + renderBlocks(R);
  const gpsCards = T.es ? "" : R.filter(r => r.kind === "gps" && r.lat != null).slice(0, 3).map(g => `
    <div class="exif-gps"><div class="exif-gps-head"><b>${esc(g.title)}</b><span class="mono">${esc(g.detail || "")}</span>
      <a class="text-link" href="${esc(g.url)}" target="_blank" rel="noopener noreferrer">Google Maps'te aç ↗</a></div>${mapEmbed(+g.lat, +g.lon, 0.08)}</div>`).join("");
  if (!rows.length) {
    $("#tResults").innerHTML = err + gpsCards + blocks + (R.length ? (blocks ? "" : '<div class="empty">Bu sekmede sonuç yok. “Tümü” sekmesine bakın.</div>') : (T.es ? '<div class="empty">Çalışıyor…</div>' : ""));
    initGeoMap();
    return;
  }
  $("#tResults").innerHTML = err + gpsCards + blocks + bulkBar(R) + `<div class="rlist">${rows.map(r => `
    <div class="ritem ${preview.url && preview.url === (r.url || "#" + r.i) ? "sel" : ""}" data-ti="${r.i}">
      <div class="thumb">${r.image ? `<img src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'dot ${r.status}'}))">` : `<i class="dot ${r.status}"></i>`}</div>
      <div>
        <div class="t1">${esc(r.title)}</div>
        ${r.url ? `<div class="t2"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url)}</a></div>` : ""}
        ${r.detail ? `<div class="t3">${esc(r.detail)}</div>` : ""}
      </div>
      <div class="ractions"><span class="tag2">${esc(r.tags || "")}</span>${rowButtons(r)}</div>
    </div>`).join("")}</div>`;
  initGeoMap();
}

/* ---------------- İsim araştırma: kişi kartı + bölümler ---------------- */
const CC_NAMES = new Intl.DisplayNames(["tr"], { type: "region" });
const ccName = cc => { try { return CC_NAMES.of(cc.toUpperCase()); } catch { return cc; } };
const LINK_SECTIONS = new Set(["Sosyal medya", "Arama motorları", "Görseller", "Şirket ve kamu kayıtları"]);
const OPEN_SECTIONS = new Set(["Tanınmış kişi", "Kullanıcı adı kontrolü", "GitHub", "Haberler", "Akademik", "Yaptırım / PEP", "E-posta tahmini"]);

function rowHTML(r) {
  return `<div class="ritem ${preview.url && preview.url === (r.url || "#" + r.i) ? "sel" : ""}" data-ti="${r.i}">
    <div class="thumb">${r.image ? `<img src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('i'),{className:'dot ${r.status}'}))">` : `<i class="dot ${r.status}"></i>`}</div>
    <div>
      <div class="t1">${esc(r.title)}</div>
      ${r.url ? `<div class="t2"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.url.length > 90 ? r.url.slice(0, 88) + "…" : r.url)}</a></div>` : ""}
      ${r.detail ? `<div class="t3">${esc(r.detail)}</div>` : ""}
    </div>
    <div class="ractions">${r.status === "maybe" ? '<span class="tag2">olası</span>' : ""}${rowButtons(r)}</div>
  </div>`;
}

function renderNameSearch(R) {
  const p = R.find(r => r.kind === "person");
  if (!p) return "";
  const d = p.data, m = d.match;
  const q = $("#tFilter").value.trim().toLowerCase();
  const warns = R.filter(r => r.kind === "warn");
  const facts = [];
  if (d.gender) facts.push(["Olası cinsiyet", `${d.gender.value} (%${Math.round(d.gender.p * 100)})`]);
  if (d.age) facts.push(["İsmin yaş ortalaması", `${d.age.value}`]);
  if (d.nationality?.length) facts.push(["Soyadın olası kökeni", d.nationality.map(n => `${ccName(n.cc)} %${Math.round(n.p * 100)}`).join(", ")]);
  if (d.place) facts.push(["Şehir / ülke", d.place]);
  if (d.org) facts.push(["Kurum", d.org]);
  const counts = Object.entries(d.counts).map(([k, v]) => `<span class="pc-count"><b>${v}</b>${esc(k)}</span>`).join("");
  const mfacts = m ? [["Doğum", m.birth], ["Doğum yeri", m.birthplace], ["Meslek", m.occupation], ["Uyruk", m.citizenship],
                      ["Çalıştığı yer", m.employer], ["Eğitim", m.education], ["Ölüm", m.death]].filter(([, v]) => v) : [];
  const card = `<section class="pcard">
    <div class="pc-main">
      ${m?.image ? `<img class="pc-photo" src="${esc(m.image)}" alt="" referrerpolicy="no-referrer">` : `<div class="pc-photo pc-initials">${esc(d.name.split(" ").map(x => x[0]).slice(0, 2).join(""))}</div>`}
      <div class="pc-id">
        <h2>${esc(d.name)}</h2>
        ${m ? `<p class="pc-desc"><span class="pc-badge">Tanınmış kişi</span>${esc(m.desc)} · <a class="text-link" href="${esc(m.url)}" target="_blank" rel="noopener">Wikidata ↗</a></p>`
            : `<p class="pc-desc muted">Wikidata'da bu isimde tanınmış kişi kaydı yok; özel bir kişi olabilir.</p>`}
        ${d.common ? '<p class="pc-common">Bu ad yaygın: sonuçların bir kısmı başka kişilere ait olabilir.</p>' : ""}
        <div class="pc-counts">${counts || '<span class="muted">Doğrudan eşleşen kayıt bulunamadı</span>'}</div>
      </div>
      <div class="pc-actions">
        <button type="button" class="pill-btn" data-pc="sherlock">Kullanıcı adlarını Sherlock'a gönder</button>
        <button type="button" class="pill-btn" data-save="${p.i}">Vakaya ekle</button>
      </div>
    </div>
    ${facts.length || mfacts.length ? `<dl class="pc-facts">${[...mfacts, ...facts].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}
  </section>`;
  const warnHTML = warns.length ? `<div class="exif-warns">${warns.map(w => `<div class="warn"><b>${esc(w.title)}</b><span>${esc(w.detail)}</span></div>`).join("")}</div>` : "";
  const rows = R.filter(r => !["person", "warn"].includes(r.kind) && r.tags &&
    (!q || `${r.title} ${r.url} ${r.detail} ${r.tags}`.toLowerCase().includes(q)));
  const groups = {};
  rows.forEach(r => (groups[r.tags] ||= []).push(r));
  const order = d.sections.length ? d.sections : Object.keys(groups);
  const sections = order.filter(s => groups[s]).map(s => {
    const list = groups[s];
    const exact = list.filter(r => r.status === "found").length;
    const maybe = list.filter(r => r.status === "maybe").length;
    const isLinks = LINK_SECTIONS.has(s) || s === "Olası kullanıcı adları";
    const label = isLinks ? `${list.length} bağlantı / aday`
      : [exact ? `${exact} eşleşme` : "", maybe ? `${maybe} olası` : ""].filter(Boolean).join(" · ") || "sonuç yok";
    return `<details class="ns-group" ${OPEN_SECTIONS.has(s) || q ? "open" : ""}>
      <summary>${esc(s)} <span class="n">${label}</span></summary>
      ${s === "Olası kullanıcı adları"
        ? `<div class="ns-chips">${list.map(r => `<button type="button" class="chain-btn" data-chain="${r.i}">${esc(r.title)}</button>`).join("")}</div>`
        : LINK_SECTIONS.has(s)
          ? `<div class="ns-links">${list.map(r => `<a class="get-key" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" title="${esc(r.detail || "")}">${esc(r.title)} ↗</a>`).join("")}</div>`
          : `<div class="rlist">${list.map(rowHTML).join("")}</div>`}
    </details>`;
  }).join("");
  return card + warnHTML + renderPersonas(R) + `<h3 class="ns-h">Kaynak kaynak bulgular</h3><div class="ns-sections">${sections}</div>`;
}

/* ---------------- Olası kişiler (aynı isimli farklı kişileri ayırma) ---------------- */
function renderPersonas(R) {
  const b = R.find(r => r.kind === "personas");
  if (!b || !b.data.personas.length) return "";
  const st = (T.personaState ||= { pinned: null, hidden: new Set() });
  const sum = b.data.summary;
  const sumBy = Object.fromEntries((sum?.personas || []).map(p => [p.id, p]));
  const deep = R.find(r => r.kind === "person")?.data?.deep;
  let ps = b.data.personas.filter(p => !st.hidden.has(p.id));
  if (st.pinned) ps = [...ps.filter(p => p.id === st.pinned), ...ps.filter(p => p.id !== st.pinned)];
  const hidden = b.data.personas.filter(p => st.hidden.has(p.id));
  const cite = srcs => srcs.map(n => `<a class="cite" href="#" data-goto="${n}">${n}</a>`).join("");
  const card = p => {
    const s = sumBy[p.id];
    return `<article class="persona ${st.pinned === p.id ? "pinned" : ""} ${st.pinned && st.pinned !== p.id ? "dim" : ""}" data-pid="${p.id}">
      <header class="pe-head">
        <div class="pe-photos">${p.photos.length ? p.photos.slice(0, 4).map(u => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">`).join("")
          : `<div class="pe-initial">${p.id}</div>`}</div>
        <div class="pe-id">
          <div class="pe-top"><b>Olası kişi ${p.id}</b><span class="pe-conf c-${p.confidence}">${p.confidence}</span><span class="mono">puan ${p.score}</span></div>
          <h4>${esc(p.name)}</h4>
          <div class="pe-sub">${[p.org, p.location].filter(Boolean).map(esc).join(" · ") || '<span class="muted">Kurum / konum bilgisi yok</span>'}</div>
          <div class="pe-srcs">${p.sources.map(s => `<span>${esc(s)}</span>`).join("")}</div>
        </div>
        <div class="pe-actions">
          ${st.pinned === p.id ? '<span class="pe-pin">✓ Aradığım kişi</span>' : `<button type="button" class="pill-btn" data-pin="${p.id}">Aradığım kişi bu</button>`}
          <button type="button" class="pill-btn" data-hide="${p.id}">Değil</button>
          <button type="button" class="pill-btn" data-deep="${p.id}">Bu kişiyi derin tara</button>
          <button type="button" class="pill-btn" data-psave="${p.id}">Vakaya kaydet</button>
        </div>
      </header>
      ${s ? `<div class="pe-sum"><span class="pe-ai">Yapay zekâ özeti — kaynaklarla doğrulayın</span><p>${esc(s.summary)}</p>
        ${s.facts?.length ? `<ul>${s.facts.map(f => `<li>${esc(f.text)} ${cite(f.sources || [])}</li>`).join("")}</ul>` : ""}</div>` : ""}
      ${p.context.length ? `<ul class="pe-ctx">${p.context.map(c => `<li>✓ ${esc(c)}</li>`).join("")}</ul>` : ""}
      ${p.accounts.length ? `<div class="pe-acc">${p.accounts.map(a => `<a class="get-key" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.platform)}: ${esc(a.handle)} ↗</a>`).join("")}
        ${p.maybe_accounts.map(a => `<a class="get-key maybe" href="${esc(a.url)}" target="_blank" rel="noopener noreferrer" title="Bu kullanıcı adı alınmış ama bu kişiye ait olduğu doğrulanmadı">${esc(a.platform)}: ${esc(a.handle)}?</a>`).join("")}</div>` : ""}
      <details class="pe-more" ${p.reasons.length ? "open" : ""}>
        <summary>Neden aynı kişi? <span class="n">${p.reasons.length ? p.reasons.length + " bağ" : "tek bulgu"}</span></summary>
        ${p.reasons.length ? `<ul>${p.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>` : '<p class="muted">Bu kişi tek bir bulgudan oluşuyor; başka kaynakla bağlanamadı.</p>'}
        <p class="pe-rows">Bulgular: ${p.rows.map(n => `<a class="cite" href="#" data-goto="${n}">${n}</a>`).join("")}</p>
      </details>
      ${p.timeline.length ? `<details class="pe-more"><summary>Zaman çizelgesi <span class="n">${p.timeline.length}</span></summary>
        <ol class="pe-tl">${p.timeline.map(t => `<li><span class="mono">${esc(t.date)}</span>${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">${esc(t.text)}</a>` : esc(t.text)}</li>`).join("")}</ol></details>` : ""}
    </article>`;
  };
  return `<section class="personas">
    <div class="ps-head"><h3>Olası kişiler <span class="n">${b.data.personas.length}</span></h3>
      <span class="muted">Bulgular ortak kullanıcı adı, e-posta, aynı profil fotoğrafı, resmî bağlantı ve kurumla gruplandı. İsim tek başına kanıt değildir.</span></div>
    ${deep ? `<p class="ps-deep">Derin tarama: “${esc(deep.target_name)}” (olası kişi ${deep.target}) için ${deep.jobs.length} araç çalıştı, ${deep.found} yeni bulgu.</p>` : ""}
    ${ps.map(card).join("")}
    ${hidden.length ? `<details class="pe-hidden"><summary>Elenenler (${hidden.length})</summary>${hidden.map(p => `<div class="pe-h-row">Olası kişi ${p.id}: ${esc(p.name)} ${p.org ? "· " + esc(p.org) : ""} <button type="button" class="text" data-unhide="${p.id}">Geri al</button></div>`).join("")}</details>` : ""}
    ${sum?.contradictions?.length ? `<div class="pe-sum"><b>Çelişkiler</b><ul>${sum.contradictions.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
    ${sum?.next_steps?.length ? `<div class="pe-sum"><b>Önerilen doğrulama adımları</b><ul>${sum.next_steps.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>` : ""}
  </section>`;
}

/* ---------------- Konum bulucu: birleşik sonuç + Leaflet haritası ---------------- */
const GF_COLORS = { exif: "#1c1b19", geoclip: "#2471a3", ocr: "#8e44ad", gemini: "#d35400", claude: "#b03a2e" };
const GF_NAMES = { exif: "EXIF GPS", geoclip: "GeoCLIP", ocr: "Yazı okuma", gemini: "Gemini", claude: "Claude" };
const CONF_TEXT = { kesin: "Kesin", yüksek: "Yüksek güven", orta: "Orta güven", düşük: "Düşük güven" };
let gfMap = null;

function renderGeoFusion(R) {
  const g = R.find(r => r.kind === "geofusion");
  if (!g || !g.data) return "";
  const d = g.data, f = d.final;
  const bySrc = {};
  d.candidates.forEach(c => (bySrc[c.source] ||= []).push(c));
  const statusRows = Object.entries(d.status).map(([name, st]) => {
    const key = Object.keys(GF_NAMES).find(k => GF_NAMES[k] === name);
    const supports = f.sources.includes(key);
    return `<li><i style="background:${GF_COLORS[key] || "#999"}"></i><b>${esc(name)}</b>
      <span>${esc(st)}</span>${supports ? '<em title="Bu kaynak sonuç kümesini destekliyor">✓ destekliyor</em>' : ""}</li>`;
  }).join("");
  const maxS = d.max_score || 1;
  const alts = d.alternatives.map((a, i) => `
    <li><span class="gf-alt-n">${i + 2}</span><div><b>${esc(a.place || `${a.lat.toFixed(3)}, ${a.lon.toFixed(3)}`)}</b>
      <span>${a.sources.map(s => GF_NAMES[s]).join(", ")}</span></div>
      <i class="gf-bar"><i style="width:${Math.min(100, (a.score / maxS) * 100)}%"></i></i></li>`).join("");
  return `<section class="gf" data-gf="${g.i}">
    <div class="gf-head">
      <div class="gf-title">
        <span class="gf-conf c-${f.confidence}">${CONF_TEXT[f.confidence] || f.confidence}</span>
        <h2>${esc(f.place || "Bilinmeyen yer")}</h2>
        <span class="mono">${f.lat.toFixed(5)}, ${f.lon.toFixed(5)} · ±${f.radius_km < 1 ? "<1" : Math.round(f.radius_km)} km</span>
      </div>
      <div class="gf-actions">
        <a class="pill-btn" href="https://www.google.com/maps?q=${f.lat},${f.lon}" target="_blank" rel="noopener noreferrer">Google Maps ↗</a>
        <a class="pill-btn" href="https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${f.lat},${f.lon}" target="_blank" rel="noopener noreferrer">Street View ↗</a>
        <button type="button" class="pill-btn" data-save="${g.i}">Vakaya ekle</button>
      </div>
    </div>
    <div class="gf-body">
      <div class="gf-map" id="gfMap"></div>
      <aside class="gf-side">
        <h3>Kaynaklar</h3><ul class="gf-src">${statusRows}</ul>
        ${alts ? `<h3>Alternatifler</h3><ol class="gf-alts">${alts}</ol>` : ""}
      </aside>
    </div>
    <div class="gf-legend">${Object.keys(bySrc).map(k => `<span><i style="background:${GF_COLORS[k]}"></i>${GF_NAMES[k]} (${bySrc[k].length})</span>`).join("")}
      <span><i class="ring"></i>Sonuç ve güven alanı</span></div>
  </section>`;
}

function initGeoMap() {
  const el = $("#gfMap");
  if (gfMap) { try { gfMap.remove(); } catch {} gfMap = null; }
  if (!el) return;
  if (!window.L) { el.innerHTML = '<div class="empty">Harita kütüphanesi yüklenemedi (internet bağlantısı gerekir).</div>'; return; }
  const g = T.results.find(r => r.kind === "geofusion");
  const d = g.data, f = d.final;
  // Katman eklemeden önce bir görünüm olmalı (çember / işaretçi koordinat dönüşümü buna ihtiyaç duyar)
  gfMap = L.map(el, { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView([f.lat, f.lon], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(gfMap);
  const pts = [[f.lat, f.lon]];
  const maxW = Math.max(...d.candidates.map(c => c.weight), 0.01);
  for (const c of d.candidates) {
    const m = L.circleMarker([c.lat, c.lon], {
      radius: 4 + 8 * Math.sqrt(c.weight / maxW), color: "#fff", weight: 1.5,
      fillColor: GF_COLORS[c.source] || "#999", fillOpacity: .9,
    }).addTo(gfMap);
    m.bindTooltip(`<b>${esc(GF_NAMES[c.source])}</b>${c.label ? " · " + esc(c.label) : ""}${c.why ? `<br>${esc(c.why)}` : ""}`, { direction: "top" });
    if (haversineKm([c.lat, c.lon], [f.lat, f.lon]) < 2500) pts.push([c.lat, c.lon]);
  }
  for (const [i, a] of d.alternatives.entries()) {
    L.marker([a.lat, a.lon], { icon: L.divIcon({ className: "gf-pin alt", html: `<span>${i + 2}</span>`, iconSize: [22, 22] }) })
      .addTo(gfMap).bindTooltip(esc(a.place || "Alternatif"));
  }
  const ring = L.circle([f.lat, f.lon], { radius: Math.max(f.radius_km, 0.05) * 1000, color: "#2f6f3e", weight: 2, fillOpacity: .08 }).addTo(gfMap);
  L.marker([f.lat, f.lon], { icon: L.divIcon({ className: "gf-pin best", html: "<span>1</span>", iconSize: [28, 28] }), zIndexOffset: 1000 })
    .addTo(gfMap).bindTooltip(`<b>En olası konum</b><br>${esc(f.place || "")}`, { direction: "top" });
  const b = L.latLngBounds(pts).extend(ring.getBounds());
  gfMap.fitBounds(b, { padding: [24, 24], maxZoom: f.confidence === "kesin" ? 15 : 12 });
}
function haversineKm(a, b) {
  const r = x => x * Math.PI / 180, dLa = r(b[0] - a[0]), dLo = r(b[1] - a[1]);
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(dLo / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
}

/* Fotoğraf / kare / saat grafiği / uyarı blokları */
function renderBlocks(R) {
  const figs = R.filter(r => r.kind === "figure");
  const hists = R.filter(r => r.kind === "histogram");
  const warns = R.filter(r => r.kind === "warn");
  let html = "";
  if (warns.length) html += `<div class="exif-warns">${warns.map(w => `<div class="warn"><b>${esc(w.title)}</b><span>${esc(w.detail)}</span></div>`).join("")}</div>`;
  for (const h of hists) {
    const vals = Array.from({ length: 24 }, (_, i) => +(h.meta?.[i] || 0));
    const mx = Math.max(1, ...vals);
    html += `<div class="hist"><div class="hist-head"><b>${esc(h.title)}</b><span>${esc(h.detail)}</span></div>
      <div class="hist-bars">${vals.map((v, i) => `<div class="hb" title="${String(i).padStart(2, "0")}:00 UTC · ${v}"><i style="height:${(v / mx) * 100}%"></i><span>${i % 3 ? "" : i}</span></div>`).join("")}</div></div>`;
  }
  if (figs.length) html += `<div class="figs ${figs.length === 1 ? "one" : ""}">${figs.map(f => `
      <figure class="fig" data-ti="${f.i}"><a href="${esc(f.image)}" target="_blank" rel="noopener"><img src="${esc(f.image)}" alt="" loading="lazy" referrerpolicy="no-referrer"></a>
        <figcaption><b>${esc(f.title)}</b>${f.detail ? `<span>${esc(f.detail)}</span>` : ""}</figcaption>
        <div class="fig-actions">${rowButtons(f)}</div></figure>`).join("")}</div>`;
  return html;
}

/* Sonuç başına: zincirleme ve vakaya ekleme düğmeleri (features.js) */
function rowButtons(r) {
  const ents = typeof entitiesOf === "function" ? entitiesOf(r, T.current) : [];
  return `${ents.length ? `<button type="button" class="rbtn" data-chain="${r.i}" title="Bu sonuçla başka bir araç çalıştır">→</button>` : ""}
          <button type="button" class="rbtn" data-save="${r.i}" title="Vakaya ekle">+</button>`;
}
function bulkBar(R) {
  const imgs = R.filter(r => /^https?:/.test(r.image || "") && r.status !== "error");
  const users = R.filter(r => r.kind === "username");
  let b = "";
  if (imgs.length >= 2) b += `<button type="button" class="text" data-bulk="compare">Fotoğrafları karşılaştır (${imgs.length})</button>`;
  if (users.length) b += `<button type="button" class="text" data-bulk="sherlock">Hepsini Sherlock'a gönder (${users.length})</button>`;
  return b ? `<div class="bulkbar">${b}</div>` : "";
}

/* ---------------- ayrıntı paneli ---------------- */
$("#tResults").addEventListener("click", e => {
  if (e.target.closest("a")) return;
  // Olası kişi kartı düğmeleri
  const pb = e.target.closest("[data-pin],[data-hide],[data-unhide],[data-deep],[data-psave],[data-goto]");
  if (pb) {
    e.preventDefault();
    const st = (T.personaState ||= { pinned: null, hidden: new Set() });
    const ps = T.results.find(r => r.kind === "personas")?.data?.personas || [];
    const d = pb.dataset;
    if (d.pin) { st.pinned = +d.pin; st.hidden.delete(+d.pin); }
    if (d.hide) { st.hidden.add(+d.hide); if (st.pinned === +d.hide) st.pinned = null; }
    if (d.unhide) st.hidden.delete(+d.unhide);
    if (d.psave) { const p = ps.find(x => x.id === +d.psave); return saveToCase(T.current, T.job, p.rows.map(i => T.results[i]).filter(Boolean)); }
    if (d.deep) {
      const p = ps.find(x => x.id === +d.deep);
      const person = T.results.find(r => r.kind === "person")?.data || {};
      return runTool("namesearch", { name: person.name, place: person.place || "", org: person.org || "",
        known: [...p.usernames, ...p.emails].slice(0, 6).join(" "), deep: "on" });
    }
    if (d.goto) {
      const el = $(`#tResults [data-ti="${d.goto}"]`);
      if (el) { el.closest("details")?.setAttribute("open", ""); el.scrollIntoView({ block: "center" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); }
      else toast("Bu bulgu listede gizli (filtre ya da bağlantı bölümü)");
      return;
    }
    return renderTool();
  }
  if (e.target.closest("[data-pc=sherlock]")) {
    // Önce büyük platformlarda alınmış görünen adlar, sonra en olası adaylar
    const taken = T.results.filter(r => r.tags === "Kullanıcı adı kontrolü" && r.status === "found").map(r => r.title.split(" · ").pop());
    const cands = T.results.filter(r => r.tags === "Olası kullanıcı adları").map(r => r.title);
    return sendToSherlock([...new Set([...taken, ...cands])].slice(0, 10));
  }
  const chain = e.target.closest("[data-chain]");
  if (chain) return openChainMenu(chain, T.results[+chain.dataset.chain], T.current);
  const save = e.target.closest("[data-save]");
  if (save) return saveToCase(T.current, T.job, [T.results[+save.dataset.save]]);
  const bulk = e.target.closest("[data-bulk]");
  if (bulk) {
    if (bulk.dataset.bulk === "compare")
      return runTool("image-compare", { urls: T.results.filter(r => /^https?:/.test(r.image || "")).map(r => r.image).slice(0, 20).join("\n") });
    return sendToSherlock(T.results.filter(r => r.kind === "username").map(r => r.title));
  }
  const el = e.target.closest("[data-ti]");
  if (!el) return;
  const r = T.results[+el.dataset.ti];
  showToolDetail(r);
});

async function showToolDetail(r) {
  preview.url = r.url || "#" + r.i;
  $$(".ritem").forEach(x => x.classList.toggle("sel", +x.dataset.ti === r.i));
  $("#pvSite").innerHTML = `${r.url ? favicon(r.url) : ""}${esc(T.registry.find(t => t.id === T.current)?.title || "")}`;
  const render = pv => {
    if (preview.url !== (r.url || "#" + r.i)) return;
    const img = r.image || (pv && pv.ok !== false && pv.image) || "";
    const title = (pv && pv.ok !== false && pv.title) || r.title;
    const desc = r.detail || (pv && pv.ok !== false && pv.description) || "";
    const meta = [["sonuç", r.title], ...(r.tags ? [["etiket", r.tags]] : []), ...Object.entries(r.meta || {}),
                  ...(pv?.http_status ? [["yanıt", `HTTP ${pv.http_status}`]] : [])];
    $("#pvBody").innerHTML = `
      ${img ? `<img class="pv-img" src="${esc(img)}" alt="" referrerpolicy="no-referrer" onerror="this.remove()">` : ""}
      <h3 class="pv-title">${esc(title)}</h3>
      ${desc ? `<p class="pv-desc">${esc(desc)}</p>` : ""}
      <div class="pv-meta wide">${meta.map(([k, v]) => `<span>${esc(k)}</span><span>${esc(v)}</span>`).join("")}</div>
      ${r.url ? `<a class="pv-open" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">Bağlantıyı aç ↗</a>` : ""}
      ${chainListHTML(r, T.current)}`;
  };
  render(null);
  openDrawer();
  // görseli olmayan profil bağlantıları için sayfa önizlemesi getir
  if (r.url && !r.image && (r.status === "found" || r.status === "maybe") && /^https?:/.test(r.url)) {
    const cached = state.previews[r.url];
    if (cached) return render(cached);
    try {
      const pv = await (await fetch("/api/preview?url=" + encodeURIComponent(r.url))).json();
      state.previews[r.url] = pv;
      render(pv);
    } catch {}
  }
}

/* ---------------- dışa aktarma ---------------- */
function setToolExports(on) {
  $$("[data-texport]").forEach(b => (b.disabled = !on));
  $("#tCopy").disabled = !on;
}
$$("[data-texport]").forEach(b => b.onclick = () => {
  location.href = `/api/export/${T.job}.${b.dataset.texport}?found=${$("#tExportFound").checked ? 1 : 0}`;
});
$("#tCopy").onclick = async () => {
  const urls = toolRows().map(r => r.url).filter(Boolean);
  try { await navigator.clipboard.writeText(urls.join("\n")); toast(`${urls.length} link kopyalandı`); }
  catch { toast("Panoya kopyalanamadı"); }
};

loadNav();
