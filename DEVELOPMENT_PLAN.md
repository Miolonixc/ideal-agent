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

## Закрыто после первого плана

- Память и индекс изолированы namespace от канонического пути workspace.
- В GitHub Actions добавлен интеграционный sandbox-тест Bubblewrap.
- Ошибки провайдеров нормализованы, временные HTTP-ошибки повторяются.
- HTTP ограничивает размер сообщений и частоту запросов.
- Skills и MCP требуют явного доверия, получают namespace и не могут заменить
  встроенные инструменты.
- MCP ограничивает размер входящего JSON-RPC сообщения (256 KiB), отменяет
  запрос при таймауте и аварийно завершает сервер, нарушивший лимит.
- Skills поддерживают manifest capabilities `filesystem`, `network`, `shell`,
  `secrets`; TUI запрашивает и сохраняет подтверждение первого запуска.
- Android-компаньон показывает версию и состояние соединения, умеет проверить
  сервер и отменить streaming; CI публикует APK, SHA-256 и declared-dependencies SBOM.
- Диагностика `/health`, `/audit` и `--dry-run` доступна без LLM-запроса.

## P2 — следующий цикл

1. Распространить capabilities и first-run approval на MCP (сейчас MCP требует
   ручного доверия до старта процесса).
2. Android: Compose UI и реальные сетевые тесты, светлая тема и accessibility.
3. Локальные метрики без записи промптов, вложений и ключей (опционально).

## P3 — выпуск

1. `CHANGELOG.md`, versionCode/versionName от git-тега и release notes.
2. Подписанный release APK через GitHub Secrets, SHA-256 и SBOM.
3. Опциональные локальные метрики без промптов, вложений и ключей.

## Рекомендуемый порядок

1. `feat: MCP capability manifest and TUI approval`
2. `feat(android): accessibility, light theme and network tests`
3. `feat: privacy-preserving local metrics`
