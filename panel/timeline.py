"""Case timeline: every date found in a case (account creations, births, uploads, breaches, archive
captures, commits…) on one axis, plus when items were saved, archived and when the watcher saw changes."""
import datetime as dt
import re

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS.update({m: i for i, m in enumerate(["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos",
                                           "eylül", "ekim", "kasım", "aralık"], 1)})
# Bu anahtar adlarındaki tarihler olay sayılır (TR + EN etiketler)
DATE_KEYS = re.compile(r"(hesap açıl|account created|katılım|joined|üyelik|member since|doğum|born|ölüm|died|yükleme|upload|"
                       r"sızıntı tarihi|breach date|ilk kayıt|first capture|son kayıt|last capture|ilk sertifika|first certificate|"
                       r"oluşturma|created|kayıt|registered|bitiş|expires|güncelle|updated|son görülme|last seen|last online|"
                       r"çekim tarihi|date taken|son etkinlik|last activity|tarih|date|başlangıç|start)", re.I)
ISO = re.compile(r"\b(19\d{2}|20\d{2})-(\d{2})-(\d{2})")
DMY = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](19\d{2}|20\d{2})\b")
MDY = re.compile(r"\b([A-Za-zçğıöşüÇĞİÖŞÜ]+)\s+(\d{1,2}),?\s+(19\d{2}|20\d{2})\b")
YEAR = re.compile(r"^(19\d{2}|20\d{2})$")


def parse_date(text):
    s = str(text or "").strip()
    m = ISO.search(s)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    m = DMY.search(s)
    if m:
        return _mk(int(m[3]), int(m[2]), int(m[1]))
    m = MDY.search(s)
    if m and m[1].lower() in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1].lower()], int(m[2]))
    m = YEAR.match(s)
    if m:
        return _mk(int(m[1]), 1, 1, precision="year")
    return None


def _mk(y, mo, d, precision="day"):
    try:
        return dt.date(y, mo, d), precision
    except ValueError:
        return None


def build(case, evidence=(), changes=()):
    ev = []
    for it in case.get("items", []):
        for k, v in (it.get("meta") or {}).items():
            if not DATE_KEYS.search(k):
                continue
            p = parse_date(v)
            if p:
                ev.append({"date": p[0].isoformat(), "precision": p[1], "label": k, "title": it.get("title", ""),
                           "url": it.get("url", ""), "item": it["id"], "tool": it.get("tool", ""), "kind": "finding"})
        if it.get("created"):
            ev.append({"date": dt.datetime.fromtimestamp(it["created"]).date().isoformat(), "precision": "day",
                       "label": "vakaya eklendi", "title": it.get("title", ""), "url": it.get("url", ""),
                       "item": it["id"], "tool": it.get("tool", ""), "kind": "saved"})
    for e in evidence:
        ev.append({"date": e["captured_at"][:10], "precision": "day", "label": "kanıt arşivlendi", "title": e.get("url", ""),
                   "url": e.get("url", ""), "item": e.get("item_id"), "tool": "evidence", "kind": "evidence"})
    for c in changes:
        ev.append({"date": dt.datetime.fromtimestamp(c["ts"]).date().isoformat(), "precision": "day", "label": c.get("kind", ""),
                   "title": c.get("title", ""), "url": c.get("url", ""), "item": None, "tool": "watch", "kind": "change"})
    # aynı gün + aynı etiket + aynı başlık tekrarı kaldır
    seen, out = set(), []
    for e in sorted(ev, key=lambda e: (e["date"], e["kind"] != "finding")):
        key = (e["date"], e["label"].lower(), e["title"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
