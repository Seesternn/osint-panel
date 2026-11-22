"""Fediverse and new-network username check: Mastodon (popular instances), Bluesky, Threads."""
import re
from concurrent.futures import ThreadPoolExecutor

from plugin_api import F, L, session

INSTANCES = ["mastodon.social", "mstdn.social", "mastodon.online", "mastodon.world", "mas.to", "fosstodon.org",
             "infosec.exchange", "hachyderm.io", "techhub.social", "social.vivaldi.net", "mastodon.art", "masto.ai"]


def _strip(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _mastodon(s, inst, user):
    try:
        r = s.get(f"https://{inst}/api/v1/accounts/lookup", params={"acct": user}, timeout=12)
    except Exception:
        return inst, None
    return inst, (r.json() if r.status_code == 200 else None)


def run(job, inp, emit):
    user = inp["username"].strip().lstrip("@").split("@")[0]
    s = session()
    found = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        for inst, d in ex.map(lambda i: _mastodon(s, i, user), INSTANCES):
            if job["cancel"].is_set():
                return
            if not d:
                continue
            found += 1
            emit(title=f"Mastodon · {inst}", url=d.get("url", ""), status="found", image=d.get("avatar", ""),
                 detail=_strip(d.get("note"))[:300] or d.get("display_name", ""), tags="Fediverse",
                 meta={L(job, "Ad", "Name"): d.get("display_name"), L(job, "Hesap açılışı", "Account created"): (d.get("created_at") or "")[:10],
                       L(job, "Takipçi", "Followers"): d.get("followers_count"), L(job, "Gönderi", "Posts"): d.get("statuses_count")})
    # Bluesky: kullanıcı adı.bsky.social
    try:
        r = s.get("https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile", params={"actor": f"{user}.bsky.social"}, timeout=12)
        if r.status_code == 200:
            d = r.json()
            found += 1
            emit(title="Bluesky", url=f"https://bsky.app/profile/{d.get('handle')}", status="found", image=d.get("avatar", ""),
                 detail=(d.get("description") or "")[:300], tags="Bluesky",
                 meta={L(job, "Ad", "Name"): d.get("displayName"), L(job, "Takipçi", "Followers"): d.get("followersCount"),
                       L(job, "Hesap açılışı", "Account created"): (d.get("createdAt") or "")[:10]})
    except Exception:
        pass
    # Threads: herkese açık profil sayfasının og:title'ı "(@kullanıcı)" içerir
    try:
        r = s.get(f"https://www.threads.net/@{user}", timeout=12)
        m = re.search(r'<meta property="og:title" content="([^"]+)"', r.text)
        if r.status_code == 200 and m and f"(@{user.lower()})" in m.group(1).lower():
            img = re.search(r'<meta property="og:image" content="([^"]+)"', r.text)
            found += 1
            emit(title="Threads", url=f"https://www.threads.net/@{user}", status="found", image=img.group(1) if img else "",
                 detail=m.group(1).replace("&#064;", "@"), tags="Threads")
    except Exception:
        pass
    if not found:
        emit(title=L(job, "Fediverse / Bluesky / Threads hesabı bulunamadı", "No Fediverse / Bluesky / Threads account found"),
             status="notfound", detail=L(job, f"{len(INSTANCES)} Mastodon sunucusu kontrol edildi.", f"{len(INSTANCES)} Mastodon servers checked."))


PLUGIN = {
    "id": "fediverse", "group": "Kullanıcı adı", "title": "Fediverse / Bluesky / Threads", "icon": "network",
    "desc": "Kullanıcı adını popüler Mastodon sunucularında, Bluesky'de ve Threads'te arar.",
    "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı")],
    "run": run,
    "accepts": {"username": {"fields": {"username": "$"}, "default": True}},
    "about": {"what": "Mastodon'un herkese açık hesap arama API'siyle 12 popüler sunucuyu, Bluesky'yi (kullanıcı.bsky.social) ve Threads profil sayfasını kontrol eder; ad, biyografi, takipçi ve hesap açılış tarihini getirir.",
              "when": "X / Twitter'dan ayrılanların yeni hesaplarını bulmak için.", "input": "Kullanıcı adı.",
              "output": "Bulunan profiller ve ayrıntıları.", "tips": "Mastodon'da aynı kullanıcı adı farklı sunucularda farklı kişilere ait olabilir; fotoğraf ve biyografiyi karşılaştırın."},
    "en": {"title": "Fediverse / Bluesky / Threads", "desc": "Looks up a username on popular Mastodon servers, Bluesky and Threads.",
           "fields": {"username": {"label": "Username", "placeholder": "username"}},
           "about": {"what": "Checks 12 popular Mastodon servers through the public account lookup API, Bluesky (user.bsky.social) and the Threads profile page; returns name, bio, followers and account creation date.",
                     "when": "To find the new accounts of people who left X / Twitter.", "input": "Username.",
                     "output": "Found profiles and details.", "tips": "On Mastodon the same username on different servers can belong to different people; compare photo and bio."}},
}
