# OSINT Panel

A local, single-page web panel that puts ~45 open-source intelligence tools behind one search box.
Type a username, e-mail, phone number, full name, domain, IP, link or drop an image: the panel detects
what it is, runs every tool that accepts that kind of input in parallel and merges the results into one
report you can filter, select from and save to a case.

Everything runs on your own computer (`127.0.0.1`). API keys and case data stay in the panel folder and
are never committed.

> 🇹🇷 Türkçe açıklama aşağıda: [Türkçe](#türkçe)

## Features

- **Smart search** – one input, automatic type detection, all matching tools in parallel, results merged
  by profile/site with "found by N tools" badges, select → copy / save to case.
- **Username** – Sherlock, Maigret, WhatsMyName, Blackbird, user-scanner, socialscan, Nexfil,
  Social Analyzer, GitHub profile extractor, Reddit / HN / Keybase, Telegram, username generator.
- **E-mail** – Holehe, account check (Gravatar, Microsoft), verifier, HIBP, h8mail, GHunt, header analyzer.
- **Phone** – PhoneInfoga, number parser, Ignorant, number-format search.
- **Person** – name research: Wikidata, news, academic records, GitHub, Bluesky, Stack Overflow,
  sanctions lists, real web search through a local SearXNG, *possible persons* clustering (shared
  usernames, e-mails, identical profile photos, official links), optional deep scan and Gemini summary.
- **Image / video** – ExifTool, photo geolocation (EXIF + GeoCLIP + OCR + optional Gemini),
  reverse image search links, photo matching, ELA, video analysis.
- **Domain / IP** – WHOIS/DNS, crt.sh, subfinder, dnstwist, Wayback Machine, analytics-ID pivoting,
  Shodan, theHarvester, document metadata, SpiderFoot, Recon-ng.
- **Workspace** – cases with notes, link graph, HTML/PDF report, CSV/JSON/XLSX export, tool chaining (→),
  persistent API keys, Turkish / English interface.

## Install

Requirements: `git`, [`uv`](https://docs.astral.sh/uv/), macOS or Linux. Optional system tools:
`exiftool`, `phoneinfoga`, `subfinder`, `ffmpeg` (`brew install exiftool phoneinfoga subfinder ffmpeg`).

```bash
git clone <this-repo> osint-panel && cd osint-panel
./setup.sh              # everything (~3 GB, GeoCLIP/PyTorch is the big part)
./setup.sh --minimal    # panel + Sherlock + core Python tools only
./setup.sh --no-geoclip # everything except the photo-geolocation model
./run_panel.sh          # → http://127.0.0.1:5050
```

`launch_panel.sh` starts the server in the background and opens the browser.
API keys (all optional) are added in **Settings**; each field has a "Get key" button.

## Responsible use

This panel only queries public sources. It deliberately does **not** include identity/address lookup
panels, leaked databases or face recognition. Use it for your own footprint, authorized investigations,
journalism and research, and follow the law where you live (e.g. GDPR / KVKK).

## Credits

- **Author:** Seesternn
- Built on the work of the open-source projects it wraps: Sherlock, Maigret, WhatsMyName, Blackbird,
  user-scanner, socialscan, Holehe, h8mail, GHunt, PhoneInfoga, Ignorant, Instaloader, Toutatis,
  theHarvester, Nexfil, SpiderFoot, Recon-ng, dnstwist, subfinder, SearXNG, GeoCLIP, ExifTool and others.
  Each tool keeps its own license; they are downloaded by `setup.sh`, not redistributed here.

## License

MIT © Seesternn — see [LICENSE](LICENSE).

---

## Türkçe

Bilgisayarında çalışan, ~45 açık kaynak istihbarat (OSINT) aracını tek arama kutusunda toplayan panel.
Kullanıcı adı, e-posta, telefon, ad soyad, alan adı, IP, bağlantı yaz ya da görsel yükle: panel türünü
anlar, o veriyi kabul eden bütün araçları aynı anda çalıştırır ve sonuçları tek raporda birleştirir.
Beğendiğin sonuçları seçip vakaya kaydedebilir, rapor alabilirsin.

**Kurulum:** `./setup.sh` → `./run_panel.sh` → http://127.0.0.1:5050. Arayüz dili sağ üstteki
TR / EN düğmesiyle değiştirilir. API anahtarları **Ayarlar** sayfasından girilir ve yalnızca bu
bilgisayarda saklanır (`panel/settings.json`, depoya girmez).

**Sorumlu kullanım:** Kimlik / adres sorgu panelleri, sızdırılmış veriler ve yüz tanıma bilinçli olarak
yoktur. KVKK ve TCK 136'ya uygun, yalnızca kamuya açık kaynaklarla çalışır.

**Emeği geçenler:** Seesternn
