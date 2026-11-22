"""Panelin kalıcı verisi: ayarlar (API anahtarları) ve vakalar (SQLite).

Her şey bu bilgisayarda, panel klasöründe tutulur; dışarı gönderilmez.
"""
import json
import os
import sqlite3
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")
DB_PATH = os.path.join(HERE, "cases.db")
_lock = threading.Lock()

# ------------------------------------------------------------------ ayarlar
SETTINGS = [
    # key, etiket, açıklama, gizli mi, anahtarın alındığı adres, kullanan araçlar
    ("hibp_api_key", "Have I Been Pwned API anahtarı",
     "Ücretli abonelik. Sayfada e-postanı doğrulayıp planı seçince anahtar e-postayla gelir.", True,
     "https://haveibeenpwned.com/API/Key", "HIBP sızıntı sorgusu"),
    ("shodan_api_key", "Shodan API anahtarı",
     "Ücretsiz hesapla alınır; hesap sayfasında 'API Key' yazan yerde. Yoksa ücretsiz InternetDB kullanılır.", True,
     "https://account.shodan.io/", "Shodan"),
    ("github_token", "GitHub erişim anahtarı",
     "İsteğe bağlı. Hiçbir izin seçmeden bir anahtar oluştur; saatlik 60 olan API sınırı 5000'e çıkar.", True,
     "https://github.com/settings/personal-access-tokens/new", "GitHub profil çıkarıcı"),
    ("anthropic_api_key", "Anthropic (Claude) API anahtarı",
     "Console'da 'Create Key' ile oluşturulur. Kullandıkça ücretlendirilir.", True,
     "https://platform.claude.com/settings/keys", "Görsel konum tahmini"),
    ("gemini_api_key", "Google Gemini API anahtarı",
     "Ücretsiz. Google hesabınla 'Create API key' ile alınır. Ücretsiz katmanda gönderilen fotoğraflar Google tarafından ürün geliştirmede kullanılabilir.", True,
     "https://aistudio.google.com/apikey", "Konum bulucu"),
    ("opensanctions_api_key", "OpenSanctions API anahtarı",
     "Gazeteci, STK ve akademik (kâr amacı gütmeyen) kullanım için ücretsiz. Yaptırım listeleri ve siyasi nüfuz sahibi kişiler.", True,
     "https://www.opensanctions.org/api/", "İsim araştırma"),
    ("youtube_api_key", "YouTube Data API anahtarı",
     "Ücretsiz (günlük kota). Google Cloud Console'da 'YouTube Data API v3'ü etkinleştirip API anahtarı oluşturun.", True,
     "https://console.cloud.google.com/apis/library/youtube.googleapis.com", "İsim araştırma"),
    ("companies_house_api_key", "İngiltere Şirketler Sicili (Companies House) anahtarı",
     "Ücretsiz. Geliştirici hesabı açıp 'REST' türünde anahtar oluşturun; İngiltere'deki şirket yöneticiliklerini gösterir.", True,
     "https://developer.company-information.service.gov.uk/", "İsim araştırma"),
    ("demografix_api_key", "Genderize / Nationalize anahtarı",
     "İsteğe bağlı. Anahtarsız ayda ~2.500 ad sorgulanabilir; daha fazlası için.", True,
     "https://genderize.io/", "İsim araştırma"),
    ("h8mail_keys", "h8mail API anahtarları",
     "Ör. snusbase=xxx leak-lookup_pub=yyy (boşlukla ayır). Desteklenen servisler bağlantıdaki listede.", True,
     "https://github.com/khast3x/h8mail#apis", "h8mail"),
    ("instagram_sessionid", "Instagram sessionid çerezi",
     "instagram.com'a giriş yap → Geliştirici araçları (⌥⌘I) → Application → Cookies → sessionid değerini kopyala. Kimseyle paylaşma.", True,
     "https://www.instagram.com/accounts/login/", "Toutatis"),
    ("default_timeout", "Varsayılan zaman aşımı (sn)", "Araçlarda boş bırakılan zaman aşımı alanları için.", False, "", ""),
]
# Hangi araç hangi anahtarı ister (sol paneldeki simgeler için). required=False: anahtarsız da çalışır.
TOOL_KEYS = {
    "hibp": ("hibp_api_key", True), "geolocate": ("anthropic_api_key", True), "toutatis": ("instagram_sessionid", True),
    "ghunt": ("ghunt_login", True), "shodan": ("shodan_api_key", False), "github": ("github_token", False),
    "h8mail": ("h8mail_keys", False), "geofusion": ("gemini_api_key", False),
    "namesearch": ("opensanctions_api_key", False),
}


def load_settings():
    try:
        return json.load(open(SETTINGS_PATH))
    except Exception:
        return {}


def get(key, default=""):
    v = load_settings().get(key)
    return v if v not in (None, "") else default


def save_settings(values):
    with _lock:
        cur = load_settings()
        for k, v in values.items():
            if k in {s[0] for s in SETTINGS} and v is not None:
                if v is None or v == "":
                    cur.pop(k, None)
                elif v != "__keep__":
                    cur[k] = str(v).strip()
        tmp = SETTINGS_PATH + ".tmp"
        json.dump(cur, open(tmp, "w"), indent=2)
        os.replace(tmp, SETTINGS_PATH)
        os.chmod(SETTINGS_PATH, 0o600)


def public_settings():
    """Panel yalnızca 127.0.0.1'de çalıştığı için kayıtlı değerler arayüze geri gönderilir (göz simgesiyle görülebilsin)."""
    cur = load_settings()
    return [{"key": key, "label": label, "help": help_, "secret": secret, "set": bool(cur.get(key)),
             "value": cur.get(key, ""), "url": url, "used_by": used_by}
            for key, label, help_, secret, url, used_by in SETTINGS]


def key_status():
    cur = load_settings()
    st = {key: bool(cur.get(key)) for key, *_ in SETTINGS}
    st["anthropic_api_key"] = st["anthropic_api_key"] or bool(os.environ.get("ANTHROPIC_API_KEY"))
    st["ghunt_login"] = os.path.exists(os.path.expanduser("~/.malfrats/ghunt/creds.m"))
    return st


# ------------------------------------------------------------------ vakalar
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            notes TEXT DEFAULT '',
            created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            tool TEXT, query TEXT,
            title TEXT, url TEXT, detail TEXT, image TEXT, tags TEXT, status TEXT, kind TEXT,
            meta TEXT, note TEXT DEFAULT '', created REAL);
        CREATE INDEX IF NOT EXISTS items_case ON items(case_id);
        """)


def list_cases():
    with db() as con:
        rows = con.execute("""SELECT c.*, (SELECT COUNT(*) FROM items i WHERE i.case_id = c.id) AS n
                              FROM cases c ORDER BY updated DESC""").fetchall()
    return [dict(r) for r in rows]


def create_case(name):
    now = time.time()
    with db() as con:
        cur = con.execute("INSERT INTO cases(name, created, updated) VALUES (?,?,?)", (name.strip() or "Adsız vaka", now, now))
        return cur.lastrowid


def get_case(cid):
    with db() as con:
        c = con.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        if not c:
            return None
        items = con.execute("SELECT * FROM items WHERE case_id=? ORDER BY id", (cid,)).fetchall()
    out = dict(c)
    out["items"] = [dict(i) | {"meta": json.loads(i["meta"] or "{}")} for i in items]
    return out


def update_case(cid, name=None, notes=None):
    with db() as con:
        if name is not None:
            con.execute("UPDATE cases SET name=?, updated=? WHERE id=?", (name.strip() or "Adsız vaka", time.time(), cid))
        if notes is not None:
            con.execute("UPDATE cases SET notes=?, updated=? WHERE id=?", (notes, time.time(), cid))


def delete_case(cid):
    with db() as con:
        con.execute("DELETE FROM items WHERE case_id=?", (cid,))
        con.execute("DELETE FROM cases WHERE id=?", (cid,))


def add_items(cid, tool, query, items):
    """Aynı vakada aynı (araç, başlık, url) varsa tekrar eklemez."""
    now = time.time()
    added = 0
    with db() as con:
        existing = {(r["tool"], r["title"], r["url"]) for r in
                    con.execute("SELECT tool, title, url FROM items WHERE case_id=?", (cid,))}
        for it in items:
            key = (tool, it.get("title", ""), it.get("url", ""))
            if key in existing:
                continue
            existing.add(key)
            con.execute("""INSERT INTO items(case_id, tool, query, title, url, detail, image, tags, status, kind, meta, created)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cid, tool, query, it.get("title", ""), it.get("url", ""), it.get("detail", ""),
                         it.get("image", ""), it.get("tags", ""), it.get("status", ""), it.get("kind", ""),
                         json.dumps(it.get("meta") or {}, ensure_ascii=False), now))
            added += 1
        con.execute("UPDATE cases SET updated=? WHERE id=?", (now, cid))
    return added


def update_item(iid, note):
    with db() as con:
        con.execute("UPDATE items SET note=? WHERE id=?", (note, iid))


def delete_item(iid):
    with db() as con:
        con.execute("DELETE FROM items WHERE id=?", (iid,))


init_db()
