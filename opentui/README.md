# Experimental OpenTUI frontend

This is an optional Bun/OpenTUI client. It talks only to the local Python HTTP
API and never reads LLM keys. The regular curses frontend remains the default
and reliable fallback, especially on Termux.

```bash
# terminal 1
python3 main.py http --port 8080

# terminal 2
cd opentui
bun install
bun run start -- --url http://127.0.0.1:8080 --token "$IDEAL_HTTP_TOKEN"
```

Or from a repository with Bun installed:

```bash
IDEAL_HTTP_TOKEN=... python3 main.py opentui
```

OpenTUI needs Bun because it loads a native Zig renderer. If the runtime or
native binary is unavailable on a device, use `python3 main.py tui` instead.

## Управление

`Enter` отправляет сообщение, `F2` повторно проверяет сервер и показывает
сводку, `F3` выводит skills/tools, `F4` запрашивает отмену активного streaming
на сервере, `Ctrl+L` очищает локальное окно истории.
История прокручивается и удерживается внизу во время streaming-ответа.

## Вложения

`/attach ПУТЬ` прикрепляет текстовый файл или изображение к следующему
сообщению. `/files` показывает очередь, `/detach НОМЕР` удаляет элемент из неё.
Клиент читает файл локально, передаёт его только в текущий запрос и очищает
очередь после успешной отправки. Лимит: до 5 файлов, каждый до 6 MiB.
