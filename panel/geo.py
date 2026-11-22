"""Konum bulucu: fotoğrafın çekildiği yeri birden çok bağımsız kaynaktan tahmin edip birleştirir.

Kaynaklar (hepsi ücretsiz; Claude isteğe bağlı):
  1. EXIF GPS (ExifTool)                      — varsa kesin
  2. GeoCLIP (yerel model, Apple GPU)         — görüntünün genel görünümünden koordinat
  3. Yazı okuma (macOS Vision) + Nominatim    — tabela, telefon kodu, alan adı, sokak / şehir adları
  4. Gemini (ücretsiz katman, anahtar ile)     — ipuçlarını yorumlar, diğer kaynakları doğrular
  5. Claude (anahtar varsa)                   — aynı görev, ek görüş
Adaylar mesafeye göre kümelenir, kaynak çeşitliliği ve ülke uyumuyla puanlanır.
"""
import base64
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from urllib.parse import quote

import requests

import store
from tools import TOOLS, ToolError, _image_to_file, which

UA = "osint-panel-local/1.0 (personal OSINT panel; local use)"   # HTTP başlıkları yalnızca ASCII olabilir
SOURCES = {"exif": "EXIF GPS", "geoclip": "GeoCLIP", "ocr": "Yazı okuma", "gemini": "Gemini", "claude": "Claude"}


@dataclass
class Cand:
    lat: float
    lon: float
    source: str
    weight: float
    label: str = ""
    why: str = ""
    country: str = ""          # ISO kodu (küçük harf), biliniyorsa


def haversine(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


# --------------------------------------------------------------------- Nominatim (OSM)
_nom_lock = threading.Lock()
_nom_last = [0.0]
_nom_cache = {}


def _nominatim(path, params):
    key = (path, tuple(sorted(params.items())))
    if key in _nom_cache:
        return _nom_cache[key]
    with _nom_lock:   # kullanım kuralı: en fazla 1 istek / sn
        wait = 1.1 - (time.time() - _nom_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            r = requests.get(f"https://nominatim.openstreetmap.org/{path}", params={**params, "format": "jsonv2"},
                             headers={"User-Agent": UA, "Accept-Language": "tr,en"}, timeout=15)
            data = r.json() if r.status_code == 200 else None
        except Exception:
            data = None
        _nom_last[0] = time.time()
    _nom_cache[key] = data
    return data


def reverse(lat, lon, zoom=10):
    d = _nominatim("reverse", {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "zoom": zoom})
    if not d or "error" in d:
        return {"name": "", "country": "", "cc": ""}
    a = d.get("address") or {}
    place = a.get("city") or a.get("town") or a.get("village") or a.get("county") or a.get("state_district") or a.get("state") or ""
    region = a.get("state") or a.get("province") or ""
    hood = (a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or "") if zoom >= 14 else ""
    district = (a.get("town") or a.get("county") or a.get("city_district") or "") if zoom >= 14 else ""
    parts = [p for p in dict.fromkeys([hood, district, place, region if region != place else "", a.get("country", "")]) if p]
    return {"name": ", ".join(parts), "country": a.get("country", ""), "cc": (a.get("country_code") or "").lower()}


FOLD = str.maketrans("ıİğĞşŞöÖüÜçÇâÂîÎ", "iIgGsSoOuUcCaAiI")


def geocode(q, cc=""):
    # OCR Türkçe noktaları kaçırabiliyor (MAHALLESI / Sokagi); Nominatim aksansız aramada daha toleranslı
    params = {"q": q.translate(FOLD), "limit": 1}
    if cc:
        params["countrycodes"] = cc
    d = _nominatim("search", params)
    if d:
        x = d[0]
        return float(x["lat"]), float(x["lon"]), x.get("display_name", "")
    return None


# --------------------------------------------------------------------- 1) EXIF
def src_exif(job, path):
    exe = which("exiftool", "/opt/homebrew/bin/exiftool")
    if not exe:
        return []
    out = subprocess.run([exe, "-j", "-n", "-GPSLatitude", "-GPSLongitude", path], capture_output=True, text=True)
    try:
        g = json.loads(out.stdout)[0]
        la, lo = g.get("GPSLatitude"), g.get("GPSLongitude")
        if isinstance(la, (int, float)) and isinstance(lo, (int, float)) and (la or lo):
            return [Cand(la, lo, "exif", 3.0, "Fotoğrafın içindeki GPS", "Fotoğraf dosyasına kamera / telefon tarafından yazılmış konum.")]
    except Exception:
        pass
    return []


# --------------------------------------------------------------------- 2) GeoCLIP (sıcak süreç)
class _GeoclipWorker:
    def __init__(self):
        self.proc = None
        self.lock = threading.Lock()
        self.device = "?"

    def _start(self, log):
        py = os.path.join(TOOLS, "geoclip", "bin", "python")
        script = os.path.join(TOOLS, "geoclip_worker.py")
        if not os.path.exists(py):
            raise ToolError("GeoCLIP kurulu değil.")
        log("GeoCLIP modeli yükleniyor (ilk seferde ~10-20 sn)…")
        self.proc = subprocess.Popen([py, script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, env=dict(os.environ, PYTHONWARNINGS="ignore", TOKENIZERS_PARALLELISM="false"))
        line = self._readline(180)
        self.device = json.loads(line).get("device", "?")

    def _readline(self, timeout):
        res = [None]
        def rd():
            while True:
                l = self.proc.stdout.readline()
                if not l:
                    return
                if l.lstrip().startswith("{"):
                    res[0] = l
                    return
        t = threading.Thread(target=rd, daemon=True)
        t.start()
        t.join(timeout)
        if res[0] is None:
            self.proc.kill()
            self.proc = None
            raise ToolError("GeoCLIP yanıt vermedi.")
        return res[0]

    def predict(self, path, k, log):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                self._start(log)
            self.proc.stdin.write(json.dumps({"path": path, "top_k": k}) + "\n")
            self.proc.stdin.flush()
            d = json.loads(self._readline(120))
            if "error" in d:
                raise ToolError("GeoCLIP: " + d["error"])
            return d["top"]


GEOCLIP = _GeoclipWorker()


def src_geoclip(job, path):
    top = GEOCLIP.predict(path, 10, job["log"])
    total = sum(p for _, _, p in top) or 1
    return [Cand(la, lo, "geoclip", 0.9 * p / total, f"GeoCLIP #{i + 1}", f"Olasılık %{p * 100:.1f}")
            for i, (la, lo, p) in enumerate(top)]


# --------------------------------------------------------------------- 3) Yazı okuma
TLD_CC = {"tr": "tr", "de": "de", "fr": "fr", "it": "it", "es": "es", "uk": "gb", "nl": "nl", "ru": "ru", "gr": "gr",
          "pt": "pt", "pl": "pl", "at": "at", "ch": "ch", "be": "be", "se": "se", "no": "no", "dk": "dk", "fi": "fi",
          "cz": "cz", "hu": "hu", "ro": "ro", "bg": "bg", "ua": "ua", "az": "az", "ge": "ge", "jp": "jp", "kr": "kr",
          "cn": "cn", "br": "br", "ar": "ar", "mx": "mx", "ca": "ca", "au": "au", "in": "in", "ae": "ae", "sa": "sa",
          "eg": "eg", "ir": "ir", "iq": "iq", "il": "il", "cy": "cy", "ba": "ba", "rs": "rs", "hr": "hr", "al": "al", "mk": "mk"}
STREET_WORDS = re.compile(r"\b(cad(desi)?|cd\.?|sok(ağı|ak)?|sk\.?|mah(allesi)?|mh\.?|bulvar[ıi]?|blv\.?|meydan[ıi]?|köy[üu]?|"
                          r"street|st\.|avenue|ave\.?|road|rd\.?|square|via|piazza|corso|rue|place|avenue|boulevard|straße|strasse|"
                          r"platz|weg|gasse|calle|plaza|avenida|rua|praça|ulica|ul\.|проспект|улица)\b", re.I)


def _tesseract(path):
    """Linux / Docker: Tesseract ile satır satır yazı okuma (macOS Vision yardımcısı yoksa)."""
    exe = shutil.which("tesseract")
    if not exe:
        return []
    langs = os.environ.get("TESSERACT_LANGS", "eng+tur")
    out = subprocess.run([exe, path, "stdout", "--psm", "11", "-l", langs, "tsv"], capture_output=True, text=True, timeout=90)
    rows = {}
    for l in out.stdout.splitlines()[1:]:
        f = l.split("\t")
        if len(f) < 12 or not f[11].strip():
            continue
        try:
            conf = float(f[10])
        except ValueError:
            continue
        if conf < 0:
            continue
        key = (f[2], f[3], f[4])                      # blok, paragraf, satır
        rows.setdefault(key, []).append((conf, f[11].strip()))
    lines = []
    for words in rows.values():
        c = sum(w[0] for w in words) / len(words) / 100
        t = " ".join(w[1] for w in words)
        if c >= 0.45 and len(t) >= 2:
            lines.append(t)
    return lines


def run_ocr(path):
    exe = os.path.join(TOOLS, "ocr", "ocr")
    if not os.path.exists(exe):
        return _tesseract(path)
    out = subprocess.run([exe, path], capture_output=True, text=True, timeout=60)
    lines = []
    for l in out.stdout.splitlines():
        if "\t" in l:
            c, t = l.split("\t", 1)
            if float(c) >= 0.3 and len(t.strip()) >= 2:
                lines.append(t.strip())
    return lines


def ocr_clues(lines):
    """Yazılardan ülke ipuçları ve yer adı sorguları çıkarır."""
    import phonenumbers
    from phonenumbers import geocoder
    text = " · ".join(lines)
    countries, places, notes = {}, [], []
    # Telefon numaraları → ülke (+ sabit hatlarda şehir)
    for region in ("TR", None):
        for m in phonenumbers.PhoneNumberMatcher(text, region or "US"):
            n = m.number
            rc = (phonenumbers.region_code_for_number(n) or "").lower()
            if rc:
                countries[rc] = countries.get(rc, 0) + 1
                city = geocoder.description_for_number(n, "tr")
                if city and city.lower() not in ("türkiye", phonenumbers.region_code_for_number(n).lower()):
                    places.append((city, rc, 0.8, f"Telefon numarası {m.raw_string} → {city}"))
                notes.append(f"Telefon: {m.raw_string} ({rc.upper()})")
        if countries:
            break
    # Alan adı uzantıları
    for tld in re.findall(r"\b[\w-]+\.(?:com\.|org\.|gov\.|edu\.|net\.|bel\.)?([a-z]{2})\b", text.lower()):
        if tld in TLD_CC:
            countries[TLD_CC[tld]] = countries.get(TLD_CC[tld], 0) + 1
            notes.append(f"Alan adı uzantısı .{tld}")
    # Alfabe / dil ipuçları
    if re.search(r"[ğşıİĞŞ]", text):
        countries["tr"] = countries.get("tr", 0) + 2
        notes.append("Türkçe karakterler (ğ, ş, ı)")
    if re.search(r"[а-яА-Я]", text):
        notes.append("Kiril alfabesi")
    if re.search(r"[α-ωΑ-Ω]", text):
        countries["gr"] = countries.get("gr", 0) + 1
        notes.append("Yunan alfabesi")
    if re.search(r"[؀-ۿ]", text):
        notes.append("Arap alfabesi")
    # Tabela adresi: sokak + mahalle + ilçe satırlarını tek adres olarak ara (en isabetli sorgu)
    kw_only = re.compile(r"(?i)^(soka[gğ][ıi]|sokak|sk\.?|caddesi|cadde|cad\.?|cd\.?|bulvar[ıi]|bulvar|street|st\.?|road|"
                         r"avenue|strasse|straße|via|viale|rue|calle|rua)$")
    mah = next((l for l in lines if re.search(r"(?i)\b(mahalle(si)?|mah\.|mh\.)", l)), "")
    ilce = [l for l in lines if 3 <= len(l) <= 20 and l.upper() == l and not re.search(r"\d|→|:", l)
            and not kw_only.match(l.strip()) and not re.search(r"(?i)mahalle|mah\.", l) and len(l.split()) <= 2]
    streets = []
    for i, l in enumerate(lines):
        s = l.strip()
        if kw_only.match(s) and i > 0:
            # Sokak adı tabelada kendi satırının üstündedir: 1 ve 2 satır geriye bakıp iki ayrı aday üret
            for n in (1, 2):
                prev = [x for x in lines[max(0, i - n):i] if not re.search(r"→|\d{3,}|:", x) and not kw_only.match(x.strip())]
                if len(prev) == n:
                    streets.append((" ".join(prev + [s]), 0.9 if n == 1 else 0.85))
        elif STREET_WORDS.search(s) and len(s) <= 50 and len(s.split()) >= 2:
            streets.append((s, 0.9))
    seen = set()
    for street, w in streets[:3]:
        # İlçe satırı bazen reklam yazısıdır; ilçeli ve ilçesiz iki sorgu dene
        for with_ilce in (True, False):
            parts = [tr_title(street)] + ([tr_title(mah)] if mah else []) + ([tr_title(ilce[-1])] if ilce and with_ilce else [])
            q = ", ".join(dict.fromkeys(parts))
            if q not in seen:
                seen.add(q)
                places.append((q, "", w, f"Tabela adresi: “{q}”"))
    # Yer adı adayları: sokak sözcüğü içeren satırlar, sonra büyük harfle yazılmış kısa satırlar
    for l in lines:
        if (STREET_WORDS.search(l) or re.search(r"(?i)mahalle", l)) and len(l) <= 60 and not kw_only.match(l.strip()):
            places.append((tr_title(l), "", 0.6, f"Tabela: “{l}”"))
    for l in lines:
        if len(places) >= 9:
            break
        if 3 <= len(l) <= 30 and l.upper() == l and re.search(r"[A-ZÇĞİÖŞÜ]{3}", l) and not re.search(r"\d{3}", l) \
                and not kw_only.match(l.strip()) and not STREET_WORDS.search(l):
            places.append((tr_title(l), "", 0.35, f"Büyük harfli yazı: “{l}”"))
    # aynı sorguyu iki kez arama
    uniq, seen_q = [], set()
    for p in places:
        if p[0].lower() not in seen_q:
            seen_q.add(p[0].lower())
            uniq.append(p)
    return countries, uniq[:9], notes


def tr_title(s):
    """Türkçe büyük/küçük harf kurallarıyla baş harfleri büyütür (İ→i, I→ı)."""
    low = s.replace("İ", "i").replace("I", "ı").lower()
    return " ".join(w[:1].replace("i", "İ").replace("ı", "I").upper() + w[1:] if w else w for w in low.split(" "))


# --------------------------------------------------------------------- 4-5) Yapay zekâ yorumu
GEO_SCHEMA = {
    "type": "object",
    "properties": {
        "best_guess": {"type": "string"},
        "country": {"type": "string"},
        "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2, küçük harf"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "confidence": {"type": "string", "enum": ["düşük", "orta", "yüksek"]},
        "radius_km": {"type": "number"},
        "clues": {"type": "array", "items": {"type": "object", "properties": {"clue": {"type": "string"}, "inference": {"type": "string"}},
                                             "required": ["clue", "inference"]}},
        "alternatives": {"type": "array", "items": {"type": "object", "properties": {
            "place": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}, "why": {"type": "string"}},
            "required": ["place", "latitude", "longitude", "why"]}},
    },
    "required": ["best_guess", "country", "country_code", "latitude", "longitude", "confidence", "radius_km", "clues", "alternatives"],
}


def _prompt(ctx, lang="tr"):
    return f"""Bu fotoğrafın çekildiği yeri bir OSINT coğrafi konum uzmanı gibi tahmin et.
Görünen ipuçlarını tek tek değerlendir: tabelalar ve dil, plakalar, yol çizgileri ve trafik işaretleri, mimari, bitki örtüsü,
iklim, güneşin açısı, elektrik direkleri, trafiğin hangi şeritten aktığı, mağaza / marka adları, arazi şekli.
Kendi bağımsız değerlendirmeni yap. Aşağıda fotoğraftan okunan yazılar olabilir; bunlar OCR çıktısıdır ve hatalı
okunmuş olabilir, görüntüyle tutarlı olup olmadıklarını kontrol et.
{ctx}
Her ipucunun neyi gösterdiğini kısa yaz. Emin olmadığın yerde güveni düşük tut, uydurma ayrıntı ekleme.
En fazla 3 alternatif ver. Tüm metinler {'İngilizce (English)' if lang == 'en' else 'Türkçe'} olsun. Yanıtı yalnızca JSON olarak ver."""


def _llm_cands(g, source):
    w = {"yüksek": 1.0, "orta": 0.7, "düşük": 0.4}.get(g.get("confidence"), 0.5)
    cc = (g.get("country_code") or "").lower()[:2]
    out = [Cand(float(g["latitude"]), float(g["longitude"]), source, w, g.get("best_guess", ""),
                f"Güven: {g.get('confidence')} · ±{g.get('radius_km', 0):.0f} km", cc)]
    for a in (g.get("alternatives") or [])[:3]:
        try:
            out.append(Cand(float(a["latitude"]), float(a["longitude"]), source, 0.25, a.get("place", ""), a.get("why", "")))
        except Exception:
            pass
    return out


# Ücretsiz katmandaki modeller. Biri çalışmazsa (404 / kota / zaman aşımı) sıradakine geçilir.
# gemini-3.8-flash testte ücretsiz katmanda 150 sn içinde yanıt vermedi; bu yüzden listede yok.
GEMINI_MODELS = ["gemini-3.5-flash-lite", "gemini-4-hydrogen"]
GEMINI_TIMEOUT = 45


def src_gemini(job, img_b64, mime, ctx):
    return gemini_json(job, [{"inlineData": {"mimeType": mime, "data": img_b64}}, {"text": _prompt(ctx, job.get("lang", "tr"))}], GEO_SCHEMA)


def ollama_ready():
    return bool(store.get("ollama_model"))


def ollama_json(job, parts, schema):
    """Yerel Ollama sunucusundan JSON yanıt ister (veri bilgisayardan çıkmaz). Görsel için görsel destekli model gerekir."""
    url = (store.get("ollama_url") or "http://127.0.0.1:11434").rstrip("/")
    model = store.get("ollama_model")
    text = "\n\n".join(p["text"] for p in parts if "text" in p)
    images = [p["inlineData"]["data"] for p in parts if "inlineData" in p]
    msg = {"role": "user", "content": text + "\n\nYanıtı yalnızca şemaya uyan JSON olarak ver."}
    if images:
        msg["images"] = images
    job.get("log", lambda m: None)(f"Ollama ({model}) çalışıyor…")
    for fmt in (schema, "json"):
        try:
            r = requests.post(f"{url}/api/chat", json={"model": model, "messages": [msg], "stream": False, "format": fmt,
                                                      "options": {"temperature": 0.2}}, timeout=int(store.get("ollama_timeout", 180)))
        except requests.RequestException as e:
            return None, f"Ollama'ya bağlanılamadı ({url}): {type(e).__name__}"
        if r.status_code == 404:
            return None, f"Ollama modeli bulunamadı: {model} (ollama pull {model})"
        if r.status_code != 200:
            continue
        try:
            return json.loads(r.json()["message"]["content"]), None
        except Exception:
            continue
    return None, "Ollama yanıtı çözümlenemedi"


def gemini_json(job, parts, schema):
    """Yapay zekâdan JSON yanıt ister. Ayarlarda bir Ollama modeli girildiyse yerel model kullanılır (veri dışarı çıkmaz);
    yoksa Gemini (ücretsiz katman) — model yoğun / kota dolu / yavaşsa sıradakine geçer.
    Dönüş: (sözlük, None) ya da (None, hata metni)."""
    if ollama_ready():
        return ollama_json(job, parts, schema)
    models, tmo = GEMINI_MODELS, GEMINI_TIMEOUT
    key = store.get("gemini_api_key")
    if not key:
        return None, "Gemini anahtarı yok"
    last = ""
    retried = {}
    for model in models:
        for with_schema in (True, False):
            gen = {"responseMimeType": "application/json"}
            if with_schema:
                gen["responseJsonSchema"] = schema
            body = {"contents": [{"parts": parts}], "generationConfig": gen}
            t0 = time.time()
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=tmo)
            except requests.exceptions.Timeout:
                job["log"](f"Gemini {model}: {tmo} sn içinde yanıt yok, sonraki model deneniyor")
                last = f"{model} zaman aşımı"
                break                     # yavaş model: şemasız denemeye gerek yok, sonraki modele geç
            except Exception as e:
                last = type(e).__name__
                continue
            job["log"](f"Gemini {model}{'' if with_schema else ' (şemasız)'}: HTTP {r.status_code} · {time.time() - t0:.1f} sn")
            if r.status_code in (401, 403):
                return None, "Gemini anahtarı geçersiz ya da yetkisiz"
            if r.status_code in (500, 503) and not retried.get(model):
                retried[model] = True
                job["log"](f"Gemini {model} şu an yoğun (HTTP {r.status_code}); 3 sn sonra tekrar deneniyor")
                time.sleep(3)
                try:
                    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                      headers={"x-goog-api-key": key, "Content-Type": "application/json"}, json=body, timeout=tmo)
                except requests.exceptions.RequestException as e:
                    last = f"{model} yanıt vermedi ({type(e).__name__})"
                    break                 # sonraki modeli dene
            if r.status_code in (500, 503):
                last = f"{model} şu an aşırı yoğun (Google tarafında geçici sorun)"
                break                     # sonraki modeli dene
            if r.status_code == 429:
                last = f"{model} ücretsiz kota sınırı doldu"
                break                     # sonraki (daha hafif) modeli dene
            if r.status_code == 404:
                last = f"{model} bulunamadı"
                break                     # sonraki modeli dene
            if r.status_code == 400 and with_schema:
                last = "şema reddedildi"
                continue                  # şemasız dene
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:160]}"
                continue
            try:
                parts = r.json()["candidates"][0]["content"]["parts"]
                text = "".join(p.get("text", "") for p in parts)
                text = text[text.find("{"): text.rfind("}") + 1]
                g = json.loads(text)
                g["_model"] = model
                return g, None
            except Exception as e:
                last = f"yanıt çözümlenemedi ({type(e).__name__})"
    return None, f"Gemini çalışmadı: {last}"


def src_claude(job, img_b64, mime, ctx):
    key = store.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None, None
    import anthropic
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.beta.messages.create(
            model="claude-opus-5-5", max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": {**GEO_SCHEMA, "additionalProperties": False,
                "properties": {**GEO_SCHEMA["properties"],
                               "clues": {"type": "array", "items": {**GEO_SCHEMA["properties"]["clues"]["items"], "additionalProperties": False}},
                               "alternatives": {"type": "array", "items": {**GEO_SCHEMA["properties"]["alternatives"]["items"], "additionalProperties": False}}}}}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": img_b64}},
                {"type": "text", "text": _prompt(ctx, job.get("lang", "tr"))}]}],
        )
    except anthropic.AuthenticationError:
        return None, "Anthropic anahtarı geçersiz"
    except anthropic.RateLimitError:
        return None, "Anthropic hız sınırı"
    except anthropic.APIStatusError as e:
        return None, f"Anthropic API hatası ({e.status_code})"
    except anthropic.APIConnectionError:
        return None, "Anthropic API'ye bağlanılamadı"
    if resp.stop_reason == "refusal":
        return None, "Claude bu görsel için tahmin yapmadı"
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        g = json.loads(text)
        g["_model"] = resp.model
        return g, None
    except Exception:
        return None, "Claude yanıtı çözümlenemedi"


# --------------------------------------------------------------------- birleştirme
def fuse(cands, clue_cc):
    """Açgözlü kümeleme (75 km), kaynak çeşitliliği ve ülke uyumuyla puan."""
    order = sorted(cands, key=lambda c: -c.weight)
    clusters = []
    for c in order:
        for cl in clusters:
            if haversine((c.lat, c.lon), cl["center"]) <= 75:
                cl["members"].append(c)
                tw = sum(m.weight for m in cl["members"])
                cl["center"] = (sum(m.lat * m.weight for m in cl["members"]) / tw, sum(m.lon * m.weight for m in cl["members"]) / tw)
                break
        else:
            clusters.append({"center": (c.lat, c.lon), "members": [c]})
    for cl in clusters:
        srcs = {m.source for m in cl["members"]}
        cl["sources"] = sorted(srcs)
        cl["score"] = sum(m.weight for m in cl["members"]) * (1 + 0.5 * (len(srcs) - 1))
        cl["radius"] = max([5.0] + [haversine((m.lat, m.lon), cl["center"]) for m in cl["members"]])
        # Kümede tabeladan bulunmuş kesin bir adres varsa nokta ona oturur (GeoCLIP kaba, tabela sokak düzeyinde)
        precise = [m for m in cl["members"] if m.source == "ocr" and m.weight >= 0.6]
        if precise and len(srcs) >= 2:
            best_w = max(m.weight for m in precise)
            top = [m for m in precise if m.weight == best_w]
            cl["center"] = (sum(m.lat for m in top) / len(top), sum(m.lon for m in top) / len(top))
            cl["radius"] = max(1.0, max(haversine((m.lat, m.lon), cl["center"]) for m in top))
            cl["precise"] = True
        cl["geoclip_n"] = sum(1 for m in cl["members"] if m.source == "geoclip")
    clusters.sort(key=lambda c: -c["score"])
    # İlk 4 küme için ülke / yer adı ve ülke uyumu
    for cl in clusters[:4]:
        rv = reverse(*cl["center"], zoom=10)
        cl["place"], cl["country"], cl["cc"] = rv["name"], rv["country"], rv["cc"]
        if cl["cc"] and cl["cc"] in clue_cc:
            cl["score"] *= 1 + 0.25 * min(clue_cc[cl["cc"]], 2)
            cl["country_match"] = True
    clusters.sort(key=lambda c: -c["score"])
    return clusters


def confidence(best, clusters, has_exif):
    if has_exif:
        return "kesin"
    close = {m.source for m in best["members"] if haversine((m.lat, m.lon), best["center"]) <= 50}
    if len(close) >= 2:
        return "yüksek"
    # GeoCLIP'in 10 tahmininden en az 4'ü aynı bölgedeyse model kendi içinde tutarlıdır
    if best.get("country_match") or len(best["sources"]) >= 2 or best.get("geoclip_n", 0) >= 4:
        return "orta"
    return "düşük"


# --------------------------------------------------------------------- ana çalıştırıcı
def run_geofusion(job, inp, emit):
    path = _image_to_file(job, inp)
    # HEIC / RAW vb. → JPEG (GeoCLIP, OCR ve yapay zekâ için ortak)
    jpg = os.path.join(job["dir"], "geo_input.jpg")
    if subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "2048", path, "--out", jpg], capture_output=True).returncode != 0:
        raise ToolError("Görsel okunamadı.")
    job["files"]["photo"] = (jpg, "image/jpeg")
    emit(kind="figure", title="İncelenen fotoğraf", status="info", image=f"/api/jobfile/{job['id']}/photo")
    use = lambda k: inp.get(k, True) not in ("off", False, "0")
    log = job["log"]
    status = {}

    # Aşama 1: EXIF, GeoCLIP, OCR paralel
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_exif = ex.submit(src_exif, job, path)
        f_clip = ex.submit(src_geoclip, job, jpg)
        f_ocr_lines = ex.submit(run_ocr, jpg) if use("use_ocr") else None
        exif = f_exif.result()
        try:
            clip = f_clip.result()
            status["geoclip"] = f"{len(clip)} tahmin · {GEOCLIP.device.upper()}"
        except Exception as e:
            clip, status["geoclip"] = [], f"çalışmadı: {e}"
        lines = f_ocr_lines.result() if f_ocr_lines else []
    status["exif"] = "konum var" if exif else "konum yok"
    log(f"EXIF: {status['exif']} · GeoCLIP: {status['geoclip']} · OCR: {len(lines)} satır")
    countries, places, notes = ocr_clues(lines) if lines else ({}, [], [])

    # Aşama 2: yapay zekâ (diğer kaynakların bulgularını bağlam olarak alır)
    ctx_parts = []
    if lines:
        ctx_parts.append("Fotoğraftan okunan yazılar: " + " | ".join(lines[:25]))
    if notes:
        ctx_parts.append("Yazılardan çıkan ipuçları: " + "; ".join(notes[:8]))
    # GeoCLIP'in tahminleri yapay zekâya VERİLMEZ: verilince model onları tekrarlıyor ve iki kaynak bağımsız
    # olmaktan çıkıyor (birleştirmede yanlış "yüksek güven" üretir). Yapay zekâ yalnızca fotoğrafın kendisinden
    # gelen kanıtı (görüntü + okunan yazılar) görür.
    for c in clip[:3]:
        rv = reverse(c.lat, c.lon, zoom=8)
        c.label = f"{c.label}: {rv['name'] or f'{c.lat:.2f}, {c.lon:.2f}'}"
        c.country = rv["cc"]
    if inp.get("context"):
        ctx_parts.append("Kullanıcının verdiği bağlam: " + str(inp["context"]))
    ctx = "\n".join(ctx_parts)
    img_b64 = base64.standard_b64encode(open(jpg, "rb").read()).decode()
    llm = {}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {}
        if use("use_gemini"):
            log("Gemini fotoğrafı yorumluyor…") if store.get("gemini_api_key") and not ollama_ready() else None
            futs["gemini"] = ex.submit(src_gemini, job, img_b64, "image/jpeg", ctx)
        if use("use_claude"):
            futs["claude"] = ex.submit(src_claude, job, img_b64, "image/jpeg", ctx)
        for k, f in futs.items():
            # Bir yapay zekâ kaynağının hatası aracı durdurmasın; diğer kaynaklarla sonuç yine üretilir
            try:
                g, err = f.result()
            except Exception as e:
                g, err = None, f"{SOURCES[k]} çalışmadı ({type(e).__name__})"
            if g:
                llm[k] = g
                status[k] = f"{g.get('_model')} · güven {g.get('confidence')}"
            elif err:
                status[k] = err
    llm_cands = [c for k, g in llm.items() for c in _llm_cands(g, k)]
    clue_cc = dict(countries)
    for g in llm.values():
        cc = (g.get("country_code") or "").lower()[:2]
        if cc:
            clue_cc[cc] = clue_cc.get(cc, 0) + 1

    # Aşama 3: yazılardaki yer adlarını haritada bul (ülke ipucuyla daralt)
    ocr_c = []
    if places:
        cc = max(clue_cc, key=clue_cc.get) if clue_cc else ""
        log(f"Yazılardaki {len(places)} yer adı haritada aranıyor…")
        for q, qcc, w, why in sorted(places, key=lambda p: -p[2]):
            if w < 0.5 and any(c.weight >= 0.85 for c in ocr_c):
                break          # sokak düzeyinde adres bulundu; belirsiz tek kelimelik aramalara gerek yok
            hit = geocode(q, qcc or cc)
            if hit:
                la, lo, disp = hit
                ocr_c.append(Cand(la, lo, "ocr", w, q, f"{why} → {disp[:110]}", qcc or cc))
    status["ocr"] = f"{len(lines)} satır yazı · {len(ocr_c)} yer bulundu" if lines else "yazı yok"

    cands = exif + clip + ocr_c + llm_cands
    if not cands:
        raise ToolError("Hiçbir kaynak konum adayı üretemedi.")
    clusters = fuse(cands, clue_cc)
    best = clusters[0] if not exif else next(c for c in clusters if "exif" in c["sources"])
    conf = confidence(best, clusters, bool(exif))
    if exif:
        radius = 0.05
    elif best.get("precise"):
        radius = max(best["radius"], 2.0)          # tabela adresi: sokak / mahalle düzeyi
    else:
        radius = max(best["radius"], {"yüksek": 15, "orta": 40, "düşük": 250}[conf])
    lat, lon = best["center"]
    # Kesin / sokak düzeyindeki sonuçlarda semt adını da göster
    place = reverse(lat, lon, zoom=16 if (exif or best.get("precise")) else 10)["name"] or best.get("place", "")

    # Ana blok: harita + kaynaklar
    data = {
        "final": {"lat": lat, "lon": lon, "place": place, "confidence": conf, "radius_km": round(radius, 1),
                  "sources": best["sources"]},
        "alternatives": [{"lat": c["center"][0], "lon": c["center"][1], "place": c.get("place", ""), "score": round(c["score"], 3),
                          "sources": c["sources"]} for c in clusters[1:4] if c is not best],
        "candidates": [asdict(c) for c in cands],
        "status": {SOURCES[k]: v for k, v in status.items() if k in SOURCES},
        "max_score": clusters[0]["score"],
    }
    emit(kind="geofusion", title=f"En olası konum: {place or f'{lat:.4f}, {lon:.4f}'}", status="found", lat=lat, lon=lon,
         url=f"https://www.google.com/maps?q={lat},{lon}", data=data,
         detail=f"Güven: {conf} · yaklaşık ±{radius:.0f} km · destekleyen kaynaklar: {', '.join(SOURCES[s] for s in best['sources'])}")

    # Kaynak kaynak ayrıntı
    for k, g in llm.items():
        emit(title=f"{SOURCES[k]}: {g.get('best_guess')}", status="found", tags=SOURCES[k],
             url=f"https://www.google.com/maps?q={g['latitude']},{g['longitude']}",
             detail=f"Güven {g.get('confidence')} · ±{g.get('radius_km', 0):.0f} km · {g.get('_model')}")
        for c in g.get("clues") or []:
            emit(title=c.get("clue", ""), detail=c.get("inference", ""), status="found", tags=f"İpucu · {SOURCES[k]}")
    for c in clip[:5]:
        emit(title=c.label, status="info", tags="GeoCLIP", detail=c.why, url=f"https://www.google.com/maps?q={c.lat},{c.lon}")
    if lines:
        emit(title="Fotoğraftaki yazılar", status="found", tags="Yazı okuma", detail=" | ".join(lines[:30]))
    for n in notes:
        emit(title=n, status="found", tags="Yazı ipucu")
    for c in ocr_c:
        emit(title=f"Yer adı: {c.label}", status="found", tags="Yazı okuma", detail=c.why, url=f"https://www.google.com/maps?q={c.lat},{c.lon}")
    for k, v in status.items():
        if k in ("gemini", "claude") and k not in llm and v:
            emit(kind="warn", title=SOURCES[k], status="found",
                 detail=v + (" — Ayarlar'dan ücretsiz Gemini anahtarı ekleyin (aistudio.google.com/apikey). Ücretsiz katmanda "
                             "gönderilen fotoğraflar Google tarafından ürün geliştirmede kullanılabilir." if v == "Gemini anahtarı yok" else ""))

    # Doğrulama bağlantıları
    links = [("Street View", f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}"),
             ("Mapillary sokak fotoğrafları", f"https://www.mapillary.com/app/?lat={lat}&lng={lon}&z=15"),
             ("Google Earth", f"https://earth.google.com/web/@{lat},{lon},500a,3000d,35y,0h,0t,0r"),
             ("SunCalc (gölge / güneş açısı)", f"https://www.suncalc.org/#/{lat},{lon},15/null/null/null/null"),
             ("Overpass Turbo (harita sorgusu)", f"https://overpass-turbo.eu/?C={lat};{lon};15"),
             ("OpenStreetMap", f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}")]
    if inp.get("url", "").startswith("http"):
        u = quote(inp["url"], safe="")
        links += [("Yandex ters görsel arama", f"https://yandex.com/images/search?rpt=imageview&url={u}"),
                  ("Google Lens", f"https://lens.google.com/uploadbyurl?url={u}")]
    for t, u in links:
        emit(title=t, url=u, status="info", tags="Doğrulama")
