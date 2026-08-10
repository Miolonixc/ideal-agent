# План развития ideal-agent

Актуально для `main` после усиления установщика и провайдеров.

## Что уже закрыто

- HTTP по умолчанию доступен только на localhost, поддерживает токен и проверку
  GitHub webhook; LLM-конфиг нельзя подменить HTTP-запросом.
- IDE использует токен handshake; Telegram без allow-list требует явного opt-in.
- У `Agent`, памяти, audit-лога и MCP есть управляемое завершение; MCP-соединение
  устойчивее к ошибкам жизненного цикла.
- Shell tools валидируются, ограничены workspace и имеют настраиваемый sandbox.
- Установщик корректно работает с checkout/Termux, не перезаписывает конфиг и
  создаёт токен для Android-компаньона.
- Провайдеры используют корректные endpoint по умолчанию, ключи из обычных env
  переменных и нормализованные ошибки; 408/429/5xx повторяются с backoff.
- Android-компаньон не принимает и не пересылает ключ LLM; APK собирается в CI.

## P1 — следующий цикл

1. Изоляция проектной памяти.
   - Добавить namespace от канонического пути workspace для MemoryStore и RepoIndex.
   - Критерий: факты/индекс проекта A никогда не появляются в проекте B.

2. Интеграционные sandbox-тесты в Ubuntu CI.
   - Проверить bwrap/unshare: нет сети, запись только в workspace, чтение вне него
     заблокировано.
   - Критерий: отдельная обязательная GitHub Actions job.

3. Полнота ошибок провайдеров.
   - Покрыть реальными mock-сценариями Anthropic/Gemini, пустой ответ и обрыв SSE.
   - Показать пользователю тип ошибки (auth/rate-limit/timeout) без секретов.

4. HTTP для долгоживущей эксплуатации.
   - Ограничить длину `text`, добавить rate limit по токену/IP и негативные тесты
     конкурентных сессий.

## P2 — расширяемость и Android

1. Skills/MCP manifest разрешений: filesystem, network, shell, secrets; отдельное
   подтверждение для первого запуска непроверенного расширения.
2. MCP cancellation, лимиты stdout/stderr и тест аварийного процесса.
3. Android: состояния offline/connecting/connected/error, отмена streaming,
   Compose UI и сетевые тесты, светлая тема и accessibility.
4. Команды `/audit`, `/health` и `--dry-run` для диагностики и безопасного preview.

## P3 — выпуск

1. `CHANGELOG.md`, versionCode/versionName от git-тега и release notes.
2. Подписанный release APK через GitHub Secrets, SHA-256 и SBOM.
3. Опциональные локальные метрики без промптов, вложений и ключей.

## Рекомендуемый порядок

1. `feat: namespace memory by workspace`
2. `test: add Ubuntu sandbox integration job`
3. `fix: rate-limit HTTP channel and classify provider errors`
4. `feat: add MCP permissions manifest`
5. `feat(android): connection state, cancellation and UI tests`
