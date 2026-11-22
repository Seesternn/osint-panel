"""İsim araştırma: bir ad soyaddan herkese açık, yasal kaynaklarla neler bulunabileceğini toplar.

Bölümler paralel çalışır ve sonuçlarını liste olarak döndürür; ana iş parçacığı hepsini sırayla yayar
(böylece sonuç sıra numaraları karışmaz). Bir bölümün hatası aracı durdurmaz.

Bilinçli olarak kullanılmayanlar: TC kimlik / adres "sorgu panelleri", sızdırılmış veritabanları (KVKK, TCK 136),
özel kişiler için yüz tanıma araması.
"""
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, quote_plus

import requests

import store
import tools2
from tools import ToolError, gravatar_lookup, run_socialscan

UA = "osint-panel-local/1.0 (personal OSINT panel; local use)"
S = requests.Session()
S.headers["User-Agent"] = UA
FOLD = str.maketrans("ıİğĞşŞöÖüÜçÇâÂîÎ", "iIgGsSoOuUcCaAiI")
fold = lambda s: s.translate(FOLD).lower().strip()

SECTIONS = ["Tanınmış kişi", "Web araması", "Haberler", "Akademik", "GitHub", "Bluesky", "Stack Overflow", "YouTube",
            "Şirket yöneticilikleri", "Yaptırım / PEP", "Kullanıcı adı kontrolü", "Olası kullanıcı adları", "E-posta tahmini",
            "Wikipedia'da geçtiği yerler", "Wikimedia fotoğrafları", "Sosyal medya", "Arama motorları", "Görseller",
            "Şirket ve kamu kayıtları"]



LANGS = ["tr", "en"]          # veri dili sırası; run_namesearch iş diline göre ayarlar


def _l1():
    return LANGS[0]

def R(section, **kw):
    """Bölüm sonucu (emit'e verilecek sözlük)."""
    kw.setdefault("status", "found")
    kw["tags"] = section
    return kw


def split_name(name):
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if len(parts) < 2:
        return parts[0] if parts else "", ""
    return " ".join(parts[:-1]), parts[-1]


# --------------------------------------------------------------------- isim analizi
def name_stats(first, last):
    key = store.get("demografix_api_key")
    extra = {"apikey": key} if key else {}
    out = {}
    try:
        f1 = first.split()[0]
        g = S.get("https://api.genderize.io", params={"name": f1, **extra}, timeout=10).json()
        if g.get("gender") and g.get("count", 0) >= 50:
            out["gender"] = {"value": {"male": "erkek", "female": "kadın"}.get(g["gender"], g["gender"]),
                             "p": g.get("probability", 0), "n": g.get("count", 0)}
        a = S.get("https://api.agify.io", params={"name": f1, **extra}, timeout=10).json()
        if a.get("age"):
            out["age"] = {"value": a["age"], "n": a.get("count", 0)}
        n = S.get("https://api.nationalize.io", params={"name": last or f1, **extra}, timeout=10).json()
        out["count"] = n.get("count", 0)
        # Az verisi olan (nadir) soyadlarda tahmin anlamsız (ör. "Torvalds" → %44 Çin); yeterli veri yoksa gösterme
        if n.get("country") and out["count"] >= 300 and n["country"][0]["probability"] >= 0.25:
            out["nationality"] = [{"cc": c["country_id"], "p": c["probability"]} for c in n["country"][:3] if c["probability"] >= 0.05]
    except Exception as e:
        out["error"] = type(e).__name__
    return out


# --------------------------------------------------------------------- Wikidata
SOCIAL_PROPS = {"P2002": ("X / Twitter", "https://x.com/{}"), "P2003": ("Instagram", "https://www.instagram.com/{}/"),
                "P2013": ("Facebook", "https://www.facebook.com/{}"), "P6634": ("LinkedIn", "https://www.linkedin.com/in/{}/"),
                "P2037": ("GitHub", "https://github.com/{}"), "P2397": ("YouTube", "https://www.youtube.com/channel/{}"),
                "P7085": ("TikTok", "https://www.tiktok.com/@{}"), "P4033": ("Mastodon", ""), "P12361": ("Bluesky", "https://bsky.app/profile/{}"),
                "P1902": ("Spotify", "https://open.spotify.com/artist/{}"), "P2847": ("Google+", "")}


def _claims(ent, pid):
    out = []
    for c in ent.get("claims", {}).get(pid, []):
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if v is not None:
            out.append(v)
    return out


def wikidata(name, place, org):
    api = "https://www.wikidata.org/w/api.php"
    res = S.get(api, params={"action": "wbsearchentities", "search": name, "language": _l1(), "uselang": _l1(),
                             "type": "item", "limit": 8, "format": "json"}, timeout=15).json()
    ids = [x["id"] for x in res.get("search", [])]
    if not ids:
        return None, []
    ents = S.get(api, params={"action": "wbgetentities", "ids": "|".join(ids), "props": "claims|descriptions|labels|sitelinks",
                              "languages": "|".join(LANGS), "format": "json"}, timeout=20).json().get("entities", {})
    humans = []
    for i in ids:
        e = ents.get(i, {})
        if not any((v or {}).get("id") == "Q5" for v in _claims(e, "P31")):
            continue
        label = (e.get("labels", {}).get(LANGS[0]) or e.get("labels", {}).get(LANGS[1]) or {}).get("value", "")
        desc = (e.get("descriptions", {}).get(LANGS[0]) or e.get("descriptions", {}).get(LANGS[1]) or {}).get("value", "")
        score = 2 if fold(label) == fold(name) else (1 if fold(name) in fold(label) else 0)
        for hint in (place, org):
            if hint and fold(hint) in fold(desc):
                score += 2
        humans.append((score, i, e, label, desc))
    if not humans:
        return None, []
    humans.sort(key=lambda h: -h[0])
    score, qid, e, label, desc = humans[0]
    if score < 2:          # isim tam eşleşmiyorsa "tanınmış kişi" demeyelim
        return None, [(h[3], h[4], h[1]) for h in humans[:3]]
    # Etiketleri çözümlenecek kimlikler (meslek, uyruk, doğum yeri)
    refs = {"P106": _claims(e, "P106"), "P27": _claims(e, "P27"), "P19": _claims(e, "P19"), "P108": _claims(e, "P108"), "P69": _claims(e, "P69")}
    want = [v["id"] for vs in refs.values() for v in vs if isinstance(v, dict) and "id" in v][:40]
    labels = {}
    if want:
        le = S.get(api, params={"action": "wbgetentities", "ids": "|".join(want), "props": "labels", "languages": "|".join(LANGS),
                                "format": "json"}, timeout=15).json().get("entities", {})
        labels = {k: (v.get("labels", {}).get(LANGS[0]) or v.get("labels", {}).get(LANGS[1]) or {}).get("value", k) for k, v in le.items()}
    lab = lambda pid: ", ".join(labels.get(v["id"], v["id"]) for v in refs[pid] if isinstance(v, dict))
    date = lambda pid: next((v["time"][1:11] for v in _claims(e, pid) if isinstance(v, dict) and "time" in v), "")
    img = next(iter(_claims(e, "P18")), "")
    socials = []
    for pid, (nm, fmt) in SOCIAL_PROPS.items():
        for v in _claims(e, pid):
            if isinstance(v, str) and fmt:
                socials.append((nm, v, fmt.format(v)))
    sites = [v for v in _claims(e, "P856") if isinstance(v, str)]
    sl = e.get("sitelinks", {})
    wiki = None
    for lang in [l + "wiki" for l in LANGS]:
        if lang in sl:
            t = sl[lang]["title"]
            try:
                sm = S.get(f"https://{lang[:2]}.wikipedia.org/api/rest_v1/page/summary/{quote(t.replace(' ', '_'))}", timeout=10).json()
                wiki = {"title": t, "url": f"https://{lang[:2]}.wikipedia.org/wiki/{quote(t.replace(' ', '_'))}", "extract": sm.get("extract", "")}
            except Exception:
                wiki = {"title": t, "url": f"https://{lang[:2]}.wikipedia.org/wiki/{quote(t.replace(' ', '_'))}", "extract": ""}
            break
    match = {"qid": qid, "label": label, "desc": desc, "url": f"https://www.wikidata.org/wiki/{qid}",
             "image": f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(img)}?width=400" if img else "",
             "birth": date("P569"), "death": date("P570"), "occupation": lab("P106"), "citizenship": lab("P27"),
             "birthplace": lab("P19"), "employer": lab("P108"), "education": lab("P69"),
             "socials": socials, "websites": sites, "wiki": wiki}
    return match, [(h[3], h[4], h[1]) for h in humans[1:4]]


def section_wikidata(name, place, org):
    sec = "Tanınmış kişi"
    match, others = wikidata(name, place, org)
    out = []
    if match:
        out.append(R(sec, title=f"{match['label']} — {match['desc']}", url=match["url"], image=match["image"],
                     detail=(match["wiki"] or {}).get("extract", "")[:500],
                     meta={"Doğum": match["birth"], "Ölüm": match["death"], "Doğum yeri": match["birthplace"],
                           "Meslek": match["occupation"], "Uyruk": match["citizenship"], "Çalıştığı yer": match["employer"],
                           "Eğitim": match["education"], "Ad": match["label"]}))
        if match["wiki"]:
            out.append(R(sec, title=f"Wikipedia: {match['wiki']['title']}", url=match["wiki"]["url"], status="info"))
        for nm, handle, url in match["socials"]:
            out.append(R(sec, kind="username" if nm in ("X / Twitter", "Instagram", "GitHub", "TikTok") else "",
                         title=handle, url=url, detail=f"Resmî {nm} hesabı (Wikidata'da kayıtlı)"))
        for w in match["websites"]:
            out.append(R(sec, title=w, url=w, detail="Resmî web sitesi (Wikidata)"))
    for label, desc, qid in others:
        out.append(R(sec, title=f"Benzer isimli kayıt: {label}", url=f"https://www.wikidata.org/wiki/{qid}", detail=desc, status="maybe"))
    return match, out


# --------------------------------------------------------------------- haberler
def section_news(name, extra):
    sec = "Haberler"
    out, seen = [], set()
    q = f'"{name}"' + (f" {extra}" if extra else "")
    # Google Haberler RSS (Türkçe, güncel)
    try:
        r = S.get(f"https://news.google.com/rss/search?q={quote_plus(q)}" + ("&hl=en-US&gl=US&ceid=US:en" if _l1() == "en" else "&hl=tr&gl=TR&ceid=TR:tr"), timeout=15)
        for it in ET.fromstring(r.content).iter("item"):
            t = (it.findtext("title") or "").strip()
            if not t or fold(t) in seen:
                continue
            seen.add(fold(t))
            src = it.find("source")
            out.append(R(sec, title=t, url=it.findtext("link") or "", detail=f"{(src.text if src is not None else '')} · {(it.findtext('pubDate') or '')[:16]}"))
            if len(out) >= 15:
                break
    except Exception as e:
        out.append(R(sec, kind="warn", title="Google Haberler", detail=f"Okunamadı ({type(e).__name__})"))
    # GDELT (65 dil, son 3 ay)
    try:
        r = S.get("https://api.gdeltproject.org/api/v2/doc/doc", timeout=20,
                  params={"query": f'"{name}"', "mode": "artlist", "format": "json", "maxrecords": 15, "sort": "datedesc", "timespan": "3m"})
        if r.status_code == 200 and r.text.strip().startswith("{"):
            for a in r.json().get("articles", []):
                t = a.get("title", "").strip()
                if t and fold(t) not in seen:
                    seen.add(fold(t))
                    d = a.get("seendate", "")
                    out.append(R(sec, title=t, url=a.get("url", ""), image=a.get("socialimage", ""),
                                 detail=f"{a.get('domain', '')} · {d[:4]}-{d[4:6]}-{d[6:8]} · {a.get('language', '')} (GDELT)"))
    except Exception:
        pass
    if not [o for o in out if o.get("kind") != "warn"]:
        out.append(R(sec, title="Bu isimle güncel haber bulunamadı", status="notfound"))
    return out


# --------------------------------------------------------------------- akademik
def section_academic(name, first, last):
    sec = "Akademik"
    out = []
    try:
        d = S.get("https://api.openalex.org/authors", params={"search": name, "per-page": 6}, timeout=15).json()
        for a in d.get("results", []):
            inst = ", ".join(i.get("display_name", "") for i in (a.get("last_known_institutions") or [])[:2])
            topics = ", ".join(t.get("display_name", "") for t in (a.get("topics") or [])[:3])
            orcid = (a.get("orcid") or "").replace("https://orcid.org/", "")
            out.append(R(sec, title=a.get("display_name", ""), url=a.get("id", "").replace("https://openalex.org/", "https://openalex.org/authors/"),
                         detail=" · ".join(x for x in [inst, topics] if x),
                         status="found" if fold(a.get("display_name", "")) == fold(name) else "maybe",
                         meta={"Yayın": a.get("works_count"), "Atıf": a.get("cited_by_count"), "ORCID": orcid, "Kaynak": "OpenAlex",
                               "Ad": a.get("display_name", "")}))
    except Exception as e:
        out.append(R(sec, kind="warn", title="OpenAlex", detail=f"Okunamadı ({type(e).__name__})"))
    if first and last:
        try:
            q = f'given-names:"{first}" AND family-name:"{last}"'
            d = S.get("https://pub.orcid.org/v3.0/expanded-search/", params={"q": q, "rows": 6},
                      headers={"Accept": "application/json"}, timeout=15).json()
            for x in d.get("expanded-result") or []:
                nm = f"{x.get('given-names', '')} {x.get('family-names', '')}".strip()
                out.append(R(sec, title=f"ORCID: {nm}", url=f"https://orcid.org/{x.get('orcid-id')}",
                             detail=", ".join((x.get("institution-name") or [])[:3]), status="maybe",
                             meta={"ORCID": x.get("orcid-id"), "Kaynak": "ORCID", "Ad": nm}))
        except Exception:
            pass
    for t, u in [("Google Scholar yazar araması", f"https://scholar.google.com/citations?view_op=search_authors&mauthors={quote_plus(name)}"),
                 ("DergiPark (Türk dergileri)", f"https://dergipark.org.tr/tr/search?q={quote_plus(name)}&section=articles"),
                 ("YÖK Akademik", "https://www.google.com/search?q=" + quote_plus(f'site:akademik.yok.gov.tr "{name}"')),
                 ("YÖK Ulusal Tez Merkezi", "https://tez.yok.gov.tr/UlusalTezMerkezi/"),
                 ("Semantic Scholar", f"https://www.semanticscholar.org/search?q={quote_plus(name)}")]:
        out.append(R(sec, title=t, url=u, status="info"))
    return out


# --------------------------------------------------------------------- GitHub
def section_github(name):
    sec = "GitHub"
    h = {"Accept": "application/vnd.github+json"}
    tok = store.get("github_token")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    r = S.get("https://api.github.com/search/users", params={"q": f'fullname:"{name}"', "per_page": 8}, headers=h, timeout=15)
    if r.status_code != 200:
        return [R(sec, kind="warn", title="GitHub araması", detail=f"HTTP {r.status_code} (API sınırı olabilir; Ayarlar'a GitHub anahtarı ekleyin)")], 0
    d = r.json()
    out = []
    for u in d.get("items", [])[:5]:
        try:
            p = S.get(u["url"], headers=h, timeout=10).json()
        except Exception:
            p = {}
        out.append(R(sec, kind="username", title=u["login"], url=u["html_url"], image=u.get("avatar_url", ""),
                     detail=" · ".join(x for x in [p.get("name"), p.get("location"), p.get("company"), p.get("bio")] if x),
                     status="found" if fold(p.get("name") or "") == fold(name) else "maybe",
                     meta={"Ad": p.get("name"), "Konum": p.get("location"), "Şirket": p.get("company"), "Blog": p.get("blog"),
                           "Herkese açık repo": p.get("public_repos"),
                           "Hesap açılışı": (p.get("created_at") or "")[:10], "Twitter / X": p.get("twitter_username")}))
    if not out:
        out.append(R(sec, title="Bu isimde GitHub hesabı yok", status="notfound"))
    return out, d.get("total_count", 0)


# --------------------------------------------------------------------- yaptırım / PEP
def section_sanctions(name):
    sec = "Yaptırım / PEP"
    key = store.get("opensanctions_api_key")
    link = R(sec, title="OpenSanctions'ta ara", url=f"https://www.opensanctions.org/search/?q={quote_plus(name)}", status="info",
             detail="Yaptırım listeleri, siyasi nüfuz sahibi kişiler (PEP), suç kayıtları")
    if not key:
        return [link, R(sec, kind="warn", title="OpenSanctions anahtarı yok",
                        detail="Ayarlar'dan ücretsiz (kâr amacı gütmeyen kullanım) anahtar eklenirse bu bölüm otomatik taranır.")]
    r = S.get("https://api.opensanctions.org/search/default", params={"q": name, "schema": "Person", "limit": 6},
              headers={"Authorization": f"ApiKey {key}"}, timeout=20)
    if r.status_code != 200:
        return [link, R(sec, kind="warn", title="OpenSanctions", detail=f"HTTP {r.status_code}")]
    out = []
    for x in r.json().get("results", []):
        props = x.get("properties", {})
        out.append(R(sec, title=x.get("caption", ""), url=f"https://www.opensanctions.org/entities/{x.get('id')}/",
                     detail=", ".join(x.get("datasets", [])[:4]), status="found" if fold(x.get("caption", "")) == fold(name) else "maybe",
                     meta={"Konular": ", ".join(props.get("topics", [])), "Uyruk": ", ".join(props.get("nationality", [])),
                           "Doğum": ", ".join(props.get("birthDate", [])), "Görev": "; ".join(props.get("position", [])[:3])}))
    if not out:
        out.append(R(sec, title="Yaptırım / PEP kaydı yok", status="notfound", detail="OpenSanctions veritabanında eşleşme bulunamadı."))
    return [*out, link]


# --------------------------------------------------------------------- kullanıcı adları
def section_usernames(job, first, last):
    variants = tools2.make_variants(first, last, seps_mode="all")
    f0 = re.sub(r"[^a-z0-9]", "", first.split()[0].translate(tools2.TR_MAP).lower()) if first else ""
    l0 = re.sub(r"[^a-z0-9]", "", last.translate(tools2.TR_MAP).lower())
    top = [v for v in dict.fromkeys([f"{f0}{l0}", f"{f0}.{l0}", f"{f0}_{l0}", f"{f0[:1]}{l0}", f"{l0}{f0}"]) if len(v) >= 3 and f0 and l0]
    out = [R("Olası kullanıcı adları", kind="username", title=v, status="found") for v in variants[:30]]
    checks = []
    if top:
        def collect(**r):
            if r.get("status") == "found":
                row = {k: v for k, v in r.items() if k != "tags"}
                row["detail"] = (r.get("detail") or "") + " — aynı isimdeki başka biri de olabilir"
                checks.append(R("Kullanıcı adı kontrolü", **row))
        try:
            run_socialscan(job, {"query": " ".join(top)}, collect)
        except Exception as e:
            checks.append(R("Kullanıcı adı kontrolü", kind="warn", title="socialscan", detail=f"Çalışmadı ({type(e).__name__})"))
        if not checks:
            checks.append(R("Kullanıcı adı kontrolü", status="notfound", title="En olası adlar büyük platformlarda alınmamış",
                            detail=", ".join(top)))
    return out, checks


# --------------------------------------------------------------------- e-posta tahmini (isteğe bağlı)
def section_emails(first, last, org_domain):
    sec = "E-posta tahmini"
    f0 = re.sub(r"[^a-z0-9]", "", first.split()[0].translate(tools2.TR_MAP).lower()) if first else ""
    l0 = re.sub(r"[^a-z0-9]", "", last.translate(tools2.TR_MAP).lower())
    if not (f0 and l0):
        return [R(sec, kind="warn", title="E-posta tahmini", detail="Ad ve soyad birlikte gerekli.")]
    locals_ = [f"{f0}.{l0}", f"{f0}{l0}", f"{f0}_{l0}", f"{f0[0]}{l0}"]
    domains = ["gmail.com", "hotmail.com", "outlook.com"]
    cands = [f"{lp}@{d}" for d in domains for lp in locals_[:3]] + [f"{f0}.{l0}@yahoo.com", f"{f0}.{l0}@icloud.com"]
    if org_domain:
        cands = [f"{lp}@{org_domain}" for lp in (f"{f0}.{l0}", f"{f0[0]}{l0}", f0)] + cands
    out = []
    for em in cands[:12]:
        try:
            g = gravatar_lookup(em, S)
        except Exception:
            g = None
        if g:
            out.append(R(sec, title=em, url=g["entry"].get("profileUrl", ""), image=f"https://gravatar.com/avatar/{g['hash']}?s=200",
                         detail=f"Gravatar profili var: {g['name']}".strip(": "), meta={"email": em, "Ad": g["name"]}))
    if not out:
        out.append(R(sec, status="notfound", title=f"{len(cands[:12])} olası adresin hiçbirinde Gravatar profili yok",
                     detail="Bu, adresin olmadığı anlamına gelmez. 'E-posta doğrulayıcı' veya Holehe ile tek tek kontrol edebilirsiniz.",
                     meta={"Denenen": ", ".join(cands[:12])}))
    return out


# --------------------------------------------------------------------- bağlantılar
def section_links(job, name, place, org):
    q = quote_plus(name)
    qq = quote_plus(f'"{name}"')
    g = lambda s: "https://www.google.com/search?q=" + quote_plus(s)
    out = []
    for t, u in [("LinkedIn kişi araması", f"https://www.linkedin.com/search/results/people/?keywords={q}"),
                 ("Facebook kişi araması", f"https://www.facebook.com/search/people/?q={q}"),
                 ("Instagram (Google üzerinden)", g(f'site:instagram.com "{name}"')),
                 ("X / Twitter kullanıcı araması", f"https://x.com/search?q={qq}&f=user"),
                 ("TikTok kullanıcı araması", f"https://www.tiktok.com/search/user?q={q}"),
                 ("YouTube kanal araması", f"https://www.youtube.com/results?search_query={q}&sp=EgIQAg%253D%253D"),
                 ("VK kişi araması", f"https://vk.com/search/people?q={q}"),
                 ("Bluesky kişi araması", f"https://bsky.app/search?q={q}")]:
        out.append(R("Sosyal medya", title=t, url=u, status="info"))
    # Google dork'ları (mevcut araç)
    def collect(**r):
        out.append(R("Arama motorları", **{k: v for k, v in r.items() if k != "tags"}))
    tools2.run_dorks(job, {"value": name, "kind": "name", "extra": place or org}, collect)
    for t, u in [("Google Görseller", f"https://www.google.com/search?tbm=isch&q={qq}"),
                 ("Yandex Görseller", f"https://yandex.com.tr/images/search?text={qq}"),
                 ("Bing Görseller", f"https://www.bing.com/images/search?q={qq}")]:
        out.append(R("Görseller", title=t, url=u, status="info"))
    for t, u in [("OpenCorporates (şirket yöneticileri)", f"https://opencorporates.com/officers?q={q}"),
                 ("Türkiye Ticaret Sicili Gazetesi", g(f'site:ticaretsicil.gov.tr "{name}"')),
                 ("Resmî Gazete (atama, ilan)", g(f'site:resmigazete.gov.tr "{name}"')),
                 ("ilan.gov.tr", g(f'site:ilan.gov.tr "{name}"')),
                 ("TBMM", g(f'site:tbmm.gov.tr "{name}"')),
                 ("Şikayetvar", g(f'site:sikayetvar.com "{name}"')),
                 ("Ekşi Sözlük", f"https://eksisozluk.com/?q={q}"),
                 ("KAP (borsa şirketi yöneticileri)", g(f'site:kap.org.tr "{name}"')),
                 ("ABD SEC EDGAR belgeleri", f"https://www.sec.gov/edgar/search/#/q=%22{quote(name)}%22"),
                 ("DBLP (bilgisayar bilimi yayınları)", f"https://dblp.org/search?q={q}")]:
        out.append(R("Şirket ve kamu kayıtları", title=t, url=u, status="info"))
    return out


# --------------------------------------------------------------------- isim varyasyonları
def name_variants(name):
    """Aynı kişinin farklı yazımları: Türkçe karaktersiz, ikinci ad atılmış."""
    out = [name]
    f = name.translate(FOLD)
    if f != name:
        out.append(f)
    parts = name.split()
    if len(parts) >= 3:
        out.append(f"{parts[0]} {parts[-1]}")
    return list(dict.fromkeys(out))


# --------------------------------------------------------------------- yeni ücretsiz kaynaklar
def section_bluesky(name):
    sec = "Bluesky"
    out, seen = [], set()
    for v in name_variants(name)[:2]:
        d = S.get("https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors", params={"q": v, "limit": 8}, timeout=12).json()
        for a in d.get("actors", []):
            if a["did"] in seen:
                continue
            seen.add(a["did"])
            dn = a.get("displayName") or ""
            exact = fold(dn) == fold(name)
            if not exact and not (set(fold(name).split()) & set(fold(dn).split())):
                continue
            out.append(R(sec, title=f"{dn or a['handle']} (@{a['handle']})", url=f"https://bsky.app/profile/{a['handle']}",
                         image=a.get("avatar", ""), detail=(a.get("description") or "")[:300], status="found" if exact else "maybe",
                         meta={"Ad": dn, "Hesap açılışı": (a.get("createdAt") or "")[:10], "Kullanıcı adı": a["handle"].removesuffix(".bsky.social"),
                               "Varyant": v if v != name else ""}))
    return out or [R(sec, title="Bu isimde Bluesky hesabı yok", status="notfound")]


def section_stackoverflow(name):
    sec = "Stack Overflow"
    out, seen = [], set()
    for v in name_variants(name)[:2]:
        r = S.get("https://api.stackexchange.com/2.3/users", params={"inname": v, "site": "stackoverflow", "pagesize": 8,
                                                                       "order": "desc", "sort": "reputation"}, timeout=12)
        for u in r.json().get("items", []):
            if u["user_id"] in seen:
                continue
            seen.add(u["user_id"])
            dn = html_unescape(u.get("display_name", ""))
            exact = fold(dn) == fold(name)
            out.append(R(sec, title=dn, url=u.get("link", ""), image=u.get("profile_image", ""),
                         detail=" · ".join(x for x in [u.get("location"), f"itibar {u.get('reputation')}"] if x),
                         status="found" if exact else "maybe",
                         meta={"Ad": dn, "Konum": html_unescape(u.get("location") or ""), "Web sitesi": u.get("website_url") or "",
                               "Hesap açılışı": time.strftime("%Y-%m-%d", time.gmtime(u.get("creation_date", 0)))}))
    return out[:8] or [R(sec, title="Bu isimde Stack Overflow hesabı yok", status="notfound")]


def html_unescape(s):
    import html
    return html.unescape(s or "")


def section_crossref(name):
    sec = "Akademik"
    out = []
    d = S.get("https://api.crossref.org/works", params={"query.author": name, "rows": 8, "sort": "relevance",
                                                         "select": "title,author,issued,DOI,container-title"}, timeout=15).json()
    for w in d.get("message", {}).get("items", []):
        au = next((a for a in w.get("author", []) if fold(f"{a.get('given', '')} {a.get('family', '')}") == fold(name)), None)
        if not au:
            continue
        aff = ", ".join(x.get("name", "") for x in au.get("affiliation", []) if x.get("name"))
        year = ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        out.append(R(sec, title=f"Yayın: {(w.get('title') or ['?'])[0][:120]}", url=f"https://doi.org/{w.get('DOI')}",
                     detail=" · ".join(str(x) for x in [year, (w.get("container-title") or [""])[0], aff] if x),
                     meta={"Ad": name, "Kurum": aff, "Yıl": str(year or ""), "Kaynak": "Crossref", "ORCID": (au.get("ORCID") or "").rsplit("/", 1)[-1]}))
    return out


def section_semantic_scholar(name):
    r = S.get("https://api.semanticscholar.org/graph/v1/author/search", timeout=12,
              params={"query": name, "limit": 5, "fields": "name,affiliations,paperCount,citationCount,homepage,url"})
    if r.status_code != 200:
        return []          # anahtarsız ortak kota sık doluyor (429); sessizce atla
    out = []
    for a in r.json().get("data", []):
        out.append(R("Akademik", title=f"Semantic Scholar: {a.get('name')}", url=a.get("url", ""),
                     detail=", ".join(a.get("affiliations") or []), status="found" if fold(a.get("name", "")) == fold(name) else "maybe",
                     meta={"Ad": a.get("name"), "Yayın": a.get("paperCount"), "Atıf": a.get("citationCount"),
                           "Kurum": ", ".join(a.get("affiliations") or []), "Web sitesi": a.get("homepage") or ""}))
    return out


def section_wiki_mentions(name, match):
    sec = "Wikipedia'da geçtiği yerler"
    out = []
    own = fold((match or {}).get("label", ""))
    for lang in LANGS:
        d = S.get(f"https://{lang}.wikipedia.org/w/api.php", timeout=12, params={
            "action": "query", "list": "search", "srsearch": f'"{name}"', "srlimit": 8, "format": "json"}).json()
        for x in d.get("query", {}).get("search", []):
            if fold(x["title"]) in (fold(name), own):
                continue
            snip = re.sub(r"<[^>]+>", "", x.get("snippet", ""))
            out.append(R(sec, title=f"{x['title']} ({lang})", url=f"https://{lang}.wikipedia.org/wiki/{quote(x['title'].replace(' ', '_'))}",
                         detail=html_unescape(snip)[:240], status="found"))
    return out


def section_commons(name):
    sec = "Wikimedia fotoğrafları"
    d = S.get("https://commons.wikimedia.org/w/api.php", timeout=15, params={
        "action": "query", "generator": "search", "gsrsearch": f'"{name}"', "gsrnamespace": 6, "gsrlimit": 8,
        "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 300, "format": "json"}).json()
    out = []
    for p in (d.get("query", {}).get("pages") or {}).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("thumburl"):
            out.append(R(sec, title=p["title"].removeprefix("File:")[:90], url=ii.get("descriptionurl", ""), image=ii["thumburl"],
                         detail="Wikimedia Commons (özgür lisanslı görsel)"))
    return out


def section_youtube(name):
    key = store.get("youtube_api_key")
    if not key:
        return []
    d = S.get("https://www.googleapis.com/youtube/v3/search", timeout=12, params={
        "part": "snippet", "type": "channel", "q": name, "maxResults": 6, "key": key}).json()
    out = []
    for it in d.get("items", []):
        sn = it.get("snippet", {})
        cid = it.get("id", {}).get("channelId", "")
        out.append(R("YouTube", title=sn.get("channelTitle", ""), url=f"https://www.youtube.com/channel/{cid}",
                     image=((sn.get("thumbnails") or {}).get("default") or {}).get("url", ""), detail=sn.get("description", "")[:200],
                     status="found" if fold(sn.get("channelTitle", "")) == fold(name) else "maybe",
                     meta={"Ad": sn.get("channelTitle", ""), "Hesap açılışı": (sn.get("publishedAt") or "")[:10]}))
    return out


def section_companies_house(name):
    key = store.get("companies_house_api_key")
    if not key:
        return []
    r = S.get("https://api.company-information.service.gov.uk/search/officers", auth=(key, ""), timeout=15,
              params={"q": name, "items_per_page": 10})
    if r.status_code != 200:
        return [R("Şirket yöneticilikleri", kind="warn", title="Companies House", detail=f"HTTP {r.status_code}")]
    out = []
    for o in r.json().get("items", []):
        dob = o.get("date_of_birth") or {}
        out.append(R("Şirket yöneticilikleri", title=o.get("title", ""),
                     url="https://find-and-update.company-information.service.gov.uk" + (o.get("links") or {}).get("self", ""),
                     detail=" · ".join(x for x in [o.get("address_snippet"), f"{o.get('appointment_count', 0)} görev",
                                                   f"doğum {dob.get('month', '')}/{dob.get('year', '')}" if dob else ""] if x),
                     status="found" if fold(o.get("title", "")).replace(",", "") .split() and set(fold(name).split()) <= set(fold(o.get("title", "")).replace(",", "").split()) else "maybe",
                     meta={"Ad": o.get("title", ""), "Konum": o.get("address_snippet", ""), "Kaynak": "İngiltere Şirketler Sicili"}))
    return out


# --------------------------------------------------------------------- gerçek web araması (yerel SearXNG)
def _web_meta(title, url):
    """Arama sonucu başlığından ad / kurum çıkarır (ör. 'Ad Soyad - Unvan at Şirket | LinkedIn')."""
    nm = re.split(r"\s[-–|•(]\s?", title)[0].strip()
    meta = {"Ad": nm}
    if "linkedin.com" in url:
        parts = [p.strip() for p in re.split(r"\s[-–]\s", title)]
        if len(parts) >= 2:
            role = parts[1].split(" | ")[0]
            if " at " in role:
                meta["Şirket"] = role.split(" at ")[-1]
            elif " - " not in role and "LinkedIn" not in role:
                meta["Şirket"] = role
    return meta


def section_web(job, name, place, org):
    import searx
    from persona import parse_account
    sec = "Web araması"
    qs = [f'"{name}"', f'"{name}" site:linkedin.com/in', f'"{name}" site:instagram.com', f'"{name}" (site:x.com OR site:twitter.com)',
          f'"{name}" site:facebook.com', f'"{name}" site:tiktok.com', f'"{name}" filetype:pdf']
    if place:
        qs.insert(1, f'"{name}" "{place}"')
    if org:
        qs.insert(1, f'"{name}" "{org}"')
    f = name.translate(FOLD)
    if f != name:
        qs.append(f'"{f}"')
    out, seen, dead = [], set(), set()
    for q in qs[:10]:
        try:
            res, unresp = searx.search(q, lang=_l1(), log=job["log"])
        except Exception as e:
            return out + [R(sec, kind="warn", title="Web araması çalışmadı", detail=str(e)[:200])]
        dead |= {str(u[0]) if isinstance(u, (list, tuple)) else str(u) for u in unresp}
        for x in res[:12]:
            u = x["url"]
            if not u or u in seen:
                continue
            seen.add(u)
            t = x["title"]
            hit = fold(name) in fold(f"{t} {x['content']}") or fold(f) in fold(f"{t} {x['content']}")
            acc = parse_account(u)
            meta = _web_meta(t, u)
            meta["Sorgu"] = q
            if acc:
                meta["Platform"] = acc[0]
            out.append(R(sec, title=t[:140], url=u, detail=x["content"][:260], status="found" if hit else "maybe",
                         meta=meta))
    out.sort(key=lambda r: (r["status"] != "found", "Platform" not in r["meta"]))
    if dead:
        out.append(R(sec, kind="warn", title="Bazı arama motorları yanıt vermedi", detail=", ".join(sorted(dead))[:200]))
    return out[:60]


# --------------------------------------------------------------------- Gemini özeti (isteğe bağlı)
SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "personas": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "summary": {"type": "string"},
            "facts": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "sources": {"type": "array", "items": {"type": "integer"}}}, "required": ["text", "sources"]}}},
            "required": ["id", "summary", "facts"]}},
        "contradictions": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["personas", "contradictions", "next_steps"],
}


def gemini_summary(job, name, personas, rows_by_i):
    import geo
    lines, allowed = [], set()
    for p in personas[:4]:
        lines.append(f"\n## Olası kişi {p['id']} (puan {p['score']}, bağlama nedenleri: {'; '.join(p['reasons'][:4]) or 'yok'})")
        for i in p["rows"][:25]:
            r = rows_by_i.get(i)
            if not r:
                continue
            allowed.add(i)
            meta = "; ".join(f"{k}: {v}" for k, v in (r.get("meta") or {}).items() if v and k not in ("Sorgu",))[:240]
            lines.append(f"[{i}] ({r.get('tags')}) {r.get('title', '')[:140]} | {r.get('detail', '')[:200]} | {meta} | {r.get('url', '')}")
    if not allowed:
        return None, "Özetlenecek kişi bulgusu yok"
    lang_name = "İngilizce (English)" if job.get("lang") == "en" else "Türkçe"
    prompt = f"""Aşağıda "{name}" adıyla yapılan açık kaynak araştırmasının bulguları var; bulgular "olası kişi" gruplarına ayrılmış.
Her olası kişi için 2-3 cümlelik tarafsız bir özet ve önemli bilgileri madde madde yaz. Yalnızca verilen bulguları kullan;
her bilginin yanına dayandığı bulgu numaralarını (köşeli parantezdeki sayılar) "sources" alanına koy. Emin olmadığın bilgiyi yazma,
tahmin yürütme, bulgularda olmayan kişisel bilgi (adres, telefon, aile) ekleme. Gruplar arasındaki çelişkileri ve araştırmacının
yapabileceği doğrulama adımlarını da yaz. Tüm metin {lang_name} olsun.
{''.join(chr(10) + l for l in lines)}"""
    g, err = geo.gemini_json(job, [{"text": prompt}], SUMMARY_SCHEMA)
    if not g:
        return None, err
    for p in g.get("personas", []):          # yalnızca gerçekten verilen bulgu numaralarına atıf kalsın
        for f in p.get("facts", []):
            f["sources"] = [s for s in f.get("sources", []) if s in allowed]
    g["_model"] = g.get("_model")
    return g, None


# --------------------------------------------------------------------- ana çalıştırıcı
def run_namesearch(job, inp, emit):
    LANGS[:] = ["en", "tr"] if job.get("lang") == "en" else ["tr", "en"]
    import persona as P
    name = re.sub(r"\s+", " ", (inp.get("name") or "").strip())
    if len(name) < 3:
        raise ToolError("Bir ad soyad girin.")
    first, last = split_name(name)
    place, org = (inp.get("place") or "").strip(), (inp.get("org") or "").strip()
    org_domain = org.lower() if re.fullmatch(r"[\w-]+(\.[\w-]+)+", org.lower()) else ""
    on = lambda k, d="on": (inp.get(k) or d) not in ("off", False)
    log = job["log"]
    log(f"“{name}” için kaynaklar taranıyor…")

    tasks = {"stats": lambda: name_stats(first, last),
             "wiki": lambda: section_wikidata(name, place, org),
             "links": lambda: section_links(job, name, place, org),
             "bluesky": lambda: section_bluesky(name),
             "stackoverflow": lambda: section_stackoverflow(name),
             "commons": lambda: section_commons(name),
             "youtube": lambda: section_youtube(name),
             "companies": lambda: section_companies_house(name)}
    if on("news"):
        tasks["news"] = lambda: section_news(name, place)
    if on("academic"):
        tasks["academic"] = lambda: section_academic(name, first, last)
        tasks["crossref"] = lambda: section_crossref(name)
        tasks["s2"] = lambda: section_semantic_scholar(name)
    if on("github"):
        tasks["github"] = lambda: section_github(name)
    if on("sanctions"):
        tasks["sanctions"] = lambda: section_sanctions(name)
    if on("usernames") and last:
        tasks["usernames"] = lambda: section_usernames(job, first, last)
    if on("emails", "off"):
        tasks["emails"] = lambda: section_emails(first, last, org_domain)
    if on("web"):
        tasks["web"] = lambda: section_web(job, name, place, org)

    results = {}
    warns = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {k: ex.submit(f) for k, f in tasks.items()}
        for k, f in futs.items():
            try:
                results[k] = f.result()
                log(f"✓ {k}")
            except Exception as e:
                results[k] = None
                warns.append(R("Uyarılar", kind="warn", title=f"{k} bölümü çalışmadı", detail=type(e).__name__))

    stats = results.get("stats") or {}
    match, wiki_rows = results.get("wiki") or (None, [])
    try:
        mentions = section_wiki_mentions(name, match)
    except Exception:
        mentions = []
    gh_rows, gh_total = results.get("github") or ([], 0)
    rows = list(wiki_rows)
    for k in ("news", "academic", "crossref", "s2"):
        rows += results.get(k) or []
    rows += gh_rows
    for k in ("bluesky", "stackoverflow", "youtube", "companies", "sanctions"):
        rows += results.get(k) or []
    if results.get("usernames"):
        uns, checks = results["usernames"]
        rows += checks + uns
    rows += results.get("emails") or []
    rows += results.get("web") or []
    rows += mentions + (results.get("commons") or [])
    rows += results.get("links") or []
    rows += warns

    # Satırları yay (sıra numaraları kişi ayırmada kullanılır)
    def emit_rows(rs):
        for r in rs:
            r["i"] = len(job["results"])
            emit(**r)
    emit_rows(rows)

    ctx = {"place": place, "org": org, "birth_year": inp.get("birth_year"), "known": inp.get("known")}
    ref_path = inp.get("_file")
    log("Bulgular olası kişilere ayrılıyor…")
    personas = P.cluster(rows, name, ctx, ref_path, log)

    # Derin tarama: en olası kişinin hesaplarını diğer araçlara gönder, sonra yeniden kümele
    deep_info = None
    if on("deep", "off") and personas:
        import deepscan
        target = personas[0]
        drows, done = deepscan.run(job, target, budget_s=int(inp.get("deep_budget") or 300))
        emit_rows(drows)
        rows += drows
        personas = P.cluster(rows, name, ctx, ref_path, log)
        deep_info = {"target": target["id"], "target_name": target["name"], "jobs": done, "found": len(drows)}

    summary = None
    if on("summary", "off") and personas:
        log("Gemini özet hazırlıyor…")
        summary, err = gemini_summary(job, name, personas, {r["i"]: r for r in rows})
        if err:
            emit(kind="warn", status="found", tags="Uyarılar", title="Gemini özeti", detail=err)

    counts = {}
    for r in rows:
        if r.get("status") == "found" and r.get("kind") != "warn" and r["tags"] not in (
                "Sosyal medya", "Arama motorları", "Görseller", "Şirket ve kamu kayıtları", "Olası kullanıcı adları", "Uyarılar",
                "Wikimedia fotoğrafları"):
            counts[r["tags"]] = counts.get(r["tags"], 0) + 1
    common = (stats.get("count", 0) or 0) > 20000 or gh_total > 15 or len([p for p in personas if p["exact"]]) >= 4
    sections = [s for s in SECTIONS if any(r["tags"] == s for r in rows)]
    sections += [t for t in dict.fromkeys(r["tags"] for r in rows) if t not in sections and t != "Uyarılar"]
    person = {
        "name": name, "first": first, "last": last, "place": place, "org": org,
        "gender": stats.get("gender"), "age": stats.get("age"), "nationality": stats.get("nationality"),
        "common": common, "match": match, "counts": counts, "sections": sections,
        "web_on": on("web"), "deep": deep_info,
    }
    emit(kind="personas", title="Olası kişiler", status="found", data={"personas": personas, "summary": summary})
    emit(kind="person", title=name, status="found", data=person, image=(match or {}).get("image", ""),
         detail=(match or {}).get("desc", "") or "Tanınmış kişi kaydı bulunamadı (özel kişi olabilir).")
    if common:
        emit(kind="warn", status="found", tags="Uyarılar", title="Bu ad yaygın",
             detail="Aynı ada sahip çok sayıda kişi var. Aşağıdaki 'Olası kişiler' kartlarını şehir, kurum, doğum yılı ya da bilinen bir "
                    "hesapla daraltın ve her eşleşmeyi ikinci bir bilgiyle doğrulayın.")
