#!/usr/bin/env bash
# ideal-agent installer — works from a checkout or via `curl ... | bash`.
set -Eeuo pipefail

REPO_URL_DEFAULT="https://github.com/Miolonixc/ideal-agent.git"
CHANNEL=""
DEST=""
INSTALL_SERVICE=0
RUN_TESTS=1
CLONE_DIR=""

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { printf 'ошибка: %s\n' "$*" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

cleanup() {
    if [ -n "$CLONE_DIR" ]; then
        rm -rf "$CLONE_DIR"
    fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Использование: bash install.sh [опции]

  --dest PATH          Папка установки
  --service             Создать и запустить HTTP-сервис для компаньона
  --channel http|telegram
                         Канал для сервиса (по умолчанию: http)
  --no-tests            Не запускать тесты после установки
  -h, --help            Показать эту справку

Переменные окружения:
  IDEAL_LLM_API_KEY, IDEAL_PROVIDER, IDEAL_BASE_URL, IDEAL_MODEL
  IDEAL_HTTP_TOKEN, IDEAL_HTTP_PORT, IDEAL_REPO
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dest) [ "$#" -ge 2 ] || fail "для --dest нужен путь"; DEST="$2"; shift 2 ;;
        --service) INSTALL_SERVICE=1; shift ;;
        --channel) [ "$#" -ge 2 ] || fail "для --channel нужен канал"; CHANNEL="$2"; shift 2 ;;
        --no-tests) RUN_TESTS=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "неизвестная опция: $1" ;;
    esac
done

if [ -d /data/data/com.termux ] || [ -n "${TERMUX_VERSION:-}" ]; then
    PLATFORM="termux"
elif [ "$(uname -s)" = "Darwin" ]; then
    PLATFORM="macos"
else
    PLATFORM="linux"
fi

install_package() {
    local package="$1"
    case "$PLATFORM" in
        termux) pkg install -y "$package" ;;
        macos) has brew || fail "нужен Homebrew для установки $package"; brew install "$package" ;;
        linux)
            if has apt-get; then sudo apt-get update && sudo apt-get install -y "$package"
            elif has dnf; then sudo dnf install -y "$package"
            elif has pacman; then sudo pacman -Sy --noconfirm "$package"
            else fail "не знаю, как установить $package; установи его вручную"
            fi ;;
    esac
}

ensure_python() {
    if ! has python3; then
        say "Устанавливаю Python"
        install_package "python"
    fi
    PYBIN="$(command -v python3)"
    "$PYBIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        || fail "нужен Python 3.10+, найден: $($PYBIN -V 2>&1)"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
SRC="$SCRIPT_DIR"

ensure_source() {
    if [ -f "$SRC/main.py" ] && [ -d "$SRC/agent" ]; then return; fi
    has git || { say "Устанавливаю Git"; install_package git; }
    CLONE_DIR="$(mktemp -d)"
    say "Скачиваю исходники"
    git clone --depth 1 "${IDEAL_REPO:-$REPO_URL_DEFAULT}" "$CLONE_DIR"
    SRC="$CLONE_DIR"
}

ensure_python
ensure_source

case "$PLATFORM" in
    termux) DEFAULT_DEST="$HOME/.local/share/ideal-agent" ;;
    macos) DEFAULT_DEST="$HOME/Library/Application Support/ideal-agent" ;;
    *) DEFAULT_DEST="$HOME/.local/share/ideal-agent" ;;
esac
DEST="${DEST:-$DEFAULT_DEST}"
DEST="$("$PYBIN" -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DEST")"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ideal-agent"
CFG="$CFG_DIR/config.json"

say "ideal-agent"
note "Платформа: $PLATFORM"
note "Установка: $DEST"
note "Python: $($PYBIN -V 2>&1)"

say "Копирую файлы"
mkdir -p "$DEST"
for item in main.py agent skills mcp_servers docs tests config.example.json README.md pyproject.toml install.sh; do
    [ -e "$SRC/$item" ] && cp -R "$SRC/$item" "$DEST/"
done
chmod +x "$DEST/install.sh" "$DEST"/skills/*/run.sh 2>/dev/null || true

say "Настраиваю конфиг"
mkdir -p "$CFG_DIR" "$HOME/dev"
if [ ! -f "$CFG" ]; then
    HTTP_TOKEN="${IDEAL_HTTP_TOKEN:-$($PYBIN -c 'import secrets; print(secrets.token_urlsafe(32))')}"
    CFG_PATH="$CFG" DEST_PATH="$DEST" HOME_PATH="$HOME" HTTP_TOKEN="$HTTP_TOKEN" \
    LLM_KEY="${IDEAL_LLM_API_KEY:-}" LLM_PROVIDER="${IDEAL_PROVIDER:-openai-compatible}" \
    LLM_BASE_URL="${IDEAL_BASE_URL:-https://api.tokenrouter.com/v1}" \
    LLM_MODEL="${IDEAL_MODEL:-moonshotai/kimi-k3-free}" "$PYBIN" - <<'PY'
import json
import os

config = {
    "llm": {
        "provider": os.environ["LLM_PROVIDER"],
        "base_url": os.environ["LLM_BASE_URL"],
        "model": os.environ["LLM_MODEL"],
        "api_key": os.environ["LLM_KEY"],
    },
    "mode": "auto",
    "deny": ["shell:rm -rf"],
    "workspace": os.path.join(os.environ["HOME_PATH"], "dev"),
    "sandbox_mode": "required",
    "skills_dir": os.path.join(os.environ["DEST_PATH"], "skills"),
    "mcp_servers": [
        f"python3 {os.path.join(os.environ['DEST_PATH'], 'mcp_servers', 'fs_mcp.py')}",
        f"python3 {os.path.join(os.environ['DEST_PATH'], 'mcp_servers', 'fetch_mcp.py')}",
    ],
    "use_context": True,
    "http": {"host": "127.0.0.1", "token": os.environ["HTTP_TOKEN"], "github_webhook_secret": ""},
    "telegram": {"token": "", "allowed": []},
}
with open(os.environ["CFG_PATH"], "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
    chmod 600 "$CFG"
    note "Создан конфиг: $CFG"
    note "HTTP-токен: $HTTP_TOKEN"
    note "Сохрани токен: он нужен Android-компаньону."
else
    note "Сохраняю существующий конфиг: $CFG"
fi

if [ "$RUN_TESTS" = 1 ]; then
    say "Проверяю установку"
    (cd "$DEST" && "$PYBIN" -m py_compile main.py agent/*.py)
    (cd "$DEST" && "$PYBIN" -m unittest discover -s tests) \
        || note "Тесты не скопированы; запусти: cd $DEST && python3 -m unittest discover -s tests"
fi

write_termux_service() {
    local launcher="$HOME/.termux/boot/ideal-agent-http.sh"
    mkdir -p "$(dirname "$launcher")" "$HOME/.local/state/ideal-agent" "$HOME/.local/state/ideal-agent/logs"
    cat > "$launcher" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
set -eu
PID_FILE="\$HOME/.local/state/ideal-agent/http.pid"
LOG_FILE="\$HOME/.local/state/ideal-agent/logs/http.log"
if [ -f "\$PID_FILE" ] && kill -0 "\$(cat "\$PID_FILE")" 2>/dev/null; then exit 0; fi
termux-wake-lock >/dev/null 2>&1 || true
cd "$DEST"
nohup "$PYBIN" -u main.py http --port "${IDEAL_HTTP_PORT:-8080}" >> "\$LOG_FILE" 2>&1 < /dev/null &
echo \$! > "\$PID_FILE"
EOF
    chmod 700 "$launcher"
    "$launcher"
    note "Termux:Boot launcher: $launcher"
    note "Лог: $HOME/.local/state/ideal-agent/logs/http.log"
}

write_linux_service() {
    local unit_dir="$HOME/.config/systemd/user"
    mkdir -p "$unit_dir"
    cat > "$unit_dir/ideal-agent.service" <<EOF
[Unit]
Description=ideal-agent HTTP companion
After=network-online.target

[Service]
WorkingDirectory=$DEST
ExecStart=$PYBIN $DEST/main.py http --port ${IDEAL_HTTP_PORT:-8080}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now ideal-agent.service
    note "systemd service запущен: ideal-agent.service"
}

write_macos_service() {
    local plist="$HOME/Library/LaunchAgents/com.idealagent.plist"
    mkdir -p "$(dirname "$plist")" "$HOME/Library/Logs/ideal-agent"
    cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.idealagent</string>
  <key>ProgramArguments</key><array><string>$PYBIN</string><string>$DEST/main.py</string><string>http</string><string>--port</string><string>${IDEAL_HTTP_PORT:-8080}</string></array>
  <key>WorkingDirectory</key><string>$DEST</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/ideal-agent/http.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/ideal-agent/http.log</string>
</dict></plist>
EOF
    launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null || true
    note "LaunchAgent: $plist"
}

if [ "$INSTALL_SERVICE" = 1 ]; then
    CHANNEL="${CHANNEL:-http}"
    [ "$CHANNEL" = http ] || fail "пока service installer поддерживает только --channel http"
    say "Создаю HTTP-сервис"
    case "$PLATFORM" in
        termux) write_termux_service ;;
        macos) write_macos_service ;;
        *) write_linux_service ;;
    esac
fi

cat <<EOF

Готово.

Запуск вручную:
  cd $DEST
  $PYBIN main.py "объясни структуру проекта"
  $PYBIN main.py http --port 8080

Android-компаньон: host 127.0.0.1:8080, токен — поле http.token в $CFG
EOF
