"""OpenCorporates: company officers (people) and companies across 140+ registries."""
from urllib.parse import quote_plus

from plugin_api import F, L, session, setting

API = "https://api.opencorporates.com/v0.4"


def run(job, inp, emit):
    q = inp["query"].strip()
    kind = inp.get("kind") or "officers"
    token = setting("opencorporates_api_token")
    web = f"https://opencorporates.com/{kind}?q={quote_plus(q)}"
    if not token:
        emit(title=L(job, "OpenCorporates'te ara", "Search on OpenCorporates"), url=web, status="info",
             detail=L(job, "API anahtarı yok: arama bağlantısı verildi. Ücretsiz (kâr amacı gütmeyen / gazetecilik) anahtar Ayarlar'dan eklenirse sonuçlar burada listelenir.",
                      "No API key: a search link is given. Add a free (non-profit / journalism) key in Settings to list results here."))
        return
    r = session().get(f"{API}/{kind}/search", params={"q": q, "api_token": token, "per_page": 50}, timeout=30)
    if r.status_code in (401, 403):
        emit(title=L(job, "OpenCorporates anahtarı geçersiz", "Invalid OpenCorporates key"), status="error", url=web)
        return
    r.raise_for_status()
    res = r.json().get("results", {})
    items = res.get(kind, [])
    if not items:
        emit(title=L(job, "Kayıt bulunamadı", "No records found"), status="notfound", url=web)
        return
    emit(title="OpenCorporates", url=web, status="info",
         detail=L(job, f"{res.get('total_count', len(items))} sonuç; ilk {len(items)} gösteriliyor", f"{res.get('total_count', len(items))} results; showing the first {len(items)}"))
    for it in items:
        if kind == "officers":
            o = it.get("officer", {})
            c = o.get("company") or {}
            emit(title=o.get("name", ""), url=o.get("opencorporates_url", ""), status="found", tags="OpenCorporates",
                 detail=f"{o.get('position', '')} · {c.get('name', '')}",
                 meta={L(job, "Şirket", "Company"): c.get("name"), L(job, "Ülke", "Jurisdiction"): c.get("jurisdiction_code"),
                       L(job, "Başlangıç", "Start"): o.get("start_date"), L(job, "Bitiş", "End"): o.get("end_date"),
                       L(job, "Doğum tarihi", "Date of birth"): o.get("date_of_birth"), L(job, "Uyruk", "Nationality"): o.get("nationality")})
        else:
            c = it.get("company", {})
            emit(title=c.get("name", ""), url=c.get("opencorporates_url", ""), status="found", tags="OpenCorporates",
                 detail=f"{c.get('jurisdiction_code', '')} · {c.get('company_number', '')} · {c.get('current_status') or ''}",
                 meta={L(job, "Kuruluş", "Incorporated"): c.get("incorporation_date"), L(job, "Kapanış", "Dissolved"): c.get("dissolution_date"),
                       L(job, "Tür", "Type"): c.get("company_type"), L(job, "Adres", "Address"): c.get("registered_address_in_full")})


PLUGIN = {
    "id": "opencorporates", "group": "Kişi", "title": "OpenCorporates", "icon": "box",
    "desc": "140'tan fazla ülkenin şirket sicilinde kişi (yönetici) ya da şirket arar.",
    "fields": [F("query", "Ad soyad ya da şirket adı", required=True, placeholder="Ad Soyad"),
               F("kind", "Ne aranacak", type="select", options=[["officers", "Şirket yöneticileri (kişi)"], ["companies", "Şirketler"]])],
    "run": run,
    "key": ("opencorporates_api_token", False),
    "settings": [("opencorporates_api_token", "OpenCorporates API anahtarı",
                  "Kâr amacı gütmeyen, gazetecilik ve akademik kullanım için ücretsiz başvuru. Anahtarsız yalnızca arama bağlantısı verilir.",
                  True, "https://opencorporates.com/api_accounts/new", "OpenCorporates")],
    "accepts": {"name": {"fields": {"query": "$", "kind": "officers"}, "default": True}},
    "about": {"what": "Dünyanın en büyük açık şirket veritabanında bir kişinin hangi şirketlerde yönetici olduğunu ya da şirketlerin kayıt bilgilerini (numara, kuruluş tarihi, durum, adres) arar.",
              "when": "Bir kişinin iş bağlantılarını ya da bir şirketin gerçek kaydını görmek için.",
              "input": "Ad soyad ya da şirket adı.", "output": "Yöneticilikler ya da şirket kayıtları.",
              "tips": "Aynı isimli kişiler çok olabilir; doğum tarihi, ülke ve şirket adresiyle eşleştirin."},
    "en": {"title": "OpenCorporates", "desc": "Searches officers (people) or companies across the company registries of 140+ jurisdictions.",
           "fields": {"query": {"label": "Full name or company name", "placeholder": "Full Name"},
                      "kind": {"label": "Search for", "options": [["officers", "Company officers (people)"], ["companies", "Companies"]]}},
           "about": {"what": "Searches the world's largest open company database for the companies where a person is an officer, or for company records (number, incorporation date, status, address).",
                     "when": "To see a person's business links or a company's actual registration.",
                     "input": "Full name or company name.", "output": "Officer positions or company records.",
                     "tips": "Many people share names; match on date of birth, jurisdiction and company address."}},
}
