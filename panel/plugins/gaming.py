"""Gaming platforms: Steam, Chess.com and Lichess public profiles."""
import datetime as dt
import re
import xml.etree.ElementTree as ET

from plugin_api import F, L, session


def _date(ts, ms=False):
    try:
        return dt.datetime.utcfromtimestamp(int(ts) / (1000 if ms else 1)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def run(job, inp, emit):
    user = inp["username"].strip().lstrip("@")
    s = session()
    found = 0
    # Steam (özel URL adı)
    try:
        r = s.get(f"https://steamcommunity.com/id/{user}/?xml=1", timeout=15)
        if r.status_code == 200 and "<error>" not in r.text:
            x = ET.fromstring(r.content)
            g = lambda k: (x.findtext(k) or "").strip()
            found += 1
            emit(title="Steam", url=f"https://steamcommunity.com/id/{user}", status="found", image=g("avatarFull"),
                 detail=re.sub(r"<[^>]+>", " ", g("summary"))[:300], tags="Steam",
                 meta={L(job, "Görünen ad", "Display name"): g("steamID"), L(job, "Gerçek ad", "Real name"): g("realname"),
                       L(job, "Konum", "Location"): g("location"), L(job, "Üyelik", "Member since"): g("memberSince"),
                       "SteamID64": g("steamID64"), L(job, "Gizlilik", "Privacy"): g("privacyState")})
    except Exception:
        pass
    # Chess.com
    try:
        r = s.get(f"https://api.chess.com/pub/player/{user.lower()}", timeout=15)
        if r.status_code == 200:
            d = r.json()
            found += 1
            emit(title="Chess.com", url=d.get("url", ""), status="found", image=d.get("avatar", ""), tags="Chess.com",
                 detail=d.get("name", ""),
                 meta={L(job, "Ad", "Name"): d.get("name"), L(job, "Ülke", "Country"): (d.get("country") or "").rsplit("/", 1)[-1],
                       L(job, "Konum", "Location"): d.get("location"), L(job, "Katılım", "Joined"): _date(d.get("joined")),
                       L(job, "Son görülme", "Last online"): _date(d.get("last_online")), L(job, "Unvan", "Title"): d.get("title")})
    except Exception:
        pass
    # Lichess
    try:
        r = s.get(f"https://lichess.org/api/user/{user}", timeout=15)
        if r.status_code == 200:
            d = r.json()
            p = d.get("profile") or {}
            found += 1
            emit(title="Lichess", url=d.get("url", f"https://lichess.org/@/{user}"), status="found", tags="Lichess",
                 detail=(p.get("bio") or "")[:300],
                 meta={L(job, "Ad", "Name"): " ".join(x for x in (p.get("firstName"), p.get("lastName")) if x) or p.get("realName"),
                       L(job, "Ülke", "Country"): p.get("flag") or p.get("country"), L(job, "Konum", "Location"): p.get("location"),
                       L(job, "Hesap açılışı", "Account created"): _date(d.get("createdAt"), ms=True),
                       L(job, "Son görülme", "Last online"): _date(d.get("seenAt"), ms=True), "Links": p.get("links")})
    except Exception:
        pass
    if not found:
        emit(title=L(job, "Steam, Chess.com ve Lichess'te hesap bulunamadı", "No Steam, Chess.com or Lichess account found"), status="notfound")


PLUGIN = {
    "id": "gaming", "group": "Kullanıcı adı", "title": "Oyun platformları", "icon": "gauge",
    "desc": "Steam, Chess.com ve Lichess'teki herkese açık profil ayrıntılarını getirir.",
    "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı")],
    "run": run,
    "accepts": {"username": {"fields": {"username": "$"}, "default": True}},
    "about": {"what": "Steam (özel profil adı), Chess.com ve Lichess'in herkese açık API'lerinden ad, ülke, konum, katılım ve son görülme tarihlerini çeker.",
              "when": "Oyun hesapları gerçek ad, ülke ve aktif olduğu saatler hakkında sık ipucu verir.", "input": "Kullanıcı adı.",
              "output": "Profil ayrıntıları.", "tips": "Steam'de yalnızca özel URL adı (steamcommunity.com/id/...) aranabilir."},
    "en": {"title": "Gaming platforms", "desc": "Fetches public profile details from Steam, Chess.com and Lichess.",
           "fields": {"username": {"label": "Username", "placeholder": "username"}},
           "about": {"what": "Pulls name, country, location, join and last-seen dates from the public APIs of Steam (custom profile name), Chess.com and Lichess.",
                     "when": "Gaming accounts often reveal a real name, country and active hours.", "input": "Username.",
                     "output": "Profile details.", "tips": "On Steam only the custom URL name (steamcommunity.com/id/...) can be searched."}},
}
