# Claude Code stack installer

Воспроизводит конфигурацию из `~/.claude/skills-inventory.md` на новой
машине: 3 marketplaces + 4 плагина + перенос кастомных скиллов.

## Что ставится

**Marketplaces:**
- `superpowers-marketplace` → `obra/superpowers-marketplace`
- `thedotmack` → `thedotmack/claude-mem`
- `context-mode` → `mksglu/context-mode`
- `claude-plugins-official` уже встроен

**Плагины:**
- `superpowers@superpowers-marketplace`
- `code-review@claude-plugins-official`
- `claude-mem@thedotmack`
- `context-mode@context-mode`

**Кастомные скиллы** (переносятся как есть, если есть исходник):
`agent-browser`, `database-designer`, `fastapi-expert`, `frontend-design`,
`gstack`, `tooling-references`, `production-hardening`.

## Запуск

### Windows (PowerShell)

```powershell
cd <repo>\scripts\install-claude-stack
.\install.ps1
```

Если кастомные скиллы лежат в `~\.claude\skills\` — они остаются на месте,
скрипт их не трогает. Если переносите с другой машины — сначала
скопируйте папку, потом запустите.

### Linux / macOS / WSL

```bash
cd <repo>/scripts/install-claude-stack
bash install.sh
```

## Что делает скрипт

1. Мерджит `settings.snippet.json` в `~/.claude/settings.json` (бэкап
   старого в `settings.json.bak.<timestamp>`).
2. Печатает следующие шаги: `/plugin list` и `/skills` для проверки.

Скрипт **не вызывает** slash-команды Claude Code — это user-facing
команды, их надо ввести вручную в CLI. Скрипт готовит settings.json,
после чего Claude Code сам подхватит marketplaces при старте.

## Проверка после установки

В Claude Code:
```
/plugin list      # должны быть 4 плагина enabled
/skills           # кастомные + плагинные скиллы
```

Если `production-hardening` не появился — проверьте, что
`~/.claude/skills/production-hardening/SKILL.md` существует и его
frontmatter содержит `name` и `description`.

## Cloud Claude Code

В remote-сессиях (claude.ai/code) плагины и скиллы подтягиваются с
аккаунта автоматически после первой установки на любой машине под
этим аккаунтом. Кастомные скиллы из `~/.claude/skills/` в облако
**не уезжают** — их нужно либо упаковать в `.skill`-файлы и опубликовать,
либо положить их содержимое в репозиторий и подгружать оттуда.
