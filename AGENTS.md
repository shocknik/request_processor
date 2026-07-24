# Lab_request / request-processor — правила для агента

Краткие **действенные** правила. Полная картина: `README.md`, `docs/ARCHITECTURE_ROADMAP.md`, `docs/DEV_AGENT_SETUP.md`.

## Продукт

- **Имя продукта:** Lab_request  
- **Пакет / CLI:** `request-processor`  
- **Версия:** см. `pyproject.toml` (`0.9.1`)  
- **Стек:** Python ≥ 3.10, tkinter GUI, SQLite (`data/app.db`), Click CLI, pytest  
- **Код:** `src/request_processor/`  
- **Не коммитить:** `data/` (кроме `templates/`, `families/`), `.venv/`, `dist/`, `*.db`, локальные yaml/knowledge

## Святое

1. **`data/app.db` и рабочий контур** — не затирать без явной просьбы; на боевом ПК обновление через `scripts/update.ps1`.  
2. **Прайс `test_items`** — не сносить `prepare-prod-db` / `load-data` без запроса.  
3. **protocol_generator** — отдельный проект; сюда только JSON (`export-protocol-meta`).  
4. **LLM** — opt-in (Ollama); не делать обязательной зависимостью.  
5. **Секреты / prod-пути** — не хардкодить `W:\`, логины, ключи в коде.

## Архитектура (куда класть код)

| Область | Путь |
|---------|------|
| GUI entry / shell / tabs | `ui/gui.py`, `ui/bootstrap.py`, `ui/shell/`, `ui/tabs/`, `ui/widgets/` |
| Извлечение / OCR | `extraction/`, `extraction/ocr/` |
| Генерация Word/JSON | `generation/` |
| БД | `persistence/sqlite_repo.py`, `persistence/training_repo.py` |
| CLI | `cli.py` |
| Тесты | `tests/` зеркально фиче |

UI: **sidebar**, не «9 вкладок в ряд». Справочник испытаний — меню «Данные», не sidebar.

## Команды (dev)

Интерпретатор: `.venv\Scripts\python.exe` (Windows).

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,cv]"
request-processor migrate-db
pytest tests/ -q
ruff check src tests
# mypy: mypy src/request_processor  (strict в pyproject)
request-processor gui
```

После схемы БД — всегда `migrate-db`, не ручной DROP.

## Стиль кода

- Python 3.10+: type hints, `from __future__ import annotations` где уже принято.  
- Line length **100** (ruff).  
- Новые фичи — с **тестами** (минимум happy-path + регрессия на краю).  
- GUI: логика в tab/shell-модулях; не раздувать монолит без нужды.  
- Сообщения UI/CLI — **русский** (как в существующем коде).  
- Коммиты: conventional / короткий why (`feat:`, `fix:`, `docs:`).

## Документация

| Тема | Файл |
|------|------|
| README пользователя | `README.md` |
| Установка / update | `INSTALL.md`, `docs/UPDATE.md` |
| UI | `docs/UI_ARCHITECTURE.md` |
| S4 программы | `docs/TEST_PROGRAMS.md` |
| S5 нормы | `docs/REQUIREMENTS_BASE.md` |
| Протокол JSON | `docs/PROTOCOL_GENERATOR_BRIDGE.md` |
| S1–S5 карта | `docs/ARCHITECTURE_ROADMAP.md` |
| Как помочь агенту | `docs/DEV_AGENT_SETUP.md` |

При смене публичного API/CLI/GUI — обновить README или профильный doc в том же PR.

## Чего не делать

- Не коммитить `data/app.db`, OCR-кэш, generated docs, training PDF (кроме явного seed).  
- Не добавлять torch/EasyOCR в default deps.  
- Не ломать entry points: `request-processor`, `request-processor-gui`.  
- Не рефакторить «заодно» несвязанные модули в задаче на багфикс.

## Как давать задачу агенту (шаблон)

```
Цель: …
Контекст: (вкладка / CLI / файл) …
Ограничения: не трогать БД / только tests / …
Проверка: pytest tests/test_….py -q
```

Локальные предпочтения (не в git): `CLAUDE.local.md` или `~/.grok/rules/`.
