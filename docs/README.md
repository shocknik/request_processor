# Документация request-processor

**Версия приложения:** см. корневой `pyproject.toml` · [VERSIONING.md](./VERSIONING.md)  

**GitHub:** https://github.com/shocknik/request_processor  

## Для установки на рабочий ПК (начните здесь)

| Документ | Формат | Содержание |
|----------|--------|------------|
| **[44 - Паспорт приложения…](./44%20-%20Паспорт%20приложения%20и%20экспериментальная%20эксплуатация%20(v0.9.1).pdf)** | PDF | Паспорт, эксплуатация, данные prod, требования |
| **[44 - Паспорт… (markdown)](./44%20-%20Паспорт%20приложения%20и%20экспериментальная%20эксплуатация%20(v0.9.1).md)** | MD | То же текстом |
| **[INSTALL.md](../INSTALL.md)** (корень релиза) | MD | Пошаговая установка на Windows |

## Прочее в docs/

| Файл | Назначение |
|------|------------|
| **[DEV_AGENT_SETUP.md](./DEV_AGENT_SETUP.md)** | VS Code + Grok: как настроить IDE/агента |
| **[VERSIONING.md](./VERSIONING.md)** | Версии по осям: package / схема БД / protocol_meta / роль данных |
| **[db_profile.example.yaml](./db_profile.example.yaml)** | Метка роли БД (dev / work_copy / work) |
| `ARCHITECTURE_ROADMAP.md` | Карта S1–S5 |
| `UI_ARCHITECTURE.md` | Sidebar, splash, bg_job, modal, tabs |
| `TEST_PROGRAMS.md` | Программы испытаний (S4) |
| `REQUIREMENTS_BASE.md` | Нормы / aliases (S5) |
| `PROTOCOL_GENERATOR_BRIDGE.md` | JSON → protocol_generator |
| `UPDATE.md` | Обновление in-place · zip `0.9.1_20260806` |
| `CHECKLIST_TZ70_OPERATOR.md` | Чеклист после ТЗ 70 + feedback work 06.08 |
| `client_profiles.example.yaml` | Пример локальных профилей клиентов |
| `lab_profile.example.yaml` | Реквизиты лаборатории |
| `План_Итерации_2.md` | Исторический план (если есть в полной копии) |

В корне репо: **[AGENTS.md](../AGENTS.md)** — правила для AI-агента (Grok).

## Obsidian (только на машине разработчика)

Полный журнал: `Python/Проект request-processor/`  
Ключевые: **72** (feedback work 06.08), **70–71** (HITL + lexicon 300), **69** (версии), 41/43/44, 65–68 (июль).

---

## Краткая история версий

### v0.9.1 (2026-07…08)

- Развёртывание на рабочий ПК: `install.ps1`, `prepare-prod-db`, zip + `app.db`
- LLM Ollama opt-in (`llama3.2`), GUI settings scroll
- Пакет данных prod export/import
- GUI под 1920×1080
- Паспорт экспериментальной эксплуатации
- **2026-07-27 (вечер, cycle polish):** DOCX full text + org name clean; HITL confirm/selection/dialogs; calc mark field + picker→left; KP thread-safe style; document pack sync + diagnostics logs; e2e workflow tests
- **2026-07-28 (debt + org + ops):** `ui/bg_job`, `ui/modal`; org-адреса без подмены чужим заводом; `db-info`/`db-role`; `VERSIONING.md`; zip `request_processor_0.9.1_20260728`; ~283 tests
- **2026-07-31 (ТЗ 70):** free-text через bg_job; org HITL на Заявке; редактор марок; mark lexicon; dual logs; feedback journal; zip `0.9.1_20260731`
- **2026-08-06 (work feedback):** org search casefold; clipboard Ctrl+C; document≠«стоимостью»; OCR lookalike/FRHF/LAN Cat 6 + КСВПП/КССПП; table+text marks; early splash metrics; zip `0.9.1_20260806`; **~322 tests**

### v0.8.x

- OCR Phase 2, training/eval, test_mappings, пакеты документов, human-in-the-loop
