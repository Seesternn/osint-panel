"""Merge results of several tools into one list (same rules as the web UI's Smart search)."""
import re
from urllib.parse import urlparse

SEARCH_HOSTS = re.compile(r"(^|\.)(google|bing|duckduckgo|yandex|baidu|sogou)\.[a-z.]+$|web\.archive\.org|wa\.me|lens\.google|tineye\.com|suncalc|overpass|mapillary", re.I)
SKIP_KINDS = {"histogram", "figure", "person", "personas", "geofusion", "photo", "thumb", "clean"}


def norm_url(u):
    try:
        x = urlparse(u)
        return (re.sub(r"^(www|m|mobile)\.", "", x.hostname or "") + x.path.rstrip("/")).lower()
    except Exception:
        return ""


def base_domain(host):
    p = host.lower().removeprefix("www.").split(".")
    n = 3 if len(p) > 2 and p[-2] in ("co", "com", "org", "net", "gov", "edu", "ac") else 2
    return ".".join(p[-n:])


def merge(results, value_type=None):
    """results: {tool_title: [rows]}  →  (profiles, info). Profiles are de-duplicated by URL (by site for e-mail checks)."""
    profiles, info = {}, []
    for tool, rows in results.items():
        for r in rows:
            if r.get("kind") in SKIP_KINDS:
                continue
            if r.get("status") in ("notfound", "error"):
                continue
            host = urlparse(r.get("url") or "").hostname or ""
            is_profile = r.get("url") and r.get("status") in ("found", "maybe") and not SEARCH_HOSTS.search(host)
            if r.get("kind") == "warn" or not is_profile:
                info.append({"tool": tool, **{k: r.get(k, "") for k in ("title", "url", "detail", "status")}})
                continue
            key = "e:" + base_domain(host) if value_type == "email" else norm_url(r["url"])
            cur = profiles.get(key)
            if cur:
                if tool not in cur["tools"]:
                    cur["tools"].append(tool)
                cur["image"] = cur["image"] or r.get("image", "")
                cur["detail"] = cur["detail"] or r.get("detail", "")
                if r.get("status") == "found":
                    cur["status"] = "found"
            else:
                profiles[key] = {"title": r.get("title", ""), "url": r["url"], "status": r.get("status"), "detail": r.get("detail", ""),
                                 "image": r.get("image", ""), "tools": [tool], "meta": r.get("meta") or {}}
    items = sorted(profiles.values(), key=lambda x: (-len(x["tools"]), x["status"] != "found", not x["image"]))
    return items, info
