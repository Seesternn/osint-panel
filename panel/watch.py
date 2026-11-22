"""Watchlist: re-checks a case on a schedule and records what changed.

Two sources, chosen to keep false alarms low:
* Saved findings — each saved profile page is fetched directly; title, description and profile photo
  (perceptual hash) are compared with the previous check. "Disappeared" needs a real 404 / 410 or a
  redirect to the site's home page in two consecutive checks; blocks (403 / 429) and network errors
  count as "unknown", not as gone.
* New accounts — the case's search values are re-run through the fast tools. A new URL is reported only
  after it shows up in two consecutive scans *and* its page actually opens.
"""
import html
import io
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests

import runner
import store
from tools import UA

MAX_QUERIES = 6
MAX_SAVED = 150
CONFIRM = 2                 # art arda bu kadar taramada görülen / kaybolan değişiklik raporlanır
_running = set()
_lock = threading.Lock()


def norm(url):
    try:
        u = urlparse(url)
        return (re.sub(r"^(www|m|mobile)\.", "", u.hostname or "") + u.path.rstrip("/")).lower()
    except Exception:
        return ""


def _phash(url):
    try:
        import imagehash
        from PIL import Image
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        if r.status_code != 200 or len(r.content) > 5_000_000:
            return ""
        return str(imagehash.phash(Image.open(io.BytesIO(r.content)).convert("RGB")))
    except Exception:
        return ""


def _hamming(a, b):
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 0


def _meta(text, prop):
    m = re.search(rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)', text, re.I) or \
        re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']', text, re.I)
    return html.unescape(m.group(1)).strip() if m else ""


def probe(url):
    """Open a profile page. state: ok | gone | unknown."""
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=15, allow_redirects=True)
    except requests.RequestException:
        return {"state": "unknown"}
    orig, final = urlparse(url), urlparse(r.url)
    if r.status_code in (404, 410) or (final.path.strip("/") == "" and orig.path.strip("/") != ""):
        return {"state": "gone", "http": r.status_code}
    if r.status_code >= 400:
        return {"state": "unknown", "http": r.status_code}
    t = r.text[:400_000]
    title = _meta(t, "og:title") or (re.search(r"<title[^>]*>(.*?)</title>", t, re.I | re.S) or [None, ""])[1]
    img = _meta(t, "og:image")
    return {"state": "ok", "http": r.status_code, "title": html.unescape(re.sub(r"\s+", " ", title or "")).strip()[:200],
            "desc": (_meta(t, "og:description") or _meta(t, "description"))[:400], "image": urljoin(r.url, img) if img else ""}


def queries_of(case):
    """Distinct search values of the case (what the user searched), newest first."""
    seen, out = set(), []
    for it in reversed(case.get("items", [])):
        q = (it.get("query") or "").strip()
        if q and q not in seen and it.get("tool") != "watch":
            seen.add(q)
            out.append(q)
    return out[:MAX_QUERIES]


def _saved(case):
    out = {}
    for it in case.get("items", []):
        u = it.get("url") or ""
        if u.startswith("http") and it.get("status") in ("found", "maybe", "") and norm(u):
            out.setdefault("s:" + norm(u), {"url": u, "title": it.get("title", "")})
    return dict(list(out.items())[:MAX_SAVED])


def _check_saved(saved, old, changes):
    snap = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        probes = dict(zip(saved, ex.map(lambda k: probe(saved[k]["url"]), saved)))
    for k, info in saved.items():
        p, prev = probes[k], old.get(k, {})
        cur = {"url": info["url"], "title": info["title"], "gone": prev.get("gone", 0), "state": p["state"]}
        if p["state"] == "ok":
            cur.update(ptitle=p["title"], desc=p["desc"], image=p["image"], gone=0)
            cur["hash"] = _phash(p["image"]) if p["image"] else ""
            if prev.get("reported_gone"):
                changes.append({"kind": "Hesap yeniden erişilebilir", "title": info["title"], "url": info["url"], "detail": ""})
            if prev.get("hash") and cur["hash"] and _hamming(prev["hash"], cur["hash"]) > 10:
                changes.append({"kind": "Profil fotoğrafı değişti", "title": info["title"], "url": info["url"],
                                "detail": f"{prev.get('image', '')} → {p['image']}"})
            for field, label in (("desc", "Profil bilgisi değişti"), ("ptitle", "Profil adı değişti")):
                a, b = (prev.get(field) or "").strip(), (cur.get(field) or "").strip()
                if a and b and a != b:
                    changes.append({"kind": label, "title": info["title"], "url": info["url"], "detail": f"“{a[:160]}” → “{b[:160]}”"})
        elif p["state"] == "gone":
            cur.update({k2: prev.get(k2) for k2 in ("ptitle", "desc", "image", "hash")}, gone=prev.get("gone", 0) + 1)
            if cur["gone"] >= CONFIRM and not prev.get("reported_gone"):
                cur["reported_gone"] = True
                changes.append({"kind": "Hesap kayboldu", "title": info["title"], "url": info["url"],
                                "detail": f"HTTP {p.get('http')} — {CONFIRM} kontroldür açılmıyor (silinmiş, gizlenmiş ya da adı değişmiş olabilir)"})
            else:
                cur["reported_gone"] = prev.get("reported_gone", False)
        else:                                   # engellendi / ağ hatası: önceki durumu koru
            cur.update({k2: prev.get(k2) for k2 in ("ptitle", "desc", "image", "hash", "reported_gone")})
        snap[k] = cur
    return snap


def _check_new(case, saved, old, changes, new_items, lang, log):
    tasks = []
    for q in queries_of(case):
        _, plan = runner.plan(q)
        tasks += [(tid, inp, q) for tid, inp in plan if tid not in runner.FAST_SKIP]
    log(f"İzleme: {len(saved)} kayıtlı bulgu, {len(tasks)} araç")
    seen = {}
    for q in {t[2] for t in tasks}:
        res = runner.run_many([(tid, inp) for tid, inp, qq in tasks if qq == q], lang=lang, workers=4, budget_s=600)
        for tid, r in res.items():
            for row in r["rows"]:
                if row.get("status") in ("found", "maybe") and row.get("url", "").startswith("http") and row.get("kind") not in ("warn", "figure"):
                    k = "t:" + norm(row["url"])
                    if k[2:] and ("s:" + k[2:]) not in saved:
                        seen.setdefault(k, {"title": row.get("title", ""), "url": row["url"], "tool": tid, "query": q,
                                            "detail": (row.get("detail") or "")[:300], "image": row.get("image", "")})
    snap = {}
    first = not any(k.startswith("t:") for k in old)
    for k, cur in seen.items():
        prev = old.get(k)
        if first:
            snap[k] = {**cur, "confirmed": True}
        elif not prev:
            snap[k] = {**cur, "count": 1}
        elif prev.get("confirmed"):
            snap[k] = prev
        elif prev.get("count", 1) + 1 >= CONFIRM:
            if probe(cur["url"]).get("state") == "ok":       # sayfa gerçekten açılıyorsa raporla
                changes.append({"kind": "Yeni hesap / bulgu", "title": cur["title"], "url": cur["url"], "detail": f"{cur['query']} · {cur['tool']}"})
                new_items.append({"title": cur["title"], "url": cur["url"], "detail": cur["detail"], "image": cur["image"],
                                  "status": "maybe", "tags": "İzleme", "meta": {"Bulan araç": cur["tool"]}})
            snap[k] = {**cur, "confirmed": True}
        else:
            snap[k] = {**prev, "count": prev.get("count", 1) + 1}
    for k, prev in old.items():                 # bu turda görünmeyen onaylı kayıtları unutma (araçlar dalgalı)
        if k.startswith("t:") and k not in snap and prev.get("confirmed"):
            snap[k] = prev
    return snap, first, len(seen)


def run_case(cid, lang="tr", log=lambda m: None):
    with _lock:
        if cid in _running:
            return {"error": "already running"}
        _running.add(cid)
    store.watch_mark(cid, running=True)
    err = ""
    try:
        case = store.get_case(cid)
        if not case:
            return {"error": "case not found"}
        old = store.get_snapshot(cid)
        changes, new_items = [], []
        saved = _saved(case)
        snap = _check_saved(saved, old, changes)
        tsnap, first, n_tool = _check_new(case, saved, old, changes, new_items, lang, log)
        snap.update(tsnap)
        if not any(k.startswith("s:") for k in old) and first:
            changes.append({"kind": "İzleme başladı", "title": f"{len(saved)} kayıtlı bulgu ve {n_tool} araç bulgusu kaydedildi",
                            "url": "", "detail": ", ".join(queries_of(case))})
        store.put_snapshot(cid, snap)
        if changes:
            store.add_changes(cid, changes)
        if new_items:
            store.add_items(cid, "watch", "İzleme", new_items)
        return {"changes": len(changes), "saved": len(saved), "tool_findings": n_tool}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        return {"error": err}
    finally:
        store.watch_mark(cid, done=True, last_error=err)
        with _lock:
            _running.discard(cid)


def start_scheduler(interval_s=60):
    """Background thread: runs due watches (one at a time)."""
    with store.db() as con:          # yarıda kalmış (sunucu kapanmış) taramaları serbest bırak
        con.execute("UPDATE watches SET running=0")

    def loop():
        while True:
            try:
                for w in store.due_watches():
                    run_case(w["case_id"])
            except Exception:
                pass
            time.sleep(interval_s)
    threading.Thread(target=loop, daemon=True, name="watch-scheduler").start()


def is_running(cid):
    return cid in _running
