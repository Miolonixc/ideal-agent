#!/usr/bin/env bash
# ideal-agent updater — downloads a clean release snapshot and preserves user config.
set -Eeuo pipefail

REPO_URL_DEFAULT="https://github.com/Miolonixc/ideal-agent.git"
BRANCH="main"
DEST=""
RUN_TESTS=1
RESTART=1
CHECK_ONLY=0
CLONE_DIR=""

say() { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
fail() { printf 'ошибка: %s\n' "$*" >&2; exit 1; }
has() { command -v "$1" >/dev/null 2>&1; }

cleanup() { if [ -n "$CLONE_DIR" ]; then rm -rf "$CLONE_DIR"; fi; }
trap cleanup EXIT

usage() {
    cat <<'EOF'
Использование: bash update.sh [опции]

  --dest PATH       Папка ранее установленного агента
  --branch NAME     Ветка для обновления (по умолчанию: main)
  --no-tests        Не запускать тесты после обновления
  --no-restart      Не перезапускать уже установленный HTTP-сервис
  --check           Только проверить, доступна ли новая ревизия
  -h, --help        Показать эту справку

Переменная IDEAL_REPO позволяет использовать fork/зеркало репозитория.
Конфиг ~/.config/ideal-agent/config.json этим скриптом не изменяется.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dest) [ "$#" -ge 2 ] || fail "для --dest нужен путь"; DEST="$2"; shift 2 ;;
        --branch) [ "$#" -ge 2 ] || fail "для --branch нужна ветка"; BRANCH="$2"; shift 2 ;;
        --no-tests) RUN_TESTS=0; shift ;;
        --no-restart) RESTART=0; shift ;;
        --check) CHECK_ONLY=1; shift ;;
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
case "$PLATFORM" in
    macos) DEFAULT_DEST="$HOME/Library/Application Support/ideal-agent" ;;
    *) DEFAULT_DEST="$HOME/.local/share/ideal-agent" ;;
esac
DEST="${DEST:-$DEFAULT_DEST}"
DEST="$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$DEST" 2>/dev/null || printf '%s' "$DEST")"

has git || fail "для обновления нужен git; установи его и повтори команду"
[ -d "$DEST" ] || fail "папка установки не найдена: $DEST (сначала запусти install.sh)"
[ -f "$DEST/main.py" ] || fail "в $DEST нет main.py; это не установка ideal-agent"

CLONE_DIR="$(mktemp -d)"
say "Проверяю обновление"
git clone --depth 1 --branch "$BRANCH" "${IDEAL_REPO:-$REPO_URL_DEFAULT}" "$CLONE_DIR"
REMOTE_REVISION="$(git -C "$CLONE_DIR" rev-parse --short HEAD)"
LOCAL_REVISION=""
if [ -f "$DEST/.ideal-agent-revision" ]; then LOCAL_REVISION="$(tr -d '[:space:]' < "$DEST/.ideal-agent-revision")"; fi
note "Текущая ревизия: ${LOCAL_REVISION:-неизвестна}"
note "Доступная ревизия: $REMOTE_REVISION ($BRANCH)"

if [ "$CHECK_ONLY" = 1 ]; then
    if [ -n "$LOCAL_REVISION" ] && [ "$LOCAL_REVISION" = "$REMOTE_REVISION" ]; then note "Обновление не требуется"; else note "Доступно обновление"; fi
    exit 0
fi

say "Обновляю код"
for item in main.py agent skills mcp_servers docs tests config.example.json README.md pyproject.toml install.sh update.sh; do
    [ -e "$CLONE_DIR/$item" ] && cp -R "$CLONE_DIR/$item" "$DEST/"
done
printf '%s\n' "$REMOTE_REVISION" > "$DEST/.ideal-agent-revision"
chmod +x "$DEST/install.sh" "$DEST/update.sh" "$DEST"/skills/*/run.sh 2>/dev/null || true
note "Конфиг и пользовательские данные сохранены"

if [ "$RUN_TESTS" = 1 ]; then
    say "Проверяю обновление"
    (cd "$DEST" && python3 -m py_compile main.py agent/*.py)
    (cd "$DEST" && python3 -m unittest discover -s tests) || fail "тесты не прошли; сервис не перезапущен"
fi

if [ "$RESTART" = 1 ]; then
    say "Перезапускаю сервис, если он установлен"
    case "$PLATFORM" in
        termux)
            LAUNCHER="$HOME/.termux/boot/ideal-agent-http.sh"
            PID_FILE="$HOME/.local/state/ideal-agent/http.pid"
            if [ -x "$LAUNCHER" ]; then
                if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then kill "$(cat "$PID_FILE")" || true; fi
                "$LAUNCHER"
                note "Termux HTTP-сервис перезапущен"
            fi ;;
        macos)
            PLIST="$HOME/Library/LaunchAgents/com.idealagent.plist"
            [ -f "$PLIST" ] && launchctl kickstart -k "gui/$(id -u)/com.idealagent" 2>/dev/null && note "LaunchAgent перезапущен" || true ;;
        linux)
            systemctl --user is-enabled ideal-agent.service >/dev/null 2>&1 && systemctl --user restart ideal-agent.service && note "systemd-сервис перезапущен" || true ;;
    esac
fi

printf '\nГотово: ideal-agent обновлён до %s.\n' "$REMOTE_REVISION"
