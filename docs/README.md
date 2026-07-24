# Документация request-processor

**Версия:** 0.9.1  
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
| `ARCHITECTURE_ROADMAP.md` | Карта S1–S5 |
| `UI_ARCHITECTURE.md` | Sidebar, splash, tabs |
| `TEST_PROGRAMS.md` | Программы испытаний (S4) |
| `REQUIREMENTS_BASE.md` | Нормы / aliases (S5) |
| `PROTOCOL_GENERATOR_BRIDGE.md` | JSON → protocol_generator |
| `UPDATE.md` | Обновление in-place |
| `client_profiles.example.yaml` | Пример локальных профилей клиентов |
| `lab_profile.example.yaml` | Реквизиты лаборатории |
| `План_Итерации_2.md` | Исторический план (если есть в полной копии) |

В корне репо: **[AGENTS.md](../AGENTS.md)** — правила для AI-агента (Grok).

## Obsidian (только на машине разработчика)

Полный журнал: `Python/Проект request-processor/`  
Ключевые заметки: 40 (LLM), 41 (данные prod), 43 (развёртывание на рабочий ПК), 44 (паспорт).

---

## Краткая история версий

### v0.9.1 (2026-07)

- Развёртывание на рабочий ПК: `install.ps1`, `prepare-prod-db`, zip + `app.db`
- LLM Ollama opt-in (`llama3.2`), GUI settings scroll
- Пакет данных prod export/import
- GUI под 1920×1080
- Паспорт экспериментальной эксплуатации

### v0.8.x

- OCR Phase 2, training/eval, test_mappings, пакеты документов, human-in-the-loop
