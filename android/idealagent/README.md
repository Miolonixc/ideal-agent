# ideal-agent — Android-компаньон

Минимальное нативное Android-приложение (Jetpack Compose) для общения с
`ideal-agent` через HTTP-канал (`python3 main.py http --port 8080`).

Агент и приложение работают на одном устройстве (Termux + Android): приложение
стреляет запросы на `http://127.0.0.1:8080/message`.

## Сборка
1. Открой папку `android/idealagent` в Android Studio (или `gradle build`).
2. Gradle wrapper сгенерируется при первом открытии; либо `gradle wrapper`.
3. Запусти на устройстве/эмуляторе (minSdk 24).

## Запуск агента на телефоне
```bash
pkg install python
cd ~/dev/ideal-agent
IDEAL_HTTP_HOST=127.0.0.1 IDEAL_HTTP_PORT=8080 python3 main.py http
```
Затем в приложении укажи хост `127.0.0.1:8080` и пиши сообщения.

> Безопасность: HTTP-канал слушает `127.0.0.1` — не выставляй на `0.0.0.0`
> без обратного прокси/авторизации.

## Структура
- `app/src/main/java/com/idealagent/MainActivity.kt` — UI + HTTP-клиент (HttpURLConnection, без зависимостей).
- `app/build.gradle` — Compose BOM, coroutines, INTERNET-пермишен.
