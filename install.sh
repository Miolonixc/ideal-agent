#!/usr/bin/env bash
set -euo pipefail

info(){ echo "== $*"; }
err(){ echo "ошибка: $*" >&2; }
has(){ command -v "$1" >/dev/null 2>&1; }
interactive(){ [ -c /dev/tty ] && exec 3< /dev/tty 2>/dev/null && exec 3>&-; }
prompt(){
    local q="$1" dflt="$2" v=""
    if interactive; then printf '%s [%s] ' "$q" "$dflt" >/dev/tty; read -r v </dev/tty 2>/dev/null || v=""; fi
    echo "${v:-$dflt}"
}
yesno(){
    case "$(prompt "$1" "$2")" in y|Y|yes|YES|д|Д|да|Да|1) return 0;; *) return 1;; esac
}
lan_ip(){
    ip -4 addr show 2>/dev/null | awk '/inet / && $2 !~ /^127\./ {sub(/\/.*/,"",$2); print $2; exit}'
    hostname -I 2>/dev/null | awk '{print $1}'
    return 0
}
APK_URL="${IDEAL_APK_URL:-https://github.com/Miolonixc/ideal-agent/releases/download/v0.2.5/ideal-agent-debug.apk}"
offer_apk(){
    [ "${DOWNLOAD_APK:-0}" = "1" ] || { [ "$PLATFORM" = "termux" ] && interactive; } || return 0
    [ "${DOWNLOAD_APK:-0}" = "1" ] || yesno "Скачать APK компаньона в Загрузки?" "n" || return 0
    local DL="$HOME/storage/downloads"
    [ -d "$DL" ] || DL="/sdcard/Download"
    [ -d "$DL" ] || DL="$HOME/Download"
    mkdir -p "$DL" 2>/dev/null || true
    info "скачиваю APK в $DL ..."
    if has curl; then
        curl -fL -o "$DL/ideal-agent-debug.apk" "$APK_URL" && info "APK: $DL/ideal-agent-debug.apk" || err "не удалось скачать APK"
    elif has wget; then
        wget -O "$DL/ideal-agent-debug.apk" "$APK_URL" && info "APK: $DL/ideal-agent-debug.apk" || err "не удалось скачать APK"
    else
        err "нет curl/wget — скачай вручную: $APK_URL"
    fi
}

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-}"

# если скрипт запущен не из репозитория (например, curl | bash), подтянем исходники
if [ ! -d "$SRC/agent" ]; then
    info "исходники не найдены рядом — клонирую репозиторий..."
    REPO_URL="${IDEAL_REPO:-https://github.com/Miolonixc/ideal-agent.git}"
    CLONE_DIR="$(mktemp -d)"
    if ! git clone --depth 1 "$REPO_URL" "$CLONE_DIR" 2>/dev/null; then
        err "не удалось клонировать $REPO_URL (нужен git + сеть)"
        exit 1
    fi
    SRC="$CLONE_DIR"
fi

# --- платформа ---
if [ -d "/data/data/com.termux" ] || [ -n "${TERMUX_VERSION:-}" ]; then
    PLATFORM="termux"
elif [ "$(uname)" = "Darwin" ]; then
    PLATFORM="macos"
else
    PLATFORM="linux"
fi

if [ -z "$DEST" ]; then
    case "$PLATFORM" in
        termux) DEST="$HOME/.local/share/ideal-agent" ;;
        macos)  DEST="$HOME/Library/Application Support/ideal-agent" ;;
        *)      DEST="$HOME/.local/share/ideal-agent" ;;
    esac
fi

echo "== ideal-agent installer =="
echo "platform: $PLATFORM"
echo "SRC : $SRC"
echo "DEST: $DEST"

# --- зависимости ---
info "проверка зависимостей"
if ! has git; then
    info "git не найден — ставлю..."
    case "$PLATFORM" in
        termux) pkg install -y git >/dev/null 2>&1 || { err "pkg install git не удался"; exit 1; } ;;
        macos)  brew install git >/dev/null 2>&1 || { err "brew install git не удался"; exit 1; } ;;
        *)      sudo apt-get update >/dev/null 2>&1; sudo apt-get install -y git >/dev/null 2>&1 || { err "apt-get install git не удался"; exit 1; } ;;
    esac
fi
if ! has python3; then
    info "python3 не найден — ставлю..."
    case "$PLATFORM" in
        termux) pkg install -y python >/dev/null 2>&1 || { err "pkg install python не удался"; exit 1; } ;;
        macos)  brew install python >/dev/null 2>&1 || { err "brew install python не удался"; exit 1; } ;;
        *)      sudo apt-get install -y python3 >/dev/null 2>&1 || { err "apt-get install python3 не удался"; exit 1; } ;;
    esac
fi
PYBIN="$(command -v python3)"
if [ "$("$PYBIN" -c 'import sys;print(sys.version_info>=(3,10))')" != "True" ]; then
    err "нужен python >= 3.10 (сейчас $("$PYBIN" -V 2>&1))"; exit 1
fi
info "python: $PYBIN ($("$PYBIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"
info "зависимостей pip нет: агент использует только стандартную библиотеку Python"

# --- копирование ---
if [ "$SRC" != "$DEST" ]; then
    mkdir -p "$DEST"
    for item in agent skills mcp_servers tests config.example.json README.md pyproject.toml docs install.sh; do
        [ -e "$SRC/$item" ] && cp -r "$SRC/$item" "$DEST/"
    done
    info "файлы скопированы в $DEST"
else
    info "SRC == DEST, копирование пропущено"
fi
chmod +x "$DEST"/skills/*/run.sh 2>/dev/null || true
chmod +x "$DEST"/mcp_servers/*.py 2>/dev/null || true

CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ideal-agent"
mkdir -p "$CFG_DIR"
if [ ! -f "$CFG_DIR/config.json" ]; then
    KEY="${IDEAL_LLM_API_KEY:-}"
    PROV="${IDEAL_PROVIDER:-openai-compatible}"
    BASE="${IDEAL_BASE_URL:-https://api.tokenrouter.com/v1}"
    MODEL="${IDEAL_MODEL:-moonshotai/kimi-k3-free}"
    if [ -z "$KEY" ] && interactive; then
        KEY="$(prompt 'Введите LLM API-ключ (IDEAL_LLM_API_KEY, можно оставить пустым)' "")"
    fi
    cat > "$CFG_DIR/config.json" <<JSON
{
  "llm": {
    "provider": "$PROV",
    "base_url": "$BASE",
    "model": "$MODEL",
    "api_key": "$KEY"
  },
  "mode": "auto",
  "deny": ["shell:rm -rf"],
  "workspace": "$HOME/dev",
  "skills_dir": "$DEST/skills",
  "mcp_servers": [
    "python3 $DEST/mcp_servers/fs_mcp.py",
    "python3 $DEST/mcp_servers/fetch_mcp.py"
  ],
  "use_context": true,
  "telegram": { "token": "${TELEGRAM_BOT_TOKEN:-}", "allowed": [] }
}
JSON
    info "создан конфиг: $CFG_DIR/config.json"
    [ -z "$KEY" ] && info "ВНИМАНИЕ: ключ LLM не задан — задай IDEAL_LLM_API_KEY или впиши api_key в config.json"
else
    info "конфиг уже есть: $CFG_DIR/config.json (не перезаписан)"
fi

cd "$DEST"
if [ -d tests ]; then
    if "$PYBIN" -m unittest discover -s tests >/dev/null 2>&1; then
        info "тесты: OK"
    else
        info "тесты: есть сбои (см. python3 -m unittest discover -s tests)"
    fi
fi

port_free(){
    "$PYBIN" -c "import socket,sys
s=socket.socket(); s.settimeout(0.3)
try:
    s.bind(('0.0.0.0',int(sys.argv[1]))); s.close(); sys.exit(0)
except OSError:
    sys.exit(1)" "$1"
}

# --- сервис ---
SERVICE_ARG="${2:-${SERVICE:-}}"
CHANNEL="${IDEAL_CHANNEL:-}"
if [ -z "$CHANNEL" ] && { [ "$SERVICE_ARG" = "--service" ] || [ "$SERVICE_ARG" = "1" ] || [ -n "${SERVICE:-}" ]; }; then
    if interactive && yesno "Создать сервис (автозапуск)? [telegram/http(companion)]" "http"; then
        CHANNEL="$(prompt 'Канал: telegram или http (для Android-компаньона)?' "http")"
    else
        CHANNEL="${CHANNEL:-telegram}"
    fi
fi

if [ -n "$CHANNEL" ]; then
    case "$CHANNEL" in
        http)
            PORT="${IDEAL_HTTP_PORT:-8080}"
            while ! port_free "$PORT"; do
                info "порт $PORT занят"
                if interactive; then
                    PORT="$(prompt 'Укажи другой свободный порт' "8090")"
                else
                    err "порт $PORT занят — задай IDEAL_HTTP_PORT"; exit 1
                fi
            done
            # убедимся, что ключ LLM есть
            if ! "$PYBIN" -c "import json,os,sys; c=json.load(open(os.path.expanduser('$CFG_DIR/config.json'))); sys.exit(0 if c.get('llm',{}).get('api_key') else 1)"; then
                if interactive; then
                    NK="$(prompt 'LLM API-ключ отсутствует — введите' "")"
                    [ -n "$NK" ] && "$PYBIN" -c "import json,os
p=os.path.expanduser('$CFG_DIR/config.json'); c=json.load(open(p)); c.setdefault('llm',{})['api_key']='$NK'; json.dump(c,open(p,'w'),ensure_ascii=False,indent=2)"
                fi
            fi
            case "$PLATFORM" in
                termux)
                    BOOT="$HOME/.termux/boot"; mkdir -p "$BOOT"
                    cat > "$BOOT/ideal-agent.sh" <<SH
#!/bin/sh
termux-wake-lock
cd "$DEST"
export IDEAL_LLM_API_KEY="${IDEAL_LLM_API_KEY:-}"
export IDEAL_HTTP_HOST=0.0.0.0
export IDEAL_HTTP_PORT=$PORT
nohup sh -c 'while true; do
  if ! pgrep -f "python3 -u main.py" >/dev/null 2>&1; then
    nohup python3 -u main.py http > "\$HOME/logs/ideal-agent-http.log" 2>&1 &
  fi
  sleep 30
done' >/dev/null 2>&1 &
SH
                    chmod +x "$BOOT/ideal-agent.sh"
                    info "Termux-boot скрипт: $BOOT/ideal-agent.sh (нужен Termux:Boot)"
                    ;;
                macos)
                    LAUNCH="$HOME/Library/LaunchAgents/com.idealagent.plist"
                    TOK="${TELEGRAM_BOT_TOKEN:-}"
                    cat > "$LAUNCH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.idealagent</string>
  <key>ProgramArguments</key>
  <array><string>$PYBIN</string><string>$DEST/main.py</string><string>http</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key><string>$TOK</string>
    <key>IDEAL_LLM_API_KEY</key><string>${IDEAL_LLM_API_KEY:-}</string>
    <key>IDEAL_HTTP_HOST</key><string>0.0.0.0</string>
    <key>IDEAL_HTTP_PORT</key><string>$PORT</string>
  </dict>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
PLIST
                    info "LaunchAgent: $LAUNCH (launchctl load $LAUNCH)"
                    ;;
                *)
                    UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
                    cat > "$UNIT_DIR/ideal-agent.service" <<UNIT
[Unit]
Description=ideal-agent (HTTP companion channel)
After=network-online.target
Wants=network-online.target

[Service]
Environment=TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
Environment=IDEAL_LLM_API_KEY=${IDEAL_LLM_API_KEY:-}
Environment=IDEAL_HTTP_HOST=0.0.0.0
Environment=IDEAL_HTTP_PORT=$PORT
WorkingDirectory=$DEST
ExecStart=$PYBIN $DEST/main.py http
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
                    info "юнит: $UNIT_DIR/ideal-agent.service (systemctl --user enable --now ideal-agent)"
                    ;;
            esac
            # запускаем прямо сейчас для проверки
            mkdir -p "$HOME/logs"
            setsid env IDEAL_HTTP_HOST=0.0.0.0 IDEAL_HTTP_PORT="$PORT" "$PYBIN" -u "$DEST/main.py" http > "$HOME/logs/ideal-agent-http.log" 2>&1 < /dev/null &
            sleep 2
            IP="$(lan_ip)"
            info "HTTP-канал запущен на 0.0.0.0:$PORT"
            info "в Android-приложении укажи: http://${IP:-<LAN-IP-этого-телефона>}:$PORT"
            ;;
        telegram)
            TOK="${TELEGRAM_BOT_TOKEN:-}"
            if [ -z "$TOK" ] && interactive; then
                TOK="$(prompt 'Telegram-токен бота' "")"
            fi
            if [ -n "$TOK" ]; then
                "$PYBIN" -c "import json,os
p=os.path.expanduser('$CFG_DIR/config.json'); c=json.load(open(p)); c.setdefault('telegram',{})['token']='$TOK'; json.dump(c,open(p,'w'),ensure_ascii=False,indent=2)"
            fi
            case "$PLATFORM" in
                termux)
                    BOOT="$HOME/.termux/boot"; mkdir -p "$BOOT"
                    cat > "$BOOT/ideal-agent.sh" <<SH
#!/bin/sh
termux-wake-lock
cd "$DEST"
export TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
export IDEAL_LLM_API_KEY="${IDEAL_LLM_API_KEY:-}"
nohup sh -c 'while true; do
  if ! pgrep -f "python3 -u main.py" >/dev/null 2>&1; then
    nohup python3 -u main.py > "\$HOME/logs/ideal-agent-telegram.log" 2>&1 &
  fi
  sleep 30
done' >/dev/null 2>&1 &
SH
                    chmod +x "$BOOT/ideal-agent.sh"
                    info "Termux-boot скрипт: $BOOT/ideal-agent.sh (нужен Termux:Boot)"
                    ;;
                macos)
                    LAUNCH="$HOME/Library/LaunchAgents/com.idealagent.plist"
                    cat > "$LAUNCH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.idealagent</string>
  <key>ProgramArguments</key>
  <array><string>$PYBIN</string><string>$DEST/main.py</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TELEGRAM_BOT_TOKEN</key><string>$TOK</string>
    <key>IDEAL_LLM_API_KEY</key><string>${IDEAL_LLM_API_KEY:-}</string>
  </dict>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
PLIST
                    info "LaunchAgent: $LAUNCH (launchctl load $LAUNCH)"
                    ;;
                *)
                    UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
                    cat > "$UNIT_DIR/ideal-agent.service" <<UNIT
[Unit]
Description=ideal-agent (Telegram channel)
After=network-online.target
Wants=network-online.target

[Service]
Environment=TELEGRAM_BOT_TOKEN=$TOK
Environment=IDEAL_LLM_API_KEY=${IDEAL_LLM_API_KEY:-}
WorkingDirectory=$DEST
ExecStart=$PYBIN $DEST/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
                    info "юнит: $UNIT_DIR/ideal-agent.service (systemctl --user enable --now ideal-agent)"
                    ;;
            esac
            ;;
        *) err "неизвестный канал: $CHANNEL"; exit 1 ;;
    esac
fi

cat <<EOF

Готово. Запуск:
  python3 $DEST/main.py "твоя задача"            # CLI (одноразово)
  python3 $DEST/main.py cli "твоя задача"        # CLI явно
  python3 $DEST/main.py tui                      # TUI (ncurses)
  python3 $DEST/main.py telegram                 # Telegram long-poll
  python3 $DEST/main.py http --port 8080         # HTTP (компаньон/вебхуки)
  python3 $DEST/main.py ide                       # IDE (TCP 127.0.0.1:8765)

Ключи окружения: IDEAL_LLM_API_KEY, TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, IDEAL_PROVIDER,
IDEAL_CHANNEL, IDEAL_HTTP_PORT, IDEAL_HTTP_HOST.
Android-компаньон (APK): https://github.com/Miolonixc/ideal-agent/releases
EOF

offer_apk
