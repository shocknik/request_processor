# Обработка заявок на испытания кабелей

Автоматизация расчёта стоимости испытаний кабельной продукции, обработки заявок и формирования документов (КП и заявка на испытания).

**Версия:** 0.7.1  
**Репозиторий:** https://github.com/shocknik/request_processor

---

## Возможности

- Извлечение из **PDF** и **Word** (марки, заказчик, производитель)
- **Валидация парсинга** — отчёт уверенности, human-in-the-loop в GUI
- **Маппинг требований** — `test_mappings`, предложение испытаний из направлений
- Расчёт испытаний (`fixed`, `per_core`, `per_group`, `time_based`)
- **КП в Word** по нескольким маркам
- **Заявка на испытания в Word** — форма + приложение с объёмом испытаний
- **Заказы** — заявка + расчёты + КП = один заказ в БД
- Справочники: испытания, марки, организации
- GUI (tkinter) и CLI (Click)
- **pytest** — smoke-тесты валидатора и CLI

---

## Быстрый старт

```powershell
git clone https://github.com/shocknik/request_processor.git
cd request_processor
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ocr]"
request-processor migrate-db
request-processor gui
```

Или двойной клик: `start_gui.bat`

---

## Рабочий цикл

1. **Заявка** — извлечь марки и организации → **проверить и подтвердить** (GUI)
2. **Расчёт** — посчитать каждую марку
3. **КП** — сформировать Word → **заказ сохраняется автоматически**
4. **Заказы** — сформировать заявку на испытания, открыть/распечатать КП и заявку

---

## Структура

```
src/request_processor/
├── pdf_extractor.py           # Заявки PDF/Word
├── extraction_validator.py    # Валидация парсинга (P0–P2)
├── organization_extractor.py  # Парсинг организаций
├── cable_mark_parser.py       # Разбор марки → поля БД
├── cost_calculator.py
├── kp_generator.py            # КП Word
├── application_generator.py   # Заявка на испытания Word
├── sqlite_repo.py             # БД: orders, organizations, …
└── gui.py
tests/
├── test_extraction_validator.py
└── test_cli_extract_pdf.py
```

Шаблон заявки: `data/templates/zayavka_ispytaniy.docx`

---

## База данных

| Таблица | Назначение |
|---------|------------|
| `orders` | Заказ (= КП), заказчик, пути к КП и заявке |
| `order_marks` | Марки заказа + производитель |
| `organizations` | Справочник организаций |
| `calculations` | Расчёты по маркам |
| `cable_marks` | Накопленные марки |
| `document_extractions` | Журнал заявок |

---

## CLI

```powershell
# Извлечение
request-processor extract-pdf --pdf letter.pdf --show-marks
request-processor extract-pdf --pdf letter.pdf --dry-run          # JSON без БД
request-processor extract-pdf --pdf letter.pdf --validate         # отчёт валидатора
request-processor suggest-tests --requirements "солнечного излучения"
request-processor list-generated-documents --order-id 1

# Документы
request-processor generate-kp --customer "ООО …" --calc-ids "1,2,3"
request-processor generate-application --order-id 1
request-processor list-orders
request-processor list-organizations
request-processor gui
```

---

## Тесты

```powershell
pytest tests/ -q
```

---

## Документация

- Obsidian: `Python/Проект request-processor/`
- `docs/README.md`

---

## Лицензия

MIT