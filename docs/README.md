# Документация request-processor

> GitHub: https://github.com/shocknik/request_processor  
> Obsidian: `Python/Проект request-processor/`

## Статус v0.8.2 (2026-07-03)

### Итерация 5.4.1 — OCR-марки, вид испытаний, структура пакетов ✅

- **`ocr_mark_normalizer.py`** — латиница → кириллица в бренде (`KCBur(A)` → `КСБнг(А)`), LAN-марки без поломки
- **Подсказка по БД** — `load_known_brands_from_db()` + snap префикса из `cable_marks`
- **`test_type_extractor.py`** — виды: Приемосдаточные, Периодические, Контрольные, Исследовательские, Сертификационные, МСИ
- **GUI вкладка «КП»** — поле **«Вид испытаний»** (было «Предмет»), автозаполнение из документа
- **`config.py`** — единые пути (`PROJECT_ROOT`, `DATA_DIR`, `OCR_CACHE_DIR`, …)
- **Пакеты** — `extraction/`, `parsing/`, `persistence/`, `generation/`, `calculation/`, `mapping/`, `validation/`, `nlp/`, `ui/`
- **Пакет `assistant/`** — задел ИИ-ассистента (`MarkCorrector`, `BrandKnowledgeBase`)
- **Shim-файлы удалены** — импорты только через пакеты (`extraction/`, `ui/`, …)
- **pytest:** 64 теста (`test_ocr_mark_normalizer`, `test_test_type_extractor`, …)
- **5.5 пакетная обработка** — отложена (расширение на свободное время)
- Отчёт: [[33 — Отчёт Итерация 5.4.1 OCR-марки, вид испытаний, пакеты (2026-07-03)]]
- План ИИ: [[34 — План разработки ИИ-ассистента (2026-07-03)]]

## Статус v0.8.1 (2026-07-03)

### Итерация 5 — фаза 2 ✅ (test_mappings + GUI)

- **25+ фраз** в `test_mappings` (климатика, прайс НЧ/ВЧ)
- **GUI CRUD** на вкладке «9. Настройки»
- **`resolve_test_code()`** — алиасы slug прайса
- CLI: `update-test-mapping`, `delete-test-mapping`
- Отчёт: [[32 — Отчёт Итерация 5.4 test_mappings и GUI (2026-07-03)]]

## Статус v0.8.0 (2026-07-03)

### Итерация 5 — фаза 1 ✅ (OCR + pytest)

- **Tesseract 5.4** + кэш `data/ocr_cache/` (~2.6 с/стр., повтор ~6 мс)
- **Singleton EasyOCR** (fallback)
- **pytest:** `test_find_cable_marks`, `test_extract_organizations`, `test_gui_smoke`, `test_ocr_cache` (49 тестов)
- **CLI:** `--no-ocr-cache`
- Отчёт Obsidian: [[31 — Отчёт Итерация 5.2/5.3 OCR и pytest (2026-07-03)]]

## Статус v0.7.1 (2026-07-02)

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

### Фаза 2 — завершена ✅ (v0.7.1)

- Table-first extractor (v0.6.2)
- `test_mappings` + `requirement_mapper` (v0.7.0)
- `generated_documents` + `list-generated-documents` (v0.7.1)
- GUI: «Испытания из заявки» на вкладке «Расчёт»

См. [[27 — Фаза 2: требования и таблицы (2026-07-02)]] в Obsidian.

## Ключевые заметки Obsidian

| Заметка | Тема |
|---------|------|
| [[00 — request-processor (главная)]] | Навигация, технологии |
| [[06 — Архитектура и файлы]] | Структура пакетов v0.8.2 |
| [[22 — Валидация парсинга (панель подтверждения)]] | Human-in-the-loop, правила P0–P2 |
| [[26 — Отчёт PR-4: CLI validate и dry-run (2026-07-02)]] | Флаги `--validate`, `--dry-run` |
| [[27 — Фаза 2: требования и таблицы (2026-07-02)]] | Roadmap фазы 2 |
| [[31 — Отчёт Итерация 5.2/5.3 OCR и pytest (2026-07-03)]] | Tesseract, кэш, pytest |
| [[32 — Отчёт Итерация 5.4 test_mappings и GUI (2026-07-03)]] | Маппинг требований, UI |
| [[33 — Отчёт Итерация 5.4.1 OCR-марки, вид испытаний, пакеты (2026-07-03)]] | Нормализатор, КП, реорганизация |
| [[10 — GUI (tkinter)]] | Вкладки, кнопки |
| [[17 — Заказы (orders)]] | Бизнес-логика заказов |
| [[03 — Команды CLI]] | Все команды и флаги |
| [[19 — Запуск приложения]] | Установка и запуск GUI |