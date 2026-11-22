"""Run tools in-process without the web server (used by the watcher, the CLI and the REST batch endpoint)."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import catalog
import store
import tools

FAST_SKIP = {"spiderfoot", "recon-ng", "theharvester", "subfinder", "doc-meta", "dnstwist", "social-analyzer", "nexfil"}


def new_job(lang="tr", log=None, cancel=None):
    return {"cancel": cancel or threading.Event(), "dir": tools.new_workdir(), "proc": None, "files": {}, "id": "inproc",
            "lang": lang, "log": log or (lambda m: None), "progress": lambda a, b: None, "results": []}


def run_tool(tool_id, inp, lang="tr", log=None, cancel=None):
    """Run one tool and return (rows, error)."""
    t = tools.BY_ID.get(tool_id)
    if not t:
        return [], f"unknown tool: {tool_id}"
    job = new_job(lang, log, cancel)
    rows = []

    def emit(**r):
        r.setdefault("status", "info")
        r = {"i": len(rows), "title": "", "url": "", "detail": "", "image": "", "tags": "", "meta": {}, **r}
        r["meta"] = {k: str(v) for k, v in (r.get("meta") or {}).items() if v not in (None, "", [], {})}
        rows.append(r)

    try:
        t["run"](job, inp, emit)
        return rows, None
    except Exception as e:  # noqa: BLE001
        return rows, f"{type(e).__name__}: {e}"
    finally:
        p = job.get("proc")
        if p and p.poll() is None:
            p.kill()


def plan(value, typ=None, only=None, all_tools=False):
    """Tools Smart search would run for a value: [(tool_id, inputs)]."""
    typ = typ or catalog.detect_type(value)
    keys = store.key_status()
    out = []
    for x in catalog.build(tools.REGISTRY).get(typ, []):
        tid = x["id"]
        if tid == "sherlock" or tid not in tools.BY_ID:
            continue
        if only and tid not in only:
            continue
        need = store.TOOL_KEYS.get(tid)
        if need and need[1] and not keys.get(need[0]):
            continue
        if not only and not all_tools and not catalog.eval_default(x["default"], value, keys):
            continue
        inp = catalog.fill(x["fields"], value)
        if tid == "variants":
            parts = value.split()
            inp = {"first": " ".join(parts[:-1]) or value, "last": parts[-1] if len(parts) > 1 else ""}
        out.append((tid, inp))
    return typ, out


def run_many(tasks, lang="tr", workers=4, budget_s=900, log=None, on_result=None):
    """Run [(tool_id, inputs)] in parallel with a time budget. Returns {tool_id: {"rows", "error", "seconds"}}."""
    cancel = threading.Event()
    out = {}
    lock = threading.Lock()

    def one(tid, inp):
        t0 = time.time()
        rows, err = run_tool(tid, inp, lang, log, cancel)
        with lock:
            out[tid] = {"rows": rows, "error": err, "seconds": round(time.time() - t0, 1)}
        if on_result:
            on_result(tid, rows, err)

    ex = ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(one, tid, inp) for tid, inp in tasks]
    _, pending = wait(futs, timeout=budget_s)
    if pending:
        cancel.set()
    ex.shutdown(wait=False, cancel_futures=True)
    return out
