"""Sherlock dışındaki OSINT araçlarının kayıtları ve çalıştırıcıları.

Her araç bir giriş formu tanımlar ve iş parçacığında çalışır; bulduğu her şeyi
ortak bir sonuç biçiminde (`emit`) kuyruğa iter. Harici CLI araçları kendi
sanal ortamlarında alt süreç olarak çalıştırılır (bağımlılık çakışması olmasın diye).
"""
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
OSINT_BIN = os.path.join(TOOLS, "osint", "bin")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def which(*cands):
    for c in cands:
        if os.path.isabs(c) and os.path.exists(c):
            return c
        p = shutil.which(c)
        if p:
            return p
    return None


# --------------------------------------------------------------------------
# Ortak yardımcılar
# --------------------------------------------------------------------------
class ToolError(Exception):
    pass


def run_cmd(job, argv, cwd=None, timeout=900, on_line=None, env=None):
    """Alt süreci çalıştırır, her satırı 'log' olarak akıtır, durdurulursa öldürür."""
    exe = argv[0]
    if not exe or not os.path.exists(exe):
        raise ToolError(f"Araç bulunamadı: {argv[0]}")
    job["log"](f"$ {' '.join(os.path.basename(a) if i == 0 else a for i, a in enumerate(argv))}")
    e = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1", TERM="dumb", PYTHONIOENCODING="utf-8")
    if env:
        e.update(env)
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=e, text=True, encoding="utf-8", errors="replace", bufsize=1)
    job["proc"] = proc
    out = []
    start = time.time()
    for raw in proc.stdout:
        line = ANSI.sub("", raw).rstrip("\r\n")
        # ilerleme çubuklarındaki \r parçalarının sonuncusunu al
        line = line.split("\r")[-1].strip()
        out.append(line)
        if line:
            job["log"](line[:400])
            if on_line:
                on_line(line)
        if job["cancel"].is_set():
            proc.kill()
            break
        if time.time() - start > timeout:
            proc.kill()
            job["log"]("Zaman aşımı, süreç durduruldu.")
            break
    proc.wait()
    return "\n".join(out), proc.returncode


def http_ok(url):
    return isinstance(url, str) and url.startswith(("http://", "https://"))


# --------------------------------------------------------------------------
# Kullanıcı adı araçları
# --------------------------------------------------------------------------
def run_maigret(job, inp, emit):
    user = inp["username"].strip()
    out = job["dir"]
    argv = [os.path.join(OSINT_BIN, "maigret"), user, "-J", "simple", "-fo", out,
            "--no-progressbar", "--no-color", "--timeout", str(inp.get("timeout") or 15)]
    if inp.get("scope") == "all":
        argv.append("-a")
    else:
        argv += ["--top-sites", str(inp.get("top") or 500)]
    if inp.get("tags"):
        argv += ["--tags", inp["tags"]]
    run_cmd(job, argv)
    files = glob.glob(os.path.join(out, "*_simple.json"))
    if not files:
        raise ToolError("Maigret rapor üretmedi.")
    data = json.load(open(files[0]))
    for site, v in data.items():
        st = v.get("status") or {}
        if st.get("status") != "Claimed":
            continue
        ids = st.get("ids") or {}
        detail = ids.get("fullname") or ids.get("name") or ids.get("description") or ""
        extra = {k: str(val) for k, val in ids.items() if not k.startswith("_") and k not in ("image",) and val}
        emit(title=site, url=st.get("url") or v.get("url_user"), status="found",
             detail=detail, image=ids.get("image", ""), tags=", ".join(st.get("tags") or []), meta=extra)


_wmn_cache = {}


def load_wmn():
    if "d" in _wmn_cache:
        return _wmn_cache["d"]
    path = os.path.join(TOOLS, "wmn-data.json")
    try:
        r = requests.get("https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json", timeout=15)
        r.raise_for_status()
        open(path, "w").write(r.text)
    except Exception:
        pass
    _wmn_cache["d"] = json.load(open(path))
    return _wmn_cache["d"]


def run_whatsmyname(job, inp, emit):
    user = inp["username"].strip()
    sites = load_wmn()["sites"]
    cat = inp.get("category") or ""
    if cat:
        sites = [s for s in sites if s.get("cat") == cat]
    if not inp.get("nsfw"):
        sites = [s for s in sites if s.get("cat") != "xx NSFW xx"]
    timeout = int(inp.get("timeout") or 10)
    job["log"](f"WhatsMyName: {len(sites)} site kontrol ediliyor…")
    job["progress"](0, len(sites))

    def check(s):
        url = s["uri_check"].replace("{account}", quote(user))
        headers = {"User-Agent": UA, **(s.get("headers") or {})}
        try:
            if s.get("post_body"):
                r = requests.post(url, data=s["post_body"].replace("{account}", user), headers=headers,
                                  timeout=timeout, allow_redirects=True)
            else:
                r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            body = r.text
            if r.status_code == s.get("e_code") and s.get("e_string", "") in body:
                return s, "found"
            return s, "notfound"
        except Exception:
            return s, "error"

    done = 0
    with ThreadPoolExecutor(max_workers=32) as ex:
        futs = [ex.submit(check, s) for s in sites]
        for f in as_completed(futs):
            if job["cancel"].is_set():
                ex.shutdown(cancel_futures=True)
                break
            s, st = f.result()
            done += 1
            job["progress"](done, len(sites))
            if st == "found":
                pretty = (s.get("uri_pretty") or s["uri_check"]).replace("{account}", user)
                emit(title=s["name"], url=pretty, status="found", tags=s.get("cat", ""))
            elif st == "error" and inp.get("show_errors"):
                emit(title=s["name"], url="", status="error", detail="İstek başarısız")


def run_blackbird(job, inp, emit):
    bb = os.path.join(TOOLS, "blackbird")
    target = inp["target"].strip()
    flag = "-e" if "@" in target else "-u"
    before = set(glob.glob(os.path.join(bb, "results", "*", "*.json")))
    seen = set()

    def on_line(line):
        m = re.search(r"\[(.+?)\]\s+(https?://\S+)", line)
        if m and ("✔" in line or "✅" in line) and m.group(1) not in seen:
            seen.add(m.group(1))
            emit(title=m.group(1), url=m.group(2), status="found")

    argv = [os.path.join(bb, ".venv", "bin", "python"), "blackbird.py", flag, target, "--json",
            "--timeout", str(inp.get("timeout") or 15)]
    if not inp.get("nsfw"):
        argv.append("--no-nsfw")
    run_cmd(job, argv, cwd=bb, on_line=on_line)
    after = set(glob.glob(os.path.join(bb, "results", "*", "*.json"))) - before
    for path in after:
        try:
            for item in json.load(open(path)):
                if item.get("status") == "FOUND" and item.get("name") not in seen:
                    seen.add(item["name"])
                    emit(title=item["name"], url=item.get("url"), status="found", tags=item.get("category", ""))
        except Exception:
            pass


def run_social_analyzer(job, inp, emit):
    argv = [os.path.join(OSINT_BIN, "social-analyzer"), "--username", inp["username"].strip(),
            "--output", "json", "--method", "find", "--trim", "--mode", inp.get("mode") or "fast"]
    if inp.get("websites"):
        argv += ["--websites", inp["websites"]]
    else:
        argv += ["--top", str(inp.get("top") or 100)]
    if inp.get("metadata"):
        argv.append("--metadata")
    text, _ = run_cmd(job, argv)
    start = text.find("{")
    if start < 0:
        raise ToolError("Social Analyzer JSON çıktısı vermedi.")
    data, _ = json.JSONDecoder().raw_decode(text[start:])
    for x in data.get("detected", []):
        rate = x.get("rate", "")
        emit(title=x.get("title") or x.get("link"), url=x.get("link"),
             status="found" if x.get("status") == "good" else "maybe",
             detail=f"Güven {rate} · {x.get('status', '')}".strip(" ·"),
             tags=x.get("type", ""), meta={k: str(x[k]) for k in ("country", "language", "rank") if x.get(k)})


def run_socialscan(job, inp, emit):
    queries = [q for q in re.split(r"[\s,;]+", inp["query"]) if q]
    out = os.path.join(job["dir"], "ss.json")
    run_cmd(job, [os.path.join(OSINT_BIN, "socialscan"), *queries, "--json", out, "--show-urls"])
    data = json.load(open(out))
    for q, items in data.items():
        for x in items:
            ok = x.get("success") == "True"
            valid = x.get("valid") == "True"
            avail = x.get("available") == "True"
            if not ok:
                st, det = "error", x.get("message") or "Kontrol edilemedi"
            elif not valid:
                st, det = "notfound", x.get("message") or "Geçersiz"
            elif avail:
                st, det = "notfound", "Kullanılmıyor (alınabilir)"
            else:
                st, det = "found", "Kayıtlı / alınmış"
            emit(title=f"{x.get('platform')} · {q}", url=x.get("link") or "", status=st, detail=det)


# --------------------------------------------------------------------------
# E-posta araçları
# --------------------------------------------------------------------------
def run_holehe(job, inp, emit):
    email = inp["email"].strip()
    run_cmd(job, [os.path.join(OSINT_BIN, "holehe"), email, "--no-color", "--no-clear", "-C"], cwd=job["dir"])
    files = glob.glob(os.path.join(job["dir"], "holehe_*_results.csv"))
    if not files:
        raise ToolError("Holehe sonuç dosyası üretmedi.")
    for row in csv.DictReader(open(files[0])):
        if row.get("rateLimit") == "True":
            st, det = "error", "Hız sınırı"
        elif row.get("exists") == "True":
            st = "found"
            det = " · ".join(x for x in [row.get("emailrecovery") and f"Kurtarma e-postası: {row['emailrecovery']}",
                                         row.get("phoneNumber") and f"Telefon: {row['phoneNumber']}",
                                         row.get("others")] if x)
        else:
            if not inp.get("show_all"):
                continue
            st, det = "notfound", ""
        emit(title=row.get("name"), url=f"https://{row.get('domain')}", status=st, detail=det, tags=row.get("method", ""))


def run_h8mail(job, inp, emit):
    out = os.path.join(job["dir"], "h8.json")
    argv = [os.path.join(OSINT_BIN, "h8mail"), "-t", inp["email"].strip(), "-j", out]
    keys = (inp.get("apikeys") or "").strip()
    if keys:
        argv += ["-k", *[k for k in re.split(r"[\s,]+", keys) if k]]
    run_cmd(job, argv, cwd=job["dir"])
    data = json.load(open(out))
    for t in data.get("targets", []):
        emit(title=t["target"], status="found" if t.get("pwn_num") else "notfound",
             detail=f"{t.get('pwn_num', 0)} sızıntı kaydı")
        for d in t.get("data", []):
            row = d[0] if isinstance(d, list) and d else d
            if isinstance(row, str) and ":" in row:
                src, val = row.split(":", 1)
                emit(title=src, status="info", detail=val)


def run_ghunt(job, inp, emit):
    ghunt = os.path.join(TOOLS, "ghunt", "bin", "ghunt")
    out = os.path.join(job["dir"], "ghunt.json")
    text, _ = run_cmd(job, [ghunt, "email", inp["email"].strip(), "--json", out])
    if not os.path.exists(out):
        if "login" in text.lower() or "creds" in text.lower():
            raise ToolError("GHunt için Google oturumu gerekli. Terminalde bir kez şunu çalıştırın: "
                            "tools/ghunt/bin/ghunt login")
        raise ToolError("GHunt sonuç üretmedi.")
    data = json.load(open(out))
    prof = (data.get("PROFILE_CONTAINER") or {}).get("profile") or {}
    pics = prof.get("profilePhotos") or {}
    photo = next((p.get("url") for p in pics.values() if isinstance(p, dict) and p.get("url")), "")
    emit(title="Google hesabı", status="found", image=photo,
         detail=f"Gaia ID: {prof.get('personId', '?')}",
         meta={k: str(v) for k, v in {"Son güncelleme": (prof.get("sourceIds") or {}).get("PROFILE", {}).get("lastUpdated"),
                                      "Hesap türü": (prof.get("extendedData") or {}).get("dynamiteData", {}).get("entityType")}.items() if v})
    maps = data.get("MAPS_DATA") or {}
    if maps:
        emit(title="Google Maps", status="info", detail=json.dumps(maps, ensure_ascii=False)[:500])
    for k, v in data.items():
        if k not in ("PROFILE_CONTAINER", "MAPS_DATA") and v:
            emit(title=k, status="info", detail=json.dumps(v, ensure_ascii=False)[:500])


# --------------------------------------------------------------------------
# Telefon
# --------------------------------------------------------------------------
def run_phoneinfoga(job, inp, emit):
    exe = which("phoneinfoga", "/opt/homebrew/bin/phoneinfoga")
    text, _ = run_cmd(job, [exe, "scan", "-n", inp["number"].strip()])
    section, sub = "", ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Results for"):
            section = s.replace("Results for", "").strip()
        elif s.startswith("URL:"):
            emit(title=f"{sub or section} araması", url=s[4:].strip(), status="info", tags=section)
        elif s.endswith(":") and ":" not in s[:-1]:
            sub = s[:-1]
        elif section and section != "googlesearch" and ":" in s and "scanner" not in s:
            k, v = s.split(":", 1)
            if v.strip():
                emit(title=k.strip(), status="info", detail=v.strip(), tags=section)


# --------------------------------------------------------------------------
# Platforma özel
# --------------------------------------------------------------------------
INSTA_SCRIPT = r"""
import json, sys, time, instaloader
L = instaloader.Instaloader(quiet=True, download_pictures=False, download_videos=False, save_metadata=False,
                            max_connection_attempts=2)
p = None
for attempt in range(3):          # Instagram anonim isteklere ara sıra 404/429 döndürür
    try:
        p = instaloader.Profile.from_username(L.context, sys.argv[1]); break
    except Exception as e:
        print("Deneme", attempt + 1, "başarısız:", type(e).__name__, flush=True); time.sleep(3)
if p is None:
    sys.exit(1)
def get(attr):
    try: return getattr(p, attr)
    except Exception: return None
print("JSON:" + json.dumps({k: get(a) for k, a in {
  "username": "username", "full_name": "full_name", "biography": "biography",
  "followers": "followers", "followees": "followees", "posts": "mediacount",
  "is_private": "is_private", "is_verified": "is_verified", "is_business": "is_business_account",
  "business_category": "business_category_name", "external_url": "external_url",
  "userid": "userid", "profile_pic": "profile_pic_url"}.items()}, ensure_ascii=False, default=str))
"""


def run_instaloader(job, inp, emit):
    user = inp["username"].strip().lstrip("@")
    text, _ = run_cmd(job, [os.path.join(OSINT_BIN, "python"), "-c", INSTA_SCRIPT, user])
    m = re.search(r"^JSON:(.*)$", text, re.M)
    if not m:
        raise ToolError("Instagram profili okunamadı (gizli, yok ya da Instagram geçici olarak engelledi).")
    d = json.loads(m.group(1))
    yn = lambda v: "–" if v is None else ("evet" if v else "hayır")
    meta = {"Takipçi": d.get("followers"), "Takip": d.get("followees"), "Gönderi": d.get("posts"),
            "Gizli": yn(d.get("is_private")), "Onaylı": yn(d.get("is_verified")),
            "İşletme": d.get("business_category") or yn(d.get("is_business")),
            "Kullanıcı ID": d.get("userid"), "Web sitesi": d.get("external_url")}
    emit(title=d.get("full_name") or d.get("username") or user, url=f"https://www.instagram.com/{d.get('username') or user}/",
         status="found", image=d.get("profile_pic") or "", detail=d.get("biography") or "",
         meta={k: v for k, v in meta.items() if v not in (None, "", "–")})


def run_toutatis(job, inp, emit):
    sid = (inp.get("sessionid") or "").strip()
    if not sid:
        raise ToolError("Toutatis bir Instagram oturum kimliği (sessionid çerezi) ister.")
    text, _ = run_cmd(job, [os.path.join(OSINT_BIN, "toutatis"), "-u", inp["username"].strip().lstrip("@"), "-s", sid])
    meta = {}
    for line in text.splitlines():
        if ":" in line and not line.startswith("$"):
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v and len(k) < 40 and not k.lower().startswith("http"):
                meta[k] = v
    if not meta:
        raise ToolError("Toutatis bilgi döndürmedi; oturum kimliği geçersiz olabilir.")
    emit(title=inp["username"], url=f"https://www.instagram.com/{inp['username'].strip().lstrip('@')}/",
         status="found", detail=meta.get("Full Name", ""), meta=meta)


# --------------------------------------------------------------------------
# Görsel
# --------------------------------------------------------------------------
def _image_to_file(job, inp):
    if inp.get("_file"):
        return inp["_file"]
    url = (inp.get("url") or "").strip()
    if not http_ok(url):
        raise ToolError("Bir görsel URL'si girin ya da dosya yükleyin.")
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    # Uzantı: önce dosyanın ilk baytları, sonra içerik türü (exiftool uzantısız dosyaya yazamıyor)
    head = r.content[:12]
    ext = (".jpg" if head[:3] == b"\xff\xd8\xff" else ".png" if head[:4] == b"\x89PNG" else ".gif" if head[:3] == b"GIF"
           else ".webp" if head[8:12] == b"WEBP" else ".heic" if b"ftypheic" in r.content[:32] or b"ftypmif1" in r.content[:32]
           else ".tif" if head[:4] in (b"II*\x00", b"MM\x00*") else
           {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}.get(
               r.headers.get("content-type", "").split(";")[0].strip(), ".jpg"))
    path = os.path.join(job["dir"], "image" + ext)
    open(path, "wb").write(r.content)
    return path


EXIF_CATS = [
    ("Konum", lambda g, n: "GPS" in g or n.startswith("GPS")),
    ("Kamera", lambda g, n: n in {"Make", "Model", "CameraModelName", "LensModel", "LensMake", "LensInfo", "Lens",
                                  "SerialNumber", "BodySerialNumber", "LensSerialNumber", "InternalSerialNumber",
                                  "CameraSerialNumber", "UniqueCameraModel", "HostComputer"}),
    ("Kişi ve telif", lambda g, n: n in {"Artist", "Copyright", "Creator", "OwnerName", "CameraOwnerName", "Author",
                                         "By-line", "Rights", "XPAuthor", "XPComment", "XPSubject", "XPTitle",
                                         "UserComment", "ImageDescription", "Caption-Abstract", "Keywords", "Title",
                                         "Description", "Subject", "Headline", "Credit", "Source", "Contact"}),
    ("Yazılım ve düzenleme", lambda g, n: n in {"Software", "ProcessingSoftware", "CreatorTool", "HistorySoftwareAgent",
                                                "HistoryAction", "HistoryWhen", "HistoryChanged", "DocumentID",
                                                "InstanceID", "OriginalDocumentID", "DerivedFromDocumentID",
                                                "MetadataDate", "Rating"} or g.startswith("Photoshop") or "XMP-xmpMM" in g),
    ("Tarih ve saat", lambda g, n: "Date" in n or n.startswith(("OffsetTime", "SubSecTime", "TimeZone"))),
    ("Çekim ayarları", lambda g, n: n in {"ExposureTime", "FNumber", "ISO", "FocalLength", "Flash", "ExposureProgram",
                                          "WhiteBalance", "MeteringMode", "FocalLengthIn35mmFormat", "ExposureCompensation",
                                          "ShutterSpeedValue", "ApertureValue", "ShutterSpeed", "Aperture", "LightValue",
                                          "ExposureMode", "SceneCaptureType", "DigitalZoomRatio", "BrightnessValue",
                                          "SceneType", "SensingMethod", "MaxApertureValue", "SubjectDistanceRange",
                                          "FOV", "HyperfocalDistance", "CircleOfConfusion", "ScaleFactor35efl"}),
    ("Görüntü", lambda g, n: n in {"ImageWidth", "ImageHeight", "ImageSize", "Megapixels", "Orientation", "ColorSpace",
                                   "BitsPerSample", "ExifImageWidth", "ExifImageHeight", "XResolution", "YResolution",
                                   "ResolutionUnit", "ColorComponents", "EncodingProcess", "YCbCrSubSampling",
                                   "ProfileDescription", "ColorSpaceData"}),
    ("Dosya", lambda g, n: g.startswith("File")),
    ("Üretici notları", lambda g, n: g.startswith("MakerNotes")),
]
# Yerel dosya yolunu sızdıran ya da anlamsız alanlar gösterilmez.
EXIF_SKIP = {"SourceFile", "FileName", "Directory", "FilePermissions", "FileAccessDate", "FileInodeChangeDate",
             "FileModifyDate", "ExifToolVersion", "Warning"}
EXIF_HIGHLIGHT = {"Make", "Model", "LensModel", "SerialNumber", "BodySerialNumber", "DateTimeOriginal", "CreateDate",
                  "Software", "Artist", "Copyright", "OwnerName", "CameraOwnerName", "Creator", "HostComputer",
                  "ImageDescription", "UserComment", "GPSPosition", "GPSAltitude", "ImageSize"}
WEB_IMAGE = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif", "image/bmp", "image/svg+xml"}


def _exif_cat(group, name):
    for cat, test in EXIF_CATS:
        if test(group, name):
            return cat
    return "Teknik ayrıntılar"


def run_exiftool(job, inp, emit):
    exe = which("exiftool", "/opt/homebrew/bin/exiftool")
    path = _image_to_file(job, inp)
    text, _ = run_cmd(job, [exe, "-j", "-G0:1", "-a", "-u", "-c", "%.6f", path])
    data = json.loads(text[text.find("["):])[0]
    flat = {}
    for k, v in data.items():
        g, _, n = k.rpartition(":")
        if n in EXIF_SKIP or g.startswith("ExifTool") or isinstance(v, dict) or not str(v).strip():
            continue
        flat.setdefault(n, (g, v))
    mime = orig_mime = str(data.get("File:File:MIMEType", ""))
    job["files"] = job.get("files") or {}
    base = f"/api/jobfile/{job['id']}"

    # 1) Fotoğrafın kendisi (tarayıcının gösteremediği HEIC/TIFF vb. JPEG'e çevrilir)
    shown = path
    if mime not in WEB_IMAGE:
        conv = os.path.join(job["dir"], "photo_view.jpg")
        if which("sips") and subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", conv],
                                             capture_output=True).returncode == 0 and os.path.exists(conv):
            shown, mime = conv, "image/jpeg"
    job["files"]["photo"] = (shown, mime or "application/octet-stream")
    pick = lambda *names: next((str(flat[n][1]) for n in names if n in flat and str(flat[n][1]).strip()), "")
    summary = {
        "Kamera": (lambda mk, md: md if md.lower().startswith(mk.lower()) else f"{mk} {md}".strip())(pick("Make"), pick("Model", "CameraModelName")) or "–",
        "Objektif": pick("LensModel", "Lens") or "–",
        "Çekim tarihi": pick("DateTimeOriginal", "CreateDate", "DateCreated") or "–",
        "Boyut": pick("ImageSize") or "–",
        "Dosya": f"{pick('FileType')} · {pick('FileSize')}".strip(" ·") or "–",
        "Yazılım": pick("Software", "CreatorTool", "HistorySoftwareAgent") or "–",
    }
    emit(kind="photo", title="Fotoğraf", status="found", image=f"{base}/photo", meta=summary)

    # 2) Konum: sayısal değerleri ayrıca al
    num, _ = run_cmd(job, [exe, "-j", "-n", "-GPSLatitude", "-GPSLongitude", "-GPSAltitude", path])
    try:
        g = json.loads(num[num.find("["):])[0]
        la, lo = g.get("GPSLatitude"), g.get("GPSLongitude")
        if isinstance(la, (int, float)) and isinstance(lo, (int, float)) and (la or lo):
            alt = g.get("GPSAltitude")
            emit(kind="gps", title="Fotoğrafın çekildiği konum", status="found", lat=la, lon=lo,
                 url=f"https://www.google.com/maps?q={la},{lo}", detail=f"{la:.6f}, {lo:.6f}" +
                 (f" · rakım {alt:.0f} m" if isinstance(alt, (int, float)) else ""))
    except Exception:
        pass

    # 3) Gömülü küçük resim / önizleme (asıl fotoğraf kırpılmış olsa bile orijinali gösterebilir)
    for tag in ("ThumbnailImage", "PreviewImage"):
        out = subprocess.run([exe, "-b", f"-{tag}", path], capture_output=True).stdout
        if len(out) > 500:
            tp = os.path.join(job["dir"], f"{tag}.jpg")
            open(tp, "wb").write(out)
            job["files"][tag] = (tp, "image/jpeg")
            emit(kind="thumb", title="Gömülü küçük resim" if tag == "ThumbnailImage" else "Gömülü önizleme",
                 status="found", image=f"{base}/{tag}",
                 detail="Dosyanın içine gömülü ikinci bir görüntü. Fotoğraf sonradan kırpıldıysa orijinal kadrajı gösterebilir.")

    # 4) Dikkat çeken noktalar
    warns = []
    soft = pick("Software", "CreatorTool", "HistorySoftwareAgent")
    if re.search(r"photoshop|lightroom|gimp|snapseed|picsart|canva|affinity|pixelmator|facetune", soft, re.I):
        warns.append(("Düzenleme izi", f"Fotoğraf bir düzenleme yazılımından geçmiş: {soft}"))
    d1, d2 = pick("DateTimeOriginal"), pick("ModifyDate")
    if d1 and d2 and d1[:16] != d2[:16]:
        warns.append(("Tarih farkı", f"Çekim: {d1} · Son değişiklik: {d2}"))
    serial = pick("SerialNumber", "BodySerialNumber", "InternalSerialNumber", "CameraSerialNumber")
    if serial:
        warns.append(("Cihaz seri numarası", f"{serial} — aynı cihazla çekilmiş başka fotoğrafları eşleştirmeye yarar."))
    owner = pick("OwnerName", "CameraOwnerName", "Artist", "Creator", "XPAuthor", "Copyright")
    if owner:
        warns.append(("Kişi bilgisi", owner))
    if not any(c in ("Kamera", "Konum", "Tarih ve saat") for c in (_exif_cat(g, n) for n, (g, _) in flat.items())):
        warns.append(("EXIF yok", "Kamera, tarih ve konum bilgisi bulunamadı. Sosyal medya siteleri yüklenen fotoğraflardan bu bilgileri genelde siler."))
    for t, d in warns:
        emit(kind="warn", title=t, detail=d, status="found")

    # 5) Tüm alanlar, kategorilere ayrılmış
    order = [c for c, _ in EXIF_CATS] + ["Teknik ayrıntılar"]
    rows = sorted(flat.items(), key=lambda kv: order.index(_exif_cat(kv[1][0], kv[0])))
    for n, (g, v) in rows:
        cat = _exif_cat(g, n)
        emit(kind="field", title=n, detail=str(v)[:400], tags=cat,
             status="found" if n in EXIF_HIGHLIGHT or cat == "Konum" else "info")

    # 6) Meta verisi temizlenmiş kopya
    ext = (pick("FileTypeExtension") or "jpg").lower()
    clean = os.path.join(job["dir"], f"clean.{ext}")
    if subprocess.run([exe, "-all=", "-o", clean, path], capture_output=True).returncode == 0 and os.path.exists(clean):
        job["files"]["clean"] = (clean, orig_mime or "application/octet-stream")
        emit(kind="clean", title="Meta verisi silinmiş kopya", status="info", url=f"{base}/clean",
             detail="Konum, cihaz ve tarih bilgileri temizlenmiş halini indir.")


def run_reverse_image(job, inp, emit):
    url = (inp.get("url") or "").strip()
    if not http_ok(url):
        raise ToolError("Ters görsel arama için herkese açık bir görsel URL'si gerekli.")
    q = quote(url, safe="")
    engines = [
        ("Google Lens", f"https://lens.google.com/uploadbyurl?url={q}"),
        ("Yandex Görseller", f"https://yandex.com/images/search?rpt=imageview&url={q}"),
        ("Bing Görsel Arama", f"https://www.bing.com/images/search?view=detailv2&iss=sbi&q=imgurl:{q}"),
        ("TinEye", f"https://tineye.com/search?url={q}"),
        ("Baidu", f"https://graph.baidu.com/details?isfromtusoupc=1&tn=pc&carousel=0&image={q}"),
        ("Sogou", f"https://pic.sogou.com/ris?query={q}"),
    ]
    for name, link in engines:
        emit(title=name, url=link, status="found", image=url if name == "Google Lens" else "")


# --------------------------------------------------------------------------
# Alan adı
# --------------------------------------------------------------------------
def run_theharvester(job, inp, emit):
    exe = os.path.join(TOOLS, "theHarvester", ".venv", "bin", "theHarvester")
    base = os.path.join(job["dir"], "th")
    sources = inp.get("sources") or "crtsh,duckduckgo,hackertarget,rapiddns,otx,urlscan"
    run_cmd(job, [exe, "-d", inp["domain"].strip(), "-b", sources, "-l", str(inp.get("limit") or 200),
                  "-q", "-f", base], cwd=job["dir"])
    if not os.path.exists(base + ".json"):
        raise ToolError("theHarvester sonuç üretmedi.")
    data = json.load(open(base + ".json"))
    labels = {"emails": "E-posta", "hosts": "Alt alan adı", "ips": "IP", "asns": "ASN",
              "interesting_urls": "URL", "linkedin_people": "LinkedIn kişi", "twitter_people": "Twitter",
              "people": "Kişi", "trello_urls": "Trello"}
    for key, label in labels.items():
        for v in data.get(key) or []:
            v = str(v)
            host = v.split(":")[0]
            url = v if http_ok(v) else (f"https://{host}" if key == "hosts" else "")
            emit(title=v, url=url, status="found" if key in ("emails", "people", "linkedin_people") else "info", tags=label)


def run_whois_dns(job, inp, emit):
    import dns.resolver
    import whois
    domain = re.sub(r"^https?://", "", inp["domain"].strip()).split("/")[0]
    try:
        w = whois.whois(domain)
        job["log"]("WHOIS alındı")
        fields = {"registrar": "Kayıt firması", "creation_date": "Oluşturulma", "expiration_date": "Bitiş",
                  "updated_date": "Güncellenme", "name_servers": "Ad sunucuları", "emails": "E-postalar",
                  "org": "Kuruluş", "name": "Kayıt sahibi", "country": "Ülke", "city": "Şehir", "status": "Durum"}
        for k, label in fields.items():
            v = w.get(k)
            if not v:
                continue
            if isinstance(v, list):
                v = ", ".join(sorted({str(x) for x in v}))
            emit(title=label, status="found" if k in ("emails", "name", "org") else "info", detail=str(v)[:400], tags="WHOIS")
    except Exception as e:
        emit(title="WHOIS", status="error", detail=str(e)[:300], tags="WHOIS")
    res = dns.resolver.Resolver()
    res.lifetime = 6
    for rtype in ("A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA", "CAA"):
        try:
            for r in res.resolve(domain, rtype):
                emit(title=rtype, status="info", detail=r.to_text()[:400], tags="DNS")
        except Exception:
            pass
    try:
        for r in res.resolve("_dmarc." + domain, "TXT"):
            emit(title="DMARC", status="info", detail=r.to_text()[:400], tags="DNS")
    except Exception:
        pass


# --------------------------------------------------------------------------
# Kayıt
# --------------------------------------------------------------------------
def run_nexfil(job, inp, emit):
    exe = os.path.join(TOOLS, "nexfil", ".venv", "bin", "nexfil")
    seen = set()

    def on_line(line):
        m = re.match(r"(https?://\S+)", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            host = re.sub(r"^https?://(www\.)?", "", m.group(1)).split("/")[0]
            emit(title=host, url=m.group(1), status="found")
        p = re.search(r"Progress\s*:\s*(\d+)", line)
        if p:
            job["progress"](int(p.group(1)), 330)

    run_cmd(job, [exe, "-u", inp["username"].strip(), "-t", str(inp.get("timeout") or 10)], on_line=on_line)


# --------------------------------------------------------------------------
# Telefon (ek)
# --------------------------------------------------------------------------
def _parse_phone(number, region="TR"):
    import phonenumbers
    try:
        return phonenumbers.parse(number, None if number.strip().startswith("+") else region)
    except phonenumbers.NumberParseException as e:
        raise ToolError(f"Numara çözümlenemedi: {e}")


def run_phonenumbers(job, inp, emit):
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone, PhoneNumberType as PT
    n = _parse_phone(inp["number"], inp.get("region") or "TR")
    types = {PT.MOBILE: "Mobil", PT.FIXED_LINE: "Sabit hat", PT.FIXED_LINE_OR_MOBILE: "Sabit veya mobil",
             PT.TOLL_FREE: "Ücretsiz (0800)", PT.PREMIUM_RATE: "Ücretli özel hat (0900)", PT.VOIP: "VoIP / internet",
             PT.SHARED_COST: "Paylaşımlı ücret", PT.PERSONAL_NUMBER: "Kişisel numara", PT.PAGER: "Çağrı cihazı",
             PT.UAN: "Kurumsal (444)", PT.VOICEMAIL: "Sesli mesaj", PT.UNKNOWN: "Bilinmiyor"}
    valid = phonenumbers.is_valid_number(n)
    fmt = phonenumbers.PhoneNumberFormat
    emit(title="Geçerlilik", status="found" if valid else "error",
         detail="Geçerli numara" if valid else ("Olası ama geçersiz" if phonenumbers.is_possible_number(n) else "Geçersiz numara"))
    rows = [
        ("Ülke", f"{geocoder.country_name_for_number(n, 'tr') or '?'} ({phonenumbers.region_code_for_number(n) or '?'}) · +{n.country_code}"),
        ("Hat tipi", types.get(phonenumbers.number_type(n), "Bilinmiyor")),
        ("Bölge", geocoder.description_for_number(n, "tr") or "–"),
        ("Operatör (ilk tahsis)", carrier.name_for_number(n, "tr") or carrier.name_for_number(n, "en") or "–"),
        ("Saat dilimi", ", ".join(timezone.time_zones_for_number(n)) or "–"),
        ("Uluslararası biçim", phonenumbers.format_number(n, fmt.INTERNATIONAL)),
        ("Yerel biçim", phonenumbers.format_number(n, fmt.NATIONAL)),
        ("E.164", phonenumbers.format_number(n, fmt.E164)),
        ("RFC3966", phonenumbers.format_number(n, fmt.RFC3966)),
    ]
    for k, v in rows:
        emit(title=k, status="found" if k in ("Hat tipi", "Operatör (ilk tahsis)", "Bölge") else "info", detail=v)
    e164 = phonenumbers.format_number(n, fmt.E164)
    nat = phonenumbers.format_number(n, fmt.NATIONAL)
    emit(title="WhatsApp'ta aç", url=f"https://wa.me/{e164.lstrip('+')}", status="info", detail="Numara WhatsApp'ta kayıtlıysa sohbet ekranı açılır.")
    emit(title="Telegram'da aç", url=f"https://t.me/{e164}", status="info")
    emit(title="Google'da ara", url="https://www.google.com/search?q=" + quote(f'"{e164}" OR "{nat}" OR "{e164.lstrip("+")}"'), status="info")
    emit(title="Truecaller'da ara", url=f"https://www.truecaller.com/search/{(phonenumbers.region_code_for_number(n) or 'tr').lower()}/{n.national_number}", status="info")
    emit(title="Sync.me'de ara", url=f"https://sync.me/search/?number={quote(e164)}", status="info")


def run_ignorant(job, inp, emit):
    n = _parse_phone(inp["number"], inp.get("region") or "TR")
    text, _ = run_cmd(job, [os.path.join(OSINT_BIN, "ignorant"), str(n.country_code), str(n.national_number),
                            "--no-clear", "--no-color"])
    any_line = False
    for line in text.splitlines():
        m = re.match(r"\[([+\-x])\]\s+(\S+)$", line.strip())
        if not m:
            continue
        any_line = True
        mark, site = m.groups()
        st, det = {"+": ("found", "Bu numarayla hesap var"), "-": ("notfound", "Kayıtlı değil"),
                   "x": ("error", "Hız sınırı / kontrol edilemedi")}[mark]
        emit(title=site, url=f"https://{site}", status=st, detail=det)
    if not any_line:
        raise ToolError("Ignorant sonuç döndürmedi.")


# --------------------------------------------------------------------------
# E-posta (ek)
# --------------------------------------------------------------------------
def _mx(domain):
    import dns.resolver
    try:
        return sorted(((r.preference, r.exchange.to_text().rstrip(".")) for r in dns.resolver.resolve(domain, "MX", lifetime=6)))
    except Exception:
        return []


PROVIDERS = [("google.com", "Google (Gmail / Workspace)"), ("googlemail.com", "Google (Gmail / Workspace)"),
             ("outlook.com", "Microsoft (Outlook / 365)"), ("protection.outlook.com", "Microsoft 365"),
             ("yahoodns.net", "Yahoo"), ("icloud.com", "Apple iCloud"), ("protonmail.ch", "Proton Mail"),
             ("yandex", "Yandex"), ("zoho", "Zoho"), ("mail.ru", "Mail.ru"), ("pphosted.com", "Proofpoint"),
             ("mimecast", "Mimecast"), ("yaani", "Yaani Mail")]


def gravatar_lookup(email, session=None):
    """E-postanın Gravatar profili (pasif: yalnızca md5 özetiyle sorgu). Yoksa None."""
    import hashlib
    s = session or requests
    h = hashlib.md5(email.strip().lower().encode()).hexdigest()
    r = s.get(f"https://en.gravatar.com/{h}.json", timeout=10, headers={"User-Agent": UA})
    if r.status_code != 200:
        return None
    e = r.json()["entry"][0]
    return {"email": email, "hash": h, "entry": e,
            "name": (e.get("name") or {}).get("formatted") or e.get("displayName") or ""}


def emit_gravatar(g, emit, tag):
    e, h = g["entry"], g["hash"]
    emit(title="Gravatar profili", url=e.get("profileUrl", ""), status="found", tags=tag,
         image=f"https://gravatar.com/avatar/{h}?s=400",
         detail=" · ".join(x for x in [g["name"], e.get("currentLocation"), e.get("aboutMe")] if x),
         meta={"E-posta": g["email"], "Kullanıcı adı": e.get("preferredUsername", ""), "Ad": g["name"],
               "İş": ", ".join(j.get("title", "") for j in e.get("jobs", [])) if e.get("jobs") else ""})
    for a in e.get("accounts", []) or []:
        emit(title=f"Bağlı hesap: {a.get('name') or a.get('shortname')}", url=a.get("url", ""), status="found",
             detail=a.get("username") or a.get("display") or "", tags=tag)
    for u in e.get("urls", []) or []:
        emit(title=f"Web sitesi: {u.get('title') or ''}".strip(), url=u.get("value", ""), status="found", tags=tag)


def run_email_accounts(job, inp, emit):
    import hashlib
    email = inp["email"].strip().lower()
    if "@" not in email:
        raise ToolError("Geçerli bir e-posta girin.")
    domain = email.split("@", 1)[1]
    s = requests.Session()
    s.headers["User-Agent"] = UA

    # Posta sağlayıcısı (MX kayıtlarından)
    mx = _mx(domain)
    prov = next((p for key, p in PROVIDERS for _, h in mx if key in h), None)
    emit(title="Posta sağlayıcısı", status="info", detail=prov or (mx[0][1] if mx else "MX kaydı yok"), tags="Alan adı")
    if prov and prov.startswith("Google"):
        emit(title="Google hesabı", status="maybe", tags="Google",
             detail="Adres Google altyapısında; Google hesabı olması çok olası. Profil fotoğrafı ve ayrıntılar için GHunt aracını kullanın.")

    # Gravatar: profil, fotoğraf ve bağlı hesaplar
    try:
        g = gravatar_lookup(email, s)
        if g:
            emit_gravatar(g, emit, "Gravatar")
        else:
            emit(title="Gravatar", status="notfound", detail="Gravatar profili yok", tags="Gravatar")
    except Exception as ex:
        emit(title="Gravatar", status="error", detail=type(ex).__name__, tags="Gravatar")

    # Microsoft hesabı (Outlook, Hotmail, Xbox, Office, Skype'ın yerine geçen Teams)
    try:
        r = s.post("https://login.microsoftonline.com/common/GetCredentialType?mkt=en-US", timeout=10,
                   json={"Username": email, "isOtherIdpSupported": True, "checkPhones": False,
                         "isRemoteNGCSupported": True, "isFidoSupported": True, "federationFlags": 0, "isSignup": False})
        res = r.json().get("IfExistsResult")
        if res in (0, 5, 6):
            emit(title="Microsoft hesabı", status="found", tags="Microsoft",
                 detail="Bu adresle bir Microsoft hesabı var (" + ("kişisel hesap" if res in (5, 6) else "iş / okul hesabı") + ").")
        elif res == 1:
            emit(title="Microsoft hesabı", status="notfound", detail="Microsoft hesabı yok", tags="Microsoft")
        else:
            emit(title="Microsoft hesabı", status="error", detail=f"Belirsiz yanıt ({res})", tags="Microsoft")
    except Exception as ex:
        emit(title="Microsoft hesabı", status="error", detail=type(ex).__name__, tags="Microsoft")

    # PGP anahtar sunucusu: adres ile yayımlanmış anahtar ve isim
    try:
        r = s.get(f"https://keys.openpgp.org/vks/v1/by-email/{quote(email)}", timeout=10)
        if r.status_code == 200 and "BEGIN PGP" in r.text:
            emit(title="PGP anahtarı (keys.openpgp.org)", url=f"https://keys.openpgp.org/search?q={quote(email)}",
                 status="found", tags="PGP", detail="Bu adrese ait herkese açık bir şifreleme anahtarı yayımlanmış.")
        else:
            emit(title="PGP anahtarı", status="notfound", detail="Yayımlanmış anahtar yok", tags="PGP")
    except Exception:
        pass

    local = email.split("@")[0]
    emit(title="Kullanıcı adı olarak dene", status="info", tags="İpucu",
         detail=f"'{local}' adını Sherlock, Maigret veya Nexfil ile aratın; insanlar çoğu zaman aynı adı kullanır.")
    emit(title="Google'da ara", url="https://www.google.com/search?q=" + quote(f'"{email}"'), status="info", tags="İpucu")


_disposable = {}


def _disposable_domains():
    if "d" not in _disposable:
        path = os.path.join(TOOLS, "disposable_domains.txt")
        try:
            r = requests.get("https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/disposable_email_blocklist.conf", timeout=10)
            r.raise_for_status()
            open(path, "w").write(r.text)
        except Exception:
            pass
        _disposable["d"] = set(open(path).read().split()) if os.path.exists(path) else set()
    return _disposable["d"]


def run_email_verify(job, inp, emit):
    import secrets
    import smtplib
    import socket
    email = inp["email"].strip()
    ok = re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+", email)
    emit(title="Yazım", status="found" if ok else "error", detail="Biçim geçerli" if ok else "Geçersiz e-posta biçimi")
    if not ok:
        return
    local, domain = email.rsplit("@", 1)
    domain = domain.lower()
    disp = domain in _disposable_domains()
    emit(title="Tek kullanımlık adres", status="error" if disp else "info",
         detail="Evet — geçici / tek kullanımlık posta servisi" if disp else "Hayır")
    role = local.lower() in {"admin", "info", "support", "contact", "sales", "noreply", "no-reply", "webmaster",
                             "postmaster", "hr", "office", "iletisim", "destek", "muhasebe", "satis", "bilgi"}
    emit(title="Kurumsal / rol adresi", status="info", detail="Evet (kişiye değil göreve ait olabilir)" if role else "Hayır")
    mx = _mx(domain)
    if not mx:
        emit(title="MX kaydı", status="error", detail="Alan adının posta sunucusu yok; bu adrese posta gidemez.")
        return
    emit(title="MX kaydı", status="found", detail=", ".join(h for _, h in mx[:4]))
    prov = next((p for key, p in PROVIDERS for _, h in mx if key in h), None)
    if prov:
        emit(title="Sağlayıcı", status="info", detail=prov)

    # SMTP: sunucuya 'bu alıcı var mı' diye sorulur, posta gönderilmez.
    host = mx[0][1]
    job["log"](f"SMTP bağlantısı: {host}:25")
    try:
        srv = smtplib.SMTP(host, 25, timeout=10)
        srv.ehlo("verify.local")
        try:
            if srv.has_extn("starttls"):
                srv.starttls(); srv.ehlo("verify.local")
        except Exception:
            pass
        srv.mail("check@verify.local")
        code, msg = srv.rcpt(email)
        fake_code, _ = srv.rcpt(f"{secrets.token_hex(8)}@{domain}")
        srv.quit()
        msg = msg.decode(errors="replace")[:200]
        if code in (250, 251) and fake_code in (250, 251):
            emit(title="SMTP kontrolü", status="maybe", detail=f"Sunucu her adresi kabul ediyor (catch-all); adresin varlığı kesinleştirilemez. [{code}]")
        elif code in (250, 251):
            emit(title="SMTP kontrolü", status="found", detail=f"Posta kutusu var. [{code}] {msg}")
        elif 500 <= code < 600:
            emit(title="SMTP kontrolü", status="error", detail=f"Posta kutusu yok ya da reddedildi. [{code}] {msg}")
        else:
            emit(title="SMTP kontrolü", status="maybe", detail=f"Geçici yanıt, kesin değil. [{code}] {msg}")
    except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError) as e:
        emit(title="SMTP kontrolü", status="error",
             detail=f"25 numaralı porta bağlanılamadı ({type(e).__name__}). İnternet sağlayıcıların çoğu bu portu engeller; "
                    "bu adım yalnızca 25. portu açık bir ağda (ör. sunucu / VPS) çalışır.")
    except smtplib.SMTPException as e:
        emit(title="SMTP kontrolü", status="error", detail=f"Sunucu yanıtı: {e}"[:300])
    if prov and prov.startswith(("Google", "Microsoft", "Yahoo", "Apple")):
        emit(title="Not", status="info",
             detail=f"{prov} SMTP üzerinden adres doğrulamayı genelde engeller; 'E-posta hesap kontrolü' ve Holehe daha güvenilir sonuç verir.")


# --------------------------------------------------------------------------
# IP konumu
# --------------------------------------------------------------------------
def run_ipgeo(job, inp, emit):
    import ipaddress
    import socket
    raw = inp["target"].strip()
    try:
        ips = [str(ipaddress.ip_address(raw))]
    except ValueError:
        target = re.sub(r"^https?://", "", raw).split("/")[0].split(":")[0]
        try:
            ips = sorted({ai[4][0] for ai in socket.getaddrinfo(target, None)})
            emit(title="Alan adı çözümlendi", status="info", detail=f"{target} → {', '.join(ips)}")
        except socket.gaierror:
            raise ToolError("Geçerli bir IP adresi ya da alan adı girin.")
    fields = "status,message,continent,country,countryCode,regionName,city,district,zip,lat,lon,timezone,isp,org,as,asname,reverse,mobile,proxy,hosting,query"
    for ip in ips[:5]:
        if ipaddress.ip_address(ip).is_private:
            emit(title=ip, status="info", detail="Özel (yerel ağ) IP adresi; konumu yoktur.")
            continue
        try:
            d = requests.get(f"http://ip-api.com/json/{ip}?fields={fields}&lang=tr", timeout=10).json()
        except Exception as e:
            emit(title=ip, status="error", detail=type(e).__name__)
            continue
        if d.get("status") != "success":
            emit(title=ip, status="error", detail=d.get("message", "Sorgu başarısız"))
            continue
        place = ", ".join(x for x in [d.get("district"), d.get("city"), d.get("regionName"), d.get("country")] if x)
        flags = [x for x, on in (("mobil hat", d.get("mobile")), ("proxy / VPN / Tor", d.get("proxy")), ("barındırma / veri merkezi", d.get("hosting"))) if on]
        emit(kind="gps", title=f"{ip} · {place}", status="found", lat=d.get("lat"), lon=d.get("lon"),
             url=f"https://www.google.com/maps?q={d.get('lat')},{d.get('lon')}",
             detail=f"Yaklaşık konum (şehir düzeyinde). {', '.join(flags).capitalize() + '.' if flags else ''}".strip(),
             meta={"Servis sağlayıcı": d.get("isp"), "Kuruluş": d.get("org"), "AS": d.get("as"),
                   "Ters DNS": d.get("reverse") or "–", "Saat dilimi": d.get("timezone"), "Posta kodu": d.get("zip") or "–",
                   "Koordinat": f"{d.get('lat')}, {d.get('lon')}"})
        emit(title=f"{ip} · servis sağlayıcı", status="info", detail=f"{d.get('isp')} · {d.get('as')}")
        emit(title=f"{ip} · AbuseIPDB", url=f"https://www.abuseipdb.com/check/{ip}", status="info", detail="Kötüye kullanım bildirimleri")
        emit(title=f"{ip} · Shodan", url=f"https://www.shodan.io/host/{ip}", status="info", detail="Açık portlar ve hizmetler")


F = lambda name, label, **kw: {"name": name, "label": label, **kw}

REGISTRY = [
    # group, id, title, desc, fields, runner, note
    {"id": "maigret", "group": "Kullanıcı adı", "title": "Maigret", "icon": "user",
     "desc": "3000+ sitede kullanıcı adı arar, profillerden ad, fotoğraf ve bağlantılı hesapları çıkarır.",
     "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı"),
                F("scope", "Kapsam", type="select", options=[["top", "En popüler siteler"], ["all", "Tüm siteler (yavaş)"]]),
                F("top", "Site sayısı", type="number", value=500),
                F("tags", "Etiket filtresi", placeholder="social,coding"),
                F("timeout", "Zaman aşımı (sn)", type="number", value=15)],
     "run": run_maigret},
    {"id": "whatsmyname", "group": "Kullanıcı adı", "title": "WhatsMyName", "icon": "list",
     "desc": "Topluluğun güncel tuttuğu, yanlış sonucu az site listesiyle kullanıcı adı kontrolü.",
     "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı"),
                F("category", "Kategori", type="select", options="wmn_categories"),
                F("timeout", "Zaman aşımı (sn)", type="number", value=10),
                F("nsfw", "NSFW siteleri dahil et", type="checkbox"),
                F("show_errors", "Hata verenleri de göster", type="checkbox")],
     "run": run_whatsmyname},
    {"id": "blackbird", "group": "Kullanıcı adı", "title": "Blackbird", "icon": "bird",
     "desc": "Kullanıcı adı veya e-posta ile 600+ sitede hızlı hesap taraması.",
     "fields": [F("target", "Kullanıcı adı veya e-posta", required=True, placeholder="kullanıcı adı / e-posta"),
                F("timeout", "Zaman aşımı (sn)", type="number", value=15),
                F("nsfw", "NSFW siteleri dahil et", type="checkbox")],
     "run": run_blackbird},
    {"id": "social-analyzer", "group": "Kullanıcı adı", "title": "Social Analyzer", "icon": "gauge",
     "desc": "Profilleri bulur ve her sonuca güven puanı verir; yanlış pozitifleri ayıklamaya yarar.",
     "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı"),
                F("top", "En popüler N site", type="number", value=100),
                F("websites", "Belirli siteler", placeholder="youtube tiktok github"),
                F("mode", "Mod", type="select", options=[["fast", "Hızlı"], ["slow", "Yavaş (daha isabetli)"]]),
                F("metadata", "Meta veri çıkar", type="checkbox")],
     "run": run_social_analyzer},
    {"id": "nexfil", "group": "Kullanıcı adı", "title": "Nexfil", "icon": "zap",
     "desc": "350'den fazla sitede çok hızlı kullanıcı adı taraması.",
     "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı"),
                F("timeout", "Zaman aşımı (sn)", type="number", value=10)],
     "run": run_nexfil},
    {"id": "socialscan", "group": "Kullanıcı adı", "title": "socialscan", "icon": "check",
     "desc": "Kullanıcı adı ya da e-postanın büyük platformlarda alınmış olup olmadığını hızlıca kontrol eder.",
     "fields": [F("query", "Kullanıcı adları / e-postalar", required=True, placeholder="ad1 ad2 mail@ornek.com")],
     "run": run_socialscan},
    {"id": "holehe", "group": "E-posta", "title": "Holehe", "icon": "mail",
     "desc": "E-postanın 120+ sitede kayıtlı olup olmadığını kontrol eder; kişiye bildirim gitmez.",
     "fields": [F("email", "E-posta", required=True, placeholder="ornek@mail.com", type="email"),
                F("show_all", "Kayıtlı olmayanları da göster", type="checkbox")],
     "run": run_holehe},
    {"id": "email-accounts", "group": "E-posta", "title": "E-posta hesap kontrolü", "icon": "link",
     "desc": "E-postaya bağlı Gravatar profilini, Microsoft hesabını, PGP anahtarını ve posta sağlayıcısını bulur.",
     "fields": [F("email", "E-posta", required=True, placeholder="ornek@mail.com", type="email")],
     "run": run_email_accounts},
    {"id": "email-verify", "group": "E-posta", "title": "E-posta doğrulayıcı", "icon": "mailcheck",
     "desc": "Adresin biçimini, alan adının posta sunucusunu, tek kullanımlık olup olmadığını ve posta kutusunun varlığını kontrol eder.",
     "note": "Posta kutusu kontrolü 25. port üzerinden yapılır; çoğu ev internetinde bu port kapalıdır.",
     "fields": [F("email", "E-posta", required=True, placeholder="ornek@mail.com", type="email")],
     "run": run_email_verify},
    {"id": "h8mail", "group": "E-posta", "title": "h8mail", "icon": "shield",
     "desc": "E-postanın bilinen veri sızıntılarında geçip geçmediğine bakar.",
     "note": "API anahtarı olmadan yalnızca ücretsiz kaynaklar sorgulanır. Anahtarlar: hibp=…, snusbase=…, leak-lookup_pub=… gibi.",
     "fields": [F("email", "E-posta", required=True, placeholder="ornek@mail.com", type="email"),
                F("apikeys", "API anahtarları (isteğe bağlı)", placeholder="hibp=xxxx leak-lookup_pub=yyyy")],
     "run": run_h8mail},
    {"id": "ghunt", "group": "E-posta", "title": "GHunt", "icon": "google",
     "desc": "Gmail adresine ait herkese açık Google bilgilerini (profil fotoğrafı, Gaia ID, Maps) gösterir.",
     "note": "Bir kez terminalde `tools/ghunt/bin/ghunt login` ile kendi Google hesabınızla oturum açmanız gerekir.",
     "fields": [F("email", "Gmail adresi", required=True, placeholder="ornek@gmail.com", type="email")],
     "run": run_ghunt},
    {"id": "phoneinfoga", "group": "Telefon", "title": "PhoneInfoga", "icon": "phone",
     "desc": "Numaranın ülkesini ve biçimlerini çıkarır, numarayla ilgili hazır web aramaları üretir.",
     "fields": [F("number", "Telefon numarası", required=True, placeholder="+90 555 123 45 67")],
     "run": run_phoneinfoga},
    {"id": "phonenumbers", "group": "Telefon", "title": "Numara çözümleyici", "icon": "hash",
     "desc": "Numaranın geçerliliğini, hat tipini (mobil / sabit / VoIP), bölgesini, ilk tahsis edildiği operatörü ve saat dilimini çevrimdışı çıkarır.",
     "fields": [F("number", "Telefon numarası", required=True, placeholder="+90 555 123 45 67 veya 0555…"),
                F("region", "Ülke kodu (+ olmadan girilirse)", value="TR")],
     "run": run_phonenumbers},
    {"id": "ignorant", "group": "Telefon", "title": "Ignorant", "icon": "phonecheck",
     "desc": "Telefon numarasının Instagram, Snapchat ve Amazon'da kayıtlı olup olmadığını kontrol eder.",
     "fields": [F("number", "Telefon numarası", required=True, placeholder="+90 555 123 45 67"),
                F("region", "Ülke kodu (+ olmadan girilirse)", value="TR")],
     "run": run_ignorant},
    {"id": "instaloader", "group": "Platform", "title": "Instaloader", "icon": "camera",
     "desc": "Herkese açık Instagram profilinin adını, biyografisini, sayılarını ve fotoğrafını getirir.",
     "fields": [F("username", "Instagram kullanıcı adı", required=True, placeholder="kullanıcı adı")],
     "run": run_instaloader},
    {"id": "toutatis", "group": "Platform", "title": "Toutatis", "icon": "at",
     "desc": "Instagram profilinin herkese açık ek bilgilerini (kısmi e-posta/telefon vb.) çeker.",
     "note": "Kendi Instagram hesabınızın sessionid çerezini ister; bu değer yalnızca bu bilgisayarda kullanılır.",
     "fields": [F("username", "Instagram kullanıcı adı", required=True, placeholder="kullanıcı adı"),
                F("sessionid", "sessionid çerezi", type="password", required=True)],
     "run": run_toutatis},
    {"id": "exiftool", "group": "Görsel", "title": "ExifTool", "icon": "image",
     "desc": "Fotoğraftaki gizli bilgileri (konum, cihaz, tarih, yazılım) okur.",
     "fields": [F("url", "Görsel URL'si", placeholder="https://…/foto.jpg"),
                F("file", "veya dosya yükle", type="file")],
     "run": run_exiftool},
    {"id": "reverse-image", "group": "Görsel", "title": "Ters görsel arama", "icon": "search",
     "desc": "Bir görseli Google Lens, Yandex, Bing, TinEye ve diğer motorlarda aratır.",
     "fields": [F("url", "Görsel URL'si", required=True, placeholder="https://…/profil.jpg")],
     "run": run_reverse_image},
    {"id": "theharvester", "group": "Alan adı", "title": "theHarvester", "icon": "globe",
     "desc": "Alan adına ait e-postaları, alt alan adlarını, IP'leri ve kişileri açık kaynaklardan toplar.",
     "fields": [F("domain", "Alan adı", required=True, placeholder="ornek.com"),
                F("sources", "Kaynaklar", value="crtsh,duckduckgo,hackertarget,rapiddns,otx,urlscan"),
                F("limit", "Kaynak başına sonuç", type="number", value=200)],
     "run": run_theharvester},
    {"id": "whois", "group": "Alan adı", "title": "WHOIS / DNS", "icon": "server",
     "desc": "Alan adının kime kayıtlı olduğunu ve DNS kayıtlarını (A, MX, TXT, NS…) gösterir.",
     "fields": [F("domain", "Alan adı", required=True, placeholder="ornek.com")],
     "run": run_whois_dns},
    {"id": "ipgeo", "group": "Alan adı", "title": "IP konum sorgusu", "icon": "pin",
     "desc": "IP adresinin (ya da alan adının) yaklaşık konumunu, servis sağlayıcısını ve VPN / veri merkezi olup olmadığını gösterir.",
     "fields": [F("target", "IP adresi veya alan adı", required=True, placeholder="8.8.8.8 veya ornek.com")],
     "run": run_ipgeo},
]
BY_ID = {t["id"]: t for t in REGISTRY}

# Panelde "Bu araç ne işe yarar?" kutusunda ve Rehber sayfasında gösterilir.
ABOUT = {
    "sherlock": {
        "what": "Bir kullanıcı adının 400'den fazla sosyal ağda var olup olmadığını kontrol eder. Bulunan her profili arka planda açıp gerçekten erişilebilir olduğunu doğrular.",
        "when": "Bir kişinin hangi platformlarda aynı kullanıcı adını kullandığını görmek istediğinde ilk başvurulacak araç.",
        "input": "Bir ya da birden fazla kullanıcı adı (.txt dosyasından da yüklenebilir).",
        "output": "Profil bağlantıları, sayfa başlığı, açıklaması ve profil fotoğrafı.",
        "tips": "Genel adlar (ör. emre) başka kişilerin hesaplarını da getirir; yan paneldeki fotoğraftan kontrol et.",
    },
    "maigret": {
        "what": "Sherlock'un geliştirilmiş hali. 3000'den fazla siteyi tarar ve bulduğu profillerin içinden ad, fotoğraf, konum, şirket, takipçi sayısı gibi bilgileri çıkarır.",
        "when": "Sherlock'tan daha geniş kapsam ve profil ayrıntısı istediğinde. Kişiyi doğrulamak için en çok bilgi veren araç.",
        "input": "Tek bir kullanıcı adı.",
        "output": "Profil bağlantıları + profilden çıkarılan ad, fotoğraf, konum vb. bilgiler.",
        "tips": "Site sayısını 500'de tutmak hızlıdır; 'Tüm siteler' birkaç dakika sürebilir.",
    },
    "whatsmyname": {
        "what": "OSINT topluluğunun düzenli güncellediği WhatsMyName site listesiyle kullanıcı adı arar. Her site için 'var' ve 'yok' durumunu ayrı ayrı tanımladığından yanlış sonucu azdır.",
        "when": "Sherlock veya Maigret sonuçlarını çapraz kontrol etmek, ya da belirli bir kategoride (oyun, kodlama…) aramak için.",
        "input": "Kullanıcı adı; isteğe bağlı kategori.",
        "output": "Profil bağlantıları ve site kategorisi.",
        "tips": "Kategori seçmek taramayı hızlandırır.",
    },
    "blackbird": {
        "what": "600'den fazla sitede kullanıcı adı ya da e-posta ile hızlı hesap taraması yapar.",
        "when": "Elinde kullanıcı adı yerine e-posta olduğunda da çalışan hızlı bir tarama gerektiğinde.",
        "input": "Kullanıcı adı veya e-posta adresi.",
        "output": "Hesabın bulunduğu siteler ve bağlantıları.",
        "tips": "Bazı bağlantılar sitenin API adresi olabilir; profili görmek için site adına göre arayabilirsin.",
    },
    "social-analyzer": {
        "what": "Profilleri bulur ve her birine 0–100 arası güven puanı verir. Sayfa başlığı, dil ve ülke bilgisini de çıkarır.",
        "when": "Diğer araçların bulduğu sonuçlardan hangilerinin gerçekten o kişiye ait olduğunu ayırt etmek istediğinde.",
        "input": "Kullanıcı adı; isteğe bağlı belirli siteler.",
        "output": "Güven puanlı profil listesi.",
        "tips": "'Yavaş' mod daha isabetlidir ama uzun sürer.",
    },
    "socialscan": {
        "what": "Bir kullanıcı adı ya da e-postanın Instagram, GitHub, Reddit, Twitter gibi büyük platformlarda alınmış (kayıtlı) olup olmadığını platformların kendi kayıt kontrolüyle doğrular.",
        "when": "Birkaç ad veya e-postayı büyük platformlarda çok hızlı ve isabetli kontrol etmek istediğinde.",
        "input": "Bir veya birden fazla kullanıcı adı / e-posta (boşlukla ayır).",
        "output": "Her platform için alınmış / alınabilir / kontrol edilemedi.",
        "tips": "Kontrol edilen platform sayısı azdır (10 civarı) ama sonuçlar güvenilirdir.",
    },
    "holehe": {
        "what": "Bir e-posta adresinin 120'den fazla sitede (Twitter, Instagram, Spotify, Adobe…) kayıtlı olup olmadığını sitelerin 'şifremi unuttum' ve kayıt akışlarıyla kontrol eder. Kişiye bildirim gitmez.",
        "when": "Elinde bir e-posta adresi varsa ve hangi hizmetlerde hesap açıldığını öğrenmek istediğinde.",
        "input": "E-posta adresi.",
        "output": "Kayıtlı olduğu siteler; bazen kurtarma e-postası veya telefonun bir kısmı.",
        "tips": "Çok sayıda 'hız sınırı' sonucu normaldir; bir süre sonra tekrar dene.",
    },
    "h8mail": {
        "what": "Bir e-posta adresinin bilinen veri sızıntılarında (breach) geçip geçmediğini arar.",
        "when": "Bir e-postanın daha önce sızdırılıp sızdırılmadığını, hangi sızıntılarda yer aldığını görmek için.",
        "input": "E-posta adresi; isteğe bağlı HIBP, Snusbase gibi servislerin API anahtarları.",
        "output": "Sızıntı sayısı ve kaynakları.",
        "tips": "API anahtarı olmadan sonuç çok sınırlıdır.",
    },
    "ghunt": {
        "what": "Bir Gmail adresine bağlı herkese açık Google bilgilerini getirir: profil fotoğrafı, Gaia ID, son güncelleme, açık Google Maps yorumları.",
        "when": "Gmail adresi bilinen birinin Google hesabı hakkında herkese açık bilgi gerektiğinde.",
        "input": "Gmail adresi.",
        "output": "Google profil bilgileri ve fotoğraf.",
        "tips": "Önce terminalde 'tools/ghunt/bin/ghunt login' ile kendi Google hesabınla bir kez oturum aç.",
    },
    "phoneinfoga": {
        "what": "Telefon numarasını çözümler: ülke, numaranın farklı yazım biçimleri. Ayrıca numarayı sosyal medyada, tek kullanımlık SMS sitelerinde ve genel webde aramak için hazır Google sorguları üretir.",
        "when": "Bir telefon numarası hakkında ilk bilgi ve web'de nerede geçtiğini aramak için.",
        "input": "Uluslararası biçimde numara (+90…).",
        "output": "Ülke, E164 / yerel biçim ve tıklanabilir arama bağlantıları.",
        "tips": "Arama bağlantıları Google'da açılır; sonuçları kendin incelemelisin.",
    },
    "instaloader": {
        "what": "Herkese açık bir Instagram profilinin adını, biyografisini, takipçi / takip / gönderi sayılarını, profil fotoğrafını ve web sitesini getirir.",
        "when": "Bir Instagram hesabının temel bilgilerini oturum açmadan görmek için.",
        "input": "Instagram kullanıcı adı.",
        "output": "Profil bilgileri ve tam boy profil fotoğrafı.",
        "tips": "Instagram anonim istekleri sık sınırlar; hata alırsan birkaç dakika sonra tekrar dene.",
    },
    "toutatis": {
        "what": "Instagram profilinden herkese açık ek bilgileri çeker: kullanıcı ID'si, kısmi (maskelenmiş) e-posta / telefon, hesap türü.",
        "when": "Instaloader'ın gösterdiğinden daha fazla Instagram bilgisi gerektiğinde.",
        "input": "Instagram kullanıcı adı ve kendi hesabının sessionid çerezi.",
        "output": "Profilin ek bilgileri.",
        "tips": "sessionid çerezini tarayıcıda instagram.com açıkken geliştirici araçlarından alabilirsin; kimseyle paylaşma.",
    },
    "exiftool": {
        "what": "Fotoğrafların içine gömülü gizli bilgileri (EXIF, XMP, IPTC) okur: çekildiği konum, cihaz markası / modeli / seri numarası, tarih, düzenleme yazılımı, sahibi. Fotoğrafı, konumunu haritada ve dosyaya gömülü küçük resmi gösterir.",
        "when": "Bir fotoğrafın nerede, ne zaman, hangi cihazla çekildiğini ve düzenlenip düzenlenmediğini öğrenmek için.",
        "input": "Görsel URL'si ya da dosya (sürükleyip bırakabilirsin). JPEG, PNG, HEIC, TIFF, RAW desteklenir.",
        "output": "Özet kart, harita, dikkat çeken noktalar, kategorilere ayrılmış tüm alanlar ve meta verisi silinmiş bir kopya.",
        "tips": "Sosyal medya siteleri yüklenen fotoğraflardaki EXIF'i genelde siler; orijinal dosyalarda (e-posta eki, bulut paylaşımı) daha çok bilgi bulunur.",
    },
    "nexfil": {
        "what": "350'den fazla sitede kullanıcı adını çok hızlı tarar.",
        "when": "Hızlı bir ilk tarama ya da diğer kullanıcı adı araçlarının sonuçlarını çapraz kontrol etmek için.",
        "input": "Kullanıcı adı.",
        "output": "Profil bağlantıları.",
        "tips": "Sonuçlarda yanlış pozitif olabilir; şüpheli olanları Sherlock'un doğrulamasıyla karşılaştır.",
    },
    "email-accounts": {
        "what": "Bir e-postaya bağlı herkese açık hesapları bulur: Gravatar profili (fotoğraf, ad, bağlı sosyal hesaplar), Microsoft hesabı, PGP anahtarı ve posta sağlayıcısı.",
        "when": "Bir e-postanın arkasındaki kişiye ait fotoğraf, ad ve diğer hesaplara ulaşmak için. Holehe'yi tamamlar.",
        "input": "E-posta adresi.",
        "output": "Gravatar fotoğrafı ve bağlı hesaplar, Microsoft hesabı var/yok, PGP anahtarı, sağlayıcı.",
        "tips": "Gmail adreslerinin Google profili için GHunt'ı kullan. Skype Mayıs 2025'te kapandığı için kontrol edilmiyor.",
    },
    "email-verify": {
        "what": "Bir e-posta adresinin gerçekten var olup olmadığını kontrol eder: biçim, alan adının posta sunucusu (MX), tek kullanımlık posta servisi olup olmadığı ve sunucuya alıcının var olup olmadığını sorma (posta gönderilmez).",
        "when": "Elindeki e-postanın geçerli ve kullanılıyor olup olmadığından emin olmak için.",
        "input": "E-posta adresi.",
        "output": "Her kontrol için geçerli / geçersiz / belirsiz sonucu.",
        "tips": "Posta kutusu kontrolü 25. port ister; ev internetinde genelde kapalıdır. Gmail / Outlook bu kontrolü engeller.",
    },
    "phonenumbers": {
        "what": "Google'ın libphonenumber kütüphanesiyle numarayı çözümler: geçerlilik, mobil / sabit / VoIP, bölge, ilk tahsis edildiği operatör, saat dilimi ve tüm yazım biçimleri. Ayrıca WhatsApp, Telegram, Truecaller ve Google'da arama bağlantıları üretir.",
        "when": "Bir telefon numarası hakkında hızlı ve internete bağlanmadan ilk bilgiyi almak için.",
        "input": "Telefon numarası (+90… ya da 0555… ve ülke kodu).",
        "output": "Numara bilgileri ve arama bağlantıları.",
        "tips": "Operatör bilgisi numaranın ilk tahsis edildiği operatördür; numara taşındıysa güncel olmayabilir.",
    },
    "ignorant": {
        "what": "Telefon numarasının Instagram, Snapchat ve Amazon'da bir hesaba kayıtlı olup olmadığını kontrol eder. Telefon için Holehe'nin karşılığıdır.",
        "when": "Bir numaranın hangi platformlarda hesap açmak için kullanıldığını öğrenmek için.",
        "input": "Telefon numarası.",
        "output": "Her site için kayıtlı / değil / kontrol edilemedi.",
        "tips": "Snapchat sık sık hız sınırı verir.",
    },
    "ipgeo": {
        "what": "Bir IP adresinin (ya da alan adının) yaklaşık konumunu, servis sağlayıcısını, AS numarasını, ters DNS'ini ve mobil / VPN / veri merkezi olup olmadığını gösterir.",
        "when": "E-posta başlıklarında, sunucu kayıtlarında ya da WHOIS sonucunda karşına çıkan bir IP'nin nereye ait olduğunu öğrenmek için.",
        "input": "IP adresi veya alan adı.",
        "output": "Ülke / şehir, harita, servis sağlayıcı, AbuseIPDB ve Shodan bağlantıları.",
        "tips": "IP konumu şehir düzeyinde yaklaşık bir tahmindir, ev adresi vermez. Sorgu ip-api.com üzerinden yapılır.",
    },
    "reverse-image": {
        "what": "Bir görseli Google Lens, Yandex, Bing, TinEye, Baidu ve Sogou'da aratacak bağlantıları tek seferde hazırlar.",
        "when": "Bir profil fotoğrafının internette başka nerelerde kullanıldığını bulmak; sahte (çalıntı fotoğraflı) hesapları tespit etmek için.",
        "input": "Herkese açık görsel URL'si (ör. Maigret'in bulduğu profil fotoğrafı).",
        "output": "Her arama motoru için tıklanabilir arama bağlantısı.",
        "tips": "Yüz aramada genelde en iyi sonucu Yandex verir.",
    },
    "theharvester": {
        "what": "Bir alan adına (şirket, kurum) ait e-posta adreslerini, alt alan adlarını, IP adreslerini ve çalışan adlarını arama motorları ve sertifika kayıtları gibi açık kaynaklardan toplar.",
        "when": "Bir kurumun internetteki ayak izini çıkarmak ya da çalışanların e-posta biçimini öğrenmek için.",
        "input": "Alan adı (ornek.com) ve kaynak listesi.",
        "output": "E-postalar, alt alan adları, IP'ler, kişiler.",
        "tips": "Bazı kaynaklar API anahtarı ister; varsayılan kaynaklar anahtarsız çalışır.",
    },
    "whois": {
        "what": "Bir alan adının kime, ne zaman, hangi firma üzerinden kayıtlı olduğunu (WHOIS) ve DNS kayıtlarını (IP, e-posta sunucusu, TXT doğrulamaları) gösterir.",
        "when": "Bir kişinin profillerinde geçen kişisel web sitesinin sahibini ve barındırıldığı yeri öğrenmek için.",
        "input": "Alan adı.",
        "output": "Kayıt firması, tarihler, ad sunucuları, varsa sahibin adı / e-postası ve DNS kayıtları.",
        "tips": "Çoğu alan adında sahip bilgisi gizlilik hizmetiyle saklanır.",
    },
}


def public_registry(lang="tr"):
    about, titles = ABOUT, {}
    if lang == "en":
        from about_en import ABOUT_EN, TITLES_EN
        about, titles = {**ABOUT, **ABOUT_EN}, TITLES_EN
    cats = sorted({s.get("cat", "") for s in load_wmn()["sites"] if s.get("cat")})
    out = [{"id": "sherlock", "group": "Kullanıcı adı", "title": "Sherlock", "icon": "fingerprint",
            "desc": "400+ sosyal ağda kullanıcı adı arar.", "fields": [], "about": about["sherlock"]}]
    for t in REGISTRY:
        fields = []
        for f in t["fields"]:
            f = dict(f)
            if f.get("options") == "wmn_categories":
                f["options"] = [["", "Tümü"]] + [[c, c] for c in cats]
            fields.append(f)
        entry = {k: v for k, v in t.items() if not callable(v) and k not in ("en",)} | {"fields": fields, "about": about.get(t["id"], {})}
        if t["id"] in titles:
            entry["title"] = titles[t["id"]]
        en = t.get("en") if lang == "en" else None
        if en:   # eklentilerin İngilizce katmanı / plugin English overlay
            entry.update({k: en[k] for k in ("title", "desc", "note") if en.get(k)})
            if en.get("about"):
                entry["about"] = en["about"]
            fl = en.get("fields") or {}
            entry["fields"] = [{**f, **fl.get(f["name"], {})} for f in fields]
        out.append(entry)
    return out


def new_workdir():
    return tempfile.mkdtemp(prefix="osintpanel_")
