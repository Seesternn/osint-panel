"""Plugin template — copy to panel/plugins/<name>.py (or your user plugin folder) and edit.

Everything a plugin needs comes from plugin_api; see the docstring of panel/plugin_api.py for details.
"""
from plugin_api import F, L, ToolError, session, setting


def run(job, inp, emit):
    """job: {"log", "cancel", "lang", "dir"} · inp: the form values · emit(**row): send one result row."""
    username = inp["username"].strip().lstrip("@")
    if not username:
        raise ToolError(L(job, "Kullanıcı adı girin.", "Enter a username."))

    token = setting("example_api_key")          # optional: a value saved on the Settings page
    r = session().get(f"https://example.com/api/users/{username}",
                      headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=15)
    if r.status_code == 404:
        emit(title=L(job, "Hesap bulunamadı", "No account found"), status="notfound")
        return
    r.raise_for_status()
    d = r.json()
    emit(title="Example", url=d.get("url", ""), status="found", image=d.get("avatar", ""),
         detail=d.get("bio", ""), tags="Example",
         meta={L(job, "Ad", "Name"): d.get("name"), L(job, "Hesap açılışı", "Account created"): d.get("created_at")})
    # Dates in meta fields such as "Account created" / "Joined" appear in the case timeline automatically.


PLUGIN = {
    "id": "example",
    "group": "Eklentiler",          # sidebar group; existing ones: Kullanıcı adı, E-posta, Telefon, Kişi, Alan adı, Görsel, Kripto
    "title": "Örnek kaynak",
    "icon": "user",                 # any icon name from ICONS in panel/static/tools.js
    "desc": "Kullanıcı adını example.com'da arar.",
    "fields": [F("username", "Kullanıcı adı", required=True, placeholder="kullanıcı adı")],
    "run": run,
    # Join Smart search: this tool runs whenever a username is searched ("$" = the searched value)
    "accepts": {"username": {"fields": {"username": "$"}, "default": True}},
    # Optional Settings-page field and sidebar key badge
    "settings": [("example_api_key", "Example API anahtarı", "İsteğe bağlı.", True, "https://example.com/developers", "Örnek kaynak")],
    "key": ("example_api_key", False),
    "about": {"what": "…", "when": "…", "input": "…", "output": "…", "tips": "…"},
    "en": {"title": "Example source", "desc": "Looks up a username on example.com.",
           "fields": {"username": {"label": "Username", "placeholder": "username"}},
           "about": {"what": "…", "when": "…", "input": "…", "output": "…", "tips": "…"}},
}
