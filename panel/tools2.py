"""İkinci araç paketi: kullanıcı adı / sosyal, e-posta, telefon, görsel, alan adı, arama ve çerçeveler."""
import base64
import email
import glob
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from email import policy
from urllib.parse import quote, urlparse

import requests

import store
from tools import (OSINT_BIN, TOOLS, UA, ToolError, _parse_phone, http_ok, run_cmd, which, F)

S = requests.Session()
S.headers["User-Agent"] = UA


def _get_json(url, **kw):
    r = S.get(url, timeout=kw.pop("timeout", 15), **kw)
    return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") or r.text[:1] in "[{" else None)


def _resolve_ip(target):
    import ipaddress
    import socket
    raw = target.strip()
    try:
        return [str(ipaddress.ip_address(raw))]
    except ValueError:
        host = re.sub(r"^https?://", "", raw).split("/")[0].split(":")[0]
        try:
            return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None) if ":" not in ai[4][0]}) or \
                   sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})
        except socket.gaierror:
            raise ToolError("Geçerli bir IP adresi ya da alan adı girin.")


def _domain(v):
    return re.sub(r"^https?://", "", v.strip()).split("/")[0].split(":")[0].lower().removeprefix("www.")


# ==========================================================================
# 1) user-scanner
# ==========================================================================
def run_user_scanner(job, inp, emit):
    target = inp["target"].strip()
    out = os.path.join(job["dir"], "us.json")
    argv = [os.path.join(OSINT_BIN, "user-scanner"), "-e" if "@" in target else "-u", target,
            "-f", "json", "-o", out, "-t", str(inp.get("timeout") or 10)]
    if not inp.get("nsfw"):
        argv.append("--no-nsfw")
    run_cmd(job, argv, cwd=job["dir"])
    if not os.path.exists(out):
        raise ToolError("user-scanner sonuç üretmedi.")
    for x in json.load(open(out)):
        st = x.get("status")
        if st == "Found" or st == "Registered":
            extra = {k: v for k, v in (x.get("extra") or {}).items() if v not in (None, "", 0)}
            media = x.get("media") or {}
            img = next((v for v in media.values() if isinstance(v, str) and v.startswith("http")), "")
            name = extra.get("name") or extra.get("display_name") or extra.get("full_name") or ""
            emit(title=x.get("site_name"), url=x.get("url", ""), status="found", image=img, detail=str(name),
                 tags=x.get("category", ""), meta=extra)
        elif st == "Error" and inp.get("show_errors"):
            emit(title=x.get("site_name"), url=x.get("url", ""), status="error", detail=x.get("reason", ""))


# ==========================================================================
# 2) GitHub derin profil
# ==========================================================================
def run_github(job, inp, emit):
    user = inp["username"].strip().lstrip("@")
    h = {"Accept": "application/vnd.github+json"}
    tok = store.get("github_token")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    g = lambda path: S.get(f"https://api.github.com{path}", headers=h, timeout=15)
    r = g(f"/users/{quote(user)}")
    if r.status_code == 404:
        raise ToolError("GitHub kullanıcısı bulunamadı.")
    if r.status_code == 403:
        raise ToolError("GitHub API sınırı doldu. Ayarlar'a bir GitHub erişim anahtarı ekleyin ya da bir saat bekleyin.")
    u = r.json()
    emit(title=u.get("name") or u["login"], url=u["html_url"], status="found", image=u.get("avatar_url", ""),
         detail=u.get("bio") or "", tags="Profil",
         meta={"Kullanıcı adı": u["login"], "Şirket": u.get("company"), "Konum": u.get("location"),
               "Blog": u.get("blog"), "Twitter / X": u.get("twitter_username"), "E-posta (profil)": u.get("email"),
               "Hesap açılışı": (u.get("created_at") or "")[:10], "Son güncelleme": (u.get("updated_at") or "")[:10],
               "Takipçi": u.get("followers"), "Herkese açık repo": u.get("public_repos"), "Tür": u.get("type")})
    if u.get("blog"):
        blog = u["blog"] if u["blog"].startswith("http") else "https://" + u["blog"]
        emit(title="Kişisel site", url=blog, status="found", tags="Bağlantı")
    if u.get("twitter_username"):
        emit(title=f"X / Twitter: @{u['twitter_username']}", url=f"https://x.com/{u['twitter_username']}", status="found", tags="Bağlantı")

    # Commit e-postaları: herkese açık olaylar + kendi repolarındaki commit'ler
    emails = Counter()
    names = Counter()
    try:
        for ev in g(f"/users/{quote(user)}/events/public?per_page=100").json() or []:
            for c in (ev.get("payload") or {}).get("commits") or []:
                a = c.get("author") or {}
                if a.get("email"):
                    emails[a["email"].lower()] += 1
                    names[a.get("name", "")] += 1
    except Exception:
        pass
    try:
        repos = g(f"/users/{quote(user)}/repos?sort=pushed&per_page=10&type=owner").json() or []
        own = [x for x in repos if not x.get("fork")][:5]
        for repo in own:
            job["log"](f"Commit'ler okunuyor: {repo['full_name']}")
            for c in g(f"/repos/{repo['full_name']}/commits?author={quote(user)}&per_page=30").json() or []:
                a = ((c.get("commit") or {}).get("author")) or {}
                if a.get("email"):
                    emails[a["email"].lower()] += 1
                    names[a.get("name", "")] += 1
        langs = Counter(x.get("language") for x in repos if x.get("language"))
        if langs:
            emit(title="Kullandığı diller", status="info", detail=", ".join(f"{k} ({v})" for k, v in langs.most_common(6)), tags="Profil")
    except Exception:
        pass
    for e, n in emails.most_common():
        noreply = "noreply" in e
        emit(title=e, status="info" if noreply else "found", tags="Commit e-postası",
             detail=f"{n} commit'te geçiyor" + (" (GitHub gizli adresi)" if noreply else ""), meta={"email": e})
    for n, c in names.most_common(5):
        if n and n.lower() != user.lower():
            emit(title=f"Commit'teki ad: {n}", status="found", detail=f"{c} commit", tags="Commit adı")

    # Anahtarlar ve kuruluşlar
    try:
        keys = S.get(f"https://github.com/{quote(user)}.keys", timeout=10).text.strip().splitlines()
        if keys:
            emit(title=f"{len(keys)} SSH anahtarı", url=f"https://github.com/{user}.keys", status="info",
                 detail="Aynı anahtar başka sunucularda / sitelerde görülürse aynı kişiyi gösterir.", tags="Anahtar")
        for k in g(f"/users/{quote(user)}/gpg_keys").json() or []:
            for e in k.get("emails") or []:
                emit(title=f"GPG anahtarı e-postası: {e.get('email')}", status="found", tags="Anahtar",
                     detail="Doğrulanmış" if e.get("verified") else "Doğrulanmamış", meta={"email": e.get("email")})
        for o in g(f"/users/{quote(user)}/orgs").json() or []:
            emit(title=f"Kuruluş: {o['login']}", url=f"https://github.com/{o['login']}", status="info",
                 image=o.get("avatar_url", ""), tags="Kuruluş")
    except Exception:
        pass


# ==========================================================================
# 3) Reddit / Hacker News / Keybase etkinlik analizi
# ==========================================================================
def _hours_summary(hours_utc):
    """En az etkin 6 saatlik pencereyi 'uyku' sayıp yaklaşık saat dilimi tahmin eder."""
    if len(hours_utc) < 10:
        return None
    hist = Counter(hours_utc)
    counts = [hist.get(h, 0) for h in range(24)]
    best = min(range(24), key=lambda s: sum(counts[(s + i) % 24] for i in range(6)))
    # uyku penceresinin ortasını yerel saatle 04:00 kabul et
    mid = (best + 3) % 24
    off = (4 - mid + 12) % 24 - 12
    return counts, off


def run_social_activity(job, inp, emit):
    user = inp["username"].strip().lstrip("@").removeprefix("u/")
    any_found = False
    all_hours = []

    # Reddit
    try:
        r = S.get(f"https://www.reddit.com/user/{quote(user)}/about.json", timeout=12)
        if r.status_code == 200 and r.json().get("data"):
            d = r.json()["data"]
            any_found = True
            created = time.strftime("%Y-%m-%d", time.gmtime(d.get("created_utc", 0)))
            img = (d.get("snoovatar_img") or d.get("icon_img") or "").split("?")[0]
            emit(title=f"Reddit: u/{d['name']}", url=f"https://www.reddit.com/user/{d['name']}", status="found",
                 image=img, tags="Reddit", detail=(d.get("subreddit") or {}).get("public_description", ""),
                 meta={"Hesap açılışı": created, "Gönderi karması": d.get("link_karma"), "Yorum karması": d.get("comment_karma"),
                       "Doğrulanmış e-posta": "evet" if d.get("has_verified_email") else "hayır"})
            subs = Counter()
            for kind in ("comments", "submitted"):
                c = S.get(f"https://www.reddit.com/user/{quote(user)}/{kind}.json?limit=100", timeout=12)
                for ch in ((c.json().get("data") or {}).get("children") or []) if c.status_code == 200 else []:
                    x = ch.get("data") or {}
                    subs[x.get("subreddit", "")] += 1
                    all_hours.append(time.gmtime(x.get("created_utc", 0)).tm_hour)
            if subs:
                emit(title="Reddit: en etkin topluluklar", status="found", tags="Reddit",
                     detail=", ".join(f"r/{s} ({n})" for s, n in subs.most_common(10)))
        elif r.status_code in (403, 429):
            emit(title="Reddit", url=f"https://www.reddit.com/user/{user}", status="error", tags="Reddit",
                 detail=f"Reddit oturum açmadan API erişimini engelliyor (HTTP {r.status_code}). Profili bağlantıdan el ile kontrol edin.")
        else:
            emit(title="Reddit", status="notfound", detail="Hesap yok", tags="Reddit")
    except Exception as e:
        emit(title="Reddit", status="error", detail=type(e).__name__, tags="Reddit")

    # Hacker News
    try:
        d = S.get(f"https://hacker-news.firebaseio.com/v0/user/{quote(user)}.json", timeout=10).json()
        if d:
            any_found = True
            emit(title=f"Hacker News: {d['id']}", url=f"https://news.ycombinator.com/user?id={d['id']}", status="found",
                 tags="Hacker News", detail=re.sub("<[^>]+>", " ", d.get("about", ""))[:400],
                 meta={"Hesap açılışı": time.strftime("%Y-%m-%d", time.gmtime(d.get("created", 0))), "Karma": d.get("karma"),
                       "Gönderi sayısı": len(d.get("submitted") or [])})
            hits = S.get(f"https://hn.algolia.com/api/v1/search_by_date?tags=author_{quote(user)}&hitsPerPage=200", timeout=12).json().get("hits", [])
            all_hours += [time.gmtime(h["created_at_i"]).tm_hour for h in hits if h.get("created_at_i")]
        else:
            emit(title="Hacker News", status="notfound", detail="Hesap yok", tags="Hacker News")
    except Exception as e:
        emit(title="Hacker News", status="error", detail=type(e).__name__, tags="Hacker News")

    # Keybase: kriptografik olarak doğrulanmış bağlı hesaplar
    try:
        d = S.get(f"https://keybase.io/_/api/1.0/user/lookup.json?usernames={quote(user)}", timeout=10).json()
        them = (d.get("them") or [None])[0]
        if them:
            any_found = True
            prof = them.get("profile") or {}
            pic = (((them.get("pictures") or {}).get("primary")) or {}).get("url", "")
            emit(title=f"Keybase: {user}", url=f"https://keybase.io/{user}", status="found", image=pic, tags="Keybase",
                 detail=" · ".join(x for x in [prof.get("full_name"), prof.get("location"), prof.get("bio")] if x))
            for p in ((them.get("proofs_summary") or {}).get("all") or []):
                emit(title=f"Doğrulanmış hesap: {p.get('proof_type')} · {p.get('nametag')}", url=p.get("service_url") or p.get("proof_url", ""),
                     status="found", tags="Keybase", detail="Keybase üzerinde kriptografik olarak kanıtlanmış")
        else:
            emit(title="Keybase", status="notfound", detail="Hesap yok", tags="Keybase")
    except Exception as e:
        emit(title="Keybase", status="error", detail=type(e).__name__, tags="Keybase")

    hs = _hours_summary(all_hours)
    if hs:
        counts, off = hs
        emit(kind="histogram", title="Etkinlik saatleri (UTC)", status="found", tags="Analiz",
             detail=f"{len(all_hours)} gönderi/yorum. En sessiz saatlere göre tahmini saat dilimi: UTC{off:+d} civarı "
                    f"(Türkiye UTC+3). Kesin değildir; gece çalışanlarda yanılır.",
             meta={str(h): counts[h] for h in range(24)})
    if not any_found:
        job["log"]("Hiçbir platformda hesap bulunamadı.")


# ==========================================================================
# 4) Telegram
# ==========================================================================
def run_telegram(job, inp, emit):
    def meta(html, prop):
        m = re.search(rf'<meta[^>]+property=["\']{prop}["\'][^>]+content=["\']([^"\']*)', html) or \
            re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']{prop}["\']', html)
        import html as h
        return h.unescape(m.group(1)) if m else ""
    names = [n.strip().lstrip("@") for n in re.split(r"[\s,]+", inp["username"]) if n.strip()]
    for n in names[:20]:
        try:
            r = S.get(f"https://t.me/{quote(n)}", timeout=12)
            title, desc, img = meta(r.text, "og:title"), meta(r.text, "og:description"), meta(r.text, "og:image")
            extra = re.search(r'class="tgme_page_extra">\s*([^<]+)', r.text)
            extra = extra.group(1).strip() if extra else ""
            exists = bool(extra) or ("tgme_page_title" in r.text and not title.startswith("Telegram: Contact"))
            if not exists:
                emit(title=f"@{n}", status="notfound", detail="Herkese açık Telegram hesabı / kanalı yok", tags="Telegram")
                continue
            kind = "Kanal" if "subscriber" in extra else ("Grup" if "member" in extra else "Kullanıcı / bot")
            emit(title=f"{title} (@{n})", url=f"https://t.me/{n}", status="found", image=img if "telegram.org/img" not in img else "",
                 detail=desc, tags=f"Telegram · {kind}", meta={"Tür": kind, "Bilgi": extra or "–",
                                                                 "Herkese açık gönderiler": f"https://t.me/s/{n}" if kind != "Kullanıcı / bot" else "–"})
        except Exception as e:
            emit(title=f"@{n}", status="error", detail=type(e).__name__, tags="Telegram")


# ==========================================================================
# 5) Kullanıcı adı varyasyon üretici
# ==========================================================================
TR_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def run_variants(job, inp, emit):
    out = make_variants(inp.get("first") or inp.get("name") or "", inp.get("last") or "", inp.get("nick") or "",
                        inp.get("years") or "", inp.get("seps", "all"))
    limit = int(inp.get("limit") or 60)
    for v in out[:limit]:
        emit(kind="username", title=v, status="found", tags="Varyasyon")
    job["log"](f"{len(out)} varyasyon üretildi, ilk {min(limit, len(out))} gösteriliyor.")


def make_variants(first, last="", nick="", years="", seps_mode="all"):
    """Ad / soyad / takma ad / yıllardan olası kullanıcı adları (en olasıdan başlayarak)."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.translate(TR_MAP).lower())
    first = [norm(x) for x in first.split() if norm(x)]
    last = [norm(x) for x in last.split() if norm(x)]
    nick = [norm(x) for x in nick.split() if norm(x)]
    years = [y for y in re.split(r"[\s,]+", years) if y.isdigit()]
    if not first:
        raise ToolError("En az bir ad girin.")
    seps = [s for s in ["", ".", "_", "-"] if seps_mode == "all" or s == ""]
    parts = first + last
    out = []
    add = lambda v: (len(v) >= 3 and v not in out) and out.append(v)
    from itertools import permutations
    for n in range(len(parts), 0, -1):
        for combo in permutations(parts, n):
            for sep in seps:
                add(sep.join(combo))
    f0, l0 = first[0], (last[-1] if last else "")
    if l0:
        for sep in seps:
            add(f"{f0[0]}{sep}{l0}"); add(f"{f0}{sep}{l0[0]}"); add(f"{l0}{sep}{f0[0]}"); add(f"{l0[0]}{sep}{f0}")
            if len(first) > 1:
                add(f"{''.join(x[0] for x in first)}{sep}{l0}")
    for nk in nick:
        add(nk)
        for sep in seps:
            add(f"{nk}{sep}{l0}") if l0 else None
    base = list(out[:12])
    for y in years:
        for b in base:
            add(f"{b}{y}"); add(f"{b}{y[-2:]}")
            add(f"{b}_{y}") if "_" in seps else None
    return out


# ==========================================================================
# 6) Have I Been Pwned
# ==========================================================================
def run_hibp(job, inp, emit):
    key = store.get("hibp_api_key")
    if not key:
        raise ToolError("HIBP API anahtarı yok. Ayarlar sayfasından ekleyin (haveibeenpwned.com/API/Key).")
    em = inp["email"].strip()
    h = {"hibp-api-key": key, "user-agent": "osint-panel-local"}
    r = S.get(f"https://haveibeenpwned.com/api/v3/breachedaccount/{quote(em)}?truncateResponse=false", headers=h, timeout=15)
    if r.status_code == 401:
        raise ToolError("HIBP API anahtarı geçersiz.")
    if r.status_code == 429:
        raise ToolError("HIBP hız sınırı; birkaç saniye sonra tekrar deneyin.")
    if r.status_code == 404:
        emit(title=em, status="notfound", detail="Bilinen hiçbir sızıntıda geçmiyor.")
    else:
        r.raise_for_status()
        for b in sorted(r.json(), key=lambda x: x.get("BreachDate", ""), reverse=True):
            emit(title=b.get("Title") or b.get("Name"), url=f"https://haveibeenpwned.com/PwnedWebsites#{b.get('Name')}",
                 status="found", image=b.get("LogoPath", ""), tags=b.get("BreachDate", ""),
                 detail="Sızan veriler: " + ", ".join(b.get("DataClasses") or []),
                 meta={"Site": b.get("Domain"), "Sızıntı tarihi": b.get("BreachDate"), "Eklenme": (b.get("AddedDate") or "")[:10],
                       "Etkilenen hesap": f"{b.get('PwnCount', 0):,}".replace(",", "."), "Doğrulanmış": "evet" if b.get("IsVerified") else "hayır"})
    time.sleep(1.6)
    p = S.get(f"https://haveibeenpwned.com/api/v3/pasteaccount/{quote(em)}", headers=h, timeout=15)
    if p.status_code == 200:
        for x in p.json() or []:
            emit(title=f"Paste: {x.get('Source')} {x.get('Title') or ''}".strip(), status="found", tags="Paste",
                 detail=f"{(x.get('Date') or '')[:10]} · {x.get('EmailCount')} e-posta", meta={"Kimlik": x.get("Id")})


# ==========================================================================
# 7) E-posta başlığı çözümleyici
# ==========================================================================
def run_email_header(job, inp, emit):
    import ipaddress
    raw = inp.get("header") or ""
    if inp.get("_file"):
        raw = open(inp["_file"], "rb").read().decode("utf-8", "replace")
    if not raw.strip():
        raise ToolError("E-posta başlığını yapıştırın ya da .eml dosyası yükleyin.")
    msg = email.message_from_string(raw, policy=policy.default)
    dom = lambda a: (re.search(r"@([\w.-]+)", a or "") or [None, ""])[1].lower()
    frm, ret, rep = str(msg.get("From", "")), str(msg.get("Return-Path", "")), str(msg.get("Reply-To", ""))
    for k in ("From", "To", "Subject", "Date", "Reply-To", "Return-Path", "Message-ID", "X-Mailer", "User-Agent", "X-Originating-IP"):
        if msg.get(k):
            emit(title=k, status="found" if k in ("From", "Reply-To", "Return-Path", "X-Originating-IP") else "info",
                 detail=str(msg.get(k))[:300], tags="Başlık")
    if rep and dom(rep) and dom(rep) != dom(frm):
        emit(kind="warn", title="Yanıt adresi farklı", status="found", tags="Uyarı",
             detail=f"Yanıtlar {dom(rep)} alan adına gidiyor, gönderen {dom(frm)} görünüyor. Oltalama belirtisi olabilir.")
    if ret and dom(ret) and dom(ret) != dom(frm):
        emit(kind="warn", title="Geri dönüş adresi farklı", status="found", tags="Uyarı",
             detail=f"Return-Path {dom(ret)}, From {dom(frm)}. Pazarlama servislerinde normaldir, aksi halde şüphelidir.")
    mid = str(msg.get("Message-ID", ""))
    if mid and dom(mid) and dom(frm) and dom(frm) not in dom(mid) and dom(mid) not in dom(frm):
        emit(title="Message-ID alan adı", status="info", tags="Başlık", detail=f"İleti {dom(mid)} sunucusunda oluşturulmuş.")
    auth = " ".join(str(v) for v in msg.get_all("Authentication-Results", []) + msg.get_all("ARC-Authentication-Results", []))
    for m in ("spf", "dkim", "dmarc"):
        res = re.search(rf"\b{m}=(\w+)", auth, re.I)
        if res:
            ok = res.group(1).lower() == "pass"
            emit(title=m.upper(), status="found" if ok else "error", tags="Kimlik doğrulama",
                 detail=("Geçti" if ok else f"Başarısız ({res.group(1)}) — gönderen sahte olabilir"))
    recv = list(reversed(msg.get_all("Received", []) or []))
    prev = None
    seen_ips = []
    for i, h in enumerate(recv, 1):
        h = " ".join(str(h).split())
        ips = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", h)
        pub = []
        for ip in ips:
            try:
                if ipaddress.ip_address(ip).is_global and ip not in seen_ips:
                    pub.append(ip); seen_ips.append(ip)
            except ValueError:
                pass
        frm_h = (re.search(r"from\s+(\S+)", h) or [None, "?"])[1]
        by_h = (re.search(r"by\s+(\S+)", h) or [None, "?"])[1]
        when = h.rsplit(";", 1)[-1].strip() if ";" in h else ""
        delay = ""
        try:
            t = email.utils.parsedate_to_datetime(when)
            if prev:
                delay = f" · +{int((t - prev).total_seconds())} sn"
            prev = t
        except Exception:
            pass
        emit(title=f"Adım {i}: {frm_h} → {by_h}", status="found" if i == 1 and pub else "info", tags="Yol",
             detail=f"{when}{delay}" + (f" · IP: {', '.join(pub)}" if pub else ""), meta={"ip": pub[0]} if pub else {})
    if seen_ips:
        emit(kind="ip", title=f"Gönderenin olası IP'si: {seen_ips[0]}", status="found", tags="Sonuç",
             detail="İlk (en eski) Received başlığındaki herkese açık IP. 'IP konum sorgusu' ile konumuna bakabilirsiniz.",
             meta={"ip": seen_ips[0]})


# ==========================================================================
# 8) Telefon numarası varyasyon araması
# ==========================================================================
def run_phone_search(job, inp, emit):
    import phonenumbers
    n = _parse_phone(inp["number"], inp.get("region") or "TR")
    e164 = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    nat = str(n.national_number)
    natf = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.NATIONAL)
    cc = str(n.country_code)
    forms = list(dict.fromkeys([e164, e164[1:], "0" + nat if cc == "90" else natf, nat, natf,
                                f"+{cc} {nat[:3]} {nat[3:6]} {nat[6:8]} {nat[8:]}".strip(),
                                f"0{nat[:3]} {nat[3:6]} {nat[6:8]} {nat[8:]}".strip() if cc == "90" else "",
                                f"({nat[:3]}) {nat[3:6]} {nat[6:]}", f"{nat[:3]}-{nat[3:6]}-{nat[6:]}",
                                f"0{nat[:3]}-{nat[3:6]}-{nat[6:]}" if cc == "90" else ""]))
    forms = [f for f in forms if f]
    for f in forms:
        emit(title=f, status="info", tags="Yazım biçimi")
    q = " OR ".join(f'"{f}"' for f in forms[:8])
    engines = [("Google", "https://www.google.com/search?q="), ("Bing", "https://www.bing.com/search?q="),
               ("DuckDuckGo", "https://duckduckgo.com/?q="), ("Yandex", "https://yandex.com.tr/search/?text=")]
    for name, base in engines:
        emit(title=f"{name}: tüm biçimler", url=base + quote(q), status="found", tags="Genel arama")
    sites = [("Facebook", "facebook.com"), ("Instagram", "instagram.com"), ("LinkedIn", "linkedin.com"), ("X / Twitter", "x.com"),
             ("TikTok", "tiktok.com"), ("sahibinden", "sahibinden.com"), ("Ekşi Sözlük", "eksisozluk.com"),
             ("Şikayetvar", "sikayetvar.com"), ("Pastebin", "pastebin.com"), ("Telegram", "t.me")]
    short = " OR ".join(f'"{f}"' for f in forms[:4])
    for name, dom in sites:
        emit(title=f"{name} içinde", url="https://www.google.com/search?q=" + quote(f"site:{dom} ({short})"), status="found", tags="Site araması")
    emit(title="Belgelerde (PDF / Excel)", url="https://www.google.com/search?q=" + quote(f"({short}) (filetype:pdf OR filetype:xls OR filetype:xlsx OR filetype:doc)"),
         status="found", tags="Belge")


# ==========================================================================
# 9) Görsel konum tahmini (Claude görsel modeli)
# ==========================================================================
GEO_SCHEMA = {
    "type": "object",
    "properties": {
        "best_guess": {"type": "string", "description": "En olası yer: ülke, şehir, mümkünse semt / sokak"},
        "latitude": {"type": "number"},
        "longitude": {"type": "number"},
        "confidence": {"type": "string", "enum": ["düşük", "orta", "yüksek"]},
        "radius_km": {"type": "number", "description": "Tahminin yaklaşık belirsizlik yarıçapı"},
        "clues": {"type": "array", "items": {"type": "object", "properties": {
            "clue": {"type": "string"}, "inference": {"type": "string"}}, "required": ["clue", "inference"], "additionalProperties": False}},
        "alternatives": {"type": "array", "items": {"type": "object", "properties": {
            "place": {"type": "string"}, "latitude": {"type": "number"}, "longitude": {"type": "number"}, "why": {"type": "string"}},
            "required": ["place", "latitude", "longitude", "why"], "additionalProperties": False}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["best_guess", "latitude", "longitude", "confidence", "radius_km", "clues", "alternatives", "next_steps"],
    "additionalProperties": False,
}
GEO_PROMPT = """Bu fotoğrafın çekildiği yeri bir OSINT coğrafi konum uzmanı gibi tahmin et.
Görünen ipuçlarını tek tek değerlendir: tabelalar ve dil, plakalar, yol çizgileri ve trafik işaretleri, mimari, bitki örtüsü,
iklim ve güneşin açısı, elektrik direkleri, araçların hangi şeritten gittiği, mağaza / marka adları, arazi şekli.
Her ipucunun neyi gösterdiğini kısaca yaz. Emin olmadığın yerde güveni düşük tut; uydurma ayrıntı ekleme.
Yanıtın tamamı Türkçe olsun."""


def run_geolocate(job, inp, emit):
    from tools import _image_to_file
    import anthropic
    path = _image_to_file(job, inp)
    data = open(path, "rb").read()
    # Büyük / desteklenmeyen biçimleri JPEG'e çevir (API en fazla ~5 MB görsel kabul eder)
    mt = {b"\xff\xd8": "image/jpeg", b"\x89P": "image/png", b"GI": "image/gif", b"RI": "image/webp"}.get(data[:2])
    if mt is None or len(data) > 4_500_000:
        conv = os.path.join(job["dir"], "geo.jpg")
        if subprocess.run(["sips", "-s", "format", "jpeg", "-Z", "2000", path, "--out", conv], capture_output=True).returncode != 0:
            raise ToolError("Görsel okunamadı.")
        data, mt = open(conv, "rb").read(), "image/jpeg"
    job["files"]["photo"] = (path, mt)
    emit(kind="figure", title="İncelenen fotoğraf", status="info", image=f"/api/jobfile/{job['id']}/photo")

    key = store.get("anthropic_api_key")
    try:
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    except Exception:
        client = None
    if client is None or not (key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        _geo_manual(emit)
        raise ToolError("Görsel konum tahmini için Ayarlar'a bir Anthropic API anahtarı ekleyin. "
                        "Anahtarsız kullanım için aşağıdaki el ile inceleme bağlantılarını kullanabilirsiniz.")
    job["log"]("Fotoğraf Claude'a gönderiliyor (claude-opus-5-5)…")
    try:
        resp = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": GEO_SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mt, "data": base64.standard_b64encode(data).decode()}},
                {"type": "text", "text": GEO_PROMPT + (f"\nEk bağlam: {inp['context']}" if inp.get("context") else "")},
            ]}],
        )
    except anthropic.AuthenticationError:
        raise ToolError("Anthropic API anahtarı geçersiz.")
    except anthropic.RateLimitError:
        raise ToolError("Anthropic API hız sınırı; biraz sonra tekrar deneyin.")
    except anthropic.APIStatusError as e:
        raise ToolError(f"Anthropic API hatası ({e.status_code}): {e.message}"[:300])
    except anthropic.APIConnectionError:
        raise ToolError("Anthropic API'ye bağlanılamadı.")
    if resp.stop_reason == "refusal":
        raise ToolError("Model bu görsel için konum tahmini yapmayı reddetti.")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        g = json.loads(text)
    except Exception:
        raise ToolError("Model yanıtı çözümlenemedi.")
    lat, lon = g["latitude"], g["longitude"]
    emit(kind="gps", title=f"Tahmin: {g['best_guess']}", status="found", lat=lat, lon=lon,
         url=f"https://www.google.com/maps?q={lat},{lon}",
         detail=f"Güven: {g['confidence']} · yaklaşık ±{g['radius_km']:.0f} km. Yapay zekâ tahminidir, doğrulanmalıdır.",
         meta={"Model": resp.model, "Koordinat": f"{lat:.5f}, {lon:.5f}"})
    for c in g.get("clues", []):
        emit(title=c["clue"], detail=c["inference"], status="found", tags="İpucu")
    for a in g.get("alternatives", []):
        emit(title=f"Alternatif: {a['place']}", url=f"https://www.google.com/maps?q={a['latitude']},{a['longitude']}",
             detail=a["why"], status="maybe", tags="Alternatif")
    for s in g.get("next_steps", []):
        emit(title=s, status="info", tags="Doğrulama adımı")
    emit(title="Street View'da kontrol et", url=f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}",
         status="info", tags="Doğrulama adımı")


def _geo_manual(emit):
    for name, url in [("GeoSpy (web)", "https://geospy.ai"), ("Picarta (web)", "https://picarta.ai"),
                      ("Google Lens", "https://lens.google.com"), ("Yandex Görseller", "https://yandex.com/images/"),
                      ("SunCalc (gölge / güneş açısı)", "https://www.suncalc.org"), ("Overpass Turbo (harita sorgusu)", "https://overpass-turbo.eu")]:
        emit(title=name, url=url, status="info", tags="El ile inceleme")


# ==========================================================================
# 10) Görsel karşılaştırma (perceptual hash)
# ==========================================================================
def _load_images(job, inp, limit=20):
    from PIL import Image
    srcs = [u.strip() for u in re.split(r"[\s,]+", inp.get("urls") or "") if http_ok(u.strip())]
    imgs = []
    for i, u in enumerate(srcs[:limit]):
        try:
            r = S.get(u, timeout=15)
            r.raise_for_status()
            p = os.path.join(job["dir"], f"img{i}")
            open(p, "wb").write(r.content)
            imgs.append((u, p))
        except Exception as e:
            job["log"](f"İndirilemedi: {u} ({type(e).__name__})")
    for j, p in enumerate(inp.get("_files") or ([inp["_file"]] if inp.get("_file") else [])):
        imgs.append((os.path.basename(p).removeprefix("upload_"), p))
    out = []
    for label, p in imgs:
        try:
            im = Image.open(p)
            im.load()
            out.append((label, p, im))
        except Exception:
            # HEIC vb.: sips ile JPEG'e çevir
            conv = p + ".jpg"
            if subprocess.run(["sips", "-s", "format", "jpeg", p, "--out", conv], capture_output=True).returncode == 0:
                im = Image.open(conv); im.load(); out.append((label, conv, im))
            else:
                job["log"](f"Görsel açılamadı: {label}")
    return out


def run_image_compare(job, inp, emit):
    import imagehash
    imgs = _load_images(job, inp)
    if len(imgs) < 2:
        raise ToolError("Karşılaştırmak için en az iki görsel (URL ya da dosya) gerekli.")
    hashes = []
    for i, (label, p, im) in enumerate(imgs):
        rgb = im.convert("RGB")
        hashes.append((imagehash.phash(rgb), imagehash.dhash(rgb), imagehash.colorhash(rgb)))
        name = f"img{i}"
        job["files"][name] = (p, "image/jpeg" if p.endswith(".jpg") else (Image_mime(im)))
        emit(kind="figure", title=f"#{i + 1}", detail=label, status="info", image=f"/api/jobfile/{job['id']}/{name}",
             tags="Görsel", meta={"pHash": str(hashes[-1][0]), "Boyut": f"{im.width}×{im.height}"})
    pairs = []
    for a in range(len(imgs)):
        for b in range(a + 1, len(imgs)):
            ph = 1 - (hashes[a][0] - hashes[b][0]) / 64
            dh = 1 - (hashes[a][1] - hashes[b][1]) / 64
            sim = round((ph * 0.6 + dh * 0.4) * 100)
            pairs.append((sim, a, b))
    for sim, a, b in sorted(pairs, reverse=True):
        verdict = "Aynı görsel (ya da kırpılmış / yeniden boyutlandırılmış kopyası)" if sim >= 90 else \
                  "Çok benzer, büyük olasılıkla aynı kaynaktan" if sim >= 80 else \
                  "Kısmen benzer" if sim >= 65 else "Farklı görseller"
        emit(title=f"#{a + 1} ↔ #{b + 1}: %{sim} benzer", status="found" if sim >= 80 else "info",
             detail=f"{verdict}. ({imgs[a][0]} ↔ {imgs[b][0]})", tags="Karşılaştırma")


def Image_mime(im):
    return {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}.get(im.format or "", "image/jpeg")


# ==========================================================================
# 11) Görsel sahtecilik analizi (ELA)
# ==========================================================================
def run_ela(job, inp, emit):
    from PIL import Image, ImageChops, ImageEnhance
    imgs = _load_images(job, {"urls": inp.get("url", ""), "_file": inp.get("_file")}, limit=1)
    if not imgs:
        raise ToolError("Bir görsel URL'si girin ya da dosya yükleyin.")
    label, p, im = imgs[0]
    orig = im.convert("RGB")
    q = int(inp.get("quality") or 90)
    buf = io.BytesIO()
    orig.save(buf, "JPEG", quality=q)
    buf.seek(0)
    diff = ImageChops.difference(orig, Image.open(buf))
    extrema = diff.getextrema()
    mx = max(e[1] for e in extrema) or 1
    ela = ImageEnhance.Brightness(diff).enhance(255.0 / mx * float(inp.get("scale") or 1.0))
    op = os.path.join(job["dir"], "orig.jpg"); orig.save(op, "JPEG", quality=95)
    ep = os.path.join(job["dir"], "ela.png"); ela.save(ep)
    job["files"]["orig"] = (op, "image/jpeg")
    job["files"]["ela"] = (ep, "image/png")
    # Bölgesel tutarsızlık: 8x8 ızgarada ortalama hata
    import statistics
    g = diff.convert("L").resize((8, 8))
    cells = list(g.getdata())
    mean, sd = statistics.mean(cells), statistics.pstdev(cells) or 1
    hot = [i for i, c in enumerate(cells) if c > mean + 2 * sd]
    emit(kind="figure", title="Orijinal", status="info", image=f"/api/jobfile/{job['id']}/orig", detail=label)
    emit(kind="figure", title="Hata seviyesi analizi (ELA)", status="found", image=f"/api/jobfile/{job['id']}/ela",
         detail="Parlak bölgeler, görüntünün geri kalanından farklı sıkıştırılmış alanlardır. Sonradan eklenen / değiştirilen "
                "parçalar genelde çevresinden belirgin şekilde parlak görünür. Kenarlar ve yazılar doğal olarak parlaktır.")
    emit(title="En yüksek fark", status="info", detail=f"{mx} / 255 (JPEG kalite {q} ile yeniden kaydedildi)")
    if hot:
        names = ["sol üst", "üst", "sağ üst", "sol", "orta", "sağ", "sol alt", "alt", "sağ alt"]
        zones = sorted({names[(i // 8 * 3 // 8) * 3 + (i % 8 * 3 // 8)] for i in hot})
        emit(kind="warn", title="Dikkat çeken bölgeler", status="found",
             detail=f"Ortalamadan belirgin şekilde farklı hata oranı: {', '.join(zones)}. Bu bölgeleri yakından inceleyin.")
    else:
        emit(title="Bölgesel tutarsızlık", status="info", detail="Belirgin bir aykırı bölge bulunmadı.")
    emit(title="Not", status="info", detail="ELA kesin kanıt değildir; birden çok kez kaydedilmiş, küçültülmüş ya da PNG'den "
                                            "dönüştürülmüş görsellerde yanıltıcı olabilir. ExifTool'daki düzenleme izleriyle birlikte değerlendirin.")


# ==========================================================================
# 12) Video meta verisi ve kare çıkarma
# ==========================================================================
def run_video(job, inp, emit):
    url = inp["url"].strip()
    ytdlp = os.path.join(OSINT_BIN, "yt-dlp")
    text, code = run_cmd(job, [ytdlp, "--dump-json", "--no-warnings", "--skip-download", url], timeout=120)
    js = next((l for l in text.splitlines() if l.startswith("{")), None)
    if not js:
        raise ToolError("Video bilgisi alınamadı (desteklenmeyen site, gizli ya da silinmiş video).")
    d = json.loads(js)
    up = d.get("upload_date") or ""
    if len(up) == 8:
        up = f"{up[:4]}-{up[4:6]}-{up[6:]}"
    dur = int(d.get("duration") or 0)
    emit(title=d.get("title", "?"), url=d.get("webpage_url", url), status="found", image=d.get("thumbnail", ""),
         detail=(d.get("description") or "")[:600], tags=d.get("extractor_key", ""),
         meta={"Yükleyen": d.get("uploader"), "Kanal": d.get("channel_url") or d.get("uploader_url"), "Yükleme tarihi": up,
               "Süre": f"{dur // 60}:{dur % 60:02d}", "İzlenme": d.get("view_count"), "Beğeni": d.get("like_count"),
               "Konum": d.get("location"), "Etiketler": ", ".join((d.get("tags") or [])[:15]), "Video ID": d.get("id")})
    if d.get("uploader_url") or d.get("channel_url"):
        emit(title=f"Yükleyen: {d.get('uploader')}", url=d.get("uploader_url") or d.get("channel_url"), status="found", tags="Kanal")
    for t in (d.get("thumbnails") or [])[-1:]:
        pass
    if not inp.get("frames", True) or inp.get("frames") == "off":
        return
    ffmpeg = which("ffmpeg", "/opt/homebrew/bin/ffmpeg")
    if not ffmpeg:
        emit(title="Kare çıkarma", status="error", detail="ffmpeg bulunamadı.")
        return
    secs = min(int(inp.get("seconds") or 60), 300)
    step = max(int(inp.get("interval") or 10), 1)
    vid = os.path.join(job["dir"], "video.mp4")
    job["log"](f"İlk {secs} saniye düşük çözünürlükte indiriliyor…")
    run_cmd(job, [ytdlp, "-f", "worst[ext=mp4]/worst", "--download-sections", f"*0-{secs}", "--no-warnings",
                  "-o", vid, url], timeout=300)
    cand = glob.glob(os.path.join(job["dir"], "video*"))
    if not cand:
        emit(title="Kare çıkarma", status="error", detail="Video indirilemedi.")
        return
    run_cmd(job, [ffmpeg, "-loglevel", "error", "-i", cand[0], "-vf", f"fps=1/{step},scale=640:-2",
                  os.path.join(job["dir"], "frame_%03d.jpg")], timeout=180)
    for i, fp in enumerate(sorted(glob.glob(os.path.join(job["dir"], "frame_*.jpg")))[:40]):
        name = f"frame{i}"
        job["files"][name] = (fp, "image/jpeg")
        emit(kind="figure", title=f"{i * step} sn", status="found", image=f"/api/jobfile/{job['id']}/{name}",
             tags="Kare", detail="Ters görsel aramaya / ExifTool'a gönderilebilir.")


# ==========================================================================
# 13) Sertifika şeffaflığı (crt.sh)
# ==========================================================================
def run_crtsh(job, inp, emit):
    d = _domain(inp["domain"])
    job["log"]("crt.sh sorgulanıyor (birkaç saniye sürebilir)…")
    rows = None
    for attempt in range(2):
        try:
            r = S.get(f"https://crt.sh/?q={quote('%.' + d)}&output=json", timeout=45)
            if r.status_code == 200:
                rows = r.json()
                break
            job["log"](f"crt.sh HTTP {r.status_code}")
        except Exception as e:
            job["log"](f"crt.sh hatası: {type(e).__name__}")
        time.sleep(2)
    if rows is None:
        # Yedek: Cert Spotter (SSLMate) — anahtarsız, saatlik sınırlı
        job["log"]("crt.sh yanıt vermedi; Cert Spotter kullanılıyor…")
        r = S.get("https://api.certspotter.com/v1/issuances", timeout=45,
                  params={"domain": d, "include_subdomains": "true", "expand": ["dns_names", "issuer"]})
        if r.status_code != 200:
            raise ToolError(f"crt.sh ve Cert Spotter yanıt vermedi (HTTP {r.status_code}); biraz sonra tekrar deneyin.")
        rows = [{"name_value": "\n".join(x.get("dns_names") or []), "not_before": x.get("not_before", ""),
                 "issuer_name": "O=" + ((x.get("issuer") or {}).get("friendly_name") or (x.get("issuer") or {}).get("name") or "?")}
                for x in r.json()]
    names = {}
    issuers = Counter()
    for x in rows:
        issuers[re.sub(r".*O=([^,]+).*", r"\1", x.get("issuer_name", ""))] += 1
        for n in (x.get("name_value") or "").lower().split("\n"):
            n = n.strip().lstrip("*.")
            if n.endswith(d):
                first = names.get(n)
                nb = (x.get("not_before") or "")[:10]
                names[n] = min(first, nb) if first else nb
    emit(title=f"{len(rows)} sertifika · {len(names)} benzersiz ad", status="info", tags="Özet",
         detail="Sertifika verenler: " + ", ".join(f"{k} ({v})" for k, v in issuers.most_common(5)))
    for n, first in sorted(names.items(), key=lambda kv: kv[1] or "", reverse=True):
        emit(title=n, url=f"https://{n}", status="found", tags="Alt alan adı", detail=f"İlk sertifika: {first}")


# ==========================================================================
# 14) subfinder + httpx
# ==========================================================================
def run_subfinder(job, inp, emit):
    d = _domain(inp["domain"])
    sub = which("subfinder", "/opt/homebrew/bin/subfinder")
    hx = which("httpx", "/opt/homebrew/bin/httpx")
    subs_path = os.path.join(job["dir"], "subs.txt")
    run_cmd(job, [sub, "-d", d, "-silent", "-all" if inp.get("all") else "-recursive", "-o", subs_path], timeout=600)
    subs = sorted(set(open(subs_path).read().split())) if os.path.exists(subs_path) else []
    if not subs:
        raise ToolError("Alt alan adı bulunamadı.")
    job["log"](f"{len(subs)} alt alan adı bulundu; canlı olanlar httpx ile kontrol ediliyor…")
    if not inp.get("probe", True) or inp.get("probe") == "off" or not hx:
        for s in subs:
            emit(title=s, url=f"https://{s}", status="info", tags="Alt alan adı")
        return
    out = os.path.join(job["dir"], "httpx.json")
    run_cmd(job, [hx, "-l", subs_path, "-silent", "-json", "-title", "-tech-detect", "-status-code", "-ip",
                  "-web-server", "-follow-redirects", "-timeout", "8", "-threads", "40", "-o", out], timeout=900)
    live = {}
    if os.path.exists(out):
        for line in open(out):
            try:
                x = json.loads(line)
            except Exception:
                continue
            host = x.get("input") or x.get("host")
            live[host] = x
            emit(title=host, url=x.get("url", ""), status="found", tags=f"HTTP {x.get('status_code', '?')}",
                 detail=" · ".join(v for v in [x.get("title"), x.get("webserver"), ", ".join(x.get("tech") or [])] if v),
                 meta={"IP": ", ".join(x.get("a") or []) if isinstance(x.get("a"), list) else x.get("host"),
                       "Durum": x.get("status_code"), "Teknolojiler": ", ".join(x.get("tech") or [])})
    for s in subs:
        if s not in live:
            emit(title=s, status="info", tags="Yanıt yok", detail="DNS'te var ama web sunucusu yanıt vermedi.")


# ==========================================================================
# 15) dnstwist
# ==========================================================================
def run_dnstwist(job, inp, emit):
    d = _domain(inp["domain"])
    argv = [os.path.join(OSINT_BIN, "dnstwist"), "-r", "-f", "json", "-t", "40"]
    if inp.get("mx"):
        argv.append("--mxcheck")
    if inp.get("whois"):
        argv.append("--whois")
    argv.append(d)
    text, _ = run_cmd(job, argv, timeout=900)
    try:
        data = json.loads(text[text.find("["):text.rfind("]") + 1])
    except Exception:
        raise ToolError("dnstwist çıktısı okunamadı.")
    for x in data:
        if x.get("fuzzer") == "*original":
            continue
        a = ", ".join(x.get("dns_a") or [])
        mx = ", ".join(x.get("dns_mx") or [])
        emit(title=x["domain"], url=f"http://{x['domain']}", status="found" if mx or a else "info",
             tags=x.get("fuzzer", ""), detail=" · ".join(v for v in [f"A: {a}" if a else "", f"MX: {mx}" if mx else "",
                                                                     f"Kayıt: {x.get('whois_created', '')}" if x.get("whois_created") else ""] if v),
             meta={"Yöntem": x.get("fuzzer"), "NS": ", ".join(x.get("dns_ns") or []),
                   "Posta alabilir": "evet" if mx else "hayır"})


# ==========================================================================
# 16) Wayback Machine
# ==========================================================================
def run_wayback(job, inp, emit):
    target = inp["url"].strip()
    mode = inp.get("mode") or "page"
    base = "https://web.archive.org/cdx/search/cdx"
    if mode == "domain":
        d = _domain(target)
        params = {"url": f"{d}/*", "output": "json", "fl": "timestamp,original,mimetype,statuscode", "collapse": "urlkey",
                  "limit": str(int(inp.get("limit") or 500))}
    else:
        params = {"url": re.sub(r"^https?://", "", target), "output": "json", "fl": "timestamp,original,statuscode,digest",
                  "collapse": "digest", "limit": str(int(inp.get("limit") or 500))}
    job["log"]("Web arşivi sorgulanıyor…")
    r = S.get(base, params=params, timeout=90)
    if r.status_code != 200:
        raise ToolError(f"Wayback Machine yanıt vermedi (HTTP {r.status_code}).")
    rows = r.json()[1:] if r.text.strip() else []
    if not rows:
        emit(title=target, status="notfound", detail="Bu adres web arşivinde hiç kaydedilmemiş.")
        emit(title="Şimdi arşivle", url=f"https://web.archive.org/save/{target}", status="info", detail="Sayfanın bugünkü halini arşive kaydettirir.")
        return
    fmt = lambda ts: f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[8:10]}:{ts[10:12]}"
    if mode == "domain":
        types = Counter(x[2] for x in rows)
        emit(title=f"{len(rows)} farklı adres arşivde", status="info", tags="Özet",
             detail="Türler: " + ", ".join(f"{k} ({v})" for k, v in types.most_common(6)))
        interesting = re.compile(r"\.(pdf|docx?|xlsx?|pptx?|csv|txt|zip|sql|bak|json|xml)$|/(admin|login|wp-admin|api|backup|config)", re.I)
        for ts, orig, mt, sc in sorted(rows, key=lambda x: (not interesting.search(x[1]), x[1])):
            emit(title=orig, url=f"https://web.archive.org/web/{ts}/{orig}", status="found" if interesting.search(orig) else "info",
                 tags=mt, detail=f"Son görülme: {fmt(ts)} · HTTP {sc}")
    else:
        emit(title=f"{len(rows)} farklı sürüm", status="info", tags="Özet",
             detail=f"İlk kayıt: {fmt(rows[0][0])} · Son kayıt: {fmt(rows[-1][0])}. İçerik değişikliği olan sürümler listeleniyor.")
        for ts, orig, sc, dg in reversed(rows):
            emit(title=fmt(ts), url=f"https://web.archive.org/web/{ts}/{orig}", status="found" if sc == "200" else "info",
                 tags=f"HTTP {sc}", detail=orig)


# ==========================================================================
# 17) Web sitesi teknoloji ve izleyici analizi
# ==========================================================================
TRACKERS = [
    ("Google Analytics (UA)", r"\bUA-\d{4,10}-\d{1,4}\b"),
    ("Google Analytics 4", r"\bG-[A-Z0-9]{8,12}\b"),
    ("Google Tag Manager", r"\bGTM-[A-Z0-9]{5,9}\b"),
    ("Google AdSense", r"\bca-pub-\d{10,20}\b|\bpub-\d{16}\b"),
    ("Google Ads", r"\bAW-\d{9,11}\b"),
    ("Meta (Facebook) Pixel", r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{10,20})['\"]"),
    ("Yandex Metrica", r"ym\((\d{6,10}),\s*['\"]init|mc\.yandex\.ru/watch/(\d{6,10})"),
    ("Hotjar", r"hjid\s*:\s*(\d{5,10})"),
    ("Microsoft Clarity", r"clarity\.ms/tag/([a-z0-9]{8,12})"),
    ("TikTok Pixel", r"ttq\.load\(['\"]([A-Z0-9]{15,25})['\"]"),
    ("LinkedIn Insight", r"_linkedin_partner_id\s*=\s*['\"](\d{5,10})"),
]
TECH = [("WordPress", r"wp-content|wp-includes"), ("Shopify", r"cdn\.shopify\.com"), ("Wix", r"static\.wixstatic\.com"),
        ("Squarespace", r"squarespace\.com"), ("Ghost", r"ghost\.io|content=\"Ghost"), ("Joomla", r"/media/jui/|Joomla!"),
        ("Drupal", r"Drupal\.settings|/sites/default/files"), ("Next.js", r"/_next/static"), ("Nuxt", r"/_nuxt/"),
        ("React", r"react(-dom)?(\.production)?\.min\.js|data-reactroot"), ("Vue", r"vue(\.runtime)?(\.min)?\.js"),
        ("Cloudflare", r"cdnjs\.cloudflare\.com|cf-ray"), ("Ticimax", r"ticimax"), ("IdeaSoft", r"ideasoft"), ("T-Soft", r"tsoft")]


def run_site_intel(job, inp, emit):
    url = inp["url"].strip()
    if not url.startswith("http"):
        url = "https://" + url
    r = S.get(url, timeout=20, allow_redirects=True)
    html = r.text
    d = _domain(r.url)
    emit(title=r.url, url=r.url, status="info", tags="Sayfa", detail=f"HTTP {r.status_code} · {len(html) // 1024} KB",
         meta={k: r.headers.get(k) for k in ("server", "x-powered-by", "via", "cf-ray", "x-generator") if r.headers.get(k)})
    gen = re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if gen:
        emit(title="Üretici (generator)", status="found", detail=gen.group(1), tags="Teknoloji")
    found_tech = [n for n, rx in TECH if re.search(rx, html + str(r.headers), re.I)]
    if found_tech:
        emit(title="Teknolojiler", status="info", detail=", ".join(found_tech), tags="Teknoloji")
    ids = []
    for name, rx in TRACKERS:
        for m in re.finditer(rx, html):
            v = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
            if v and (name, v) not in ids:
                ids.append((name, v))
    if not ids:
        emit(title="İzleme kimliği bulunamadı", status="notfound",
             detail="Sayfada Google Analytics / AdSense / Pixel kimliği yok ya da JavaScript ile sonradan yükleniyor.")
    for name, v in ids:
        emit(title=f"{name}: {v}", status="found", tags="İzleme kimliği",
             detail="Aynı kimliği kullanan başka siteler büyük olasılıkla aynı kişi / firmaya aittir.",
             meta={"Kimlik": v})
        emit(title=f"↳ {v} kullanan diğer siteler (PublicWWW)", url=f"https://publicwww.com/websites/%22{quote(v)}%22/",
             status="info", tags="Ters arama")
        emit(title=f"↳ {v} Google'da", url="https://www.google.com/search?q=" + quote(f'"{v}"'), status="info", tags="Ters arama")
    emit(title="BuiltWith ilişkileri", url=f"https://builtwith.com/relationships/{d}", status="info", tags="Ters arama",
         detail="Bu siteyle aynı izleme kimliklerini paylaşan siteler")
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", html)) - {""})
    for e in [e for e in emails if not e.endswith((".png", ".jpg", ".gif", ".webp", ".svg"))][:20]:
        emit(title=e, status="found", tags="Sayfadaki e-posta", meta={"email": e})
    socials = sorted(set(re.findall(r"https?://(?:www\.)?(?:instagram\.com|facebook\.com|x\.com|twitter\.com|linkedin\.com/(?:in|company)|"
                                    r"youtube\.com/(?:@|c/|channel/)|tiktok\.com/@|t\.me|github\.com)/[\w.@/-]+", html)))
    for s in socials[:30]:
        emit(title=s, url=s, status="found", tags="Sosyal bağlantı")


# ==========================================================================
# 18) Shodan
# ==========================================================================
def run_shodan(job, inp, emit):
    key = store.get("shodan_api_key")
    for ip in _resolve_ip(inp["target"])[:5]:
        if key:
            r = S.get(f"https://api.shodan.io/shodan/host/{ip}?key={key}", timeout=20)
            if r.status_code == 200:
                d = r.json()
                emit(title=f"{ip} · {d.get('org') or d.get('isp') or ''}", status="found", tags="Shodan",
                     detail=f"{d.get('city') or ''} {d.get('country_name') or ''} · İşletim sistemi: {d.get('os') or '?'}",
                     meta={"Açık portlar": ", ".join(map(str, d.get("ports") or [])), "Ana bilgisayar adları": ", ".join(d.get("hostnames") or []),
                           "Etiketler": ", ".join(d.get("tags") or []), "Son tarama": d.get("last_update")})
                for s in d.get("data") or []:
                    prod = " ".join(x for x in [s.get("product"), s.get("version")] if x)
                    banner = (s.get("data") or "").strip().splitlines()[0][:160] if s.get("data") else ""
                    emit(title=f"{ip}:{s.get('port')}/{s.get('transport', 'tcp')} {prod}".strip(), status="found", tags="Hizmet",
                         detail=banner, url=f"https://www.shodan.io/host/{ip}")
                for v in list((d.get("vulns") or {}))[:30]:
                    emit(title=v, url=f"https://nvd.nist.gov/vuln/detail/{v}", status="found", tags="Bilinen açık")
                continue
            job["log"](f"Shodan API: HTTP {r.status_code}, InternetDB'ye geçiliyor.")
        r = S.get(f"https://internetdb.shodan.io/{ip}", timeout=15)
        if r.status_code == 404:
            emit(title=ip, status="notfound", detail="Shodan bu IP'yi taramamış ya da açık port yok.", tags="InternetDB")
            continue
        d = r.json()
        emit(title=ip, url=f"https://www.shodan.io/host/{ip}", status="found", tags="InternetDB (ücretsiz)",
             detail="Açık portlar: " + (", ".join(map(str, d.get("ports") or [])) or "yok"),
             meta={"Ana bilgisayar adları": ", ".join(d.get("hostnames") or []) or "–", "Etiketler": ", ".join(d.get("tags") or []) or "–",
                   "Yazılımlar (CPE)": ", ".join(d.get("cpes") or []) or "–"})
        for v in (d.get("vulns") or [])[:30]:
            emit(title=v, url=f"https://nvd.nist.gov/vuln/detail/{v}", status="found", tags="Bilinen açık")


# ==========================================================================
# 19) Google Dork üretici
# ==========================================================================
def run_dorks(job, inp, emit):
    kind = inp.get("kind") or "name"
    v = inp["value"].strip()
    extra = (inp.get("extra") or "").strip()
    q = f'"{v}"'
    ex = f' "{extra}"' if extra else ""
    sets = {
        "name": [("Genel", f"{q}{ex}"), ("LinkedIn", f"site:linkedin.com/in {q}{ex}"), ("Facebook", f"site:facebook.com {q}{ex}"),
                 ("Instagram", f"site:instagram.com {q}"), ("X / Twitter", f"site:x.com OR site:twitter.com {q}"),
                 ("Belgeler", f"{q}{ex} (filetype:pdf OR filetype:doc OR filetype:docx OR filetype:xls OR filetype:xlsx)"),
                 ("Özgeçmiş", f"{q} (cv OR özgeçmiş OR resume) filetype:pdf"), ("Haberler", f"{q}{ex} (haber OR news)"),
                 ("Resmi Gazete / ilanlar", f"site:resmigazete.gov.tr OR site:ilan.gov.tr {q}"),
                 ("Akademik", f"site:dergipark.org.tr OR site:scholar.google.com OR site:researchgate.net {q}"),
                 ("Ekşi Sözlük", f"site:eksisozluk.com {q}"), ("Şikayetvar", f"site:sikayetvar.com {q}"),
                 ("Fotoğraflar", f"{q}{ex} (inurl:photo OR inurl:foto OR inurl:image)")],
        "username": [("Genel", q), ("Profil sayfaları", f'inurl:"{v}" -site:github.com'), ("Forumlar", f"{q} (forum OR topic OR thread)"),
                     ("Pastebin vb.", f"site:pastebin.com OR site:ghostbin.co OR site:justpaste.it {q}"),
                     ("GitHub kod", f"site:github.com {q}"), ("Reddit", f"site:reddit.com {q}"), ("YouTube", f"site:youtube.com {q}"),
                     ("E-posta olarak", f'"{v}@gmail.com" OR "{v}@hotmail.com" OR "{v}@outlook.com" OR "{v}@yahoo.com"')],
        "email": [("Genel", q), ("Belgelerde", f"{q} (filetype:pdf OR filetype:xls OR filetype:xlsx OR filetype:csv OR filetype:txt)"),
                  ("Paste siteleri", f"site:pastebin.com OR site:justpaste.it {q}"), ("Sosyal", f"{q} (site:facebook.com OR site:linkedin.com OR site:x.com)"),
                  ("Kullanıcı adı olarak", f'"{v.split("@")[0]}"'), ("Alan adı çalışanları", f'"@{v.split("@")[-1]}" -"{v}"')],
        "phone": [("Genel", q), ("Boşluklu", f'"{v[:4]} {v[4:7]} {v[7:9]} {v[9:]}"' if len(v) >= 10 else q),
                  ("İlanlar", f"site:sahibinden.com OR site:letgo.com OR site:arabam.com {q}"), ("Belgeler", f"{q} filetype:pdf"),
                  ("Sosyal", f"{q} (site:facebook.com OR site:instagram.com OR site:x.com)")],
        "domain": [("Tüm sayfalar", f"site:{v}"), ("Alt alan adları", f"site:*.{v} -site:www.{v}"),
                   ("Belgeler", f"site:{v} (filetype:pdf OR filetype:docx OR filetype:xlsx OR filetype:pptx)"),
                   ("Giriş / yönetim", f"site:{v} (inurl:login OR inurl:admin OR inurl:panel OR intitle:giriş)"),
                   ("Açık dizinler", f'site:{v} intitle:"index of"'), ("Yapılandırma dosyaları", f"site:{v} (ext:env OR ext:ini OR ext:conf OR ext:sql OR ext:bak OR ext:log)"),
                   ("E-postalar", f'"@{v}" -site:{v}'), ("Başka sitelerde bahsi", f'"{v}" -site:{v}'),
                   ("Pastebin'de", f"site:pastebin.com {q}")],
    }
    engines = [("Google", "https://www.google.com/search?q="), ("Bing", "https://www.bing.com/search?q="),
               ("DuckDuckGo", "https://duckduckgo.com/?q="), ("Yandex", "https://yandex.com.tr/search/?text=")]
    for label, dork in sets.get(kind, sets["name"]):
        emit(title=label, url=engines[0][1] + quote(dork), status="found", detail=dork, tags="Google",
             meta={name: base + quote(dork) for name, base in engines[1:]})


# ==========================================================================
# 20) Belge meta verisi
# ==========================================================================
DOC_EXT = r"\.(pdf|docx?|xlsx?|pptx?|odt|ods|odp|rtf)$"


def run_doc_meta(job, inp, emit):
    exe = which("exiftool", "/opt/homebrew/bin/exiftool")
    files = list(inp.get("_files") or ([inp["_file"]] if inp.get("_file") else []))
    limit = min(int(inp.get("limit") or 15), 50)

    # Doğrudan verilen belge adresleri (ör. Google dork sonuçlarından)
    links = [u.strip() for u in re.split(r"\s+", inp.get("urls") or "") if http_ok(u.strip())][:limit]
    for i, u in enumerate(links):
        try:
            rr = S.get(u, timeout=40)
            rr.raise_for_status()
            m = re.search(DOC_EXT, u.split("?")[0], re.I)
            ct = rr.headers.get("content-type", "")
            ext = m.group(0) if m else (".pdf" if "pdf" in ct else ".docx")
            pth = os.path.join(job["dir"], f"link{i}{ext}")
            open(pth, "wb").write(rr.content)
            files.append((pth, u))
        except Exception as e:
            emit(title=u, url=u, status="error", detail=f"İndirilemedi ({type(e).__name__})")

    if inp.get("domain"):
        d = _domain(inp["domain"])
        job["log"](f"{d} için web arşivindeki belgeler aranıyor (büyük sitelerde uzun sürebilir)…")
        try:
            r = S.get("https://web.archive.org/cdx/search/cdx", timeout=75, params={
                "url": d, "matchType": "domain", "output": "json", "fl": "timestamp,original,mimetype", "collapse": "urlkey",
                "limit": "2000", "filter": ["statuscode:200",
                                            "mimetype:application/(pdf|msword|rtf|vnd\\.openxmlformats.*|vnd\\.ms-.*|vnd\\.oasis.*)"]})
            rows = r.json()[1:] if r.status_code == 200 and r.text.strip() else []
            if r.status_code != 200:
                job["log"](f"Web arşivi HTTP {r.status_code}")
        except requests.exceptions.Timeout:
            rows = []
            emit(kind="warn", title="Arşiv araması zaman aşımına uğradı", status="found",
                 detail="Web arşivi büyük sitelerde belge aramasını çok yavaş yapıyor. 'Google Dork üretici' ile "
                        f"site:{d} filetype:pdf aramasını yapıp bulduğunuz belge bağlantılarını 'Belge adresleri' alanına yapıştırın.")
            emit(title=f"Google: site:{d} belgeleri", status="info", tags="Arama",
                 url="https://www.google.com/search?q=" + quote(f"site:{d} (filetype:pdf OR filetype:docx OR filetype:xlsx OR filetype:doc OR filetype:pptx)"))
        # PDF'leri öne al, sonra Office belgeleri
        rows.sort(key=lambda x: (0 if "pdf" in x[2] else 1))
        emit(title=f"Arşivde {len(rows)} belge bulundu", status="info", tags="Özet", detail=f"İlk {min(limit, len(rows))} tanesi indirilip inceleniyor.")

        def dl(i_row):
            i, (ts, orig, mime) = i_row
            m = re.search(DOC_EXT, orig.split("?")[0], re.I)
            ext = m.group(0) if m else {"application/pdf": ".pdf", "application/msword": ".doc", "application/rtf": ".rtf"}.get(
                mime, ".xlsx" if "sheet" in mime or "excel" in mime else ".pptx" if "presentation" in mime or "powerpoint" in mime else ".docx")
            p = os.path.join(job["dir"], f"doc{i}{ext}")
            try:
                rr = S.get(f"https://web.archive.org/web/{ts}id_/{orig}", timeout=40)
                if rr.status_code == 200 and len(rr.content) > 200:
                    open(p, "wb").write(rr.content)
                    return (p, orig)
            except Exception:
                pass
            return None
        with ThreadPoolExecutor(max_workers=6) as ex:
            files += [x for x in ex.map(dl, enumerate(rows[:limit])) if x]
    if not files:
        raise ToolError("İncelenecek belge yok. Bir alan adı girin ya da belge yükleyin.")
    authors = Counter()
    software = Counter()
    for f in files:
        path, src = (f if isinstance(f, tuple) else (f, os.path.basename(f).removeprefix("upload_")))
        text, _ = run_cmd(job, [exe, "-j", "-G1", path])
        try:
            m = json.loads(text[text.find("["):])[0]
        except Exception:
            continue
        pick = lambda *ks: next((str(v) for k, v in m.items() if k.split(":")[-1] in ks and str(v).strip()), "")
        who = [x for x in {pick("Author"), pick("Creator") if not re.search(r"word|writer|acrobat|office|pdf|designer|livecycle|indesign|illustrator|photoshop|latex|tex|calc|impress|pages|numbers|keynote|quartz|ghostscript|prince|chrome|skia|excel|powerpoint|\\d+\\.\\d", pick("Creator"), re.I) else "",
                           pick("LastModifiedBy"), pick("Company"), pick("Manager")} if x and not re.fullmatch(r"[A-Z]{2}:[A-Z:]+", x)]
        for w in who:
            authors[w] += 1
        sw = pick("Producer", "Software", "Application", "CreatorTool")
        if sw:
            software[sw] += 1
        emit(title=os.path.basename(src.split("?")[0]) or src, url=src if src.startswith("http") else "", status="found" if who else "info",
             tags=pick("FileType"), detail=" · ".join(x for x in [", ".join(who), pick("Title")] if x),
             meta={"Yazar": pick("Author"), "Son değiştiren": pick("LastModifiedBy"), "Şirket": pick("Company"),
                   "Oluşturma": pick("CreateDate"), "Değiştirme": pick("ModifyDate"), "Yazılım": sw, "Sayfa": pick("PageCount", "Pages")})
    for a, n in authors.most_common():
        emit(title=f"Kişi / kurum: {a}", status="found", tags="Özet", detail=f"{n} belgede geçiyor")
    if software:
        emit(title="Kullanılan yazılımlar", status="info", tags="Özet", detail=", ".join(f"{k} ({v})" for k, v in software.most_common(8)))


# ==========================================================================
# 21) SpiderFoot
# ==========================================================================
SF_SKIP = {"Raw Data from RIRs", "Raw DNS Records", "Raw File Meta Data", "HTTP Headers", "Web Content", "Raw Data",
           "Linked URL - Internal", "Search Engine Web Content", "Account on External Site - Probe"}


def run_spiderfoot(job, inp, emit):
    exe = os.path.join(TOOLS, "spiderfoot", "bin", "spiderfoot-ng")
    target = inp["target"].strip()
    argv = [exe, "-s", target, "-o", "json", "-q", "-max-threads", "10"]
    if inp.get("modules"):
        argv += ["-m", inp["modules"].replace(" ", "")]
    else:
        argv += ["-u", inp.get("usecase") or "passive"]
    count = Counter()

    def on_line(line):
        s = line.strip().lstrip("[").rstrip(",").rstrip("]")
        if not s.startswith("{"):
            return
        try:
            x = json.loads(s)
        except Exception:
            return
        t = x.get("type", "")
        if t in SF_SKIP or x.get("module") == "SpiderFoot UI":
            return
        count[t] += 1
        data = str(x.get("data", ""))[:400]
        url = data if http_ok(data) else ""
        emit(title=data.split("\n")[0][:200], url=url, status="found", tags=t, detail=f"Modül: {x.get('module')} · Kaynak: {str(x.get('source'))[:100]}")

    minutes = min(int(inp.get("minutes") or 5), 30)
    run_cmd(job, argv, on_line=on_line, timeout=minutes * 60)
    if count:
        emit(title="Özet", status="info", tags="Özet", detail=", ".join(f"{k} ({v})" for k, v in count.most_common(12)))


# ==========================================================================
# 22) Recon-ng
# ==========================================================================
RECON_MODULES = {
    "domain": ["recon/domains-hosts/certificate_transparency", "recon/domains-hosts/hackertarget", "recon/domains-contacts/whois_pocs"],
    "username": ["recon/profiles-profiles/profiler"],
}


def run_reconng(job, inp, emit):
    py = os.path.join(TOOLS, "recon-ng", ".venv", "bin", "python")
    cli = os.path.join(TOOLS, "recon-ng", "recon-cli")
    kind = inp.get("kind") or "domain"
    src = _domain(inp["target"]) if kind == "domain" else inp["target"].strip()
    ws = f"panel_{job['id']}"
    for m in RECON_MODULES[kind]:
        run_cmd(job, [py, cli, "-w", ws, "--no-analytics", "--no-version", "-m", m, "-o", f"SOURCE={src}", "-x"], timeout=300)
    dbp = os.path.expanduser(f"~/.recon-ng/workspaces/{ws}/data.db")
    if not os.path.exists(dbp):
        raise ToolError("Recon-ng sonuç üretmedi.")
    con = sqlite3.connect(dbp)
    con.row_factory = sqlite3.Row
    n0 = len(job.get("results", [])) if isinstance(job.get("results"), list) else 0
    emitted = [0]
    _emit = emit
    def emit(**r):
        emitted[0] += 1
        _emit(**r)
    try:
        for r in con.execute("SELECT DISTINCT host, ip_address, module FROM hosts WHERE host IS NOT NULL"):
            emit(title=r["host"], url=f"https://{r['host']}", status="found", tags="Ana bilgisayar",
                 detail=" · ".join(x for x in [r["ip_address"], r["module"]] if x))
        for r in con.execute("SELECT * FROM contacts"):
            name = " ".join(x for x in [r["first_name"], r["middle_name"], r["last_name"]] if x)
            emit(title=name or r["email"] or "?", status="found", tags="Kişi", detail=" · ".join(x for x in [r["email"], r["title"], r["region"], r["country"]] if x),
                 meta={"email": r["email"]} if r["email"] else {})
        for r in con.execute("SELECT * FROM profiles"):
            emit(title=f"{r['resource']}: {r['username']}", url=r["url"], status="found", tags=r["category"] or "Profil")
    finally:
        con.close()
        shutil.rmtree(os.path.dirname(dbp), ignore_errors=True)   # bu iş için açılan geçici çalışma alanı
    if not emitted[0]:
        raise ToolError("Recon-ng modülleri sonuç bulamadı ya da kaynaklara ulaşamadı; ayrıntılar Günlük sekmesinde.")


# ==========================================================================
# Kayıt
# ==========================================================================
def run_websearch(job, inp, emit):
    import searx
    from persona import parse_account
    q = inp["q"].strip()
    seen = set()
    for page in range(1, min(int(inp.get("pages") or 1), 3) + 1):
        res, dead = searx.search(q, lang=inp.get("lang") or "tr", pageno=page, log=job["log"])
        job["progress"](page, min(int(inp.get("pages") or 1), 3))
        for x in res:
            if x["url"] in seen:
                continue
            seen.add(x["url"])
            acc = parse_account(x["url"])
            emit(title=x["title"][:160], url=x["url"], detail=x["content"][:300], status="found",
                 tags=(acc[0] if acc else ", ".join(x["engines"][:3])), meta={"Motorlar": ", ".join(x["engines"]), "Tarih": x.get("date", "")})
        if dead:
            emit(kind="warn", status="found", title="Yanıt vermeyen motorlar",
                 detail=", ".join(str(d[0]) if isinstance(d, (list, tuple)) else str(d) for d in dead))
    if not seen:
        emit(title="Sonuç yok", status="notfound", detail="Sorguyu sadeleştirin ya da tırnakları kaldırın.")


REGISTRY2 = [
    {"id": "namesearch", "group": "Kişi", "title": "İsim araştırma", "icon": "idcard",
     "desc": "Bir ad soyaddan herkese açık kaynakları tarar: tanınmış kişi kaydı, haberler, akademik kayıtlar, GitHub, yaptırım listeleri, olası kullanıcı adları ve sosyal medya aramaları.",
     "note": "Yalnızca herkese açık, yasal kaynaklar kullanılır. Kimlik / adres sorgu panelleri ve sızdırılmış veriler kullanılmaz (KVKK, TCK 136).",
     "fields": [F("name", "Ad soyad", required=True, placeholder="Ad Soyad"),
                F("place", "Şehir / ülke (isteğe bağlı)", placeholder="İstanbul"),
                F("org", "Kurum, okul, şirket ya da alan adı (isteğe bağlı)", placeholder="Boğaziçi Üniversitesi veya sirket.com"),
                F("birth_year", "Doğum yılı (isteğe bağlı)", type="number", placeholder="1990"),
                F("known", "Bilinen kullanıcı adı / e-posta (isteğe bağlı)", placeholder="kullaniciadi veya ad@mail.com"),
                F("web", "Web araması", type="select", options=[["on", "Gerçek web araması (SearXNG)"], ["off", "Kapalı"]]),
                F("deep", "Derin tarama", type="select", options=[["off", "Derin tarama kapalı"], ["on", "En olası kişiyi derin tara (~5 dk)"]]),
                F("summary", "Yapay zekâ özeti", type="select", options=[["off", "Özet kapalı"], ["on", "Kaynaklı özet (Gemini anahtarı ya da yerel Ollama)"]]),
                F("news", "Haberler", type="select", options=[["on", "Haberleri tara"], ["off", "Haberler kapalı"]]),
                F("academic", "Akademik", type="select", options=[["on", "Akademik kayıtlar"], ["off", "Akademik kapalı"]]),
                F("github", "GitHub", type="select", options=[["on", "GitHub hesapları"], ["off", "GitHub kapalı"]]),
                F("sanctions", "Yaptırım / PEP", type="select", options=[["on", "OpenSanctions"], ["off", "Kapalı"]]),
                F("usernames", "Kullanıcı adları", type="select", options=[["on", "Üret ve hızlı kontrol et"], ["off", "Kapalı"]]),
                F("emails", "E-posta tahmini", type="select", options=[["off", "Kapalı"], ["on", "Olası adresleri Gravatar'da ara"]]),
                F("file", "Referans fotoğraf (isteğe bağlı): aynı fotoğrafı kullanan hesaplar öne çıkar", type="file")],
     "run": lambda job, inp, emit: __import__("namesearch").run_namesearch(job, inp, emit)},
    {"id": "websearch", "group": "Arama", "title": "Web araması", "icon": "search",
     "desc": "Google, Bing, DuckDuckGo ve Startpage sonuçlarını birleştiren, bu bilgisayarda çalışan SearXNG ile gerçek web araması.",
     "note": "Arama motorları çok hızlı ve çok sayıda sorguda geçici olarak engelleyebilir; sorgular bu yüzden aralıklı gönderilir.",
     "fields": [F("q", "Arama sorgusu", required=True, placeholder='"Ad Soyad" site:linkedin.com/in'),
                F("pages", "Sayfa sayısı", type="number", value=1),
                F("lang", "Dil", type="select", options=[["tr", "Türkçe"], ["en", "İngilizce"], ["all", "Tümü"]])],
     "run": lambda job, inp, emit: run_websearch(job, inp, emit)},
    {"id": "user-scanner", "group": "Kullanıcı adı", "title": "user-scanner", "icon": "radar",
     "desc": "Tek araçta kullanıcı adı ve e-posta taraması; 2500'den fazla platform.",
     "fields": [F("target", "Kullanıcı adı veya e-posta", required=True, placeholder="kullanıcı adı / e-posta"),
                F("timeout", "Zaman aşımı (sn)", type="number", value=10), F("nsfw", "NSFW siteleri dahil et", type="checkbox"),
                F("show_errors", "Hata verenleri de göster", type="checkbox")], "run": run_user_scanner},
    {"id": "github", "group": "Kullanıcı adı", "title": "GitHub profil çıkarıcı", "icon": "git",
     "desc": "GitHub hesabından ad, şirket, konum, commit e-postaları, SSH/GPG anahtarları ve kuruluşları çıkarır.",
     "fields": [F("username", "GitHub kullanıcı adı", required=True, placeholder="kullanıcı adı")], "run": run_github},
    {"id": "social-activity", "group": "Kullanıcı adı", "title": "Reddit / HN / Keybase", "icon": "activity",
     "desc": "Reddit, Hacker News ve Keybase hesaplarını, etkin olduğu toplulukları ve paylaşım saatlerinden saat dilimini çıkarır.",
     "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı")], "run": run_social_activity},
    {"id": "telegram", "group": "Kullanıcı adı", "title": "Telegram kontrolü", "icon": "send",
     "desc": "Telegram kullanıcı / kanal / grubunun herkese açık adını, biyografisini, fotoğrafını ve üye sayısını getirir.",
     "fields": [F("username", "Telegram adı (birden fazla olabilir)", required=True, placeholder="kullanıcıadı kanaladı")], "run": run_telegram},
    {"id": "variants", "group": "Kullanıcı adı", "title": "Kullanıcı adı üretici", "icon": "shuffle",
     "desc": "Ad ve soyaddan olası kullanıcı adlarını üretir; tek tıkla Sherlock'a gönderilir.",
     "fields": [F("first", "Ad(lar)", required=True, placeholder="Emre Tuna"), F("last", "Soyad", placeholder="Ulaş"),
                F("nick", "Takma ad(lar)", placeholder="isteğe bağlı"), F("years", "Yıllar", placeholder="1998 2003"),
                F("seps", "Ayraçlar", type="select", options=[["all", "Hepsi (yok . _ -)"], ["none", "Yalnızca ayraçsız"]]),
                F("limit", "En fazla", type="number", value=60)], "run": run_variants},
    {"id": "hibp", "group": "E-posta", "title": "HIBP sızıntı sorgusu", "icon": "shield",
     "desc": "Have I Been Pwned'in resmî API'siyle e-postanın geçtiği sızıntıları tarih ve sızan veri türleriyle listeler.",
     "note": "Ayarlar sayfasına HIBP API anahtarı eklenmelidir (ücretli).",
     "fields": [F("email", "E-posta", required=True, type="email", placeholder="ornek@mail.com")], "run": run_hibp},
    {"id": "email-header", "group": "E-posta", "title": "E-posta başlığı çözümleyici", "icon": "inbox",
     "desc": "E-posta başlığından gönderen IP'sini, geçtiği sunucuları ve SPF / DKIM / DMARC sonuçlarını çıkarır.",
     "fields": [F("header", "Ham başlık (Gmail: Orijinali göster)", type="textarea", required=False,
                  placeholder="Received: from …\nAuthentication-Results: …\nFrom: …"),
                F("file", "veya .eml dosyası", type="file", accept=".eml,.txt,message/rfc822")], "run": run_email_header},
    {"id": "phone-search", "group": "Telefon", "title": "Numara varyasyon araması", "icon": "phonesearch",
     "desc": "Numaranın tüm yazım biçimlerini Google, Bing, DuckDuckGo, Yandex ve popüler sitelerde aratan bağlantılar üretir.",
     "fields": [F("number", "Telefon numarası", required=True, placeholder="0555 123 45 67"), F("region", "Ülke kodu", value="TR")],
     "run": run_phone_search},
    {"id": "geofusion", "group": "Görsel", "title": "Konum bulucu", "icon": "crosshair",
     "desc": "Fotoğrafın çekildiği yeri EXIF, GeoCLIP yapay zekâ modeli, tabela / yazı okuma ve Gemini yorumunu birleştirerek bulur. Ücretsiz.",
     "note": "GeoCLIP ve yazı okuma bu bilgisayarda çalışır. Gemini isteğe bağlıdır: Ayarlar'a ücretsiz anahtar eklenirse ipuçlarını da yorumlar.",
     "fields": [F("url", "Görsel URL'si", placeholder="https://…/foto.jpg"),
                F("context", "Ek bağlam (isteğe bağlı)", placeholder="ör. Türkiye'de olabilir, 2020 yazı"),
                F("use_gemini", "Yapay zekâ yorumu", type="select", options=[["on", "Kullan (Gemini anahtarı ya da yerel Ollama varsa)"], ["off", "Kullanma"]]),
                F("use_ocr", "Yazı okuma", type="select", options=[["on", "Tabela / yazı oku"], ["off", "Yazı okuma kapalı"]]),
                F("use_claude", "Claude", type="select", options=[["off", "Claude kullanma"], ["on", "Claude da kullan (ücretli, anahtar varsa)"]]),
                F("file", "veya dosya yükle", type="file")],
     "run": lambda job, inp, emit: __import__("geo").run_geofusion(job, inp, emit)},
    {"id": "geolocate", "group": "Görsel", "title": "Görsel konum tahmini", "icon": "globe2",
     "desc": "EXIF'i olmayan bir fotoğrafın nerede çekildiğini tabela, mimari, bitki örtüsü gibi ipuçlarından tahmin eder (Claude).",
     "note": "Ayarlar'a bir Anthropic API anahtarı eklenmelidir. Fotoğraf Anthropic API'sine gönderilir; ücretlendirilir.",
     "fields": [F("url", "Görsel URL'si", placeholder="https://…/foto.jpg"), F("context", "Ek bağlam (isteğe bağlı)", placeholder="ör. Türkiye'de olabilir"),
                F("file", "veya dosya yükle", type="file")], "run": run_geolocate},
    {"id": "image-compare", "group": "Görsel", "title": "Fotoğraf eşleştirme", "icon": "copy",
     "desc": "Farklı sitelerdeki profil fotoğraflarının aynı olup olmadığını parmak izi (perceptual hash) ile karşılaştırır.",
     "fields": [F("urls", "Görsel URL'leri (her satıra bir tane)", type="textarea", placeholder="https://…/a.jpg\nhttps://…/b.jpg"),
                F("file", "veya dosyalar", type="file", multiple=True)], "run": run_image_compare},
    {"id": "ela", "group": "Görsel", "title": "Sahtecilik analizi (ELA)", "icon": "layers",
     "desc": "Hata seviyesi analiziyle fotoğrafın sonradan değiştirilmiş bölgelerini ısı haritası olarak gösterir.",
     "fields": [F("url", "Görsel URL'si", placeholder="https://…/foto.jpg"), F("quality", "JPEG kalitesi", type="number", value=90),
                F("scale", "Parlaklık çarpanı", type="number", value=1), F("file", "veya dosya yükle", type="file")], "run": run_ela},
    {"id": "video", "group": "Görsel", "title": "Video analizi", "icon": "film",
     "desc": "YouTube, TikTok, Instagram, X vb. videoların meta verisini çeker ve belirli aralıklarla kareler çıkarır.",
     "fields": [F("url", "Video bağlantısı", required=True, placeholder="https://www.youtube.com/watch?v=…"),
                F("seconds", "İlk kaç saniye", type="number", value=60), F("interval", "Kare aralığı (sn)", type="number", value=10),
                F("frames", "Kare çıkarma", type="select", options=[["on", "Açık"], ["off", "Kapalı (yalnızca meta veri)"]])], "run": run_video},
    {"id": "crtsh", "group": "Alan adı", "title": "Sertifika kayıtları (crt.sh)", "icon": "lock",
     "desc": "Alan adı için verilmiş tüm SSL sertifikalarından alt alan adlarını ve ilk görülme tarihlerini çıkarır.",
     "fields": [F("domain", "Alan adı", required=True, placeholder="ornek.com")], "run": run_crtsh},
    {"id": "subfinder", "group": "Alan adı", "title": "subfinder + httpx", "icon": "network",
     "desc": "Pasif kaynaklardan alt alan adlarını bulur, hangilerinin canlı olduğunu, başlıklarını ve teknolojilerini gösterir.",
     "fields": [F("domain", "Alan adı", required=True, placeholder="ornek.com"),
                F("probe", "Canlılık kontrolü (httpx)", type="select", options=[["on", "Açık"], ["off", "Kapalı"]]),
                F("all", "Tüm kaynakları kullan (yavaş)", type="checkbox")], "run": run_subfinder},
    {"id": "dnstwist", "group": "Alan adı", "title": "Sahte alan adı (dnstwist)", "icon": "alert",
     "desc": "Alan adının yazım hatalı kopyalarını üretir ve hangilerinin kayıtlı olduğunu bulur (oltalama tespiti).",
     "fields": [F("domain", "Alan adı", required=True, placeholder="ornek.com"), F("mx", "Posta sunucusu kontrolü", type="checkbox"),
                F("whois", "WHOIS kayıt tarihleri (yavaş)", type="checkbox")], "run": run_dnstwist},
    {"id": "wayback", "group": "Alan adı", "title": "Wayback Machine", "icon": "clock",
     "desc": "Bir sayfanın ya da sitenin web arşivindeki eski sürümlerini listeler; silinmiş içerikleri bulmaya yarar.",
     "fields": [F("url", "Adres", required=True, placeholder="instagram.com/kullanici veya ornek.com"),
                F("mode", "Kapsam", type="select", options=[["page", "Bu sayfanın sürümleri"], ["domain", "Sitenin arşivdeki tüm adresleri"]]),
                F("limit", "En fazla kayıt", type="number", value=500)], "run": run_wayback},
    {"id": "site-intel", "group": "Alan adı", "title": "Site izleyici analizi", "icon": "code",
     "desc": "Sitedeki Google Analytics, AdSense, Pixel kimliklerini, teknolojileri, e-postaları ve sosyal bağlantıları çıkarır.",
     "fields": [F("url", "Site adresi", required=True, placeholder="ornek.com")], "run": run_site_intel},
    {"id": "shodan", "group": "Alan adı", "title": "Shodan", "icon": "eye",
     "desc": "IP'deki açık portları, çalışan hizmetleri, yazılımları ve bilinen güvenlik açıklarını gösterir.",
     "note": "API anahtarı yoksa ücretsiz Shodan InternetDB kullanılır (daha az ayrıntı).",
     "fields": [F("target", "IP adresi veya alan adı", required=True, placeholder="8.8.8.8 veya ornek.com")], "run": run_shodan},
    {"id": "dorks", "group": "Arama", "title": "Google Dork üretici", "icon": "search2",
     "desc": "Ad, kullanıcı adı, e-posta, telefon veya alan adı için hazır gelişmiş arama sorguları üretir.",
     "fields": [F("value", "Aranacak değer", required=True, placeholder="Ad Soyad / kullanıcı adı / e-posta / alan adı"),
                F("kind", "Tür", type="select", options=[["name", "Kişi adı"], ["username", "Kullanıcı adı"], ["email", "E-posta"],
                                                          ["phone", "Telefon"], ["domain", "Alan adı"]]),
                F("extra", "Ek kelime (şehir, şirket…)", placeholder="isteğe bağlı")], "run": run_dorks},
    {"id": "doc-meta", "group": "Arama", "title": "Belge meta verisi", "icon": "file",
     "desc": "Bir sitenin arşivdeki PDF / Word / Excel belgelerini bulur, içlerinden yazar, şirket ve yazılım bilgilerini çıkarır.",
     "fields": [F("domain", "Alan adı (web arşivinde arar)", placeholder="ornek.com"), F("limit", "En fazla belge", type="number", value=15),
                F("urls", "Belge adresleri (her satıra bir tane)", type="textarea", placeholder="https://ornek.com/dosya.pdf"),
                F("file", "veya belge yükle", type="file", multiple=True, accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.odt,.ods,.rtf")],
     "run": run_doc_meta},
    {"id": "spiderfoot", "group": "Çerçeveler", "title": "SpiderFoot", "icon": "spider",
     "desc": "200'den fazla modülle tek bir hedef (alan adı, IP, e-posta, ad) üzerinde otomatik keşif yapar.",
     "fields": [F("target", "Hedef", required=True, placeholder="ornek.com / 1.2.3.4 / ad@mail.com / \"Ad Soyad\""),
                F("usecase", "Kapsam", type="select", options=[["passive", "Pasif (hedefe dokunmaz)"], ["footprint", "Ayak izi"], ["investigate", "Soruşturma"], ["all", "Tümü (çok yavaş)"]]),
                F("modules", "Belirli modüller (isteğe bağlı)", placeholder="sfp_crt,sfp_dnsresolve"),
                F("minutes", "En fazla süre (dk)", type="number", value=5)], "run": run_spiderfoot},
    {"id": "recon-ng", "group": "Çerçeveler", "title": "Recon-ng", "icon": "box",
     "desc": "Modüler keşif çerçevesi: alan adı için ana bilgisayarlar ve WHOIS kişileri, kullanıcı adı için profiller.",
     "fields": [F("target", "Hedef", required=True, placeholder="ornek.com veya kullanıcı adı"),
                F("kind", "Tür", type="select", options=[["domain", "Alan adı"], ["username", "Kullanıcı adı"]])], "run": run_reconng},
]

ABOUT2 = {
    "namesearch": {"what": "Yalnızca ad soyad bilindiğinde başlangıç noktası. Paralel olarak Wikidata / Wikipedia, haberler (Google Haberler, GDELT), akademik kayıtlar (OpenAlex, ORCID, Crossref, Semantic Scholar), GitHub, Bluesky, Stack Overflow, Wikimedia Commons, yaptırım listeleri (OpenSanctions), isimden üretilen kullanıcı adları ve Gravatar'ı tarar; yazım varyasyonlarını (ş→s, ad / soyad yer değişimi, baş harf) da dener. Web araması açıkken LinkedIn, Instagram, Facebook, X gibi siteler bu bilgisayardaki SearXNG ile gerçekten aranır. Bulgular ortak kullanıcı adı, e-posta, aynı profil fotoğrafı, resmî bağlantı ve kurum gibi kanıtlarla 'olası kişiler'e ayrılır; derin mod en olası kişinin hesaplarını diğer araçlarla (Maigret, Holehe, GitHub…) otomatik genişletir, Gemini özeti isteğe bağlıdır.",
                   "when": "Bir kişinin yalnızca adını bildiğinde. Akıllı aramaya ad soyad yazınca bu araç kendiliğinden çalışır.",
                   "input": "Ad soyad; daraltmak için şehir, kurum, doğum yılı, bilinen kullanıcı adı / e-posta ve referans fotoğraf.",
                   "output": "Olası kişi kartları (fotoğraflar, bağlı hesaplar, 'neden aynı kişi' kanıtları, zaman çizelgesi), kişi kartı ve kaynak kaynak bulgular.",
                   "tips": "Yaygın isimlerde sonuçların çoğu başka kişilere ait olur; kartlardaki 'Aradığım kişi bu / Değil' düğmeleriyle daraltın ve her eşleşmeyi ikinci bir kanıtla doğrulayın. Yüz tanıma yapılmaz; fotoğraflar yalnızca birebir / çok benzer görsel olarak eşleştirilir. Kimlik ve adres sorgu panelleri yasa dışıdır ve kullanılmaz."},
    "geofusion": {"what": "Birbirinden bağımsız kaynakları birleştirir: fotoğraftaki GPS bilgisi (EXIF), görüntünün genel görünümünden konum tahmin eden GeoCLIP modeli (bu bilgisayarda çalışır), tabela ve yazıları okuyup telefon kodu, alan adı, sokak ve şehir adlarını haritada bulan yazı okuma, ve isteğe bağlı olarak ipuçlarını yorumlayan Gemini. Adaylar haritada kümelenir; birden çok kaynağın aynı yeri göstermesi güveni artırır.",
                  "when": "Bir fotoğrafın nerede çekildiğini ücretsiz bulmak için; özellikle EXIF'i silinmiş sosyal medya fotoğraflarında.",
                  "input": "Görsel URL'si ya da dosya; isteğe bağlı bağlam.",
                  "output": "Haritada en olası konum ve güven çemberi, alternatifler, her kaynağın kendi tahmini, okunan yazılar ve doğrulama bağlantıları (Street View, Mapillary, SunCalc…).",
                  "tips": "GeoCLIP tek başına genelde ülke / bölge düzeyinde isabetlidir; tabela okunan ya da Gemini'nin de aynı yeri gösterdiği sonuçlar çok daha güvenilirdir. İlk çalıştırmada model yüklendiği için ~20 sn sürer."},
    "user-scanner": {"what": "Holehe'nin e-posta kontrolüyle Sherlock'un kullanıcı adı taramasını birleştiren, 2500'den fazla platformu tarayan araç. Bulduğu profillerden ad gibi ek bilgileri de çıkarır.",
                     "when": "Holehe hız sınırına takıldığında ya da kullanıcı adı ve e-posta için tek bir geniş tarama istediğinde.",
                     "input": "Kullanıcı adı veya e-posta.", "output": "Profil bağlantıları ve profillerden çıkarılan bilgiler.", "tips": "Hata veren siteleri görmek için ilgili kutuyu işaretle."},
    "github": {"what": "GitHub'ın herkese açık API'siyle profil bilgilerini, kullanıcının commit'lerinde geçen gerçek e-posta adreslerini ve adları, SSH / GPG anahtarlarını, kuruluşlarını ve kullandığı dilleri çıkarır.",
               "when": "Bir kullanıcı adının GitHub hesabı varsa; commit e-postaları kullanıcı adından gerçek e-postaya geçmenin en güvenilir yollarından biridir.",
               "input": "GitHub kullanıcı adı.", "output": "Profil, e-postalar, adlar, anahtarlar, kuruluşlar.", "tips": "Saatte 60 istek sınırı var; Ayarlar'a GitHub anahtarı eklenirse 5000 olur."},
    "social-activity": {"what": "Reddit, Hacker News ve Keybase hesaplarını bulur. Reddit'te en çok yazdığı toplulukları, tüm platformlarda paylaşım saatlerini çıkarır ve en sessiz saatlere bakarak saat dilimini tahmin eder. Keybase'de kriptografik olarak doğrulanmış bağlı hesapları gösterir.",
                        "when": "Bir kişinin ilgi alanlarını, hangi ülkede / saat diliminde yaşadığını ve hesaplarının gerçekten aynı kişiye ait olup olmadığını anlamak için.",
                        "input": "Kullanıcı adı.", "output": "Hesaplar, topluluklar, saat grafiği, doğrulanmış bağlantılar.", "tips": "Saat dilimi tahmini en az birkaç düzine paylaşım olduğunda anlamlıdır."},
    "telegram": {"what": "t.me sayfasından Telegram kullanıcısının, kanalının ya da grubunun adını, biyografisini, profil fotoğrafını ve üye / abone sayısını okur.",
                 "when": "Bir kullanıcı adının Telegram'da kullanılıp kullanılmadığını ve kime ait olduğunu görmek için.", "input": "Bir veya birden fazla Telegram adı.",
                 "output": "Ad, biyografi, fotoğraf, tür ve üye sayısı.", "tips": "Kanallarda herkese açık gönderiler t.me/s/ad adresinden okunabilir."},
    "variants": {"what": "Ad, soyad, takma ad ve yıllardan olası kullanıcı adı kombinasyonlarını üretir (sıra değişimi, baş harfler, ayraçlar, yıl ekleri). Türkçe karakterleri dönüştürür.",
                 "when": "Kişinin yalnızca adını bildiğinde, kullanıcı adı aramalarına başlamak için.", "input": "Ad, soyad, isteğe bağlı takma ad ve yıl.",
                 "output": "Kullanıcı adı listesi; tek tıkla Sherlock listesine eklenir.", "tips": "Liste uzadıkça tarama süresi artar; önce ayraçsız seçenekle başla."},
    "hibp": {"what": "Have I Been Pwned'in resmî API'siyle bir e-postanın geçtiği tüm veri sızıntılarını; sızıntı tarihi, etkilenen hesap sayısı ve sızan veri türleriyle (şifre, telefon, adres…) listeler.",
             "when": "Bir e-postanın hangi hizmetlerde hesabı olduğunu ve hangi bilgilerinin sızdığını öğrenmek için.", "input": "E-posta adresi.",
             "output": "Sızıntılar ve paste kayıtları.", "tips": "Ücretli API anahtarı gerekir; Ayarlar sayfasından eklenir."},
    "email-header": {"what": "Bir e-postanın ham başlığını çözümler: gönderenin IP adresi, geçtiği sunucular ve aradaki gecikmeler, SPF / DKIM / DMARC sonuçları, yanıt ve geri dönüş adresi tutarsızlıkları.",
                     "when": "Şüpheli ya da tehdit içeren bir e-postanın gerçekte nereden geldiğini bulmak için.", "input": "Ham başlık metni (Gmail'de ⋮ > Orijinali göster) veya .eml dosyası.",
                     "output": "Başlık alanları, yol, kimlik doğrulama sonuçları ve uyarılar.", "tips": "Bulunan IP'yi 'IP konum sorgusu'na gönderebilirsin. Gmail ve Outlook çoğu zaman gönderenin gerçek IP'sini gizler."},
    "phone-search": {"what": "Bir numaranın tüm yazım biçimlerini (0555…, +90 555…, boşluklu, tireli) üretir ve bunları Google, Bing, DuckDuckGo, Yandex ile sosyal medya, ilan ve şikayet sitelerinde aratan bağlantılar hazırlar.",
                     "when": "Numaranın internette nerelerde geçtiğini bulmak için.", "input": "Telefon numarası.", "output": "Yazım biçimleri ve arama bağlantıları.",
                     "tips": "İnsanlar numarayı farklı biçimlerde yazar; tek biçimle arama çoğu sonucu kaçırır."},
    "geolocate": {"what": "Claude'un görsel yeteneğiyle fotoğraftaki tabelaları, plakaları, mimariyi, bitki örtüsünü, yol işaretlerini inceleyip çekildiği yeri tahmin eder; ipuçlarını ve alternatifleri tek tek açıklar.",
                  "when": "EXIF'i silinmiş fotoğraflarda (sosyal medyadan indirilenler gibi) konum bulmak için.", "input": "Görsel URL'si veya dosya, isteğe bağlı bağlam.",
                  "output": "Haritada tahmini konum, güven düzeyi, ipuçları, alternatifler, doğrulama adımları.", "tips": "Bir yapay zekâ tahminidir; Street View ve ters görsel aramayla mutlaka doğrula. Anahtar yoksa el ile inceleme bağlantıları verilir."},
    "image-compare": {"what": "Görsellerin parmak izini (perceptual hash) çıkarıp ikişer ikişer karşılaştırır. Yeniden boyutlandırılmış, sıkıştırılmış ya da hafif kırpılmış kopyaları da aynı görsel olarak tanır.",
                      "when": "Farklı sitelerdeki profil fotoğraflarının aynı olup olmadığını, yani hesapların aynı kişiye ait olabileceğini anlamak için.", "input": "Görsel URL'leri ve / veya dosyalar.",
                      "output": "Görseller ve benzerlik yüzdeleri.", "tips": "Sonuç listelerindeki 'Fotoğrafları karşılaştır' düğmesi bulunan tüm profil fotoğraflarını buraya gönderir."},
    "ela": {"what": "Hata seviyesi analizi (ELA): görsel belirli bir kalitede yeniden kaydedilir ve farkı ısı haritası olarak gösterilir. Sonradan eklenen ya da değiştirilen bölgeler genelde çevresinden farklı parlaklıkta görünür.",
            "when": "Bir fotoğrafın / ekran görüntüsünün üzerinde oynanıp oynanmadığından şüphelendiğinde.", "input": "Görsel URL'si veya dosya.",
            "output": "Orijinal, ELA ısı haritası ve dikkat çeken bölgeler.", "tips": "Kesin kanıt değildir; ExifTool'daki düzenleme izleriyle birlikte değerlendir."},
    "video": {"what": "yt-dlp ile YouTube, TikTok, Instagram, X ve yüzlerce sitedeki videoların başlığını, yükleyenini, yükleme tarihini, açıklamasını, etiketlerini çeker; ffmpeg ile belirli aralıklarla kareler çıkarır.",
              "when": "Bir videonun kaynağını, tarihini doğrulamak ya da karelerini ters görsel aramada kullanmak için.", "input": "Video bağlantısı.",
              "output": "Meta veriler ve video kareleri.", "tips": "Kareleri 'Ters görsel arama' ve 'Görsel konum tahmini' araçlarına gönderebilirsin."},
    "crtsh": {"what": "Sertifika şeffaflığı kayıtlarından (crt.sh) alan adı için verilmiş tüm SSL sertifikalarını ve sertifikalarda geçen alt alan adlarını çıkarır. Anahtar istemez.",
              "when": "DNS'te görünmeyen, gizli ya da eski alt alan adlarını bulmak için.", "input": "Alan adı.", "output": "Alt alan adları ve ilk sertifika tarihleri.",
              "tips": "crt.sh bazen yavaş yanıt verir; hata alırsan tekrar dene."},
    "subfinder": {"what": "subfinder onlarca pasif kaynaktan alt alan adlarını toplar; httpx bunlardan hangilerinin canlı olduğunu, sayfa başlıklarını, durum kodlarını ve kullandıkları teknolojileri bulur.",
                  "when": "Bir kurumun internetteki tüm sitelerini çıkarmak için; theHarvester ve crt.sh'tan daha kapsamlıdır.", "input": "Alan adı.",
                  "output": "Alt alan adları, canlılık, başlık, teknoloji.", "tips": "'Tüm kaynaklar' seçeneği daha fazla sonuç verir ama yavaştır."},
    "dnstwist": {"what": "Bir alan adının harf değişimi, eksik / fazla harf, benzer görünen karakterler gibi yöntemlerle sahte kopyalarını üretir ve hangilerinin kayıtlı olduğunu kontrol eder.",
                 "when": "Bir kurumu taklit eden oltalama sitelerini bulmak için.", "input": "Alan adı.", "output": "Kayıtlı benzer alan adları, IP'leri ve posta sunucuları.",
                 "tips": "Posta sunucusu (MX) olan sahte alan adları oltalama e-postası gönderebilir; önceliklidir."},
    "wayback": {"what": "Internet Archive'ın Wayback Machine arşivinde bir sayfanın içerik değişikliği olan tüm sürümlerini ya da bir sitenin arşivde bilinen tüm adreslerini listeler.",
                "when": "Silinmiş profil biyografilerini, kapatılmış hesapları, kaldırılmış sayfaları ve unutulmuş belgeleri bulmak için.", "input": "Sayfa adresi veya alan adı.",
                "output": "Arşiv bağlantıları ve tarihler.", "tips": "Site kapsamında belge ve yönetim sayfaları öne çıkarılır."},
    "site-intel": {"what": "Bir sitenin kaynak kodundan Google Analytics, Tag Manager, AdSense, Meta Pixel, Yandex Metrica gibi izleme kimliklerini, kullanılan teknolojileri, e-postaları ve sosyal medya bağlantılarını çıkarır.",
                   "when": "Birbirinden bağımsız görünen sitelerin aynı kişiye ait olup olmadığını anlamak için: aynı Analytics / AdSense kimliği aynı sahibi gösterir.", "input": "Site adresi.",
                   "output": "İzleme kimlikleri ve ters arama bağlantıları, teknolojiler, e-postalar, sosyal bağlantılar.", "tips": "PublicWWW ve BuiltWith bağlantıları aynı kimliği kullanan diğer siteleri gösterir."},
    "shodan": {"what": "Shodan'ın internet taramalarından bir IP'deki açık portları, çalışan hizmetleri, yazılım sürümlerini ve bilinen güvenlik açıklarını (CVE) gösterir.",
               "when": "Bir sunucunun ya da cihazın internete neler açtığını görmek için.", "input": "IP adresi veya alan adı.",
               "output": "Portlar, hizmetler, yazılımlar, açıklar.", "tips": "Anahtarsız modda ücretsiz InternetDB kullanılır; Ayarlar'dan Shodan anahtarı eklenirse ayrıntı artar."},
    "dorks": {"what": "Seçilen türe göre (kişi adı, kullanıcı adı, e-posta, telefon, alan adı) hazır gelişmiş arama sorguları üretir: site:, filetype:, inurl:, intitle: gibi.",
              "when": "Arama motorlarında hedefe ait sayfaları, belgeleri ve açıkta kalmış dosyaları hızlıca taramak için.", "input": "Değer, tür ve isteğe bağlı ek kelime.",
              "output": "Google bağlantıları; ayrıntıda Bing, DuckDuckGo, Yandex sürümleri.", "tips": "Ek kelime olarak şehir ya da şirket adı vermek sonuçları çok daraltır."},
    "doc-meta": {"what": "Bir sitenin web arşivindeki PDF, Word, Excel, PowerPoint belgelerini bulup indirir ve içlerindeki yazar, son değiştiren kişi, şirket ve kullanılan yazılım bilgilerini çıkarır.",
                 "when": "Bir kurumun çalışan adlarını, kullanıcı adı biçimini ve kullandığı yazılımları öğrenmek için.", "input": "Alan adı ve / veya belge dosyaları.",
                 "output": "Belgeler ve meta verileri, kişi / kurum özeti.", "tips": "Belgeler arşivden indirildiği için hedef siteye istek gitmez."},
    "spiderfoot": {"what": "200'den fazla modülü olan otomatik OSINT çerçevesi. Bir hedeften başlayıp DNS, sertifika, WHOIS, sızıntı, sosyal medya gibi kaynakları zincirleme tarar.",
                   "when": "Bir alan adı ya da IP hakkında geniş ve otomatik bir ilk tarama istediğinde.", "input": "Alan adı, IP, e-posta ya da tırnak içinde ad.",
                   "output": "Olay türlerine göre bulgular.", "tips": "'Pasif' kapsam hedefe doğrudan istek göndermez. Uzun sürebilir; süre sınırını ayarla."},
    "recon-ng": {"what": "Metasploit benzeri modüler keşif çerçevesi. Panelde alan adı için sertifika ve HackerTarget kaynaklı ana bilgisayarlar ile WHOIS kişileri, kullanıcı adı için profil modülü çalıştırılır.",
                 "when": "Diğer alan adı araçlarının sonuçlarını farklı kaynaklarla tamamlamak için.", "input": "Alan adı veya kullanıcı adı.",
                 "output": "Ana bilgisayarlar, kişiler, profiller.", "tips": "Daha fazla modül için terminalde recon-ng marketplace kullanılabilir."},
}
