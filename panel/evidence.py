"""Evidence archive: saves a found page as raw HTML + full-page screenshot with SHA-256 hashes and a UTC
timestamp, plus a manifest whose own hash fingerprints the whole capture (chain of custody).

Screenshots use a local headless Chrome / Chromium if one is found (CHROME_PATH overrides);
without it only the HTML and response headers are archived.
"""
import datetime as dt
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import urlparse

import requests

import store
from tools import UA

ROOT = os.path.join(store.DATA_DIR, "evidence")
MAC_CHROME = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"]
KEEP_HEADERS = ("content-type", "server", "date", "last-modified", "etag", "x-powered-by", "content-length")


def chrome_path():
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return next((p for p in MAC_CHROME if os.path.exists(p)), None)


def _public_url(url):
    """Only http(s) to public addresses — never the panel itself or the local network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        for info in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
    except Exception:
        return False
    return True


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _screenshot(url, png, timeout=60):
    exe = chrome_path()
    if not exe:
        return "Chrome / Chromium bulunamadı"
    profile = tempfile.mkdtemp(prefix="osint_chrome_")
    args = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={profile}", "--window-size=1366,2400",
            "--virtual-time-budget=8000", f"--user-agent={UA}", f"--screenshot={png}", url]
    if os.environ.get("CHROME_NO_SANDBOX") == "1" or (hasattr(os, "geteuid") and os.geteuid() == 0):
        args.insert(1, "--no-sandbox")
    try:
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "ekran görüntüsü zaman aşımı"
    finally:
        shutil.rmtree(profile, ignore_errors=True)
    return None if os.path.exists(png) and os.path.getsize(png) > 0 else "ekran görüntüsü alınamadı"


def capture(case_id, item):
    """Archive one case item's URL. Returns the stored evidence row."""
    url = item.get("url") or ""
    if not _public_url(url):
        raise ValueError("Bu bulgunun arşivlenebilir herkese açık bir bağlantısı yok.")
    now = dt.datetime.now(dt.timezone.utc)
    folder = os.path.join(ROOT, str(case_id), f"{item['id']}-{now.strftime('%Y%m%dT%H%M%SZ')}")
    os.makedirs(folder, exist_ok=True)
    rec = {"case_id": case_id, "item_id": item["id"], "url": url, "captured_at": now.isoformat(timespec="seconds"),
           "final_url": "", "http_status": None, "html_path": "", "html_sha256": "", "png_path": "", "png_sha256": "", "error": ""}
    errors = []
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=25, allow_redirects=True)
        rec["final_url"], rec["http_status"] = r.url, r.status_code
        html_path = os.path.join(folder, "page.html")
        with open(html_path, "wb") as f:
            f.write(r.content)
        rec["html_path"], rec["html_sha256"] = html_path, _sha(html_path)
        headers = {k: v for k, v in r.headers.items() if k.lower() in KEEP_HEADERS}
    except Exception as e:
        errors.append(f"HTML: {type(e).__name__}")
        headers = {}
    png = os.path.join(folder, "screenshot.png")
    err = _screenshot(url, png)
    if err:
        errors.append(err)
    else:
        rec["png_path"], rec["png_sha256"] = png, _sha(png)
    manifest = {"tool": "OSINT Panel", "case_id": case_id, "item_id": item["id"], "item_title": item.get("title", ""),
                "url": url, "final_url": rec["final_url"], "http_status": rec["http_status"], "captured_at_utc": rec["captured_at"],
                "response_headers": headers,
                "files": {k: v for k, v in (("page.html", rec["html_sha256"]), ("screenshot.png", rec["png_sha256"])) if v},
                "hash_algorithm": "SHA-256"}
    mpath = os.path.join(folder, "manifest.json")
    with open(mpath, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    rec["manifest_path"], rec["manifest_sha256"] = mpath, _sha(mpath)
    rec["error"] = "; ".join(errors)
    if not rec["html_sha256"] and not rec["png_sha256"]:
        rec["error"] = rec["error"] or "arşivlenemedi"
    rec["id"] = store.add_evidence(rec)
    return rec
