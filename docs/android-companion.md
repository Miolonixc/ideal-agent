# Android-компаньон для ideal-agent

## Концепция

`ideal-agent` уже работает на Android внутри Termux и предоставляет несколько
интерфейсов. Чтобы превратить телефон в полноценного «компаньона», не нужно
собирать тяжёлый нативный сервер — достаточно поднять **HTTP-канал** агента и
написать лёгкое Android-приложение (WebView/Kotlin), которое стучится в него
по `localhost`. Весь «мозг» остаётся в Python, приложение — только клиент.

```
┌──────────────┐     HTTP localhost      ┌────────────────────┐
│ Android App  │ ──── POST /message ───▶ │ ideal-agent (Termux)│
│ (Kotlin/WebView)│◀─── {reply} ────────│  HTTPChannel :8080  │
└──────────────┘                        └────────────────────┘
        │                                        │
        │  push-уведомления                      │ Telegram / GitHub
        ▼                                        ▼
   System notification (FCM/локально)      long-poll, webhooks
```

## Вариант A. Быстрый (Termux:Widget + уведомления)
1. Установи Termux:Boot и Termux:Widget.
2. Скрипт автозапуска бота уже создаёт `install.sh --service` (Termux-boot).
3. Для пуш-уведомлений агент шлёт ответы в Telegram (где бы пользователь ни был).
   Это работает без отдельного приложения.

## Вариант B. Нативное приложение (Kotlin + Compose)
Минимальный клиент к HTTP-каналу (без сторонних библиотек, `HttpURLConnection`):

```kotlin
data class Req(val text: String)
data class Resp(val ok: Boolean, val reply: String, val chat_id: String)

fun askAgent(prompt: String): String {
    val url = URL("http://127.0.0.1:8080/message")
    val conn = url.openConnection() as HttpURLConnection
    conn.requestMethod = "POST"
    conn.doOutput = true
    conn.setRequestProperty("Content-Type", "application/json")
    conn.setRequestProperty("X-Ideal-Agent-Token", token)
    conn.outputStream.write("""{"text":${ JSONObject.quote(prompt) }}""".toByteArray())
    val reply = conn.inputStream.bufferedReader().readText()
    val json = JSONObject(reply)
    return json.optString("reply", json.optString("error", "no response"))
}
```

Запуск агента на телефоне:
```bash
pkg install python
IDEAL_HTTP_HOST=127.0.0.1 IDEAL_HTTP_PORT=8080 python3 main.py http
```
Или с установкой и автозапуском через Termux:Boot:

```bash
IDEAL_LLM_API_KEY=sk-... bash install.sh --service
```

Установщик выводит токен HTTP — сохрани его и укажи в настройках приложения.
Чтобы приложение видело `127.0.0.1:8080`, агент должен быть запущен в том же
Termux-окружении (Termux предоставляет общий localhost).

## Вариант C. Вебхуки внешних сервисов
HTTP-канал принимает `POST /webhook/github` — подключи его в настройках
репозитория GitHub → Webhooks → `http://<твой-хост>:8080/webhook/github`.
Агент получит события push/issues/PR и сможет реагировать (напр. создать
issue-комментарий через навык `github`).

## Безопасность
- HTTP-канал слушает `127.0.0.1` по умолчанию. Для внешнего доступа задай
  `http.token` (или `IDEAL_HTTP_TOKEN`) и передавай его в заголовке
  `X-Ideal-Agent-Token`.
- LLM API-ключ остаётся в конфигурации сервера и не должен передаваться из
  мобильного клиента.
- Для доступа снаружи используй Telegram-канал (уже с `allowed`-белым списком)
  или положи HTTP за nginx + basic-auth / mTLS.
- Ключи (LLM, GitHub, Telegram) хранятся в `config.json`/`~/.config/ideal-agent`.

## Что можно добавить
- История диалогов в приложении (агент уже хранит `history`).
- Стриминг ответов (HTTP-канал можно расширить SSE).
- Локальные push через `termux-notification` из навыка/скрипта.
- Офлайн-режим: провайдер `ollama` (модель локально, без сети).
