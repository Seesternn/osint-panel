#!/bin/sh
# OSINT Panel başlatıcı / launcher
# Sunucu çalışmıyorsa arka planda başlatır, hazır olunca tarayıcıda açar. Başlatılamazsa hatayı gösterir.
# Starts the server in the background if needed, opens the browser once it's ready, shows the error otherwise.
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-5050}"
URL="http://127.0.0.1:$PORT"
LOG="panel.log"

if [ "$1" = "--uninstall-service" ]; then
  launchctl bootout "gui/$(id -u)/com.osint-panel.server" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/com.osint-panel.server.plist"
  echo "OSINT Panel service removed."; exit 0
fi

is_panel() { curl -s -m 2 "$URL/healthz" 2>/dev/null | grep -q '"ok":true'; }

notify() {   # $1 = message
  if command -v osascript >/dev/null; then
    osascript -e "display dialog \"$1\" with title \"OSINT Panel\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1
  else
    echo "OSINT Panel: $1" >&2
  fi
}

if ! is_panel; then
  n=0   # panel yeni kapanıyorsa port birkaç saniye dolu görünebilir: biraz bekle
  while lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && [ $n -lt 6 ] && ! is_panel; do sleep 0.5; n=$((n + 1)); done
  if is_panel; then open "$URL" 2>/dev/null || xdg-open "$URL" >/dev/null 2>&1; exit 0; fi
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    notify "$PORT portunu başka bir program kullanıyor, panel başlatılamadı. O programı kapatın.\n\nPort $PORT is used by another program, so the panel cannot start."
    exit 1
  fi
  if [ ! -x .venv/bin/python ]; then
    notify "Panel bu klasörde kurulu değil (.venv yok). Önce ./setup.sh çalıştırın.\n\nThe panel is not installed here (.venv missing). Run ./setup.sh first."
    exit 1
  fi
  # Günlük üzerine yazılmaz, eklenir (son ~2000 satır tutulur) — bir hata sonradan da görülebilsin
  [ -f "$LOG" ] && tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
  printf '\n===== %s start =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
  # macOS: sunucuyu launchd başlatır. Kısayol uygulamasının alt süreci olarak başlatılan sunucu, uygulama kapanınca
  # sistem tarafından sonlandırılıyor; launchd işi kısayoldan bağımsızdır. Durdurmak: launchctl remove com.osint-panel.server
  # macOS: launchd starts the server, because processes started by the shortcut app are killed when the app quits.
  if [ "$(uname)" = Darwin ] && command -v launchctl >/dev/null; then
    # macOS: sunucuyu kullanıcı oturumundaki bir launchd servisi çalıştırır. Kısayol uygulamasının başlattığı süreçler
    # uygulama kapanınca sonlandırıldığı için sunucu kısayola bağlı olmamalı. Servis bir kez kaydedilir (girişte otomatik
    # BAŞLAMAZ); her açılışta yalnızca "kickstart" ile çalıştırılır. Kaldırmak: ./launch_panel.sh --uninstall-service
    LABEL=com.osint-panel.server
    PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
    DOMAIN="gui/$(id -u)"
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST.new" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$(pwd)/.venv/bin/python</string><string>panel/app.py</string></array>
  <key>WorkingDirectory</key><string>$(pwd)</string>
  <key>EnvironmentVariables</key><dict><key>PORT</key><string>$PORT</string></dict>
  <key>StandardOutPath</key><string>$(pwd)/$LOG</string>
  <key>StandardErrorPath</key><string>$(pwd)/$LOG</string>
  <key>RunAtLoad</key><false/>
  <key>KeepAlive</key><false/>
  <key>ProcessType</key><string>Interactive</string>
  <key>SoftResourceLimits</key><dict><key>NumberOfFiles</key><integer>65536</integer></dict>
  <key>HardResourceLimits</key><dict><key>NumberOfFiles</key><integer>65536</integer></dict>
</dict></plist>
PL
    if ! cmp -s "$PLIST.new" "$PLIST" || ! launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1
      mv "$PLIST.new" "$PLIST"
      launchctl bootstrap "$DOMAIN" "$PLIST" >> "$LOG" 2>&1
    else
      rm -f "$PLIST.new"
    fi
    launchctl kickstart "$DOMAIN/$LABEL" >> "$LOG" 2>&1 || PORT="$PORT" nohup .venv/bin/python panel/app.py >> "$LOG" 2>&1 &
  else
    PORT="$PORT" nohup .venv/bin/python panel/app.py >> "$LOG" 2>&1 &
  fi
  i=0
  while [ $i -lt 120 ]; do            # en fazla ~60 sn (ilk açılışta macOS kütüphaneleri tarayabilir)
    is_panel && break
    sleep 0.5
    i=$((i + 1))
  done
  if ! is_panel; then
    ERR=$(tail -n 8 "$LOG" | tr '"\\' "'/" | tr '\n' ' ' | cut -c1-600)
    notify "Panel başlatılamadı / The panel could not start.\n\n$ERR\n\nGünlük / log: $(pwd)/$LOG"
    exit 1
  fi
fi

if command -v open >/dev/null; then open "$URL"; else xdg-open "$URL" >/dev/null 2>&1 || echo "$URL"; fi
