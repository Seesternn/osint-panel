"""Public API for OSINT Panel plugins.

A plugin is a single .py file in ``panel/plugins/`` (bundled) or in the user plugin folder
(``$OSINT_PLUGIN_DIR``, default ``<data dir>/plugins_user``) that defines a ``PLUGIN`` dict:

    from plugin_api import F, ToolError, L, session

    def run(job, inp, emit):
        user = inp["username"].strip()
        r = session().get(f"https://example.com/api/{user}", timeout=15)
        if r.status_code == 404:
            emit(title=L(job, "Hesap yok", "No account"), status="notfound")
            return
        d = r.json()
        emit(title=d["name"], url=d["url"], status="found", image=d.get("avatar", ""),
             meta={L(job, "Katılım", "Joined"): d.get("created")})

    PLUGIN = {
        "id": "example",                       # unique, url-safe
        "group": "Kullanıcı adı",              # sidebar group (Turkish group names are translated by the UI)
        "title": "Örnek", "icon": "user",      # icon: any name from ICONS in static/tools.js
        "desc": "Tek satırlık açıklama.",
        "fields": [F("username", "Kullanıcı adı", required=True)],
        "run": run,
        # optional ---------------------------------------------------------------
        "accepts": {"username": {"fields": {"username": "$"}, "default": True}},   # join Smart search
        "en": {"title": "Example", "desc": "One-line description.",
               "fields": {"username": {"label": "Username"}},
               "about": {"what": "...", "when": "...", "input": "...", "output": "...", "tips": "..."}},
        "about": {"what": "...", "when": "...", "input": "...", "output": "...", "tips": "..."},
        "key": ("some_api_key", False),        # (setting key, required?) → key badge in the sidebar
    }

``emit(**row)`` fields: title, url, status ("found" | "maybe" | "notfound" | "info" | "error"),
detail, image, tags, meta (dict). ``job`` gives ``job["log"](text)``, ``job["cancel"]`` (Event),
``job["dir"]`` (scratch dir) and ``job.get("lang")`` ("tr" or "en").
Smart-search input types: username, email, phone, name, domain, ip, url, image, crypto.
"""
import requests

from tools import F, ToolError, UA, run_cmd, which  # noqa: F401  (re-exported for plugins)
import store

__all__ = ["F", "ToolError", "UA", "run_cmd", "which", "L", "session", "setting"]


def L(job, tr, en):
    """Pick the Turkish or English text for the job's UI language."""
    return en if (job or {}).get("lang") == "en" else tr


def session():
    s = requests.Session()
    s.headers["User-Agent"] = UA
    return s


def setting(key, default=""):
    """Read a value saved on the Settings page (e.g. an API key)."""
    return store.get(key, default)
