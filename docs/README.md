# Документация request-processor

> GitHub: https://github.com/shocknik/request_processor  
> Obsidian: `Python/Проект request-processor/`

## Статус v0.6.1 (2026-07-02)

### Итерация 4 — фаза 1 ✅ (доверие к парсингу)

- **`extraction_validator.py`** — правила P0–P2, `ValidationReport`, без ИИ
- **GUI human-in-the-loop** — вкладка «1. Заявка»: черновик → проверка → «Подтвердить заявку»
- **Редактор марки** — все поля `cable_marks`, «Заполнить из обозначения»
- **Экспорт правок** → `data/training/corrections/*.jsonl`
- **CLI:** `--validate`, `--dry-run` для `extract-pdf`
- **pytest:** `tests/test_extraction_validator.py`, `tests/test_cli_extract_pdf.py`

### Базовый цикл (v0.5.x)

- **Заявка на испытания:** `application_generator.py`, шаблон `data/templates/zayavka_ispytaniy.docx`
- **Заказы:** `orders`, кнопки в GUI, `generate-application` в CLI
- **Цикл:** Заявка → Расчёт → КП → Заказ → Заявка на испытания

### Фаза 2 — в работе

- Table-first extractor для направлений в ИЛ
- `test_mappings` — требования → испытания
- `generated_documents` — история файлов по заказу

См. [[27 — Фаза 2: требования и таблицы (2026-07-02)]] в Obsidian.

## Ключевые заметки Obsidian

| Заметка | Тема |
|---------|------|
| [[00 — request-processor (главная)]] | Навигация, технологии |
| [[22 — Валидация парсинга (панель подтверждения)]] | Human-in-the-loop, правила P0–P2 |
| [[26 — Отчёт PR-4: CLI validate и dry-run (2026-07-02)]] | Флаги `--validate`, `--dry-run` |
| [[27 — Фаза 2: требования и таблицы (2026-07-02)]] | Roadmap фазы 2 |
| [[10 — GUI (tkinter)]] | Вкладки, кнопки |
| [[17 — Заказы (orders)]] | Бизнес-логика заказов |
| [[03 — Команды CLI]] | Все команды и флаги |
| [[19 — Запуск приложения]] | Установка и запуск GUI |