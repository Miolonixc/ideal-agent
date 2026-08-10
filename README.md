# ideal-agent

Провайдер-агностичный AI-агент для разработки (open-source, local-first). Собран из
лучших практик Codex CLI, Claude Code, opencode, Hermes, Aider, Gemini CLI, Cline/Roo, Goose.

## Возможности

- **Провайдер-агностичность** — один LLM-интерфейс (`OpenAICompatible`); модель меняется в конфиге.
- **Агентный цикл** — `prompt → tool_calls → observe → repeat`, парсинг нативных tool-call и markdown-fallback, компакшн истории.
- **Память** — локальный BM25 repo-index + KV-память по скоупам (+ опц. эмбеддинги).
- **Тулы** — `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `shell` (с ограничением по workspace).
- **Расширяемость** — skills (папка навыков) и MCP-клиент (JSON-RPC over stdio), subagents.
- **Безопасность** — режимы апрува `suggest`/`auto`/`full-auto`, audit-log, diff, sandbox.
- **Каналы** — CLI, TUI (curses), Telegram (long-poll) и IDE (TCP/JSON).

## Установка

Требуется Python 3.10+. Внешних зависимостей нет.

```
cd ideal-agent
python3 main.py "твоя задача"
```

## Конфиг

`~/.config/ideal-agent/config.json` (шаблон: `config.example.json`):

```json
{
  "llm": {
    "provider": "openrouter",
    "base_url": "https://openrouter.ai/api/v1",
    "model": "openrouter/free"
  },
  "mode": "auto",
  "allow": [],
  "deny": ["shell:rm -rf"],
  "workspace": "~/dev",
  "skills_dir": "skills",
  "mcp_servers": ["python3 mcp_servers/fs_mcp.py"]
}
```

Ключ берётся из `IDEAL_LLM_API_KEY` либо стандартной переменной выбранного
провайдера (например, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`),
или из `llm.api_key` в конфиге.

### Полная справка по конфигу

| Поле | Значение по умолчанию | Описание |
|------|----------------------|----------|
| `llm.provider` | `openrouter` | Провайдер: `openai-compatible`, `openai`, `openrouter`, `ollama`, `anthropic`, `gemini`, `groq`, `deepseek`, `moonshot`, `together` |
| `llm.base_url` | `https://openrouter.ai/api/v1` | Базовый URL чат-комплишена (только для OpenAI-совместимых) |
| `llm.api_key` | — | Ключ (иначе из `IDEAL_LLM_API_KEY` или переменной провайдера) |
| `llm.model` | `openrouter/free` | Имя модели |
| `llm.temperature` | `0.3` | Температура генерации |
| `llm.timeout` | `120` | Таймаут запроса, сек |
| `llm.max_tokens` | `2048` | Лимит выходных токенов (важен для reasoning-моделей) |
| `llm.retries` | `2` | Повторы только для HTTP 408/429/5xx; сетевые обрывы не повторяются во избежание дублей |
| `mode` | `auto` | Апрув-гейт: `suggest`/`auto`/`full-auto` |
| `allow` | `[]` | Правила авто-разрешения (`shell:ls`, `read_file:*`) |
| `deny` | `[]` | Правила блокировки (`shell:rm -rf`) |
| `workspace` | `~/dev` | Рабочая папка (ограничение тулов) |
| `sandbox_mode` | `required` | Shell sandbox: `required`, `best-effort` или `disabled` |
| `context_budget` | `6000` | Бюджет токенов до компакшна истории |
| `skills_dir` | — | Папка с навыками |
| `mcp_servers` | `[]` | Список `["cmd args", ...]` MCP-серверов |
| `embeddings` | — | `{"provider":"hash"}` или `{"provider":"remote",...}` |
| `use_context` | `true` | Авто-извлечение контекста в промпт |
| `http.host` | `127.0.0.1` | Адрес HTTP-канала; внешний адрес требует `http.token` |
| `http.token` | — | Токен для HTTP-клиентов (`X-Ideal-Agent-Token`) |
| `http.github_webhook_secret` | — | Secret для проверки `X-Hub-Signature-256` GitHub webhook |
| `ide.host` | `127.0.0.1` | Адрес IDE TCP-канала; внешний адрес требует `ide.token` |
| `ide.token` | — | Токен IDE handshake в первом JSON-сообщении |
| `telegram.token` | — | Токен Telegram-бота (альтернатива env `TELEGRAM_BOT_TOKEN`) |
| `telegram.allowed` | `[]` | Список разрешённых chat_id |

Правила `allow`/`deny` — строки `tool` или `tool:regex`; `*` — любой тул/аргумент.

### Провайдеры LLM
- `openai-compatible` / `openai` — любой OpenAI-совместимый endpoint (`base_url`+`api_key`).
- `openrouter` — `https://openrouter.ai/api/v1`; для быстрого старта используй `openrouter/free`.
- `ollama` — локальный `http://localhost:11434/v1` (офлайн, без ключа).
- `anthropic` — Claude через Messages API (`api_key` обязателен).
- `gemini` — Google Gemini через generativeLanguage API (`api_key` обязателен).
- `groq`, `deepseek`, `moonshot`, `together` — их нативные OpenAI-совместимые API.

Для нативного провайдера `base_url` можно оставить пустым: агент выберет его
официальный endpoint. Это также защищает старый конфиг от URL TokenRouter.

Переопределить из командной строки: `main.py --provider ollama --model llama3.1 ...`.

## Каналы

- **CLI** — `python3 main.py "задача"` (одноразово) или `python3 main.py cli` (цикл).
- **TUI** — `python3 main.py tui`: история сверху, ввод снизу, кириллица и перенос
  текста. `F2` открывает настройки (провайдер, модель, workspace, sandbox и retry),
  `F3` — подключённые tools/skills/MCP, `PgUp/PgDn` прокручивает историю,
  `/about` показывает версию. Вложения: `/attach ПУТЬ`, `/files`, `/detach N` и
  `/screenshot`; текст и изображения передаются в LLM, прочие файлы доступны как
  путь для tools. Режим апрува берётся из конфига.
- **Telegram** — `python3 main.py telegram` (токен из env `TELEGRAM_BOT_TOKEN` или
  `telegram.token` в конфиге; белый список `ALLOWED_USER_IDS`/`telegram.allowed`).
  Поддерживаются слэш-команды (см. ниже).
- **IDE** — `python3 main.py ide` (TCP `127.0.0.1:8765`, JSON-строки `{"text":"..."}`).
- **HTTP** — `python3 main.py http --port 8080` (для Android-компаньона и вебхуков):
  `GET /` статус, `POST /message` `{"text":...}`→`{"reply":...}`,
  `POST /webhook/github` принимает события GitHub (push/issues/PR).

## Слэш-команды (Telegram / TUI / HTTP)
`/help`, `/mode [auto|suggest|full-auto]`, `/clear`, `/status`, `/provider`, `/skills`.

## Навыки (skills) и MCP
- Встроенные навыки: `git_commit`, `run_tests`, `tree`, `web_fetch`, `github`,
  `make_tests` (генератор pytest-заготовок), `lint` (py_compile).
  Каждый — папка `skills/<name>/` с `SKILL.md` и `run.sh`/`run.py`.
  Аргументы передаются через env `IDEAL_SKILL_INPUT` (JSON).
- MCP-серверы (stdio JSON-RPC): `fs_mcp.py` (чтение файлов), `fetch_mcp.py`
  (загрузка веба), `github_mcp.py` (issues/repos). Подключаются через `mcp_servers`.
- Внешние MCP-серверы подключаются так же (любой stdio-MCP совместимый процесс).

## Потоковые ответы (streaming)
- **TUI**: текст ответа выводится по мере генерации.
- **HTTP**: `POST /message/stream` отдаёт Server-Sent Events (`data: {"chunk": ...}`),
  завершается `data: [DONE]`. Используй `companion/http_client_example.py` или
  приложение из `android/idealagent`.
- Потоковая генерация работает для OpenAI-совместимых провайдеров; остальные
  отдают ответ целиком одним куском.

## Установка на другой девайс
```bash
bash install.sh                       # установка в ~/.local/share/ideal-agent
IDEAL_LLM_API_KEY=sk-... bash install.sh --service   # + автозапуск
bash ~/.local/share/ideal-agent/update.sh            # обновление, конфиг сохраняется
```
Поддерживаются Termux (Termux:Boot), Linux (systemd --user) и macOS (LaunchAgent).
Установщик не перезаписывает существующий конфиг, создаёт защищённый HTTP-токен
и выводит его один раз для Android-компаньона. Для чистого Termux:

```bash
pkg update -y
pkg install -y git
git clone https://github.com/Miolonixc/ideal-agent.git
cd ideal-agent
IDEAL_LLM_API_KEY=sk-... bash install.sh --service
```

После установки укажи в приложении `127.0.0.1:8080` и напечатанный токен.
Для автозапуска поставь приложение Termux:Boot и один раз открой его.
Для обновления из папки установки запусти `bash update.sh`; полезные опции:
`--check`, `--branch beta`, `--no-restart` и `--no-tests`.
Android-компаньон —
см. `docs/android-companion.md` и готовый проект `android/idealagent/`
(Jetpack Compose, собирается в Android Studio).


## Безопасность и sandbox

`shell`-тул изолируется по умолчанию (`sandbox_mode: required`): предпочтительно `bwrap` (root readonly,
workspace доступен на запись, сеть отключена), иначе `unshare`. Если sandbox
недоступен, shell отклоняется. `best-effort` и `disabled` допускают запуск без
изоляции и предназначены только для доверенной локальной среды.
HTTP по умолчанию слушает только `127.0.0.1`; для внешнего интерфейса задай
`http.token` или `IDEAL_HTTP_TOKEN`. LLM-провайдер и его ключ настраиваются на
сервере и не принимаются из HTTP-запросов. Всегда работают deny-правила
апрув-гейта (например `"shell:rm -rf"`).

## Эмбеддинги (опц.)

`RepoIndex` поддерживает гибридный поиск (BM25 + косинус). Бэкенд задаётся в
`embeddings`: `{"provider":"hash"}` (локально, без зависимостей) или
`{"provider":"remote","base_url":...,"model":...,"api_key":...}`
(OpenAI-совместимый `/embeddings`).

## Контекст (авто-извлечение)

Перед каждым шагом агент строит RepoIndex рабочей папки (один раз) и извлекает
топ-3 релевантных куска кода + факты из памяти, подставляя их в system-сообщение.
Отключается флагом `"use_context": false` в конфиге.

## Skills

Положи навыки в `skills/<name>/`: `SKILL.md` (frontmatter `name`/`description`) + `run.sh`/`run.py`.
Скрипт получает JSON аргументов на stdin и пишет результат в stdout.

```
SKILLS_DIR=skills python3 main.py "запусти тесты"
```

## MCP

Запусти stdio-MCP-сервер и укажи его в `mcp_servers` (или `MCP_SERVERS="cmd args|..."`):

```
python3 main.py "прочитай файл через mcp"
```

Пример сервера — `mcp_servers/fs_mcp.py` (читает файлы).

## Написание MCP-сервера

Сервер — отдельный процесс, общение по stdin/stdout в виде JSON-RPC 2.0
(по одному JSON на строку). Обязательные методы:

- `initialize` → вернуть `protocolVersion`, `capabilities`, `serverInfo`.
- `tools/list` → вернуть `tools: [{name, description, inputSchema}]`.
- `tools/call` → принять `{name, arguments}`, вернуть `{content:[{type:"text", text:"..."}]}`.

Минимальный каркас:

```python
import sys, json
def handle(method, params):
    if method == "initialize":
        return {"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"x"}}
    if method == "tools/list":
        return {"tools":[{"name":"ping","description":"","inputSchema":{"type":"object","properties":{}}}]}
    if method == "tools/call":
        return {"content":[{"type":"text","text":"pong"}]}
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    m=json.loads(line)
    if m.get("method") and "id" in m:
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":m["id"],"result":handle(m["method"],m.get("params",{}))})+"\n")
        sys.stdout.flush()
```

Подключение: `mcp_servers: ["python3 mcp_servers/my_server.py"]` или
`MCP_SERVERS="python3 mcp_servers/my_server.py"`.

## Subagents

Изолированные агенты с собственным контекстом для узких задач (исследование кода,
тесты, рефакторинг). Запускаются внутри `agent` через `run_subagent(task, cfg, provider,
tools=[...])`; при передаче списка `tools` регистрируется только их подмножество, а
апрув-гейт переводится в `full-auto`, чтобы subagent не блокировался на подтверждении.

## Тесты

```
python3 -m unittest discover -s tests
```

## Структура

```
agent/   — ядро (config, llm, core, memory, tools, builtin_tools, skills, mcp, subagents, safety, channels)
skills/  — встроенные навыки
mcp_servers/ — примеры MCP-серверов
tests/   — тесты (unittest)
benchmarks/ — смоук-бенчмарк
```

## Устранение неполадок

- **`401 Unauthorized`** — не задан ключ (`IDEAL_LLM_API_KEY`/`TOKENROUTER_API_KEY`) или
  неверен `llm.base_url`/`llm.model`.
- **Нет сети** — агент не сможет дойти до LLM/MCP-remote; локальные тулы, skills и
  BM25-индекс работают офлайн.
- **Тулы не выполняются в `auto`** — не-read-only тулы требуют подтверждения; в
  неинтерактивном канале (Telegram/IDE) они отклоняются. Переведи в `full-auto` или
  добавь правило в `allow`.
- **`bwrap`/`unshare` недоступны** — sandbox не применяется, shell запускается честно;
  поставь `bwrap` (bubblewrap) для изоляции.
- **Контекст не подтягивается** — проверь `use_context: true` и что `workspace`
  указывает на нужную папку; индекс строится лениво при первом `run`.
