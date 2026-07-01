# request-processor

Автоматизация расчёта стоимости испытаний кабельной продукции, извлечения марок из PDF и формирования документов.

**Версия:** 0.3.0  
**Репозиторий:** https://github.com/shocknik/request_processor  
**Статус:** Итерация 2+ (PDF, GUI, марки, настройки, **КП Word**)

---

## Возможности

- Парсинг марок кабелей (сечение, жилы, пожарный класс, ТУ/ГОСТ)
- Расчёт стоимости испытаний по правилам прайс-листа (`fixed`, `per_core`, `per_group`, `time_based`)
- Извлечение марок из PDF (текстовые документы и сканы через OCR)
- Накопительная таблица марок в SQLite без полных дублей
- Настройка времени выдержки для 5 климатических испытаний (`time_based`)
- GUI с визуальным списком испытаний и полями часов выдержки
- Добавление испытаний в расчёт двойным кликом из справочника
- **Генерация коммерческого предложения (Word)** по нескольким маркам
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
├── climatic_tests.py      # Константы климатических испытаний
├── test_rules.py          # Типы правил и категории из Excel
├── kp_generator.py        # Коммерческое предложение (Word)
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
request-processor set-climatic-hours --temp-low 2 --temp-high 4 --temp-cycling 2 --humidity 72 --solar-radiation 36
request-processor history --limit 20
```

### Коммерческое предложение (Word)

```powershell
request-processor generate-kp `
    --customer "ООО «Калужский кабельный завод»" `
    --subject "Проведение периодических испытаний" `
    --calc-ids "6,7,8,9"
```

Файлы сохраняются в `data/generated/` (абсолютный путь от корня проекта, не зависит от cwd).

**Содержимое КП:** вводная строка (предмет + заказчик), таблица марок с суммами без НДС / НДС 22% / с НДС, строка **ИТОГО**. Без детализации по видам испытаний.

**Полный цикл (письмо с 4 марками):**

1. **PDF** — извлечь марки из письма
2. **Расчёт** — для каждой марки посчитать стоимость (сохраняется в БД)
3. **КП** — заказчик, предмет, выбрать расчёты → Word

### GUI

```powershell
request-processor gui
# или
request-processor-gui
```

**Полный цикл:** PDF → расчёт по каждой марке → вкладка «КП» → Word.

**Вкладка «КП»:**

- Кнопка **«▶ Сформировать КП»** — вверху (под полями заказчика)
- **Выбрать все** / **Обновить список**
- Превью итогов при выборе расчётов
- Двойной клик по строке — сформировать КП
- После генерации Word открывается автоматически

> На вкладке «КП» выбираются **сохранённые расчёты** (с ценой), а не просто марки из вкладки «Марки».

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

### Климатические испытания (`test_items`, все `time_based`)

| Код | Наименование |
|-----|--------------|
| `temp_low` | Стойкость к пониженной температуре |
| `temp_high` | Стойкость к повышенной температуре |
| `temp_cycling` | Стойкость к изменению температур (резкое/плавное) |
| `humidity` | Стойкость к повышенной влажности воздуха |
| `solar_radiation` | Стойкость к солнечной радиации |

Формула: `base_cost + cost_per_hour × hours`

### Настройки выдержки (`app_settings`)

Ключ `climatic_test_hours` — часы по умолчанию для каждого ключа:  
`temp_low`, `temp_high`, `temp_cycling`, `humidity`, `solar_radiation`

### GUI — расчёт

1. Вкладка **Справочник** → двойной клик по испытанию
2. Вкладка **Расчёт** → список испытаний; для климатических — поле **⏱ часы**
3. Часы подставляются из **Настройки**, можно изменить для конкретного расчёта

---

## PDF: типы документов и OCR

| Тип | Признак | Обработка |
|-----|---------|-----------|
| Текстовый | есть текстовый слой | pdfplumber |
| Скан | нет текста, есть изображения | PyMuPDF + Tesseract (или easyocr) |

Оптимизации OCR: DPI 200, параллельная обработка страниц, исправление типичных ошибок OCR (`Зх`→`3х`, `lх6`→`1х6`).

---

## Правила расчёта

| `rule_type` | Формула | Когда применяется |
|-------------|---------|-------------------|
| `fixed` | `base_cost` | Большинство испытаний |
| `per_core` | `base_cost × cores` | Электрические сопротивления (× кол-во жил) |
| `per_group` | `base_cost × groups` | Ёмкость, индуктивность, затухание, волновое (× кол-во пар) |
| `time_based` | `base_cost + cost_per_hour × hours` | Климатические испытания |

Правила определяются автоматически при загрузке прайса (`load-data`) и при `migrate-db`  
(модуль `test_rules.py`).

### Справочник в GUI

- Испытания сгруппированы по категориям из Excel (Конструкция, Электрические НЧ/ВЧ, Климатика…)
- **Двойной клик** — добавить в расчёт
- **ПКМ** на строке в расчёте — удалить испытание

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