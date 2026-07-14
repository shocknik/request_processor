# Обработка заявок на испытания кабелей

Автоматизация расчёта стоимости испытаний кабельной продукции, извлечения данных из заявок (PDF/Word), валидации парсинга оператором и формирования документов (коммерческое предложение и заявка на испытания).

**Версия:** 0.9.1  
**Репозиторий:** https://github.com/shocknik/request_processor  
**Python:** ≥ 3.10

---

## Содержание

- [Возможности](#возможности)
- [Быстрый старт](#быстрый-старт)
- [Зависимости и OCR](#зависимости-и-ocr)
- [Рабочий цикл](#рабочий-цикл)
- [Архитектура](#архитектура)
- [Каталог data/](#каталог-data)
- [База данных](#база-данных)
- [Извлечение данных](#извлечение-данных)
- [OCR (Фаза 2)](#ocr-фаза-2)
- [Обучение и оценка качества (Фаза 1)](#обучение-и-оценка-качества-фаза-1)
- [Семейства документов (YAML)](#семейства-документов-yaml)
- [Графический интерфейс](#графический-интерфейс)
- [CLI](#cli)
- [Тесты](#тесты)
- [Скрипты](#скрипты)
- [Дорожная карта](#дорожная-карта)
- [Документация](#документация)
- [Лицензия](#лицензия)

---

## Возможности

### Бизнес-цикл

- **Извлечение** из **PDF**, **Word (.docx)** и **свободного текста** (речь/письмо заказчика): марки, заказчик, производитель, организации
- **Валидация парсинга** — отчёт уверенности (правила P0–P2), human-in-the-loop в GUI, экспорт правок оператора
- **Маппинг требований** — справочник `test_mappings` (25+ фраз), подсказки «Испытания из заявки» на вкладке «Расчёт»
- **Расчёт испытаний** — правила `fixed`, `per_core`, `per_group`, `time_based`; климатические часы выдержки
- **КП в Word** по нескольким маркам; автоматическое создание заказа в БД
- **Заявка на испытания в Word** — форма + приложение с объёмом испытаний
- **Макет протокола** + **пакет документов** (заявка + КП + протокол + summary) по заказу
- **Заказы** — заявка + расчёты + КП = один заказ; история сгенерированных документов
- Справочники: испытания, марки, организации
- **GUI-first** (tkinter) + **CLI** (Click) для eval/migrate/агента

### OCR и распознавание сканов

- **Tesseract** (приоритет) + **EasyOCR** (fallback, опционально)
- **Кэш OCR** — `data/ocr_cache/` (fingerprint файла + DPI + движок + версия препроцессинга)
- **Препроцессинг v2** (OpenCV, опционально `pip install -e ".[cv]"`): grayscale → deskew → denoise → upscale → adaptive threshold
- **Table OCR v0** — детекция сетки линий на сканах, OCR по ячейкам; fallback «полосы строк» для Word-экспортов без горизонтальных линий
- **Confidence scoring** — пословная уверенность Tesseract (`OcrPageResult`, `OcrWord`)
- **OCR benchmark** — сравнение raw vs preprocess на странице, метрики CER

### Нормализация и семейства документов

- **Нормализация OCR-марок** — латиница → кириллица (`KCBur(A)` → `КСБнг(А)`), подсказка по `cable_marks`
- **Семейства документов (YAML)** — `periodic_letter_v1`, `lan_letter_v1` с детекцией по маркерам типа документа и таблицы
- **Специализированные экстракторы** — письма с таблицей периодических испытаний, гарантийные письма (LAN), направления в ИЛ, таблицы серийных марок
- **Вид испытаний** — автоопределение из письма/заявки (вкладка «КП»)

### Обучение и оценка (Фаза 1)

- **training_documents** — регистрация PDF/DOCX, inbox → registered
- **training_labels** — эталонная разметка (marks, organizations, requirements, ocr_page, full_json)
- **eval-extraction** — сравнение извлечённых марок с ground truth, recall micro/macro
- **training_corrections** — синхронизация правок оператора из `data/training/corrections/*.jsonl`
- **RAG-корпус** — индексация ТУ/ГОСТ/ПМИ/протоколов в `rag_documents` (без embeddings — задел Фазы 4)
- **document_families** — YAML-семейства в БД

### Ассистент (спринт B)

- `MarkCorrector` + fuzzy snap по `cable_marks` + `BrandKnowledgeBase`
- Вкладка «Заявка»: колонка **💡**, кнопки **Принять/Отклонить**, диалог **Ассистент**
- Журнал решений → `data/training/corrections/assistant_*.jsonl` + `assistant_sessions`
- Подсказки испытаний в панели марки; LLM — позже, opt-in

### Тестирование

- **pytest** — **116** тестов: валидатор, CLI, марки (периодические письма, LAN, серийные кабели, направления), OCR, организации, training repo, eval extraction, table OCR, preprocess, GUI smoke

---

## Быстрый старт

**На рабочий ПК (рекомендуется):** см. **[INSTALL.md](INSTALL.md)** — один скрипт `scripts/install.ps1`.

**Разработка:**

```powershell
git clone https://github.com/shocknik/request_processor.git
cd request_processor
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# или вручную:
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,cv]"
request-processor migrate-db
request-processor gui
```

Запуск: `start_gui.bat` или ярлык на рабочем столе.

Для dev-тестов OCR-fallback (тяжёлый torch, **не default**):

```powershell
pip install -e ".[dev,ocr,cv]"
```

---

## Зависимости и OCR

| Группа | Установка | Назначение |
|--------|-----------|------------|
| *(базовые)* | `pip install -e .` | pydantic, click, openpyxl, pdfplumber, python-docx, pymupdf, pytesseract, Pillow, PyYAML |
| `dev` | `pip install -e ".[dev]"` | pytest, ruff, mypy |
| `ocr` | `pip install -e ".[ocr]"` | EasyOCR (fallback без Tesseract) |
| `cv` | `pip install -e ".[cv]"` | opencv-python-headless — препроцессинг сканов (Фаза 2) |
| `nlp` | `pip install -e ".[nlp]"` | torch, transformers — NER (опционально) |

**Tesseract OCR** (рекомендуется для продакшена):

1. Установить [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) (Windows: `C:\Program Files\Tesseract-OCR\tesseract.exe`)
2. Языки: `rus`, `eng`
3. Проект ищет бинарник автоматически; при отсутствии — fallback на EasyOCR (если установлен)

**PyMuPDF** рендерит страницы PDF в изображения (без poppler).

---

## Рабочий цикл

```
Заявка (PDF/DOCX)
    → извлечение (текст / OCR / таблицы)
    → валидация (P0–P2)
    → подтверждение оператором (GUI)
    → расчёт по маркам
    → КП (Word) → заказ в БД
    → заявка на испытания (Word)
```

1. **Заявка** — загрузить документ → извлечь марки и организации → проверить и подтвердить (вкладка «1. Заявка»)
2. **Расчёт** — выбрать марку, испытания (вручную или «Испытания из заявки»), посчитать
3. **КП** — сформировать Word → **заказ сохраняется автоматически**
4. **Заказы** — сформировать заявку на испытания, открыть/распечатать КП и заявку

Правки оператора при подтверждении экспортируются в `data/training/corrections/*.jsonl` для дообучения пайплайна.

---

## Архитектура

```
src/request_processor/
├── __init__.py              # версия пакета
├── config.py                # PROJECT_ROOT, пути data/, training/, ocr_cache/
├── cli.py                   # Click CLI (30+ команд)
├── models.py                # Pydantic-модели (PdfExtractionResult, ValidationReport, …)
│
├── extraction/              # Извлечение из документов
│   ├── pdf_extractor.py     # PDF/DOCX, OCR, find_cable_marks, кэш
│   ├── periodic_letter_extractor.py   # Таблица периодических испытаний
│   ├── letter_extractor.py            # Деловые письма
│   ├── direction_table_extractor.py   # Направления в ИЛ
│   ├── organization_extractor.py
│   ├── test_type_extractor.py         # Вид испытаний
│   ├── ocr_mark_normalizer.py         # Латиница → кириллица
│   ├── ocr_text_normalizer.py
│   ├── families/
│   │   └── registry.py      # YAML-семейства, match_score
│   └── ocr/                 # Фаза 2
│       ├── preprocess.py    # OpenCV pipeline v2
│       ├── confidence.py    # OcrPageResult, OcrWord
│       ├── table.py         # Table OCR v0
│       └── benchmark.py     # raw vs preprocess, CER
│
├── parsing/                 # Разбор марки кабеля (бренд, жилы, сечение, ТУ)
│   └── cable_mark_parser.py
│
├── persistence/
│   ├── sqlite_repo.py       # Операционная БД (заказы, расчёты, марки, …)
│   └── training_repo.py     # Обучение: documents, labels, RAG, corrections
│
├── generation/              # Word-документы
│   ├── kp_generator.py        # Коммерческое предложение
│   └── application_generator.py  # Заявка на испытания
│
├── calculation/
│   ├── cost_calculator.py
│   ├── test_rules.py
│   └── climatic_tests.py
│
├── mapping/
│   └── requirement_mapper.py  # test_mappings → коды испытаний
│
├── validation/
│   ├── extraction_validator.py  # Human-in-the-loop, P0–P2
│   └── eval_extraction.py       # Сравнение с ground truth
│
├── nlp/                     # NER (опционально)
│   └── nlp_extractor.py
│
├── assistant/               # Задел ИИ-ассистента
│   ├── mark_corrector.py
│   ├── brand_knowledge.py
│   └── models.py
│
└── ui/
    └── gui.py               # tkinter, 9 вкладок

data/
├── app.db                   # SQLite (операционная + training)
├── families/                # YAML-семейства документов
├── templates/               # Шаблоны Word
├── extracted/               # JSON результатов extract-pdf
├── generated/               # Сгенерированные КП и заявки
├── ocr_cache/               # Кэш распознанного текста
└── training/                # Обучающий контур (см. ниже)

tests/                       # 116 pytest-тестов
scripts/                     # PowerShell/Python утилиты
docs/                        # История итераций
```

Точки входа после `pip install -e .`:

- `request-processor` — CLI
- `request-processor-gui` — GUI
- `python -m request_processor.ui.gui` — GUI без entry point

---

## Каталог data/

| Путь | Назначение |
|------|------------|
| `data/app.db` | Основная SQLite-база |
| `data/templates/zayavka_ispytaniy.docx` | Шаблон заявки на испытания |
| `data/templates/Форма Протокола испытаний (2025).docx` | Шаблон протокола |
| `data/extracted/` | JSON после `extract-pdf` / GUI |
| `data/generated/` | Сгенерированные КП и заявки |
| `data/ocr_cache/` | Кэш OCR (ключ: hash + dpi + engine + preprocess) |
| `data/families/*.yaml` | Конфигурации семейств документов (типы: письмо, направление, …) |
| `data/client_profiles.local.yaml` | Локальные адреса/профили клиентов (**не в git**, см. `docs/client_profiles.example.yaml`) |

### Обучающий контур (`data/training/`)

| Путь | Назначение |
|------|------------|
| `documents/inbox/` | Входящие PDF/DOCX для регистрации (`ingest-training-inbox`) |
| `documents/registered/` | Зарегистрированные документы |
| `documents/archived/` | Архив |
| `labels/marks/` | Эталоны марок (JSON) для `eval-extraction` |
| `labels/organizations/` | Эталоны организаций |
| `labels/requirements/` | Эталоны требований |
| `labels/ocr_pages/` | Эталоны OCR постранично |
| `corrections/` | JSONL правок оператора (`sync-corrections`) |
| `exports/reports/` | Отчёты eval-extraction, ocr-benchmark |
| `exports/jsonl/` | Экспорт датасетов |
| `rag_corpus/tu/` | ТУ |
| `rag_corpus/gost/` | ГОСТ |
| `rag_corpus/pmi/` | ПМИ |
| `rag_corpus/protocols/` | Протоколы |
| `rag_corpus/internal/` | Внутренние документы |

Инициализация папок: `scripts/init_training_folders.ps1`

---

## База данных

`request-processor migrate-db` создаёт и обновляет схему.

### Операционные таблицы

| Таблица | Назначение |
|---------|------------|
| `test_items` | Справочник испытаний (прайс) |
| `calculations` | Сохранённые расчёты |
| `calculation_lines` | Строки расчёта |
| `cable_marks` | Накопленные марки кабелей |
| `organizations` | Справочник организаций (ИНН, адрес, ФСА) |
| `document_extractions` | Журнал обработанных заявок |
| `orders` | Заказ (= КП): заказчик, пути к файлам |
| `order_marks` | Марки заказа + производитель |
| `test_applications` | Сформированные заявки на испытания |
| `test_mappings` | Фраза требования → код испытания |
| `generated_documents` | История КП и заявок |
| `app_settings` | Настройки (климатические часы) |

### Таблицы обучения и RAG (Фаза 1)

| Таблица | Назначение |
|---------|------------|
| `training_documents` | Зарегистрированные PDF/DOCX, hash, label_status |
| `training_labels` | Эталонная разметка (payload JSON) |
| `document_families` | Семейства из YAML |
| `ocr_runs` | Журнал прогонов OCR (движок, dpi, confidence) |
| `training_corrections` | Правки оператора |
| `rag_documents` | Файлы корпуса (ТУ, ГОСТ, …) |
| `rag_chunks` | Чанки для RAG (embedding_blob — задел) |
| `assistant_sessions` | Сессии ассистента (задел) |

---

## Извлечение данных

Единая точка входа: `extract_from_document(path)` в `pdf_extractor.py`.

### Поддерживаемые форматы

- **PDF** — pdfplumber (текст + таблицы); при скане — PyMuPDF → Tesseract/EasyOCR
- **DOCX** — python-docx (параграфы + таблицы)

### Поиск марок

1. Классификация семейства (`families/registry.py`, YAML)
2. Специализированные паттерны (периодические письма, LAN, серийные/гибкие марки, направления, …)
3. Общий `find_cable_marks()` по тексту и таблицам
4. OCR-фиксы по семействам документов (периодические, LAN, направления, …)
5. `ocr_mark_normalizer` — нормализация бренда и латиницы
6. Дедупликация и `is_plausible_mark()` — отсев мусора

### Организации

`organization_extractor.py` — заказчик, производитель, испытательный центр; ИНН/КПП, адрес, ФСА.

### Валидация (human-in-the-loop)

`extraction_validator.py`:

- Классификация типа документа: `letter`, `direction`, `act`, `unknown`
- Оценка полей: марки, организации, пустой текст, OCR-штраф
- `ValidationReport.block_confirm` — блокировка подтверждения при критических проблемах
- CLI: `--validate` (код выхода 1 при блокировке); GUI: панель на вкладке «1. Заявка»

---

## OCR (Фаза 2)

Модуль `extraction/ocr/`.

### Препроцессинг (`preprocess.py`, версия **v2**)

```
grayscale → deskew (до ±5°) → denoise → upscale (min 1500px, target 2000px) → adaptive threshold
```

Требует `opencv-python-headless` (`pip install -e ".[cv]"`). Без OpenCV OCR работает на сыром изображении.

### Table OCR (`table.py`, версия **v0**)

- **grid** — детекция H/V линий OpenCV, OCR ячеек (Tesseract PSM 7)
- **row_strip** — fallback: полосы по проекции текста (марки в колонке 1)
- Результат: `TableOcrResult` (rows, text, cell_count, mode)

### Confidence (`confidence.py`)

- `ocr_image_with_data()` — Tesseract `image_to_data` → `OcrPageResult`
- `mean_word_confidence` — средняя уверенность по словам

### Benchmark (`benchmark.py`)

- Сравнение **raw** vs **preprocessed** на одной странице
- Метрики: `mean_confidence`, `text_chars`, CER (если есть ground truth)
- CLI: `ocr-benchmark --pdf scan.pdf --page 1`

### Кэш

Ключ кэша: SHA256 файла + DPI + engine + тег preprocess (`v2` или `none`).  
Путь: `data/ocr_cache/<stem>_<hash>_dpi<DPI>_<engine>[_pre<v2>].txt`

---

## Обучение и оценка качества (Фаза 1)

### Регистрация документов

```powershell
# Один файл
request-processor ingest-training-doc --file "path/to/letter.pdf" --family periodic_letter_v1

# Пакет из inbox
request-processor ingest-training-inbox

# Семена: YAML → document_families + эталоны из data/extracted
request-processor seed-training
```

### Разметка и оценка

```powershell
# Импорт эталона
request-processor import-label --file data/training/labels/marks/example_letter.json

# Сравнение с ground truth
request-processor eval-extraction
# → data/training/exports/reports/eval_marks_<дата>.json
# Метрики: micro_recall, macro_recall, per-file TP/FP/FN
```

### Правки оператора

При подтверждении заявки в GUI правки пишутся в `data/training/corrections/*.jsonl`.  
Синхронизация в БД:

```powershell
request-processor sync-corrections
```

### RAG-корпус (без embeddings)

```powershell
request-processor index-rag --folder data/training/rag_corpus/tu --kind tu
request-processor list-rag
```

---

## Семейства документов (YAML)

Файлы в `data/families/`, загрузка через `families/registry.py`.

| ID | Файл | Тип | Описание |
|----|------|-----|----------|
| `periodic_letter_v1` | `periodic_table_v1.yaml` | `letter_periodic` | Письмо производителя — таблица периодических испытаний |
| `lan_letter_v1` | `lan_letter_v1.yaml` | `letter_list` | Гарантийное письмо / список LAN-марок |

Каждое семейство задаёт:

- `sender_patterns` — паттерны отправителя
- `detection.markers` / `table_hints` — детекция по тексту
- `mark_patterns` — regex марок с kind
- `ocr_phrase_fixes` — замены OCR-ошибок по семейству
- `row_sort` — приоритет строк таблицы (периодические)

`match_score(text)` → 0..1; `is_confident_match()` — порог `confidence_threshold`.

---

## Графический интерфейс

Запуск: `request-processor gui` или `request-processor-gui`.

| Вкладка | Функции |
|---------|---------|
| **1. Заявка** | Загрузка PDF/DOCX, OCR, таблица марок (редактирование, ✓/—), организации, валидация, «Подтвердить заявку», экспорт правок |
| **2. Расчёт** | Марка, выбор испытаний (picker по категориям), климатические часы, «Испытания из заявки», итог |
| **3. КП** | Заказчик, **вид испытаний** (автозаполнение), выбор расчётов, генерация Word |
| **4. Заказы** | Список заказов, детали, заявка на испытания, открытие файлов |
| **5. Марки** | Справочник `cable_marks`, поиск, «→ В расчёт» |
| **6. Организации** | Справочник, поиск, редактирование |
| **7. Справочник** | Испытания по категориям, двойной клик → в расчёт |
| **8. История** | Последние расчёты |
| **9. Настройки** | Климатические часы; CRUD `test_mappings` |

Опции на вкладке «Заявка»: OCR, кэш OCR, сохранение марок/организаций в БД.

---

## CLI

Полный список: `request-processor --help`.

### База и справочники

```powershell
request-processor init-db
request-processor migrate-db
request-processor load-data --price data/прайс.xlsx
request-processor import-tests --file tests.xlsx
request-processor list-tests
request-processor add-test-item --code ... --name ... --base-cost ... --category ...
request-processor list-cable-marks --search "ВВГ"
request-processor list-organizations --search "производитель"
request-processor set-climatic-hours --temp-low 48 --humidity 120
```

### Извлечение и валидация

```powershell
request-processor extract-pdf --pdf letter.pdf --show-marks
request-processor extract-pdf --pdf letter.pdf --dry-run          # только JSON
request-processor extract-pdf --pdf letter.pdf --validate         # отчёт валидатора
request-processor extract-pdf --pdf scan.pdf --ocr-dpi 300
request-processor extract-pdf --pdf scan.pdf --no-ocr-cache
request-processor process --input letter.pdf                      # упрощённый extract
```

### Расчёт и документы

```powershell
request-processor calculate --mark "ВВГнг(А) 3х2,5" --tests "temp_low,humidity" --hour temp_low=48
request-processor history
request-processor suggest-tests --requirements "солнечного излучения"
request-processor suggest-tests --mark "ВВГнг"
request-processor generate-kp --customer "ООО …" --calc-ids "1,2,3"
request-processor generate-application --order-id 1
request-processor list-orders
request-processor list-generated-documents --order-id 1
request-processor list-applications
```

### Маппинг требований

```powershell
request-processor list-test-mappings
request-processor add-test-mapping --pattern "солнечн" --test-code solar_radiation
request-processor update-test-mapping --id 1 --pattern "новая фраза"
request-processor delete-test-mapping --id 1
```

### Обучение, OCR benchmark, RAG

```powershell
request-processor seed-training
request-processor ingest-training-doc --file doc.pdf --family periodic_letter_v1
request-processor ingest-training-inbox
request-processor list-training-docs
request-processor import-label --file data/training/labels/marks/example_letter.json
request-processor eval-extraction
request-processor eval-extraction --no-ocr-cache
request-processor ocr-benchmark --pdf scan.pdf --page 1 --dpi 200
request-processor sync-corrections
request-processor index-rag --folder data/training/rag_corpus/tu --kind tu
request-processor list-rag
```

### GUI

```powershell
request-processor gui
```

---

## Тесты

```powershell
pytest tests/ -q
pytest tests/test_periodic_letter_marks.py -v
pytest tests/test_eval_extraction.py -v
```

| Файл | Что проверяет |
|------|---------------|
| `test_extraction_validator.py` | Правила P0–P2, ValidationReport |
| `test_cli_extract_pdf.py` | CLI extract-pdf, --validate, --dry-run |
| `test_find_cable_marks.py` | Общий поиск марок |
| `test_periodic_letter_marks.py` | Письма с таблицей периодических испытаний |
| `test_periodic_letter_address.py` | Адреса производителя в письмах |
| `test_lan_letter_ocr.py` | LAN-письмо + OCR-кэш |
| `test_letter_marks_regression.py` | Регрессия марок из OCR-шума |
| `test_series_cable_marks.py` | Серийные/гибкие марки |
| `test_direction_marks.py` | Направления в ИЛ: типовые марки |
| `test_ocr_cache.py` | Кэш OCR |
| `test_ocr_preprocess.py` | Препроцессинг v2 |
| `test_table_ocr.py` | Table OCR v0 |
| `test_ocr_mark_normalizer.py` | Нормализация марок |
| `test_ocr_text_normalizer.py` | Нормализация текста |
| `test_training_repo.py` | training_documents, labels, RAG |
| `test_eval_extraction.py` | eval-extraction |
| `test_family_registry.py` | YAML-семейства |
| `test_requirement_mapper.py` | Маппинг требований |
| `test_test_mappings.py` | Справочник test_mappings |
| `test_test_type_extractor.py` | Вид испытаний |
| `test_extract_organizations.py` | Организации |
| `test_direction_table_extractor.py` | Направления |
| `test_pdf_extractor_regression.py` | Регрессии pdf_extractor |
| `test_generated_documents.py` | generated_documents |
| `test_assistant_mark_corrector.py` | MarkCorrector |
| `test_gui_smoke.py` | Импорт и создание GUI |

Линтер: `ruff check src tests`  
Типы: `mypy src/request_processor` (strict)

---

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `start_gui.bat` | Запуск GUI |
| `start_gui_debug.bat` | GUI с логом в `data/gui_launch.log` |
| `scripts/install.ps1` | Установка на ПК (venv, deps, БД, ярлык) |
| `scripts/build_release_zip.ps1` | Zip-релиз для другого компьютера |
| `scripts/create_desktop_shortcut.ps1` | Ярлык на рабочем столе |
| `scripts/init_training_folders.ps1` | Создание структуры `data/training/` |
| `scripts/batch_extract_inbox.ps1` | Пакетное извлечение из inbox |
| `scripts/cleanup_artifacts.ps1` | Очистка артефактов |

Ярлык на рабочем столе:

```powershell
cd D:\My_projects\request_processor
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

---

## Дорожная карта

| Фаза | Статус | Содержание |
|------|--------|------------|
| **0** | ✅ | Базовый расчёт, GUI, SQLite, КП |
| **1** | ✅ | Human-in-the-loop, test_mappings, заказы, заявки |
| **1 training** | ✅ | training_documents, labels, families YAML, eval-extraction, RAG registry |
| **2 OCR** | ✅ | preprocess v2, table OCR v0, confidence, benchmark, расширенные марки |
| **3** | 🔜 | Улучшение recall на реальных сканах, больше семейств |
| **4 RAG** | 🔜 | Embeddings, поиск по ТУ/ГОСТ |
| **5 Assistant** | 🟡 | MarkCorrector в GUI (детерминированный слой); LLM — позже |
| **6 Production** | 🟡 | v0.9: installer, пакет документов, текст/речь, DPI 400, torch opt-in |

Подробные отчёты и планы — в Obsidian (`Python/Проект request-processor/`) и `docs/README.md`.

---

## Документация

- **GitHub:** https://github.com/shocknik/request_processor
- **Obsidian:** `Python/Проект request-processor/`
- **docs/README.md** — хронология итераций (v0.7–v0.8.2)
- **docs/План_Итерации_2.md** — план фазы 2
- Ключевые заметки Obsidian: валидация парсинга (22), OCR (31), test_mappings (32), пакеты (33), ИИ-ассистент (34), eval-extraction (35m), OCR Фаза 2 (35b, 35p, 35s)

---

## Лицензия

MIT