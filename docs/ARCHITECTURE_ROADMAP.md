# Архитектура Lab_request: что уже есть (S1–S5)

Краткая карта для оператора и разработчика. Детали — в отдельных docs/ и Obsidian.

**Статус на 2026-07-22:** S1–S3 ✅ · S2.5 ✅ · **S4 polish** (match ≥9/14 Вулкан) · **S5** batch raw_text + pipe-table · prod W:\request_processor

```
┌─────────────────────────────────────────────────────────────┐
│  Lab_request (request-processor)                            │
│                                                             │
│  1 Заявка → extract (docx/pdf) → human confirm              │
│  2 Расчёт ← прайс test_items + test_mappings + aliases      │
│  3 КП ← lab_profile + logo + styles classic|modern|compact  │
│  4 Заказы → пакет / JSON protocol_meta                      │
│  Марки | Орг | Справочник | Программы | История | …         │
│  Логи: Сервис → Просмотр логов / папка data/logs            │
│                                                             │
│  data/app.db  (сохраняется при update.ps1)                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ JSON без измерений
                            ▼
              protocol_generator (отдельный проект)
                            │
                            ▼
                      DOCX протокол
```

| Спринт | Содержание | Статус | Документ |
|--------|------------|--------|----------|
| S1 | UX, Lab_request, удаления, старт, логи-теги | ✅ | INSTALL, UPDATE, UI_ARCHITECTURE |
| S2 | КП лого/стили, просмотр логов, Урок ИИ 0 | 🟡 | lab_profile.example, Obsidian |
| S3 | JSON → protocol_generator | ✅ каркас | PROTOCOL_GENERATOR_BRIDGE |
| S4 | Программы DOCX + match rate | ✅ polish 22.07 | TEST_PROGRAMS |
| S5 | Нормы raw_text + aliases | ✅ batch + seed | REQUIREMENTS_BASE |
| Ops | Обновление без сноса, seed прайса, ярлык | ✅ | UPDATE.md |

## UI-пакет (после декомпозиции)

```
ui/gui.py → entry
ui/app.py → RequestProcessorApp
ui/shell/  menubar, app_shell
ui/tabs/   pdf, calc, kp, orders, …
ui/widgets/ clipboard
ui/state.py, theme.py
```

## Принципы

1. **data/** — святое (БД, corrections, generated).  
2. **Код** обновляется zip/update.ps1.  
3. **protocol_generator** не правим — только JSON.  
4. **LLM** opt-in, human-in-the-loop.  
5. **rag_corpus** локально, не git.  
6. **Логи:** `app_*`, `scripts_*`, `tests_*` в `data/logs/`.
