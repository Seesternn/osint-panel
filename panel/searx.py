"""Yerel SearXNG yöneticisi: ilk kullanımda başlatır, sonra yeniden kullanır.

SearXNG, Google / Bing / DuckDuckGo / Startpage gibi motorların sonuçlarını birleştiren açık kaynak bir arama motorudur.
Yalnızca 127.0.0.1:8888'de dinler; dışarıdan erişilemez.
"""
import os
import subprocess
import threading
import time

import requests

from tools import TOOLS, ToolError

BASE = "http://127.0.0.1:8888"
DIR = os.path.join(TOOLS, "searxng")
_lock = threading.Lock()
_proc = [None]
_last_query = [0.0]
HDR = {"X-Real-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1", "User-Agent": "osint-panel-local/1.0"}


def installed():
    return os.path.exists(os.path.join(DIR, ".venv", "bin", "python")) and os.path.exists(os.path.join(DIR, "settings.yml"))


def running():
    try:
        return requests.get(f"{BASE}/healthz", timeout=2, headers=HDR).status_code == 200
    except Exception:
        return False


def ensure_running(log=lambda m: None):
    if running():
        return True
    if not installed():
        raise ToolError("SearXNG kurulu değil (tools/searxng).")
    with _lock:
        if running():
            return True
        log("SearXNG başlatılıyor…")
        env = dict(os.environ, SEARXNG_SETTINGS_PATH=os.path.join(DIR, "settings.yml"))
        logf = open(os.path.join(DIR, "searxng.log"), "a")
        _proc[0] = subprocess.Popen([os.path.join(DIR, ".venv", "bin", "python"), "-m", "searx.webapp"],
                                    cwd=os.path.join(DIR, "src"), env=env, stdout=logf, stderr=logf, start_new_session=True)
        for _ in range(60):
            time.sleep(0.5)
            if running():
                return True
        raise ToolError("SearXNG başlatılamadı (tools/searxng/searxng.log dosyasına bakın).")


def search(q, lang="tr", pageno=1, log=lambda m: None, min_gap=1.2):
    """Bir sorgu çalıştırır; [{title, url, content, engines}] döndürür. Arama motorları engellemesin diye sorgular arası bekler."""
    ensure_running(log)
    with _lock:
        wait = min_gap - (time.time() - _last_query[0])
        if wait > 0:
            time.sleep(wait)
        _last_query[0] = time.time()
    r = requests.get(f"{BASE}/search", params={"q": q, "format": "json", "language": lang, "pageno": pageno, "safesearch": 0},
                     headers=HDR, timeout=30)
    if r.status_code != 200:
        raise ToolError(f"SearXNG HTTP {r.status_code}")
    d = r.json()
    out = []
    for x in d.get("results", []):
        out.append({"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("content", ""),
                    "engines": x.get("engines") or [x.get("engine", "")], "date": x.get("publishedDate") or ""})
    return out, d.get("unresponsive_engines") or []
