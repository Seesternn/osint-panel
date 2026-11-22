"""Sherlock Panel — Sherlock OSINT aracı için basit bir web arayüzü.

Çalıştırma:  .venv/bin/python panel/app.py   →  http://127.0.0.1:5050
"""
import html
import io
import json
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
import os
import queue
import threading
import time
import uuid

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request, send_file

from sherlock_project import __version__ as SHERLOCK_VERSION
from sherlock_project.notify import QueryNotify
from sherlock_project.result import QueryStatus
from sherlock_project.sherlock import sherlock, multiple_usernames, check_for_parameter
from sherlock_project.sites import SitesInformation
import sherlock_project
import tools
import tools2
import store

tools.REGISTRY.extend(tools2.REGISTRY2)
tools.BY_ID.update({t['id']: t for t in tools2.REGISTRY2})
tools.ABOUT.update(tools2.ABOUT2)

app = Flask(__name__)
LOCAL_JSON = os.path.join(os.path.dirname(sherlock_project.__file__), "resources", "data.json")

_sites_cache: dict = {}
_jobs: dict = {}
_verify_pool = ThreadPoolExecutor(max_workers=16)


def load_sites(source: str, custom_json: str, ignore_exclusions: bool, keep: list):
    """README'deki --local / --json / --ignore-exclusions seçeneklerine karşılık gelir."""
    key = (source, custom_json, ignore_exclusions, tuple(sorted(keep)))
    if key in _sites_cache:
        return _sites_cache[key]
    if source == "local":
        sites = SitesInformation(LOCAL_JSON, honor_exclusions=False)
    elif source == "custom" and custom_json:
        path = custom_json
        if custom_json.isnumeric():  # PR numarası
            import requests
            pr = requests.get(f"https://api.github.com/repos/sherlock-project/sherlock/pulls/{custom_json}", timeout=10).json()
            if "head" not in pr:
                raise ValueError(f"PR #{custom_json} bulunamadı")
            path = f"https://raw.githubusercontent.com/sherlock-project/sherlock/{pr['head']['sha']}/sherlock_project/resources/data.json"
        sites = SitesInformation(path, honor_exclusions=not ignore_exclusions, do_not_exclude=keep)
    else:
        try:
            sites = SitesInformation(honor_exclusions=not ignore_exclusions, do_not_exclude=keep)
        except Exception:
            sites = SitesInformation(LOCAL_JSON, honor_exclusions=False)  # çevrimdışı yedek
    _sites_cache[key] = sites
    return sites


class PanelNotify(QueryNotify):
    """Sherlock sonuçlarını terminal yerine kuyruğa iten bildirici."""

    def __init__(self, job):
        super().__init__()
        self.job = job

    def update(self, result):
        if self.job["cancel"].is_set():
            raise KeyboardInterrupt("cancelled")
        row = {
            "username": result.username,
            "site": result.site_name,
            "url": result.site_url_user,
            "status": result.status.value,
            "time_ms": round(result.query_time * 1000) if result.query_time else None,
            "context": result.context,
            "home": self.job["homes"].get(result.site_name, ""),
            "nsfw": self.job["nsfw_map"].get(result.site_name, False),
            "i": len(self.job["results"]),
        }
        self.job["results"].append(row)
        self.job["queue"].put({"type": "result", "data": row})
        if result.status == QueryStatus.CLAIMED:
            self.job["verify"].append(_verify_pool.submit(verify_row, self.job, row))


def run_job(job, usernames, site_data, opts):
    q = job["queue"]
    try:
        for u in usernames:
            if job["cancel"].is_set():
                break
            q.put({"type": "username", "data": u})
            sherlock(u, site_data, PanelNotify(job), proxy=opts["proxy"] or None,
                     timeout=opts["timeout"], dump_response=False)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        q.put({"type": "error", "data": str(e)})
    finally:
        # Doğrulamalar bitene kadar akışı açık tut (durdurulduysa bekleme).
        pending = [f for f in job["verify"] if not f.done()]
        if pending and not job["cancel"].is_set():
            q.put({"type": "verifying", "data": len(pending)})
            for f in job["verify"]:
                if job["cancel"].is_set():
                    break
                try:
                    f.result(timeout=15)
                except Exception:
                    pass
        job["done"] = True
        q.put({"type": "done", "data": {"cancelled": job["cancel"].is_set(),
                                         "elapsed": round(time.time() - job["started"], 1)}})


@app.get("/")
def index():
    return render_template("index.html", version=SHERLOCK_VERSION)


@app.get("/api/sites")
def api_sites():
    try:
        sites = load_sites(request.args.get("source", "remote"), request.args.get("json", ""),
                           request.args.get("ignore_exclusions") == "1", [])
    except Exception as e:
        return jsonify(error=str(e)), 400
    return jsonify(sorted(({"name": s.name, "home": s.url_home, "nsfw": bool(s.is_nsfw)} for s in sites),
                          key=lambda s: s["name"].lower()))


@app.post("/api/search")
def api_search():
    body = request.get_json(force=True)
    raw = [u.strip() for u in body.get("usernames", "").replace(",", " ").split() if u.strip()]
    if not raw:
        return jsonify(error="En az bir kullanıcı adı girin."), 400
    usernames = []
    for u in raw:
        usernames.extend(multiple_usernames(u) if check_for_parameter(u) else [u])
    usernames = list(dict.fromkeys(usernames))

    selected = [s.casefold() for s in body.get("sites", [])]
    try:
        sites = load_sites(body.get("source", "remote"), body.get("json", ""),
                           bool(body.get("ignore_exclusions")), selected)
    except Exception as e:
        return jsonify(error=f"Site listesi yüklenemedi: {e}"), 400

    all_sites = {s.name: s for s in sites}
    if selected:
        pool = {n: s for n, s in all_sites.items() if n.casefold() in selected}
    else:
        pool = {n: s for n, s in all_sites.items() if body.get("nsfw") or not s.is_nsfw}
    if not pool:
        return jsonify(error="Seçilen kriterlere uyan site yok."), 400

    timeout = max(1, min(int(body.get("timeout") or 60), 300))
    job_id = uuid.uuid4().hex[:10]
    job = {"queue": queue.Queue(), "results": [], "cancel": threading.Event(), "done": False,
           "started": time.time(), "homes": {n: s.url_home for n, s in pool.items()},
           "nsfw_map": {n: bool(s.is_nsfw) for n, s in pool.items()}, "usernames": usernames, "verify": []}
    _jobs[job_id] = job
    site_data = {n: s.information for n, s in pool.items()}
    threading.Thread(target=run_job, args=(job, usernames, site_data,
                     {"proxy": body.get("proxy", "").strip(), "timeout": timeout}), daemon=True).start()
    return jsonify(job=job_id, usernames=usernames, site_count=len(pool),
                   total=len(pool) * len(usernames))


@app.get("/api/stream/<job_id>")
def api_stream(job_id):
    job = _jobs.get(job_id)
    if not job:
        return "not found", 404

    def gen():
        while True:
            try:
                ev = job["queue"].get(timeout=15)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev["type"] == "done":
                break

    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/stop/<job_id>")
def api_stop(job_id):
    job = _jobs.get(job_id)
    if job:
        job["cancel"].set()
        proc = job.get("proc")
        if proc and proc.poll() is None:
            proc.kill()
    return jsonify(ok=True)


# ---------------------------------------------------------------- diğer araçlar
@app.get("/api/tools")
def api_tools():
    return jsonify(tools.public_registry(request.args.get("lang", "tr")))


# ---------------------------------------------------------------- ayarlar (27)
@app.get("/api/settings")
def api_settings():
    ks = store.key_status()
    return jsonify(settings=store.public_settings(), keys=ks,
                   tool_keys={t: {"key": k, "required": req} for t, (k, req) in store.TOOL_KEYS.items()},
                   status={"ghunt": ks["ghunt_login"], "anthropic_env": bool(os.environ.get("ANTHROPIC_API_KEY"))})


@app.post("/api/settings")
def api_settings_save():
    store.save_settings(request.get_json(force=True) or {})
    return api_settings()


# ---------------------------------------------------------------- vakalar (23)
@app.get("/api/cases")
def api_cases():
    return jsonify(store.list_cases())


@app.post("/api/cases")
def api_case_create():
    cid = store.create_case((request.get_json(force=True) or {}).get("name", ""))
    return jsonify(store.get_case(cid))


@app.get("/api/cases/<int:cid>")
def api_case(cid):
    c = store.get_case(cid)
    return (jsonify(c), 200) if c else (jsonify(error="Vaka yok"), 404)


@app.patch("/api/cases/<int:cid>")
def api_case_update(cid):
    b = request.get_json(force=True) or {}
    store.update_case(cid, b.get("name"), b.get("notes"))
    return jsonify(store.get_case(cid))


@app.delete("/api/cases/<int:cid>")
def api_case_delete(cid):
    store.delete_case(cid)
    return jsonify(ok=True)


@app.post("/api/cases/<int:cid>/items")
def api_case_items(cid):
    """Gövde: {job, indices?} bir işin sonuçlarını, ya da {tool, query, items:[...]} doğrudan ekler."""
    b = request.get_json(force=True) or {}
    if not store.get_case(cid):
        return jsonify(error="Vaka yok"), 404
    if b.get("job"):
        job = _jobs.get(b["job"])
        if not job:
            return jsonify(error="İş bulunamadı (sunucu yeniden başlamış olabilir)"), 404
        rows = job["results"]
        if b.get("indices") is not None:
            want = set(b["indices"])
            rows = [r for r in rows if r.get("i") in want]
        tool_id = job.get("tool") or "sherlock"
        query = job.get("query") or " ".join(job.get("usernames", []))
        items = []
        for r in rows:
            if job.get("tool"):
                img = r.get("image", "")
                if img.startswith("/api/jobfile/"):
                    img = _persist_jobfile(job, img)
                items.append({**r, "image": img})
            else:  # Sherlock satırı
                pv = r.get("_pv") or {}
                items.append({"title": r["site"], "url": r["url"], "status": "found" if r["status"] == "Claimed" else r["status"],
                              "detail": r.get("username", ""), "tags": r["status"], "image": pv.get("image", ""),
                              "meta": {"Kullanıcı adı": r.get("username"), "Yanıt": f"{r.get('time_ms')} ms"}})
        n = store.add_items(cid, tool_id, query, items)
    else:
        n = store.add_items(cid, b.get("tool", "el ile"), b.get("query", ""), b.get("items", []))
    return jsonify(added=n)


@app.patch("/api/items/<int:iid>")
def api_item_update(iid):
    store.update_item(iid, (request.get_json(force=True) or {}).get("note", ""))
    return jsonify(ok=True)


@app.delete("/api/items/<int:iid>")
def api_item_delete(iid):
    store.delete_item(iid)
    return jsonify(ok=True)


CASE_FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "case_files")


def _persist_jobfile(job, url):
    """Geçici iş dosyasını (ör. ExifTool fotoğrafı) vakada kalıcı olsun diye kopyalar."""
    name = url.rsplit("/", 1)[-1].split("?")[0]
    entry = job.get("files", {}).get(name)
    if not entry:
        return ""
    os.makedirs(CASE_FILES, exist_ok=True)
    ext = os.path.splitext(entry[0])[1] or ".jpg"
    dest = f"{job['id']}_{name}{ext}"
    import shutil
    shutil.copyfile(entry[0], os.path.join(CASE_FILES, dest))
    return f"/case_files/{dest}"


@app.get("/case_files/<path:name>")
def case_file(name):
    from flask import send_from_directory
    return send_from_directory(CASE_FILES, name)


@app.get("/case/<int:cid>/report")
def case_report(cid):
    c = store.get_case(cid)
    if not c:
        return "Vaka bulunamadı", 404
    groups = {}
    for it in c["items"]:
        groups.setdefault(it["tool"], []).append(it)
    titles = {t["id"]: t["title"] for t in tools.public_registry()}
    return render_template("report.html", case=c, groups=groups, titles=titles,
                           now=time.strftime("%d.%m.%Y %H:%M"),
                           created=time.strftime("%d.%m.%Y", time.localtime(c["created"] or 0)))


def run_tool_job(job, tool, inp):
    q = job["queue"]

    def emit(**r):
        r.setdefault("status", "info")
        r = {"i": len(job["results"]), "title": "", "url": "", "detail": "", "image": "", "tags": "", "meta": {}, **r}
        r["meta"] = {k: str(v) for k, v in (r.get("meta") or {}).items() if v not in (None, "", [], {})}
        job["results"].append(r)
        q.put({"type": "result", "data": r})

    try:
        tool["run"](job, inp, emit)
    except tools.ToolError as e:
        q.put({"type": "error", "data": str(e)})
    except Exception as e:
        q.put({"type": "error", "data": f"{type(e).__name__}: {e}"})
    finally:
        job["done"] = True
        q.put({"type": "done", "data": {"cancelled": job["cancel"].is_set(),
                                         "elapsed": round(time.time() - job["started"], 1)}})


@app.get("/api/jobfile/<job_id>/<name>")
def api_jobfile(job_id, name):
    """Bir aracın ürettiği dosyalar (ör. ExifTool fotoğrafı, temizlenmiş kopya). Yalnızca kayıtlı adlar sunulur."""
    job = _jobs.get(job_id)
    entry = (job or {}).get("files", {}).get(name)
    if not entry:
        return "not found", 404
    path, mime = entry
    dl = request.args.get("download") == "1"
    ext = os.path.splitext(path)[1] or ".jpg"
    return send_file(path, mimetype=mime, as_attachment=dl, download_name=f"{name}{ext}")


@app.post("/api/tool/<tool_id>")
def api_tool(tool_id):
    tool = tools.BY_ID.get(tool_id)
    if not tool:
        return jsonify(error="Bilinmeyen araç"), 404
    inp = dict(request.form) if request.form or request.files else (request.get_json(silent=True) or {})
    for k, v in list(inp.items()):
        if v in ("on", "true"):
            inp[k] = True
    workdir = tools.new_workdir()
    saved = []
    for i, up in enumerate(request.files.getlist("file")):
        if up and up.filename:
            path = os.path.join(workdir, f"upload_{i}_" + os.path.basename(up.filename))
            up.save(path)
            saved.append(path)
    if saved:
        inp["_file"], inp["_files"] = saved[0], saved
    # Ayarlardaki varsayılanlar
    if tool_id == "toutatis" and not str(inp.get("sessionid", "")).strip():
        inp["sessionid"] = store.get("instagram_sessionid")
    if tool_id == "h8mail" and not str(inp.get("apikeys", "")).strip():
        inp["apikeys"] = store.get("h8mail_keys")
    if not str(inp.get("timeout", "")).strip() and store.get("default_timeout"):
        inp["timeout"] = store.get("default_timeout")
    for f in tool["fields"]:
        if f.get("required") and not str(inp.get(f["name"], "")).strip():
            return jsonify(error=f"'{f['label']}' alanı gerekli."), 400
    job_id = uuid.uuid4().hex[:10]
    job = {"queue": queue.Queue(), "results": [], "cancel": threading.Event(), "done": False,
           "started": time.time(), "tool": tool_id, "dir": workdir, "proc": None, "id": job_id, "files": {},
           "usernames": [str(next((inp[f["name"]] for f in tool["fields"] if f.get("required")), tool_id))],
           "query": str(next((inp.get(f["name"]) for f in tool["fields"] if str(inp.get(f["name"]) or "").strip()
                              and f.get("type") not in ("checkbox", "select", "number")),
                             os.path.basename(saved[0]).split("_", 2)[-1] if saved else tool_id))[:200]}
    job["log"] = lambda line: job["queue"].put({"type": "log", "data": line})
    job["progress"] = lambda d, t: job["queue"].put({"type": "progress", "data": [d, t]})
    _jobs[job_id] = job
    threading.Thread(target=run_tool_job, args=(job, tool, inp), daemon=True).start()
    return jsonify(job=job_id)


class _MetaParser(HTMLParser):
    """Sayfadaki <title>, og:* / twitter:* ve description etiketlerini toplar."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self._in_title, self.icon = {}, "", False, None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and "content" in a and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title" and not self.title:
            self._in_title = True
        elif tag == "link" and "icon" in a.get("rel", "").lower() and not self.icon:
            self.icon = a.get("href")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


_preview_cache: dict = {}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


@app.get("/api/preview")
def api_preview():
    url = request.args.get("url", "")
    # Yalnızca bu oturumdaki tarama sonuçlarında geçen URL'ler önizlenebilir.
    if not any(r["url"] == url for j in _jobs.values() for r in j["results"]):
        return jsonify(error="Bilinmeyen URL"), 400
    return jsonify(fetch_preview(url))


def fetch_preview(url):
    """Profil sayfasını açıp meta bilgilerini çıkarır; 'ok' alanı sayfanın gerçekten açılıp açılmadığını söyler."""
    if url in _preview_cache:
        return _preview_cache[url]
    try:
        resp = requests.get(url, timeout=(4, 6), headers={"User-Agent": UA, "Accept-Language": "en,tr;q=0.8"},
                            stream=True, allow_redirects=True)
        # Meta etiketleri <head> içinde: </head> görülünce okumayı bırak (hız için).
        raw = b""
        for chunk in resp.iter_content(16_384):
            raw += chunk
            if b"</head>" in raw.lower() or len(raw) > 400_000:
                break
        resp.close()
        enc = resp.encoding if resp.encoding and resp.encoding.lower() != "iso-8859-1" else "utf-8"
        p = _MetaParser()
        p.feed(raw.decode(enc, errors="replace"))
        m = p.meta
        pick = lambda *keys: next((m[k] for k in keys if m.get(k)), "")
        image = pick("og:image", "og:image:url", "twitter:image", "twitter:image:src")
        icon = p.icon
        data = {
            "url": url,
            "final_url": resp.url,
            "http_status": resp.status_code,
            "title": html.unescape(pick("og:title", "twitter:title") or p.title.strip())[:300],
            "description": html.unescape(pick("og:description", "twitter:description", "description"))[:600],
            "image": urljoin(resp.url, image) if image else "",
            "icon": urljoin(resp.url, icon) if icon else "",
            "site_name": pick("og:site_name"),
            "type": pick("og:type"),
        }
        orig, final = urlparse(url), urlparse(resp.url)
        bounced_home = final.path.strip("/") == "" and orig.path.strip("/") != ""
        data["ok"] = resp.status_code < 400 and not bounced_home
        if not data["ok"]:
            data["error"] = "Ana sayfaya yönlendi" if bounced_home else f"HTTP {resp.status_code}"
    except Exception as e:
        data = {"url": url, "ok": False, "error": type(e).__name__}
    _preview_cache[url] = data
    return data


def verify_row(job, row):
    """Bulunan her profili arka planda açar, sonucu SSE ile gönderir."""
    if job["cancel"].is_set():
        return
    data = fetch_preview(row["url"])
    row["verified"] = data["ok"]
    job["queue"].put({"type": "preview", "data": {**data, "i": row["i"]}})


@app.get("/api/export/<job_id>.<fmt>")
def api_export(job_id, fmt):
    job = _jobs.get(job_id)
    if not job:
        return "not found", 404
    rows = job["results"]
    if job.get("tool"):
        return export_generic(job, rows, fmt)
    if request.args.get("found") == "1":
        # Açılamayan (doğrulanamayan) profiller "bulunanlar"a dahil edilmez.
        rows = [r for r in rows if r["status"] == QueryStatus.CLAIMED.value and r.get("verified") is not False]
    df = pd.DataFrame(rows, columns=["username", "site", "url", "home", "status", "verified", "time_ms", "context"])
    name = f"sherlock_{'_'.join(job['usernames'])[:60]}"
    buf = io.BytesIO()
    if fmt == "xlsx":
        df.to_excel(buf, index=False, sheet_name="sherlock")
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        buf.write(df.to_csv(index=False).encode("utf-8-sig"))
        mime = "text/csv"
    elif fmt == "json":
        buf.write(json.dumps(rows, ensure_ascii=False, indent=2).encode())
        mime = "application/json"
    elif fmt == "txt":
        lines = []
        for u in job["usernames"]:
            found = [r["url"] for r in rows if r["username"] == u and r["status"] == "Claimed"]
            lines += [f"# {u}", *found, f"Total Websites Username Detected On : {len(found)}", ""]
        buf.write("\n".join(lines).encode())
        mime = "text/plain"
    else:
        return "bad format", 400
    buf.seek(0)
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{name}.{fmt}")


def export_generic(job, rows, fmt):
    if request.args.get("found") == "1":
        rows = [r for r in rows if r["status"] in ("found", "maybe")]
    flat = [{"title": r["title"], "url": r["url"], "status": r["status"], "detail": r["detail"],
             "tags": r["tags"], "image": r["image"],
             "meta": "; ".join(f"{k}={v}" for k, v in r["meta"].items())} for r in rows]
    name = f"{job['tool']}_{job['usernames'][0]}"[:60]
    buf = io.BytesIO()
    df = pd.DataFrame(flat, columns=["title", "url", "status", "detail", "tags", "image", "meta"])
    if fmt == "xlsx":
        df.to_excel(buf, index=False, sheet_name=job["tool"][:30])
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "csv":
        buf.write(df.to_csv(index=False).encode("utf-8-sig"))
        mime = "text/csv"
    elif fmt == "json":
        buf.write(json.dumps(rows, ensure_ascii=False, indent=2).encode())
        mime = "application/json"
    elif fmt == "txt":
        buf.write("\n".join(r["url"] or f"{r['title']}: {r['detail']}" for r in rows).encode())
        mime = "text/plain"
    else:
        return "bad format", 400
    buf.seek(0)
    return send_file(buf, mimetype=mime, as_attachment=True, download_name=f"{name}.{fmt}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"Sherlock Panel → http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
