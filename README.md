# Обработка заявок на испытания кабелей

Автоматизация расчёта стоимости испытаний кабельной продукции, обработки заявок и формирования документов (КП и заявка на испытания).

**Версия:** 0.8.2
**Репозиторий:** https://github.com/shocknik/request_processor

---

## Возможности

- Извлечение из **PDF** и **Word** (марки, заказчик, производитель)
- **Валидация парсинга** — отчёт уверенности, human-in-the-loop в GUI
- **Маппинг требований** — `test_mappings` (25+ фраз, GUI на вкладке «Настройки»), «Испытания из заявки»
- Расчёт испытаний (`fixed`, `per_core`, `per_group`, `time_based`)
- **КП в Word** по нескольким маркам
- **Заявка на испытания в Word** — форма + приложение с объёмом испытаний
- **Заказы** — заявка + расчёты + КП = один заказ в БД
- Справочники: испытания, марки, организации
- GUI (tkinter) и CLI (Click)
- **OCR** — Tesseract (приоритет) + кэш `data/ocr_cache/`, EasyOCR fallback
- **Нормализация OCR-марок** — латиница → кириллица (`KCBur(A)` → `КСБнг(А)`), подсказка по `cable_marks`
- **Вид испытаний** — автоопределение из письма/заявки (вкладка «КП»)
- **pytest** — 64 теста (валидатор, CLI, марки, OCR, организации, GUI smoke)

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

Или двойной клик: `start_gui.bat` (или ярлык на рабочем столе — см. ниже)

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
├── config.py                  # Пути: data/, templates/, ocr_cache/
├── cli.py, models.py
├── extraction/                # Заявки, OCR, организации, вид испытаний
│   ├── pdf_extractor.py
│   ├── ocr_mark_normalizer.py
│   ├── test_type_extractor.py
│   └── …
├── parsing/                   # Разбор марки кабеля
├── persistence/               # SQLite (sqlite_repo)
├── generation/                # КП и заявка на испытания (Word)
├── calculation/               # Стоимость, климатика, правила
├── mapping/                   # Требования → испытания
├── validation/                # Human-in-the-loop (P0–P2)
├── nlp/                       # NER (опционально)
└── ui/                        # tkinter GUI
tests/                         # pytest (64 теста)
data/                          # БД, шаблоны, кэш OCR, generated/
```

Пакет `assistant/` — задел ИИ-ассистента (коррекция марок по базе `cable_marks`).

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

## Ярлык на рабочем столе

```powershell
cd D:\My_projects\request_processor
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

Или вручную: ярлык на `start_gui.bat`, рабочая папка = корень проекта.

Запуск: `python -m request_processor.ui.gui` или `request-processor-gui`.

---

## Документация

- Obsidian: `Python/Проект request-processor/`
- `docs/README.md`
- План ИИ-ассистента: Obsidian [[34 — План разработки ИИ-ассистента (2026-07-03)]]

---

## Лицензия

MIT