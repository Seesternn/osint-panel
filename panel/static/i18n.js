/* Dil seçimi / language switch (TR ⇄ EN).
   Arayüz Türkçe yazılmıştır; İngilizce seçiliyse sayfadaki metinler I18N_EN sözlüğüyle (static/i18n_en.js) çevrilir.
   Yeni eklenen her düğüm MutationObserver ile anında çevrildiği için JS kodunun ayrıca bir şey yapması gerekmez.
   The UI is authored in Turkish; with English selected every text node / attribute is translated through
   the I18N_EN dictionary (exact phrase → pattern → known-phrase substitution), including content rendered later. */
const LANG = (() => {
  try {
    const s = localStorage.getItem("lang");
    if (s === "tr" || s === "en") return s;
  } catch {}
  return (navigator.language || "").toLowerCase().startsWith("tr") ? "tr" : "en";
})();
document.documentElement.lang = LANG;

function setLang(l) {
  try { localStorage.setItem("lang", l); } catch {}
  location.reload();
}

const I18N = (() => {
  if (LANG !== "en" || typeof I18N_EN === "undefined") return { t: s => s, run() {} };
  const norm = s => s.replace(/\s+/g, " ").trim();
  const dict = new Map(Object.entries(I18N_EN.phrases).map(([k, v]) => [norm(k), v]));
  // "a · b" bölücüsü en sona: önce "·" içeren özel kalıplar denensin
  const SPLIT = "(.+?) · (.+)";
  const patterns = [...I18N_EN.patterns.filter(p => p[0] !== SPLIT), ...I18N_EN.patterns.filter(p => p[0] === SPLIT)]
    .map(([re, fn]) => [new RegExp("^" + re + "$", "u"), fn]);
  // Cümle içindeki bilinen ifadeler (en uzun önce). Yalnızca 4+ harfli anahtarlar; harf sınırına dikkat edilir.
  const keys = [...dict.keys()].filter(k => k.length >= 4 && !/^[\w.@:/-]+$/.test(k) || /[çğıöşüÇĞİÖŞÜ]/.test(k) && k.length >= 3)
    .sort((a, b) => b.length - a.length);
  const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const subRe = keys.length ? new RegExp(`(?<![\\p{L}\\p{N}])(${keys.map(esc).join("|")})(?![\\p{L}\\p{N}])`, "gu") : null;
  const TR_HINT = /[çğıöşüÇĞİÖŞÜ]|\b(ve|ile|bir|yok|var|için|veya|ya da|sonuç|araç|bulgu|kaydet|vaka|anahtar|kişi|sn|dk)\b/i;
  const TR_LEFT = /[çğıöşüÇĞİÖŞÜ]|\b(ve|ile|bir|bu|da|de|ya|yok|var|için|veya|olan|olarak|gibi|daha|en|ise|ki|mi|sonuç|araç|bulgu|kişi|buraya|sürükle|ara|aç|sn|dk)\b/i;
  const cache = new Map();

  function t(s) {
    if (!s || !/[A-Za-zÇĞİÖŞÜçğıöşü]/.test(s)) return s;
    const hit = cache.get(s);
    if (hit !== undefined) return hit;
    const lead = s.match(/^\s*/)[0], trail = s.match(/\s*$/)[0], core = norm(s);
    let out = dict.get(core);
    if (out === undefined) {
      for (const [re, fn] of patterns) {
        const m = core.match(re);
        if (m) { out = typeof fn === "function" ? fn(...m.slice(1).map(x => x === undefined ? x : t(x))) : core.replace(re, fn); break; }
      }
    }
    if (out === undefined && subRe && TR_HINT.test(core) && core.length <= 160) {
      // Bilinen ifadeleri yerine koy; yalnızca sonuç tamamen İngilizceye dönüştüyse kabul et (yarı Türkçe karışım olmasın)
      const rep = core.replace(subRe, k => dict.get(k));
      if (rep !== core && !TR_LEFT.test(rep)) out = rep;
    }
    const res = out === undefined ? s : lead + out + trail;
    if (cache.size > 5000) cache.clear();
    cache.set(s, res);
    return res;
  }

  const ATTRS = ["placeholder", "title", "aria-label", "data-tip"];
  const SKIP = new Set(["SCRIPT", "STYLE", "CODE", "PRE", "TEXTAREA"]);   // metni çevrilmez (öznitelikleri çevrilir)
  function textNode(n) {
    const p = n.parentNode;
    if (!p || SKIP.has(p.nodeName) || p.closest?.("[data-noi18n], a.t2, .t2 a, .mono")) return;
    const v = n.nodeValue, nv = t(v);
    if (nv !== v) n.nodeValue = nv;
  }
  function element(el) {
    if (el.nodeName === "SCRIPT" || el.nodeName === "STYLE" || el.closest?.("[data-noi18n]")) return;
    for (const a of ATTRS) {
      const v = el.getAttribute?.(a);
      if (v) { const nv = t(v); if (nv !== v) el.setAttribute(a, nv); }
    }
    if (el.nodeName === "INPUT" && (el.type === "button" || el.type === "submit") && el.value) el.value = t(el.value);
  }
  function walk(root) {
    if (root.nodeType === 3) return textNode(root);
    if (root.nodeType !== 1) return;
    element(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) n.nodeType === 3 ? textNode(n) : element(n);
  }
  function run() {
    walk(document.documentElement);
    new MutationObserver(muts => {
      for (const m of muts) {
        if (m.type === "characterData") textNode(m.target);
        else if (m.type === "attributes") element(m.target);
        else m.addedNodes.forEach(walk);
      }
    }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
  }
  return { t, run };
})();
const _t = I18N.t;   // JS içinde gerekirse: _t("Türkçe metin")
I18N.run();
