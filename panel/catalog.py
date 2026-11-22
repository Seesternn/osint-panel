"""Smart search catalog: input-type detection and which tools accept which type.

Shared by the web UI (/api/catalog), the CLI and auto-pivot. Plugins join through their ``accepts`` key.
Field values: "$" = the searched value. ``default``: True / False / a condition string
("key:<setting>", "gmail", "video", "imageurl") evaluated by the caller.
"""
import re

TYPES = ["username", "email", "phone", "name", "domain", "ip", "url", "image", "crypto"]

# (tool id, fields, default)
CORE = {
    "username": [("sherlock", None, True), ("maigret", {"username": "$", "top": 500, "timeout": 10}, True),
                 ("whatsmyname", {"username": "$"}, True), ("user-scanner", {"target": "$"}, True),
                 ("blackbird", {"target": "$"}, True), ("socialscan", {"query": "$"}, True),
                 ("github", {"username": "$"}, True), ("social-activity", {"username": "$"}, True),
                 ("telegram", {"username": "$"}, True), ("nexfil", {"username": "$"}, False),
                 ("social-analyzer", {"username": "$"}, False), ("instaloader", {"username": "$"}, False),
                 ("dorks", {"value": "$", "kind": "username"}, False)],
    "email": [("holehe", {"email": "$"}, True), ("email-accounts", {"email": "$"}, True),
              ("email-verify", {"email": "$"}, True), ("user-scanner", {"target": "$"}, True),
              ("blackbird", {"target": "$"}, True), ("socialscan", {"query": "$"}, True),
              ("hibp", {"email": "$"}, "key:hibp_api_key"), ("ghunt", {"email": "$"}, "gmail"),
              ("h8mail", {"email": "$"}, False), ("dorks", {"value": "$", "kind": "email"}, False)],
    "phone": [("phonenumbers", {"number": "$"}, True), ("ignorant", {"number": "$"}, True),
              ("phoneinfoga", {"number": "$"}, True), ("phone-search", {"number": "$"}, True),
              ("dorks", {"value": "$", "kind": "phone"}, False)],
    "name": [("namesearch", {"name": "$"}, True), ("variants", {"first": "$"}, True),
             ("dorks", {"value": "$", "kind": "name"}, False)],
    "domain": [("whois", {"domain": "$"}, True), ("crtsh", {"domain": "$"}, True), ("site-intel", {"url": "$"}, True),
               ("ipgeo", {"target": "$"}, True), ("shodan", {"target": "$"}, True),
               ("wayback", {"url": "$", "mode": "domain", "limit": 300}, True), ("theharvester", {"domain": "$"}, False),
               ("subfinder", {"domain": "$"}, False), ("dnstwist", {"domain": "$"}, False), ("doc-meta", {"domain": "$"}, False),
               ("recon-ng", {"target": "$", "kind": "domain"}, False), ("spiderfoot", {"target": "$", "minutes": 5}, False),
               ("dorks", {"value": "$", "kind": "domain"}, False)],
    "ip": [("ipgeo", {"target": "$"}, True), ("shodan", {"target": "$"}, True)],
    "url": [("wayback", {"url": "$", "mode": "page"}, True), ("site-intel", {"url": "$"}, True),
            ("video", {"url": "$", "frames": "off"}, "video"), ("geofusion", {"url": "$"}, "imageurl"),
            ("exiftool", {"url": "$"}, "imageurl"), ("reverse-image", {"url": "$"}, "imageurl")],
    "image": [("geofusion", {}, True), ("exiftool", {}, True), ("ela", {}, False)],
    "crypto": [],
}

TLDS = set("com net org info biz io dev app co edu gov mil int xyz site online tech store shop blog me tv cc ai cloud page "
           "live news media agency digital link club pro name mobi asia eu".split())
IMG_RX = re.compile(r"\.(jpe?g|png|webp|gif|heic|tiff?|bmp)(\?|$)", re.I)
VIDEO_RX = re.compile(r"youtu\.?be|tiktok\.com|vimeo\.com|instagram\.com/(reel|p)/|(x|twitter)\.com/.+/status|dailymotion|twitch\.tv", re.I)
BTC_RX = re.compile(r"^(bc1[ac-hj-np-z02-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
ETH_RX = re.compile(r"^0x[0-9a-fA-F]{40}$")


def detect_type(v):
    """Same rules as the web UI: e-mail, url, ip, crypto, phone, name, domain, otherwise username."""
    v = (v or "").strip()
    if not v:
        return None
    if re.fullmatch(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", v):
        return "email"
    if re.match(r"https?://", v, re.I):
        return "url"
    if re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", v):
        return "ip"
    if BTC_RX.match(v) or ETH_RX.match(v):
        return "crypto"
    if re.fullmatch(r"\+?[\d\s()-]{10,18}", v) and len(re.sub(r"\D", "", v)) >= 10:
        return "phone"
    if re.fullmatch(r"[^\W\d_][\w'’.-]*(\s+[^\W\d_][\w'’.-]*){1,3}", v) and not re.search(r"\d", v):
        return "name"
    host = re.sub(r"^www\.", "", v.lower())
    if re.fullmatch(r"([a-z0-9-]+\.)+[a-z]{2,}", host):
        tld = host.rsplit(".", 1)[1]
        if len(tld) == 2 or tld in TLDS:
            return "domain"
    return "username"


def build(registry):
    """Type → [{id, fields, default}] for every tool that exists (core + plugins with ``accepts``)."""
    ids = {t["id"] for t in registry} | {"sherlock"}
    out = {t: [] for t in TYPES}
    for typ, items in CORE.items():
        for tid, fields, default in items:
            if tid in ids:
                out[typ].append({"id": tid, "fields": fields, "default": default})
    for t in registry:
        for typ, spec in (t.get("accepts") or {}).items():
            if typ in out and not any(x["id"] == t["id"] for x in out[typ]):
                out[typ].append({"id": t["id"], "fields": spec.get("fields", {}), "default": spec.get("default", True)})
    return out


def eval_default(d, value, keys):
    """Resolve a default condition. keys: {setting_key: bool}."""
    if d is True or d is False:
        return d
    if isinstance(d, str):
        if d.startswith("key:"):
            return bool(keys.get(d[4:]))
        if d == "gmail":
            return value.lower().endswith("@gmail.com") and bool(keys.get("ghunt_login"))
        if d == "video":
            return bool(VIDEO_RX.search(value))
        if d == "imageurl":
            return bool(IMG_RX.search(value))
    return False


def fill(fields, value):
    return {k: (value if v == "$" else v) for k, v in (fields or {}).items()}
