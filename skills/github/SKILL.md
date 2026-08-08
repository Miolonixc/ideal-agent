---
name: github
description: Работа с GitHub через gh CLI или REST API. Аргумент input — команда, напр. "issue owner/repo Заголовок" или "list owner/repo".
---
Набор действий с GitHub:
- issue <owner/repo> <заголовок> — создать issue
- list <owner/repo> — список открытых issues
- repos — список репозиториев пользователя (по GITHUB_TOKEN)
- read <owner/repo> <issue_number> — прочитать issue
Требуется GITHUB_TOKEN в окружении (или авторизованный gh).
