"""More web archives: archive.today snapshots and the Common Crawl index (complements the Wayback Machine tool)."""
import json
import re
from collections import Counter
from urllib.parse import quote, urlparse

from plugin_api import F, L, session


def _cc_query(s, q, limit, log):
    """En yeni dizinden başlayıp yanıt veren ilk dizini kullanır (sunucu sık sık 504 veriyor)."""
    infos = s.get("https://index.commoncrawl.org/collinfo.json", timeout=20).json()[:4]
    last = ""
    for idx in infos:
        try:
            r = s.get(idx["cdx-api"], params={"url": q, "output": "json", "limit": limit, "fl": "url,timestamp,status,mime"}, timeout=45)
        except Exception as e:
            last = type(e).__name__
            continue
        if r.status_code == 200:
            return idx, [json.loads(x) for x in r.text.splitlines() if x.startswith("{")], ""
        if r.status_code == 404:          # bu dizinde kayıt yok
            return idx, [], ""
        last = f"HTTP {r.status_code}"
        log(f"Common Crawl {idx['id']}: {last}")
    return (infos[0] if infos else {"name": "Common Crawl"}), [], last or "?"


def run(job, inp, emit):
    target = inp["target"].strip()
    limit = max(10, min(int(inp.get("limit") or 300), 2000))
    s = session()
    is_url = bool(re.match(r"https?://", target)) and urlparse(target).path not in ("", "/")
    host = urlparse(target if re.match(r"https?://", target) else "https://" + target).hostname or target

    # ---- archive.today: zaman haritası (bot korumasına takılabilir → yalnızca bağlantı)
    at_url = target if re.match(r"https?://", target) else f"https://{host}/"
    try:
        r = s.get(f"https://archive.ph/timemap/link/{at_url}", timeout=20)
        snaps = re.findall(r'<(https?://archive\.[a-z]+/[A-Za-z0-9]+)>;\s*rel="[^"]*memento[^"]*";\s*datetime="([^"]+)"', r.text) if r.status_code == 200 else []
    except Exception:
        snaps = []
    if snaps:
        emit(title="archive.today", url=f"https://archive.ph/{at_url}", status="found",
             detail=L(job, f"{len(snaps)} kayıt · ilk: {snaps[0][1]} · son: {snaps[-1][1]}",
                      f"{len(snaps)} snapshots · first: {snaps[0][1]} · last: {snaps[-1][1]}"), tags="archive.today")
        for link, when in snaps[-15:][::-1]:
            emit(title=when, url=link, status="found", tags="archive.today")
    else:
        emit(title="archive.today", url=f"https://archive.ph/{at_url}", status="info", tags="archive.today",
             detail=L(job, "Otomatik sorgu yanıtsız kaldı ya da kayıt yok; bağlantıyı açarak elle bakın (site bot doğrulaması isteyebilir).",
                      "No automatic answer or no snapshots; open the link to check manually (the site may ask for a bot check)."))

    # ---- Common Crawl
    q = target if is_url else f"{host}/*"
    try:
        idx, rows, err = _cc_query(s, q, limit, job["log"])
    except Exception as e:
        idx, rows, err = {"name": "Common Crawl"}, [], type(e).__name__
    if not rows:
        if err:
            emit(title="Common Crawl", status="error", tags="Common Crawl",
                 detail=L(job, f"Dizin sunucusu yanıt vermedi ({err}); biraz sonra tekrar deneyin.",
                          f"The index server did not respond ({err}); try again later."))
        else:
            emit(title="Common Crawl", status="notfound", tags="Common Crawl",
                 detail=L(job, f"{idx.get('name', '')}: kayıt yok.", f"{idx.get('name', '')}: no records."))
        return
    urls = {}
    for x in rows:
        urls.setdefault(x["url"], x)
    mimes = Counter(x.get("mime", "") for x in urls.values())
    emit(title="Common Crawl", status="found", tags="Common Crawl",
         url=f"https://index.commoncrawl.org/{idx.get('id', '')}-index?url={quote(q)}&output=json",
         detail=L(job, f"{idx.get('name', '')}: {len(urls)} farklı adres", f"{idx.get('name', '')}: {len(urls)} distinct URLs"),
         meta={L(job, "Türler", "Types"): ", ".join(f"{m} ({n})" for m, n in mimes.most_common(5))})
    interesting = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|csv|txt|sql|bak|zip|env|json|xml)(\?|$)|/(admin|login|wp-admin|api|backup|private)", re.I)
    ordered = sorted(urls.values(), key=lambda x: (not interesting.search(x["url"]), x["url"]))
    for x in ordered[:120]:
        ts = x.get("timestamp", "")
        when = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) >= 8 else ts
        emit(title=x["url"][:120], url=x["url"], status="found" if interesting.search(x["url"]) else "info",
             detail=f"{when} · HTTP {x.get('status', '?')} · {x.get('mime', '')}", tags="Common Crawl")


PLUGIN = {
    "id": "archives", "group": "Alan adı", "title": "archive.today + Common Crawl", "icon": "layers",
    "desc": "Wayback'e ek olarak archive.today kayıtlarını ve Common Crawl dizinindeki adresleri listeler.",
    "fields": [F("target", "Alan adı ya da sayfa adresi", required=True, placeholder="ornek.com veya https://…"),
               F("limit", "Common Crawl en fazla kayıt", type="number", value=300)],
    "run": run,
    "accepts": {"domain": {"fields": {"target": "$", "limit": 300}, "default": False},
                "url": {"fields": {"target": "$", "limit": 100}, "default": True}},
    "about": {"what": "archive.today'in zaman haritasından sayfanın kayıtlarını, Common Crawl'ın en yeni dizininden sitenin taranmış adreslerini (belge, yönetim sayfası gibi ilginç olanlar önde) getirir.",
              "when": "Wayback'te olmayan silinmiş sayfaları ve unutulmuş dosyaları bulmak için.",
              "input": "Alan adı ya da sayfa adresi.", "output": "Arşiv kayıtları ve adres listesi.",
              "tips": "archive.today bot doğrulaması isteyebilir; o durumda bağlantıyı tarayıcıda açın."},
    "en": {"title": "archive.today + Common Crawl", "desc": "Lists archive.today snapshots and Common Crawl index URLs, in addition to Wayback.",
           "fields": {"target": {"label": "Domain or page URL", "placeholder": "example.com or https://…"},
                      "limit": {"label": "Common Crawl max records"}},
           "about": {"what": "Gets a page's snapshots from archive.today's timemap and the crawled URLs of a site from the latest Common Crawl index (interesting ones such as documents and admin pages first).",
                     "when": "To find deleted pages and forgotten files that the Wayback Machine doesn't have.",
                     "input": "Domain or page URL.", "output": "Archive snapshots and a URL list.",
                     "tips": "archive.today may ask for a bot check; open the link in your browser then."}},
}
