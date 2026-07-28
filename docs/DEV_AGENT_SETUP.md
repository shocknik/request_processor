# Как настроить окружение, чтобы агент (Grok) работал продуктивнее

Инструкция для **разработчика Lab_request** на Windows.  
Цель: меньше «объясняй проект с нуля», быстрее правки, тесты и ревью.

---

## 0. Карта: кто чем пользуется

| Слой | Что это | Зачем |
|------|---------|--------|
| **Grok Build TUI / CLI** | `grok` в терминале | Агент с tools (файлы, shell, git, MCP) |
| **Grok в VS Code** | Community-расширение → `grok agent stdio` (ACP) | Тот же агент, но sidebar, diff, `@file` |
| **VS Code + Pylance/Ruff** | IDE для **вас** | Подсветка, go-to-def, Problems — вы видите качество |
| **LSP tools у Grok** | `lsp_tools` + `.grok/lsp.json` | Агент сам спрашивает diagnostics/типы |
| **AGENTS.md** | Правила репо | Контекст **каждой** сессии без повторов |
| **Memory (opt-in)** | `~/.grok` memory | Факты между сессиями |
| **MCP** | Внешние tools | GitHub, tasks, browser, … |

**Важно:** Grok **не** «подключается к Pylance внутри VS Code» сам по себе.  
Либо вы/он гоняете **те же** CLI (`ruff`, `pytest`, `mypy`), либо включаете **LSP-сервер** для Grok, либо работаете через **ACP-расширение**, где контекст — открытые файлы и diff.

---

## 1. Обязательный минимум (30–40 минут) — максимальный эффект

### 1.1. Dev-окружение проекта

```powershell
cd D:\My_projects\request_processor
py -3.11 -m venv .venv   # или 3.12; 3.10+
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,cv]"
request-processor migrate-db
pytest tests/ -q
```

Дальше всегда работайте **из активированного venv** или с полным путём:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
.\.venv\Scripts\ruff.exe check src tests
```

### 1.2. `AGENTS.md` в корне репо

Файл уже есть: [`AGENTS.md`](../AGENTS.md).  
Grok **автоматически** подхватывает его в каждой сессии в этом репозитории.

Проверка:

```powershell
grok inspect
```

Должен показать `AGENTS.md` и оценку токенов.

**Что писать в AGENTS.md (и чего не писать):**

- ✅ команды тестов, запреты, куда класть код, стиль  
- ❌ копипаст всего README  
- Лочные привычки → `CLAUDE.local.md` (в gitignore) или `~/.grok/rules/*.md`

### 1.3. Trust папки проекта

Первый раз в каталоге:

```text
/hooks-trust
```

или запуск с `--trust`.  
Иначе project MCP / LSP / hooks из `.grok/` могут не включиться.

### 1.4. Как формулировать задачи (это ускоряет сильнее расширений)

**Плохо:** «почини GUI»  
**Хорошо:**

```text
Цель: на вкладке Расчёты кнопка X не обновляет итог после смены часов.
Файлы: ui/tabs/calc_tab.py, calculation/cost_calculator.py
Не трогать: data/app.db, generation/
Проверка: pytest tests/test_cost_calculator.py -q
После — кратко что изменилось.
```

Приложите: traceback, скрин, путь к sample PDF, id заказа — если есть.

---

## 2. VS Code: IDE для вас + мост к Grok

### 2.1. Рекомендуемые расширения

Установите из Marketplace (или примите recommendation workspace — см. `.vscode/extensions.json`):

| Расширение | ID | Зачем |
|------------|-----|--------|
| **Python** | `ms-python.python` | интерпретатор, run/debug |
| **Pylance** | `ms-python.vscode-pylance` | типы, go-to-def, Problems |
| **Ruff** | `charliermarsh.ruff` | линт/format = как в CI |
| **Even Better TOML** | `tamasfe.even-better-toml` | `pyproject.toml` |
| **GitLens** (опц.) | `eamodio.gitlens` | blame/history |
| **Grok Build for VS Code (Community)** | `PawelHuryn.grok-vscode-phuryn` | Grok в sidebar через ACP |

Опционально (альтернативные агенты, не обязательны):

| | |
|--|--|
| Continue | свой open-source чат с моделями |
| Cline / Roo | agent mode с tools |
| GitHub Copilot | autocomplete + chat |

Для **этого** проекта главный выигрыш — **Python + Pylance + Ruff + Grok Community**.

### 2.2. Workspace settings

В репозитории лежат:

- `.vscode/extensions.json` — recommendations  
- `.vscode/settings.json` — интерпретатор `.venv`, ruff, excludes  

После открытия папки: **Ctrl+Shift+P** → `Python: Select Interpreter` →  
`.\.venv\Scripts\python.exe`.

### 2.3. Grok **внутри** VS Code (ACP)

Официального first-party расширения xAI нет; community-обёртка:

1. Установить **Grok Build for VS Code (Community)**  
   Marketplace: `PawelHuryn.grok-vscode-phuryn`  
2. Нужен CLI `grok` (у вас уже есть) и login (SuperGrok / Premium+ / API key).  
3. Открыть проект `D:\My_projects\request_processor`.  
4. **Ctrl+;** — sidebar Grok.  
5. Расширение поднимает `grok agent stdio` (Agent Client Protocol).

Что даёт по сравнению с чистым TUI:

- открытый файл / selection как `@` context  
- diff правок в нативном diff editor  
- sessions history, plan / auto-accept modes  
- тот же агент, MCP, skills, AGENTS.md  

Альтернатива (мульти-агент ACP): [vscode-acp](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) — подключает любой ACP-агент, в т.ч. `grok agent stdio`.

### 2.4. Launch / Debug GUI (для вас)

Пример (можно добавить в `.vscode/launch.json`):

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Lab_request GUI",
      "type": "debugpy",
      "request": "launch",
      "module": "request_processor.ui.gui",
      "cwd": "${workspaceFolder}",
      "justMyCode": true
    },
    {
      "name": "pytest current",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v"],
      "cwd": "${workspaceFolder}"
    }
  ]
}
```

Агенту дебаггер VS Code недоступен; ему достаточно `pytest` + логов `data/logs/`.

---

## 3. «Мозг IDE» для самого Grok (LSP + indexing)

### 3.1. Codebase indexing

По умолчанию в Grok часто уже:

```toml
# ~/.grok/config.toml
[features]
codebase_indexing = true
```

Индекс помогает искать по графу кода. Держите включённым.

### 3.2. LSP tools (diagnostics / hover / definition)

По умолчанию **выключено**:

```toml
[features]
lsp_tools = false
```

Включите:

```toml
# ~/.grok/config.toml
[features]
lsp_tools = true
codebase_indexing = true
```

И опишите language server. **Глобально** (`~/.grok/lsp.json`) или **в проекте** (`.grok/lsp.json` — каталог `.grok/` у вас в `.gitignore`, это нормально для локали).

Пример с **Ruff** (lint; нужен `ruff` в PATH или из venv):

```json
{
  "ruff": {
    "command": "D:\\My_projects\\request_processor\\.venv\\Scripts\\ruff.exe",
    "args": ["server"]
  }
}
```

Пример с **BasedPyright** (типы; после `pip install basedpyright`):

```json
{
  "basedpyright": {
    "command": "D:\\My_projects\\request_processor\\.venv\\Scripts\\basedpyright-langserver.exe",
    "args": ["--stdio"]
  }
}
```

Перезапустите сессию Grok. Trust папки, если project-scoped.  
Проверка: попросите агента «покажи diagnostics для `src/request_processor/cli.py` через LSP».

**Pylance** — это расширение VS Code, **не** отдельный stdio-server для Grok.  
Для агента используйте **basedpyright** / **pyright** / **ruff server**, не «подключение к Pylance».

### 3.3. Эквивалент без LSP (уже работает)

```powershell
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\python.exe -m mypy src/request_processor
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=short
```

Просите агента гонять это **после правок** — это и есть «Problems panel» в CLI-виде.

---

## 4. Memory, rules, skills

### 4.1. Cross-session memory (экспериментально)

```toml
# ~/.grok/config.toml
[memory]
enabled = true
```

или в сессии: `/memory on`.

Имеет смысл сохранять:

- «prod на W:\request_processor, update только update.ps1»  
- «не трогать torch в default deps»  
- удачные приёмы отладки OCR  

Не складывать секреты и персональные данные заказчиков.

### 4.2. Глобальные правила (все проекты)

`%USERPROFILE%\.grok\rules\*.md` — например «всегда отвечать по-русски», «PowerShell, не bash-only».

### 4.3. Project skills

`.grok/skills/<name>/SKILL.md` — сценарии «как собрать release zip», «как прогнать S4 match».  
Пока можно обойтись docs + AGENTS.md.

---

## 5. MCP — внешние руки

Сейчас в среде может быть сервер **tasks**. Полезные добавления (по желанию):

| MCP | Зачем |
|-----|--------|
| **filesystem** (осторожно) | узкий root, если нужно вне cwd |
| **github** | issues/PR без ручного gh (или используйте `gh` в shell) |
| **sqlite** / custom | read-only запросы к копии app.db для аналитики |
| **browser** | проверка web docs |

```powershell
grok mcp list
grok mcp doctor
# пример:
# grok mcp add --scope project github -- npx -y @modelcontextprotocol/server-github
```

Секреты — через env `${GITHUB_TOKEN}`, не в git.

Project MCP: `.grok/config.toml` (у вас `.grok/` в gitignore → только локально, или вынесите whitelist в git осознанно).

---

## 6. Рекомендуемый ежедневный workflow

### Вариант A — Grok TUI (как сейчас)

```powershell
cd D:\My_projects\request_processor
grok
```

1. Задача по шаблону из §1.4  
2. Агент правит код  
3. Просите: `pytest` + `ruff`  
4. `git commit` / push — **только по явной просьбе** (политика агента)

### Вариант B — VS Code + Grok sidebar

1. Открыть папку в VS Code  
2. Ctrl+; → Grok  
3. `@` на нужные файлы / selection  
4. Mode: Plan для крупных фич → Agent / Auto accept для мелких  
5. Diff approve в IDE  

### Вариант C — гибрид (часто лучший)

| Кто | Что |
|-----|-----|
| **Вы + VS Code** | чтение кода, debug GUI, ручной UX, OCR глазами |
| **Grok** | bulk-правки, тесты, docs, CLI, рефакторинг по AGENTS.md |
| **Git** | один репозиторий, короткие PR |

---

## 7. Чеклист «готово к продуктивной работе»

- [ ] `.venv` + `pip install -e ".[dev,cv]"`  
- [ ] `pytest tests/ -q` зелёный  
- [ ] `AGENTS.md` в корне; `grok inspect` видит его  
- [ ] VS Code: Python + Pylance + Ruff; interpreter = `.venv`  
- [ ] (реком.) Community Grok extension или работа из TUI  
- [ ] `[features] lsp_tools = true` + `lsp.json` (ruff и/или basedpyright)  
- [ ] (опц.) `[memory] enabled = true`  
- [ ] Trust папки `/hooks-trust`  
- [ ] Знаете `docs/UPDATE.md` — не сносить `app.db`  
- [ ] Понимаете роли БД: `db-info` / `db-role` (`dev` ≠ источник истины; `work_copy` = копия с работы)  

---

## 8. Что **не** даст магии

| Ожидание | Реальность |
|----------|------------|
| «Поставь расширение — агент станет умнее» | Умнее делают **AGENTS.md + тесты + LSP/CLI + чёткие задачи** |
| «Агент видит мой Problems panel» | Нет, пока не LSP tools / CLI ruff/mypy |
| «Cursor/Copilot заменят Grok Build» | Другие клиенты; данные проекта (AGENTS.md) всё равно нужны |
| «Открыл Obsidian — агент читает vault» | Только если файлы в workspace или вы приложили путь |

Obsidian-заметки: копируйте ключевое в `docs/` или давайте путь  
`@D:\...\Python\Проект request-processor\...md` в промпте.

---

## 9. Быстрые команды «после правок агента»

```powershell
cd D:\My_projects\request_processor
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\ruff.exe check src tests
git status
git diff --stat
```

Точечно:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_program_importer.py tests/test_norm_text_import.py -q
```

---

## 10. Связанные документы

| Документ | Содержание |
|----------|------------|
| [`AGENTS.md`](../AGENTS.md) | Правила для агента |
| [`README.md`](../README.md) | Продукт, CLI, архитектура |
| [`UI_ARCHITECTURE.md`](./UI_ARCHITECTURE.md) | GUI shell |
| [`ARCHITECTURE_ROADMAP.md`](./ARCHITECTURE_ROADMAP.md) | S1–S5 |
| Grok user guide | `~/.grok/docs/user-guide/` — MCP, ACP, rules, memory |

---

*Обновлено: 2026-07-24 — под Grok Build + VS Code Community ACP + Lab_request 0.9.1.*
