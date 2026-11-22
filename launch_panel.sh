#!/bin/sh
# OSINT Panel başlatıcı: sunucu çalışmıyorsa arka planda başlatır, sonra tarayıcıda açar.
cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:5050"

if ! curl -s -o /dev/null "$URL/api/tools"; then
  nohup .venv/bin/python panel/app.py > panel.log 2>&1 &
  # sunucu hazır olana kadar en fazla ~20 sn bekle
  i=0
  while [ $i -lt 40 ]; do
    curl -s -o /dev/null "$URL/api/tools" && break
    sleep 0.5
    i=$((i + 1))
  done
fi

if command -v open >/dev/null; then open "$URL"; else xdg-open "$URL" >/dev/null 2>&1 || echo "$URL"; fi
