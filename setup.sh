#!/usr/bin/env bash
# OSINT Panel kurulumu / setup
#   ./setup.sh            → panel + tüm araçlar (all tools)
#   ./setup.sh --minimal  → yalnızca panel + Sherlock + temel Python araçları (core only)
#   ./setup.sh --no-geoclip  → GeoCLIP'i atla (PyTorch ~2 GB) / skip the ~2 GB PyTorch model
# Gereksinimler / requirements: git, uv (https://docs.astral.sh/uv/), macOS veya Linux.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
PY=3.12
MINIMAL=0; GEOCLIP=1
for a in "$@"; do
  case "$a" in
    --minimal) MINIMAL=1 ;;
    --no-geoclip) GEOCLIP=0 ;;
    -h|--help) sed -n 2,6p "$0"; exit 0 ;;
  esac
done

say()  { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m[!] %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "Eksik / missing: $1 — $2"; exit 1; }; }
need git "https://git-scm.com"
need uv  "curl -LsSf https://astral.sh/uv/install.sh | sh"
need curl "https://curl.se"

clone() {  # clone <url> <dir>
  [ -d "$2/.git" ] || git clone --depth 1 "$1" "$2"
}
venv() {   # venv <dir> [python]
  [ -x "$1/bin/python" ] || uv venv --quiet --python "${2:-$PY}" "$1"
}

say "Panel ortamı / panel environment (.venv)"
venv .venv
uv pip install --quiet --python .venv/bin/python -r requirements.txt

say "Sherlock"
clone https://github.com/sherlock-project/sherlock.git sherlock
uv pip install --quiet --python .venv/bin/python ./sherlock

mkdir -p tools
say "Python OSINT araçları / tools (maigret, holehe, socialscan, user-scanner…)"
venv tools/osint
uv pip install --quiet --python tools/osint/bin/python \
  maigret holehe h8mail ignorant instaloader toutatis socialscan social-analyzer dnstwist user-scanner yt-dlp

if [ "$MINIMAL" = 0 ]; then
  say "GHunt"
  venv tools/ghunt
  uv pip install --quiet --python tools/ghunt/bin/python ghunt

  say "SpiderFoot"
  venv tools/spiderfoot
  uv pip install --quiet --python tools/spiderfoot/bin/python spiderfoot-ng

  say "Blackbird"
  clone https://github.com/p1ngul1n0/blackbird.git tools/blackbird
  venv tools/blackbird/.venv
  uv pip install --quiet --python tools/blackbird/.venv/bin/python -r tools/blackbird/requirements.txt

  say "Nexfil"
  clone https://github.com/thewhiteh4t/nexfil.git tools/nexfil
  venv tools/nexfil/.venv
  uv pip install --quiet --python tools/nexfil/.venv/bin/python ./tools/nexfil

  say "theHarvester"
  clone https://github.com/laramies/theHarvester.git tools/theHarvester
  venv tools/theHarvester/.venv 3.14 || venv tools/theHarvester/.venv
  uv pip install --quiet --python tools/theHarvester/.venv/bin/python ./tools/theHarvester

  say "recon-ng"
  clone https://github.com/lanmaster53/recon-ng.git tools/recon-ng
  venv tools/recon-ng/.venv
  uv pip install --quiet --python tools/recon-ng/.venv/bin/python -r tools/recon-ng/REQUIREMENTS

  say "SearXNG (yerel web araması / local web search)"
  clone https://github.com/searxng/searxng.git tools/searxng/src
  venv tools/searxng/.venv
  uv pip install --quiet --python tools/searxng/.venv/bin/python -r tools/searxng/src/requirements.txt
  if [ ! -f tools/searxng/settings.yml ]; then
    SECRET="$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    sed "s/__SECRET__/$SECRET/" tools/searxng/settings.example.yml > tools/searxng/settings.yml
    chmod 600 tools/searxng/settings.yml
  fi

  if [ "$GEOCLIP" = 1 ]; then
    say "GeoCLIP (fotoğraftan konum / photo geolocation, ~2 GB)"
    venv tools/geoclip
    if [ "$(uname)" = Linux ]; then
      # Linux'ta varsayılan PyTorch CUDA'lı gelir (~2.5 GB); CPU sürümü yeterli ve çok daha küçük
      uv pip install --quiet --python tools/geoclip/bin/python torch torchvision --index-url https://download.pytorch.org/whl/cpu
    fi
    uv pip install --quiet --python tools/geoclip/bin/python geoclip
  else
    warn "GeoCLIP atlandı / skipped"
  fi

  if [ "$(uname)" = Darwin ] && command -v swiftc >/dev/null; then
    say "Yazı okuma / OCR (macOS Vision)"
    swiftc -O tools/ocr/ocr.swift -o tools/ocr/ocr
  else
    warn "OCR yalnızca macOS'ta / OCR is macOS-only — skipped"
  fi
fi

say "Veri listeleri / data lists (WhatsMyName, disposable e-mail domains)"
curl -fsSL https://raw.githubusercontent.com/WebBreacher/WhatsMyName/main/wmn-data.json -o tools/wmn-data.json || warn "wmn-data.json indirilemedi / not downloaded"
curl -fsSL https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/main/disposable_email_blocklist.conf \
  -o tools/disposable_domains.txt || warn "disposable_domains.txt indirilemedi / not downloaded"

say "Sistem araçları / system tools"
missing=()
for b in exiftool phoneinfoga subfinder httpx ffmpeg; do command -v "$b" >/dev/null || missing+=("$b"); done
if [ ${#missing[@]} -gt 0 ]; then
  warn "Bulunamadı / not found: ${missing[*]}"
  if command -v brew >/dev/null; then echo "    brew install ${missing[*]}"; else echo "    (paket yöneticinizle kurun / install with your package manager)"; fi
  echo "    OCR (Linux): tesseract-ocr · screenshots: chromium"
fi

chmod +x launch_panel.sh run_panel.sh 2>/dev/null || true
say "Hazır / done →  ./run_panel.sh   (http://127.0.0.1:5050)"
