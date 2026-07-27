# Архитектура Lab_request: что уже есть (S1–S5)

Краткая карта для оператора и разработчика. Детали — в отдельных docs/ и Obsidian.

**Статус на 2026-07-27:** S1–S5 ✅ · S6 w1+w2 ✅ · **GUI extract Queue** ✅ · calc category filter ✅ · prod W:\request_processor

```
┌─────────────────────────────────────────────────────────────┐
│  Lab_request (request-processor)                            │
│                                                             │
│  1 Заявка → extract (worker+Queue) → human confirm + 💡     │
│  2 Расчёт ← прайс + picker (Checkbutton, категория)         │
│  3 КП ← lab_profile + logo + styles classic|modern|compact  │
│  4 Заказы → пакет / JSON protocol_meta                      │
│  S6 CLI: acceptance_items (каталог ТУ, без файлов ТУ в git) │
│  Логи: data/logs (app_*, gui_extract_trace.log)             │
│                                                             │
│  data/app.db  (сохраняется при update.ps1)                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ JSON без измерений
                            ▼
              protocol_generator (отдельный проект)
```

| Спринт | Содержание | Статус | Документ |
|--------|------------|--------|----------|
| S1 | UX, Lab_request, удаления, старт, логи-теги | ✅ | INSTALL, UPDATE, UI_ARCHITECTURE |
| S2 | КП лого/стили, просмотр логов, Урок ИИ 0–2 | 🟡 | Obsidian Уроки ИИ |
| S3 | JSON → protocol_generator | ✅ каркас | PROTOCOL_GENERATOR_BRIDGE |
| S4 | Программы DOCX + match rate | ✅ polish 22.07 | TEST_PROGRAMS |
| S5 | Нормы raw_text + aliases | ✅ batch + seed | REQUIREMENTS_BASE |
| **S6 w1** | `acceptance_items` + clauses + external refs + CLI | ✅ 2026-07-24 | REQUIREMENTS_BASE, Obsidian 63 |
| **S6 w2** | Импорт таблиц приёмки: 131/141 docx + 005 raw_text | ✅ 2026-07-24 | Obsidian 64 |
| **2026-07-27** | Extract Queue + DOCX perf + calc filter + prod-hot marks | ✅ | UI_ARCHITECTURE, Obsidian 66 |
| Ops | Обновление без сноса, seed прайса, ярлык | ✅ | UPDATE.md |

## UI-пакет

```
ui/gui.py → entry
ui/app.py → RequestProcessorApp
ui/shell/  menubar, app_shell
ui/tabs/   pdf, calc, kp, orders, …
ui/extract_job.py   # worker extract: Queue, no tkinter
ui/widgets/ clipboard, sidebar, splash
ui/state.py, theme.py
```

## Extract pipeline (2026-07-27)

1. Main thread: path/OCR options → progress dialog → `Thread(run_extract_job)`.  
2. Worker: `extract_from_document` (deterministic marks; **no** MarkCorrector/Ollama) → `prepare_extraction_draft` → Queue.  
3. Main: poll Queue → show draft → optional 💡 `suggest_many` in background.  
4. Marks: structural regex, not brand whitelist.  

## Принципы

1. **data/** — святое (БД, corrections, generated).  
2. **Код** обновляется zip/update.ps1.  
3. **protocol_generator** не правим — только JSON.  
4. **LLM** opt-in, human-in-the-loop.  
5. **rag_corpus** локально, не git.  
6. **Логи:** `app_*`, `scripts_*`, `tests_*`, `gui_extract_trace.log` в `data/logs/`.  
7. **Worker ≠ tkinter** (см. Obsidian «Урок ИИ 02»).
