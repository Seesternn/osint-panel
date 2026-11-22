"""Derin tarama: en olası kişinin kullanıcı adı / e-posta / alan adlarını panelin diğer araçlarına otomatik gönderir.

Yalnızca 1 derinlik (bulunan yeni adlar tekrar taranmaz), en fazla 3 paralel iş ve toplam süre bütçesi vardır.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait

import tools

PLAN = [  # (araç, tohum türü, girdi alanı, ek alanlar, en fazla)
    ("github", "github", "username", {}, 2),
    ("maigret", "username", "username", {"top": 300, "timeout": 8}, 2),
    ("social-activity", "username", "username", {}, 1),
    ("holehe", "email", "email", {}, 2),
    ("email-accounts", "email", "email", {}, 2),
    ("site-intel", "domain", "url", {}, 1),
    ("whois", "domain", "domain", {}, 1),
]


def seeds_from(persona):
    s = {"username": [], "email": list(persona.get("emails", [])), "domain": [], "github": []}
    for a in persona.get("accounts", []):
        if a["platform"] == "GitHub":
            s["github"].append(a["handle"])
        if a["platform"] in ("GitHub", "X", "Instagram", "Bluesky", "Keybase", "GitLab", "Reddit", "TikTok", "Medium"):
            s["username"].append(a["handle"])
    s["username"] += [u for u in persona.get("usernames", []) if "@" not in u]
    from persona import personal_domain
    for a in persona.get("accounts", []):
        d = personal_domain(a["url"])
        if d:
            s["domain"].append(d)
    return {k: list(dict.fromkeys(v)) for k, v in s.items()}


def run(job, persona, budget_s=300):
    """Alt araçları çalıştırır; (satırlar, özet) döndürür. Satırların etiketi 'Derin tarama · <araç>'."""
    seeds = seeds_from(persona)
    log = job["log"]
    tasks = []
    for tool_id, kind, field, extra, cap in PLAN:
        for v in seeds.get(kind, [])[:cap]:
            tasks.append((tool_id, {field: v, **extra}, v))
    if not tasks:
        log("Derin tarama: bu kişiden taranacak kullanıcı adı / e-posta / alan adı çıkmadı.")
        return [], []
    log(f"Derin tarama: {len(tasks)} iş, en fazla {budget_s // 60} dk")
    rows, done = [], []
    lock = threading.Lock()
    cancel = threading.Event()

    subs = []

    def one(tool_id, inp, seed):
        t = tools.BY_ID[tool_id]
        sub = {"dir": tools.new_workdir(), "cancel": cancel, "proc": None, "files": {}, "id": job["id"],
               "log": lambda m, tid=tool_id: None, "progress": lambda a, b: None}
        subs.append(sub)
        out = []
        t0 = time.time()
        try:
            t["run"](sub, inp, lambda **r: out.append(r))
            status = "tamam"
        except Exception as e:
            status = f"hata: {str(e)[:80]}"
        keep = [r for r in out if r.get("status") in ("found", "maybe") and r.get("kind") not in ("warn", "figure", "histogram")]
        for r in keep:
            r["tags"] = f"Derin tarama · {t['title']}"
            r["detail"] = (r.get("detail") or "") + f" (tohum: {seed})"
        with lock:
            rows.extend(keep[:60])
            done.append({"tool": t["title"], "seed": seed, "found": len(keep), "status": status, "sn": round(time.time() - t0, 1)})
        log(f"Derin tarama · {t['title']} ({seed}): {len(keep)} bulgu")

    ex = ThreadPoolExecutor(max_workers=3)
    futs = [ex.submit(one, *t) for t in tasks]
    _, pending = wait(futs, timeout=budget_s)
    if pending:
        cancel.set()
        for sub in subs:            # bütçe doldu: çalışan alt süreçleri hemen sonlandır
            p = sub.get("proc")
            if p and p.poll() is None:
                p.kill()
        log(f"Derin tarama süre bütçesi doldu; {len(pending)} iş durduruldu.")
    ex.shutdown(wait=False, cancel_futures=True)
    with lock:
        return list(rows), list(done)
