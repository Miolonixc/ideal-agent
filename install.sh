#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-}"

# если скрипт запущен не из репозитория (например, curl | bash), подтянем исходники
if [ ! -d "$SRC/agent" ]; then
    echo "исходники не найдены рядом — клонирую репозиторий..."
    REPO_URL="${IDEAL_REPO:-https://github.com/Miolonixc/ideal-agent.git}"
    CLONE_DIR="$(mktemp -d)"
    if ! git clone --depth 1 "$REPO_URL" "$CLONE_DIR" 2>/dev/null; then
        echo "ошибка: не удалось клонировать $REPO_URL (нужен git + сеть)" >&2
        exit 1
    fi
    SRC="$CLONE_DIR"
fi
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ideal-agent"

# --- определение платформы ---
if [ -d "/data/data/com.termux" ] || [ -n "${TERMUX_VERSION:-}" ]; then
    PLATFORM="termux"
elif [ "$(uname)" = "Darwin" ]; then
    PLATFORM="macos"
else
    PLATFORM="linux"
fi

# дефолтный каталог установки
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

PYBIN="$(command -v python3 || true)"
if [ -z "$PYBIN" ]; then
    echo "ошибка: нужен python3 (>=3.10)" >&2
    exit 1
fi
if [ "$("$PYBIN" -c 'import sys;print(sys.version_info>= (3,10))')" != "True" ]; then
    echo "ошибка: нужен python >= 3.10 (сейчас $("$PYBIN" -V 2>&1))" >&2
    exit 1
fi
echo "python: $PYBIN ($("$PYBIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])'))"

if [ "$SRC" != "$DEST" ]; then
    mkdir -p "$DEST"
    for item in agent skills mcp_servers tests config.example.json README.md pyproject.toml docs; do
        if [ -e "$SRC/$item" ]; then
            cp -r "$SRC/$item" "$DEST/"
        fi
    done
    echo "файлы скопированы в $DEST"
else
    echo "SRC == DEST, копирование пропущено"
fi

# делаем скрипты исполняемыми
chmod +x "$DEST"/skills/*/run.sh 2>/dev/null || true
chmod +x "$DEST"/mcp_servers/*.py 2>/dev/null || true

mkdir -p "$CFG_DIR"
if [ ! -f "$CFG_DIR/config.json" ]; then
    KEY="${IDEAL_LLM_API_KEY:-${TOKENROUTER_API_KEY:-}}"
    PROV="${IDEAL_PROVIDER:-openai-compatible}"
    BASE="${IDEAL_BASE_URL:-https://api.tokenrouter.com/v1}"
    MODEL="${IDEAL_MODEL:-moonshotai/kimi-k3-free}"
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
    echo "создан конфиг: $CFG_DIR/config.json"
    if [ -z "$KEY" ]; then
        echo "ВНИМАНИЕ: ключ LLM не задан. Задай IDEAL_LLM_API_KEY или впиши api_key в config.json."
    fi
else
    echo "конфиг уже есть: $CFG_DIR/config.json (не перезаписан)"
fi

cd "$DEST"
if [ -d tests ]; then
    if "$PYBIN" -m unittest discover -s tests >/dev/null 2>&1; then
        echo "тесты: OK"
    else
        echo "тесты: есть сбои (см. python3 -m unittest discover -s tests)"
    fi
fi

# --- установка сервиса (автозапуск) ---
SERVICE="${2:-${SERVICE:-}}"
CHANNEL="${IDEAL_CHANNEL:-telegram}"
if [ "$SERVICE" = "--service" ] || [ "$SERVICE" = "1" ]; then
    case "$PLATFORM" in
        termux)
            BOOT="$HOME/.termux/boot"
            mkdir -p "$BOOT"
            TOK="${TELEGRAM_BOT_TOKEN:-}"
            cat > "$BOOT/ideal-agent.sh" <<SH
#!/bin/sh
termux-wake-lock
cd "$DEST"
if ! pgrep -f "python3 -u main.py" >/dev/null 2>&1; then
  export TELEGRAM_BOT_TOKEN="$TOK"
  export IDEAL_LLM_API_KEY="${IDEAL_LLM_API_KEY:-}"
  export IDEAL_HTTP_HOST=0.0.0.0
  if [ "$CHANNEL" = "http" ]; then
    nohup python3 -u main.py http > "\$HOME/logs/ideal-agent-http.log" 2>&1 &
  else
    nohup python3 -u main.py > "\$HOME/logs/ideal-agent-telegram.log" 2>&1 &
  fi
fi
SH
            chmod +x "$BOOT/ideal-agent.sh"
            echo "Termux-boot скрипт: $BOOT/ideal-agent.sh (нужен Termux:Boot)"
            ;;
        macos)
            LAUNCH="$HOME/Library/LaunchAgents/com.idealagent.plist"
            TOK="${TELEGRAM_BOT_TOKEN:-}"
            cat > "$LAUNCH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
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
            echo "LaunchAgent: $LAUNCH (launchctl load $LAUNCH)"
            ;;
        *)
            UNIT_DIR="$HOME/.config/systemd/user"
            mkdir -p "$UNIT_DIR"
            TOK="${TELEGRAM_BOT_TOKEN:-}"
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
            echo "юнит: $UNIT_DIR/ideal-agent.service (systemctl --user enable --now ideal-agent)"
            ;;
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

Ключи окружения: IDEAL_LLM_API_KEY, TELEGRAM_BOT_TOKEN, GITHUB_TOKEN, IDEAL_PROVIDER, IDEAL_CHANNEL.
Автозапуск сервиса: bash install.sh --service            # Telegram (по умолчанию)
                     IDEAL_CHANNEL=http bash install.sh --service   # HTTP-канал для Android-компаньона

Android-компаньон (APK): скачай и установи из релиза —
  https://github.com/Miolonixc/ideal-agent/releases
В приложении укажи адрес агента: http://<LAN-IP-этого-телефона>:8080
EOF
