# Changelog

## 1.0.1 — 2026-11-22

### Security
- Block DNS rebinding (Host allow-list) and cross-site requests (CSRF) to the local panel.

### Changed
- README screenshots no longer show third-party accounts' photos, names or bios.
- Dependency minimums raised; GitHub Actions updated.

## 1.0.0 — 2026-11-22

First public release.

### Search
- Smart search: one input, automatic type detection (username, e-mail, phone, name, domain, IP, link,
  image, crypto address), every matching tool in parallel, results merged with "found by N tools".
- Auto-pivot (1–2 steps): e-mails, usernames, domains, phones and IPs found in results are scanned too,
  with a live graph.
- ~50 tools: Sherlock, Maigret, WhatsMyName, Blackbird, user-scanner, Holehe, GHunt, PhoneInfoga,
  ExifTool, theHarvester, SpiderFoot, Recon-ng and more.
- Name research with possible-person clustering, deep scan and optional AI summary.
- Photo geolocation (EXIF + GeoCLIP + OCR + optional AI).
- New sources as plugins: Fediverse / Bluesky / Threads, Steam / Chess.com / Lichess, BTC / ETH addresses,
  favicon hash pivot, archive.today + Common Crawl, OpenCorporates.

### Cases
- Evidence archive: full-page screenshot + HTML + SHA-256 manifest per finding, included in the report.
- Timeline of every date found in a case.
- Watchlist: scheduled re-checks; reports accounts that disappear, changed profile photos / text and
  confirmed new accounts.
- Link graph, notes, HTML / PDF report, CSV / JSON / XLSX export.

### Platform
- Plugin system (bundled and user plugins).
- Command line (`./osint`) and REST API (`/api/v1/search`).
- Optional local AI through Ollama instead of Gemini.
- Turkish / English interface.
- Docker image (non-root, data volume, optional access token) and CI.
