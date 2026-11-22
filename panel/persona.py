"""Kişi ayırma: aynı isimli farklı kişileri bulgulardan ayırır.

İsim eşleşmesi kimlik kanıtı değildir; bulgular ikinci kanıtlarla bağlanır:
  güçlü : aynı kullanıcı adı, aynı e-posta, aynı profil fotoğrafı, bir kaynağın diğer hesabı açıkça göstermesi
  orta  : aynı kurum + (aynı şehir ya da birebir aynı ad)
  (yalnızca aynı şehir tek başına bağlamaz)
Bağlanan bulgular "olası kişi"leri oluşturur; her kişiye neden-bağlandı açıklamaları, puan ve zaman çizelgesi eklenir.
Yüz tanıma yapılmaz: fotoğraflar yalnızca aynı / çok benzer görsel olarak eşleştirilir (perceptual hash).
"""
import io
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

FOLD = str.maketrans("ıİğĞşŞöÖüÜçÇâÂîÎ", "iIgGsSoOuUcCaAiI")
fold = lambda s: re.sub(r"\s+", " ", (s or "").translate(FOLD).lower()).strip()
UA = {"User-Agent": "osint-panel-local/1.0 (personal OSINT panel; local use)"}

# Kimlik / hesap bildiren bölümler ve ağırlıkları
SOURCE_W = {"Tanınmış kişi": 3.0, "GitHub": 1.2, "Bluesky": 1.0, "Stack Overflow": 0.8, "Akademik": 1.0,
            "Web araması": 0.8, "E-posta tahmini": 1.5, "Derin tarama": 0.6}
PLATFORMS = [  # (alan adı deseni, yol deseni → kullanıcı adı)
    (r"(^|\.)github\.com$", r"^/([\w-]+)/?$", "GitHub"), (r"(^|\.)gitlab\.com$", r"^/([\w.-]+)/?$", "GitLab"),
    (r"(^|\.)(x|twitter)\.com$", r"^/@?(\w{2,15})/?$", "X"), (r"(^|\.)instagram\.com$", r"^/([\w.]+)/?$", "Instagram"),
    (r"(^|\.)tiktok\.com$", r"^/@([\w.]+)/?$", "TikTok"), (r"(^|\.)linkedin\.com$", r"^/in/([\w%-]+)/?$", "LinkedIn"),
    (r"(^|\.)facebook\.com$", r"^/([\w.]{5,})/?$", "Facebook"), (r"(^|\.)youtube\.com$", r"^/@([\w.-]+)/?$", "YouTube"),
    (r"(^|\.)medium\.com$", r"^/@([\w.-]+)/?$", "Medium"), (r"(^|\.)reddit\.com$", r"^/u(?:ser)?/([\w-]+)/?$", "Reddit"),
    (r"^t\.me$", r"^/(\w{5,})/?$", "Telegram"), (r"(^|\.)keybase\.io$", r"^/(\w+)/?$", "Keybase"),
    (r"(^|\.)bsky\.app$", r"^/profile/([\w.-]+)/?$", "Bluesky"), (r"(^|\.)gravatar\.com$", r"^/([\w.-]+)/?$", "Gravatar"),
]
NON_USERS = {"search", "explore", "login", "signup", "home", "about", "settings", "pub", "dir", "in", "company", "jobs", "hashtag",
             "results", "watch", "channel", "share", "intent", "i", "p", "reel", "stories", "groups", "pages", "people"}
BIG_DOMAINS = re.compile(r"(google|facebook|instagram|twitter|x|tiktok|youtube|linkedin|github|gitlab|reddit|wikipedia|wikidata|"
                         r"medium|bsky|keybase|gravatar|t|telegram|orcid|openalex|crossref|stackoverflow|archive)\.\w+$")


def parse_account(url):
    """Profil URL'sinden (platform, kullanıcı adı) çıkarır."""
    try:
        u = urlparse(url)
    except Exception:
        return None
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    host = re.sub(r"^[a-z]{2}\.linkedin\.com$", "linkedin.com", host)
    for hrx, prx, plat in PLATFORMS:
        if re.search(hrx, host):
            m = re.match(prx, u.path)
            if m and m.group(1).lower() not in NON_USERS:
                h = m.group(1).lower()
                if plat == "Bluesky" and h.endswith(".bsky.social"):
                    h = h[:-len(".bsky.social")]
                return plat, h
    return None


def personal_domain(url):
    try:
        h = (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""
    return "" if not h or BIG_DOMAINS.search(h) else h


def name_match(name, seen):
    a, b = fold(name), fold(seen)
    if not b:
        return "none"
    if a == b:
        return "exact"
    ta, tb = set(a.split()), set(b.split())
    if ta <= tb or tb <= ta:
        return "partial-strong"
    return "partial" if ta & tb else "none"


NAME_F = {"exact": 1.0, "partial-strong": 0.8, "partial": 0.45, "none": 0.3}


class Evidence:
    def __init__(self, rid, row, name):
        self.rid, self.row = rid, row
        tag = row.get("tags", "")
        self.source = "Derin tarama" if tag.startswith("Derin tarama") else tag
        m = row.get("meta") or {}
        self.name_seen = m.get("Ad") or m.get("fullname") or m.get("name") or m.get("Ad Soyad") or ""
        if not self.name_seen and self.source in ("Tanınmış kişi", "Akademik"):
            self.name_seen = row.get("title", "").split(" — ")[0].removeprefix("ORCID: ")
        self.match = name_match(name, self.name_seen)
        self.usernames, self.emails, self.domains, self.declared = set(), set(), set(), set()
        self.accounts = []          # (platform, handle, url)
        acc = parse_account(row.get("url", ""))
        if acc:
            self.usernames.add(acc[1])
            self.accounts.append((acc[0], acc[1], row["url"]))
        if row.get("kind") == "username" and not acc:
            self.usernames.add(row.get("title", "").lower())
        if m.get("Kullanıcı adı"):
            self.usernames.add(str(m["Kullanıcı adı"]).lower())
        for v in [m.get("email"), m.get("E-posta")] + re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", f"{row.get('title', '')} {row.get('detail', '')}"):
            if v:
                self.emails.add(v.lower())
        for v in (m.get("Blog"), m.get("Web sitesi")):
            if v:
                d = personal_domain(v if v.startswith("http") else "https://" + v)
                if d:
                    self.declared.add("dom:" + d)
        if m.get("Twitter / X"):
            self.declared.add("user:" + str(m["Twitter / X"]).lower())
        pd = personal_domain(row.get("url", ""))
        if pd and self.source in ("Tanınmış kişi", "Web araması"):
            self.domains.add(pd)
        self.image = row.get("image", "") if str(row.get("image", "")).startswith("http") else ""
        self.location = m.get("Konum") or m.get("location") or m.get("Doğum yeri") or ""
        self.org = m.get("Şirket") or m.get("Kurum") or m.get("Çalıştığı yer") or m.get("company") or ""
        if not self.org and self.source == "Akademik":
            self.org = (row.get("detail") or "").split(" · ")[0]
        self.dates = []
        for k, label in (("Doğum", "Doğum"), ("Ölüm", "Ölüm"), ("Hesap açılışı", "Hesap açıldı"), ("Yıl", "Yayın"),
                         ("created_at", "Hesap açıldı")):
            v = m.get(k)
            if v and re.match(r"\d{4}", str(v)):
                self.dates.append((str(v)[:10], f"{label}: {row.get('title', '')[:70]}", row.get("url", "")))
        self.hash = None

    @property
    def weight(self):
        return SOURCE_W.get(self.source, 0.5) * NAME_F[self.match]


def _hash_images(evs, ref_path, log):
    """Profil fotoğraflarının parmak izleri (en fazla 30)."""
    try:
        import imagehash
        from PIL import Image
    except Exception:
        return None
    todo = [e for e in evs if e.image][:30]

    def h(e):
        try:
            r = requests.get(e.image, timeout=8, headers=UA)
            im = Image.open(io.BytesIO(r.content)).convert("RGB")
            if im.width < 24 or len(set(im.resize((16, 16)).getdata())) < 6:   # boş / tek renk varsayılan avatar
                return
            e.hash = (imagehash.phash(im), imagehash.dhash(im))
        except Exception:
            pass
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(h, todo))
    ref = None
    if ref_path:
        try:
            im = Image.open(ref_path).convert("RGB")
            ref = (imagehash.phash(im), imagehash.dhash(im))
        except Exception:
            ref = None
    log(f"{sum(1 for e in todo if e.hash)} profil fotoğrafının parmak izi çıkarıldı")
    return ref


def same_photo(a, b):
    return a and b and (a[0] - b[0]) <= 6 and (a[1] - b[1]) <= 10


def cluster(rows, name, ctx, ref_path=None, log=lambda m: None):
    """rows: emit edilen sonuç sözlükleri (i alanı ile). ctx: {place, org, birth_year, known}"""
    evs = [Evidence(r["i"], r, name) for r in rows
           if r.get("status") in ("found", "maybe") and r.get("kind") not in ("warn", "person", "personas", "summary")
           and (r.get("tags") in SOURCE_W or str(r.get("tags", "")).startswith("Derin tarama"))]
    weak = [Evidence(r["i"], r, name) for r in rows if r.get("tags") == "Kullanıcı adı kontrolü" and r.get("status") == "found"]
    for w in weak:   # socialscan başlığı "Platform · ad"
        w.usernames = {w.row.get("title", "").split(" · ")[-1].lower()}
    # Web aramasında ismi geçmeyen profil sonuçları kimlik kanıtı sayılmaz
    evs = [e for e in evs if not (e.source == "Web araması" and (not e.accounts or e.match == "none"))]
    ref = _hash_images(evs, ref_path, log)

    parent = list(range(len(evs)))
    reasons = defaultdict(list)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, why, strength):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        reasons[(min(a, b), max(a, b))].append((why, strength))

    # Wikidata kaydı ve onun bildirdiği resmî hesaplar tek kişidir
    wiki = [i for i, e in enumerate(evs) if e.source == "Tanınmış kişi"]
    for i in wiki[1:]:
        union(wiki[0], i, "Wikidata bu hesabı / siteyi kişinin resmî hesabı olarak gösteriyor", "güçlü")
    # Fotoğraf kümeleri: aynı görsel 4'ten fazla farklı isimli hesapta varsa varsayılan avatar sayılır
    photo_groups = []
    for i, e in enumerate(evs):
        if e.hash:
            for g in photo_groups:
                if same_photo(e.hash, evs[g[0]].hash):
                    g.append(i)
                    break
            else:
                photo_groups.append([i])
    for g in photo_groups:
        names = {fold(evs[i].name_seen) for i in g if evs[i].name_seen}
        if 1 < len(g) and not (len(g) > 4 and len(names) > 2):
            for i in g[1:]:
                union(g[0], i, f"Aynı profil fotoğrafı ({evs[g[0]].source} ↔ {evs[i].source})", "güçlü")
    for i, a in enumerate(evs):
        for j in range(i + 1, len(evs)):
            b = evs[j]
            common_u = {u for u in a.usernames & b.usernames if len(u) >= 4}
            if common_u and a.source != b.source:
                union(i, j, f"Aynı kullanıcı adı: {', '.join(sorted(common_u))} ({a.source} ↔ {b.source})", "güçlü")
            if a.emails & b.emails:
                union(i, j, f"Aynı e-posta: {', '.join(sorted(a.emails & b.emails))}", "güçlü")
            decl = {d for d in a.declared | b.declared}
            ids_a = {"user:" + u for u in a.usernames} | {"dom:" + d for d in a.domains}
            ids_b = {"user:" + u for u in b.usernames} | {"dom:" + d for d in b.domains}
            if (a.declared & ids_b) or (b.declared & ids_a):
                union(i, j, f"{a.source if a.declared & ids_b else b.source} hesabı diğerini kendi bağlantısı olarak gösteriyor", "güçlü")
            oa, ob = fold(a.org), fold(b.org)
            if len(oa) >= 4 and oa == ob and (a.match == b.match == "exact" or
                                               (a.location and fold(a.location).split(",")[0] == fold(b.location).split(",")[0])):
                union(i, j, f"Aynı kurum: {a.org}", "orta")

    groups = defaultdict(list)
    for i in range(len(evs)):
        groups[find(i)].append(i)

    place, org = fold(ctx.get("place", "")), fold(ctx.get("org", ""))
    by = str(ctx.get("birth_year") or "").strip()
    known = {k.strip().lower().lstrip("@") for k in re.split(r"[\s,;]+", ctx.get("known") or "") if k.strip()}
    personas = []
    for root, idx in groups.items():
        members = [evs[i] for i in idx]
        srcs = {m.source for m in members}
        score = sum(m.weight for m in members) * (1 + 0.3 * (len(srcs) - 1))
        why = []
        for (a, b), rs in reasons.items():
            if a in idx and b in idx:
                why += rs
        ctx_hits = []
        locs = [m.location for m in members if m.location]
        orgs = [m.org for m in members if m.org]
        if place and any(place in fold(l) for l in locs):
            score += 2
            ctx_hits.append(f"Konum uyuyor: {next(l for l in locs if place in fold(l))}")
        if org and any(org in fold(o) or fold(o) in org for o in orgs if len(fold(o)) >= 3):
            score += 2
            ctx_hits.append(f"Kurum uyuyor: {next(o for o in orgs if org in fold(o) or fold(o) in org)}")
        dates = sorted({d for m in members for d in m.dates})
        if by and any(d[0].startswith(by) and d[1].startswith("Doğum") for d in dates):
            score += 2
            ctx_hits.append(f"Doğum yılı uyuyor: {by}")
        ids = {u for m in members for u in m.usernames} | {e for m in members for e in m.emails}
        if known & ids:
            score += 4
            ctx_hits.append(f"Bilinen hesap / e-posta bu kişide: {', '.join(sorted(known & ids))}")
        if ref and any(same_photo(ref, m.hash) for m in members):
            score += 5
            ctx_hits.append("Yüklediğin referans fotoğrafla aynı görsel kullanılıyor")
        strong = sum(1 for w in why if w[1] == "güçlü")
        conf = "güçlü" if (strong >= 2 and len(srcs) >= 2) or ctx_hits else ("orta" if len(srcs) >= 2 or strong else "zayıf")
        names = Counter(m.name_seen for m in members if m.name_seen and m.match in ("exact", "partial-strong"))
        accounts = []
        for m in members:
            for plat, h, u in m.accounts:
                accounts.append({"platform": plat, "handle": h, "url": u, "source": m.source})
        # zayıf (yalnızca "alınmış" bilinen) kullanıcı adları: bu kişinin adlarıyla aynıysa olası hesap
        maybe_acc = [{"platform": w.row.get("title", "").split(" · ")[0], "handle": next(iter(w.usernames)), "url": w.row.get("url", "")}
                     for w in weak if w.usernames & {u for m in members for u in m.usernames}]
        personas.append({
            "score": round(score, 2), "confidence": conf, "name": names.most_common(1)[0][0] if names else name,
            "photos": list(dict.fromkeys(m.image for m in members if m.image))[:5],
            "location": Counter(locs).most_common(1)[0][0] if locs else "", "org": Counter(orgs).most_common(1)[0][0] if orgs else "",
            "sources": sorted(srcs), "accounts": accounts, "maybe_accounts": maybe_acc[:8],
            "reasons": list(dict.fromkeys(f"{w[0]}" for w in why))[:10], "context": ctx_hits,
            "timeline": [{"date": d[0], "text": d[1], "url": d[2]} for d in dates][:20],
            "rows": sorted(m.rid for m in members),
            "emails": sorted({e for m in members for e in m.emails}),
            "usernames": sorted({u for m in members for u in m.usernames if len(u) >= 3})[:10],
            "exact": any(m.match == "exact" for m in members),
        })
    personas.sort(key=lambda p: -p["score"])
    # Tek bulgulu, adı uymayan, zayıf kişiler gürültüdür; en fazla 10 kişi göster
    personas = [p for p in personas if p["score"] >= 0.5 or p["context"]][:10]
    for n, p in enumerate(personas, 1):
        p["id"] = n
    return personas
