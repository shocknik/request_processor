# Обработка заявок на испытания кабелей

Автоматизация расчёта стоимости испытаний кабельной продукции, обработки заявок и формирования документов (КП и заявка на испытания).

**Версия:** 0.5.0  
**Репозиторий:** https://github.com/shocknik/request_processor

---

## Возможности

- Извлечение из **PDF** и **Word** (марки, заказчик, производитель)
- Расчёт испытаний (`fixed`, `per_core`, `per_group`, `time_based`)
- **КП в Word** по нескольким маркам
- **Заявка на испытания в Word** — форма + приложение с объёмом испытаний
- **Заказы** — заявка + расчёты + КП = один заказ в БД
- Справочники: испытания, марки, организации
- GUI (tkinter) и CLI (Click)

---

## Быстрый старт

```powershell
git clone https://github.com/shocknik/request_processor.git
cd request_processor
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ocr]"
request-processor migrate-db
request-processor gui
```

---

## Рабочий цикл

1. **Заявка** — извлечь марки и организации из входящего документа
2. **Расчёт** — посчитать каждую марку
3. **КП** — сформировать Word → **заказ сохраняется автоматически**
4. **Заказы** — сформировать заявку на испытания, открыть/распечатать КП и заявку

---

## Структура

```
src/request_processor/
├── pdf_extractor.py          # Заявки PDF/Word
├── organization_extractor.py # Парсинг организаций
├── cost_calculator.py
├── kp_generator.py           # КП Word
├── application_generator.py  # Заявка на испытания Word
├── sqlite_repo.py            # БД: orders, organizations, …
└── gui.py
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
request-processor extract-pdf --pdf letter.pdf --show-marks
request-processor generate-kp --customer "ООО …" --calc-ids "1,2,3"
request-processor generate-application --order-id 1
request-processor list-orders
request-processor list-organizations
request-processor gui
```

---

## Документация

- Obsidian: `Python/Проект request-processor/`
- `docs/README.md`

---

## Лицензия

MIT