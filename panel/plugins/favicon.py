"""Favicon hash pivot: the Shodan-style MurmurHash3 of a site's icon finds other servers showing the same icon."""
import base64
import re
from urllib.parse import urljoin, urlparse, quote

from plugin_api import F, L, ToolError, session, setting


def mmh3_32(data: bytes, seed: int = 0) -> int:
    """MurmurHash3 x86_32, signed — the value Shodan uses for http.favicon.hash."""
    c1, c2, h = 0xcc9e2d51, 0x1b873593, seed & 0xFFFFFFFF
    n = len(data) // 4
    for i in range(n):
        k = int.from_bytes(data[4 * i:4 * i + 4], "little")
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xe6546b64) & 0xFFFFFFFF
    tail, k = data[4 * n:], 0
    if len(tail) >= 3:
        k ^= tail[2] << 16
    if len(tail) >= 2:
        k ^= tail[1] << 8
    if tail:
        k ^= tail[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85ebca6b) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & 0xFFFFFFFF
    h ^= h >> 16
    return h - (1 << 32) if h & 0x80000000 else h


def favicon_hash(content: bytes) -> int:
    return mmh3_32(base64.encodebytes(content))


def run(job, inp, emit):
    target = inp["url"].strip()
    if not re.match(r"https?://", target):
        target = "https://" + target
    s = session()
    icon_url = urljoin(target, "/favicon.ico")
    try:
        page = s.get(target, timeout=15)
        m = re.search(r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]*>', page.text, re.I)
        if m:
            href = re.search(r'href=["\']([^"\']+)["\']', m.group(0))
            if href:
                icon_url = urljoin(page.url, href.group(1))
    except Exception:
        pass
    r = None
    for u in dict.fromkeys([icon_url, urljoin(target, "/favicon.ico")]):    # bağlantılı ikon olmazsa /favicon.ico
        try:
            r = s.get(u, timeout=15)
        except Exception:
            continue
        if r.status_code == 200 and r.content:
            icon_url = u
            break
    if r is None:
        raise ToolError(L(job, "Site ikonuna ulaşılamadı.", "Could not reach the site icon."))
    if r.status_code != 200 or not r.content:
        raise ToolError(L(job, f"Site ikonu indirilemedi (HTTP {r.status_code}).", f"Could not download the site icon (HTTP {r.status_code})."))
    h = favicon_hash(r.content)
    emit(title=L(job, "Site ikonu karması", "Favicon hash"), url=icon_url, image=icon_url, status="found", detail=str(h),
         meta={"Shodan": f"http.favicon.hash:{h}", L(job, "Boyut", "Size"): f"{len(r.content)} B"})
    key = setting("shodan_api_key")
    if key:
        try:
            c = s.get("https://api.shodan.io/shodan/host/count", params={"key": key, "query": f"http.favicon.hash:{h}",
                                                                          "facets": "org:5,country:5"}, timeout=20).json()
            if "total" in c:
                facets = c.get("facets", {})
                emit(title=L(job, "Aynı ikonu kullanan sunucular", "Servers using the same icon"), status="found",
                     detail=L(job, f"Shodan'da {c['total']} sonuç", f"{c['total']} results on Shodan"),
                     meta={L(job, "Kuruluşlar", "Organisations"): ", ".join(f"{x['value']} ({x['count']})" for x in facets.get("org", [])),
                           L(job, "Ülkeler", "Countries"): ", ".join(f"{x['value']} ({x['count']})" for x in facets.get("country", []))})
        except Exception:
            pass
    fofa = base64.b64encode(f'icon_hash="{h}"'.encode()).decode()
    for name, url in [("Shodan", f"https://www.shodan.io/search?query={quote(f'http.favicon.hash:{h}')}"),
                      ("FOFA", f"https://en.fofa.info/result?qbase64={quote(fofa)}"),
                      ("ZoomEye", f"https://www.zoomeye.ai/searchResult?q={quote(f'iconhash:{h}')}")]:
        emit(title=L(job, f"{name}'da ara", f"Search on {name}"), url=url, status="info", tags=L(job, "Pivot", "Pivot"))
    host = urlparse(target).hostname or ""
    emit(title=L(job, "Not", "Note"), status="info",
         detail=L(job, f"Aynı ikon karması, {host} ile aynı yazılımı ya da aynı sahibi paylaşan sunucuları (gizli kökenler, test sunucuları) gösterebilir. Yaygın CMS ikonları çok sayıda alakasız sonuç verir.",
                  f"The same icon hash can reveal servers sharing software or an owner with {host} (hidden origins, staging servers). Common CMS icons return many unrelated results."))


PLUGIN = {
    "id": "favicon", "group": "Alan adı", "title": "Site ikonu karması", "icon": "fingerprint",
    "desc": "Sitenin ikonunun Shodan karmasını hesaplar; aynı ikonu kullanan diğer sunucuları bulmaya yarar.",
    "fields": [F("url", "Site adresi", required=True, placeholder="ornek.com")],
    "run": run,
    "accepts": {"domain": {"fields": {"url": "$"}, "default": True}, "url": {"fields": {"url": "$"}, "default": False}},
    "about": {"what": "Sitenin favicon dosyasını indirip Shodan'ın kullandığı MurmurHash3 karmasını hesaplar; Shodan, FOFA ve ZoomEye'da aynı ikonu taşıyan sunucuları aratır. Shodan anahtarı varsa sonuç sayısını, kuruluş ve ülke dağılımını da getirir.",
              "when": "CDN arkasındaki gerçek sunucuyu, test / yedek sunucuları ya da aynı sahibin başka sitelerini bulmak için.",
              "input": "Alan adı ya da site adresi.", "output": "İkon karması, pivot bağlantıları ve (anahtarla) Shodan özeti.",
              "tips": "WordPress gibi yaygın ikonlar binlerce sonuç verir; özel tasarım ikonlar daha anlamlıdır."},
    "en": {"title": "Favicon hash", "desc": "Computes the Shodan hash of a site's icon to find other servers using the same icon.",
           "fields": {"url": {"label": "Site URL", "placeholder": "example.com"}},
           "about": {"what": "Downloads the site's favicon, computes the MurmurHash3 that Shodan uses, and searches Shodan, FOFA and ZoomEye for servers with the same icon. With a Shodan key it also returns the result count and organisation / country breakdown.",
                     "when": "To find the real server behind a CDN, staging / backup servers, or other sites of the same owner.",
                     "input": "Domain or site URL.", "output": "Icon hash, pivot links and (with a key) a Shodan summary.",
                     "tips": "Common icons such as WordPress's return thousands of results; custom icons are far more telling."}},
}
