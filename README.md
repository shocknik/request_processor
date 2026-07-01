# request-processor

Автоматизация расчёта стоимости испытаний кабельной продукции, извлечения марок из PDF и формирования документов.

**Версия:** 0.2.0  
**Репозиторий:** https://github.com/shocknik/request_processor  
**Статус:** Итерация 2 (PDF, GUI, накопление марок, настройки выдержки)

---

## Возможности

- Парсинг марок кабелей (сечение, жилы, пожарный класс, ТУ/ГОСТ)
- Расчёт стоимости испытаний по правилам прайс-листа (`fixed`, `per_core`, `per_group`, `time_based`)
- Извлечение марок из PDF (текстовые документы и сканы через OCR)
- Накопительная таблица марок в SQLite без полных дублей
- Настройка времени выдержки для климатических испытаний
- CLI и графический интерфейс (tkinter)

---

## Быстрый старт

```powershell
cd D:\My_projects\request_processor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[ocr]"

request-processor init-db
request-processor gui
```

Для ускорения OCR на сканах установите [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) с языком `rus`.

---

## Структура проекта

```
src/request_processor/
├── cli.py                 # Точка входа (Click)
├── gui.py                 # Графический интерфейс
├── models.py              # Pydantic-модели
├── cable_mark_parser.py   # Разбор марок кабеля
├── pdf_extractor.py       # Извлечение из PDF + OCR
├── cost_calculator.py     # Расчёт стоимости
└── sqlite_repo.py         # SQLite (Repository)
```

---

## Команды CLI

### База и миграция

```powershell
request-processor init-db
request-processor migrate-db          # обновить схему существующей БД
```

### Расчёт

```powershell
request-processor calculate `
    --mark "ВВГ-Пнг(А) 3х4ок(М,РЕ)-0,66" `
    --tests "resistance_core,temp_high,humidity,solar_radiation" `
    --hour humidity=72
```

Часы для `time_based` берутся из настроек (`set-climatic-hours`), если не указаны вручную через `--hour`.

### PDF

```powershell
request-processor extract-pdf `
    --pdf "C:\path\letter.pdf" `
    --show-marks
```

Марки автоматически сохраняются в таблицу `cable_marks`.

### Справочник испытаний

```powershell
request-processor list-tests
request-processor add-test-item --code my_test --name "..." --base-cost 300 `
    --category "Климатические" --rule-type time_based --default-hours 48 --cost-per-hour 250
request-processor import-tests --file data\new_tests.xlsx
```

### Марки и настройки

```powershell
request-processor list-cable-marks
request-processor set-climatic-hours --temp-high 4 --humidity 72 --solar-radiation 36
request-processor history --limit 20
```

### GUI

```powershell
request-processor gui
# или
request-processor-gui
```

---

## База данных (SQLite)

Файл: `data/app.db`

| Таблица | Назначение |
|---------|------------|
| `test_items` | Справочник испытаний |
| `calculations` | Заголовки расчётов |
| `calculation_lines` | Строки расчёта |
| `cable_marks` | Накопленные марки из PDF и ручного ввода |
| `app_settings` | Настройки (время выдержки климатических испытаний) |

### Таблица `cable_marks`

| Поле | Описание |
|------|----------|
| `full_mark` | Полная марка с размерами и надписями (уникальная) |
| `brand` | Буквенная часть без пожарного обозначения (ВВГ-П, ПВС…) |
| `fire_class` | Класс пожарной безопасности (нг(А), нг(А)-LS…) |
| `cores_count` | Количество ТПЖ |
| `structural_element_type` | жила / пара / тройка |
| `structural_elements_count` | Количество структурных элементов |
| `characteristic_size` | Сечение (мм²) или диаметр (мм) |
| `document` | ТУ/ГОСТ из контекста PDF |

### Настройки выдержки (`app_settings`)

Ключ `climatic_test_hours`:

- `temp_high` — повышенная температура
- `humidity` — повышенная влажность
- `solar_radiation` — солнечная радиация

---

## PDF: типы документов и OCR

| Тип | Признак | Обработка |
|-----|---------|-----------|
| Текстовый | есть текстовый слой | pdfplumber |
| Скан | нет текста, есть изображения | PyMuPDF + Tesseract (или easyocr) |

Оптимизации OCR: DPI 200, параллельная обработка страниц, исправление типичных ошибок OCR (`Зх`→`3х`, `lх6`→`1х6`).

---

## Правила расчёта

| `rule_type` | Формула |
|-------------|---------|
| `fixed` | `base_cost` |
| `per_core` | `base_cost × cores` |
| `per_group` | `base_cost × groups` |
| `time_based` | `base_cost + cost_per_hour × hours` |

---

## Зависимости

```toml
pydantic, click, openpyxl, pdfplumber, python-docx,
pymupdf, pytesseract, Pillow
```

Опционально: `pip install -e ".[ocr]"` — easyocr как запасной OCR.

---

## Документация

- Подробная документация разработчика: `docs/README.md`
- План Итерации 2: `docs/План_Итерации_2.md`
- Obsidian: `Python/Проект request-processor/` в хранилище Obsidian Vault

---

## Лицензия

MIT