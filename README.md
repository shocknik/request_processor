# Lab_request (request-processor)

Автоматизация расчёта стоимости испытаний кабельной продукции: извлечение данных из заявок (PDF/Word/текст), валидация оператором, расчёт, КП, заявка на испытания, программы ПМИ, нормы и мост к генератору протоколов.

**Версия:** 0.9.1  
**Продуктовое имя:** Lab_request  
**Репозиторий:** https://github.com/shocknik/request_processor  
**Python:** ≥ 3.10 (рекомендуется 3.11/3.12)

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
- [OCR](#ocr)
- [Обучение и оценка](#обучение-и-оценка)
- [Семейства документов](#семейства-документов)
- [Программы, нормы, КП, протоколы](#программы-нормы-кп-протоколы)
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

- **Извлечение** из **PDF**, **Word (.docx)** и **свободного текста**: марки, заказчик, производитель, организации
- **Валидация парсинга** — отчёт уверенности (P0–P2), human-in-the-loop в GUI, экспорт правок оператора
- **Маппинг требований** — `test_mappings` + **синонимы** (`test_aliases`)
- **Расчёт испытаний** — правила `fixed`, `per_core`, `per_group`, `time_based`; климатические часы
- **КП в Word** — стили **classic / modern / compact**, логотип и реквизиты из `lab_profile`
- **Заявка на испытания** + **пакет документов** (заявка + КП + протокол-макет + summary)
- **JSON protocol_meta** — мост к отдельному `protocol_generator` (без правок чужого проекта)
- **Заказы** — заявка + расчёты + КП; история `generated_documents`
- **Программы испытаний (S4)** — импорт ПМИ/ПИ из DOCX, сопоставление с прайсом
- **Нормы (S5)** — `norm_documents` / `requirements`, импорт raw-текста, алиасы
- **GUI-first** (tkinter, sidebar) + **CLI** (Click)

### OCR и распознавание сканов

- **Tesseract** (приоритет) + **EasyOCR** (fallback, опционально; при сбое EasyOCR — снова Tesseract)
- **Кэш OCR** — `data/ocr_cache/`
- **Препроцессинг v2** (OpenCV, `pip install -e ".[cv]"`)
- **Table OCR v0** — сетка / полосы строк
- **Confidence scoring**, **OCR benchmark**, демо **MarkCorrector** (`demo-ocr-marks`)

### Нормализация и семейства

- OCR-марки: латиница → кириллица, fuzzy snap по `cable_marks`
- YAML-семейства: `periodic_letter_v1`, `lan_letter_v1`
- Специализированные экстракторы: периодические письма, LAN, направления в ИЛ, серийные марки
- Вид испытаний — автоопределение (вкладка «КП»)

### Обучение, prod-данные, ассистент

- training_documents / labels / eval-extraction / corrections / RAG registry
- **export/import-prod-data**, **prepare-prod-db** для переноса на рабочий ПК
- **MarkCorrector** + fuzzy + BrandKnowledgeBase; LLM **opt-in** (Ollama, `assistant-llm-*`)
- Снимки парсинга и вкладка **«Сравнение»**

### Тестирование

- **pytest** — **~205** тестов (экстракция, OCR, GUI smoke/splash, программы, нормы, KP styles, protocol_meta, prod data, …)

---

## Быстрый старт

**Рабочий ПК (рекомендуется):** [INSTALL.md](INSTALL.md) → `scripts/install.ps1`.  
**Обновление без сноса БД:** [docs/UPDATE.md](docs/UPDATE.md) → `scripts/update.ps1`.

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

Запуск: `start_gui.bat`, `start_gui_debug.bat` или ярлык **Lab_request**.

OCR-fallback с EasyOCR (тяжёлый torch, **не default**):

```powershell
pip install -e ".[dev,ocr,cv]"
```

---

## Зависимости и OCR

| Группа | Установка | Назначение |
|--------|-----------|------------|
| *(базовые)* | `pip install -e .` | pydantic, click, openpyxl, pdfplumber, python-docx, pymupdf, pytesseract, Pillow, PyYAML |
| `dev` | `pip install -e ".[dev]"` | pytest, ruff, mypy |
| `ocr` | `pip install -e ".[ocr]"` | EasyOCR (fallback) |
| `cv` | `pip install -e ".[cv]"` | opencv — препроцессинг сканов |
| `nlp` | `pip install -e ".[nlp]"` | torch, transformers — NER (опционально) |

**Tesseract** (рекомендуется для PDF-сканов): [UB-Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki), языки `rus` + `eng`.  
Для **Word .docx** OCR обычно не нужен. **PyMuPDF** рендерит страницы PDF (без poppler).

---

## Рабочий цикл

```
Заявка (PDF/DOCX/текст)
    → извлечение (текст / OCR / таблицы / семейства)
    → валидация (P0–P2) + подтверждение оператором
    → расчёт (прайс + mappings + aliases ± программа)
    → КП (Word, стиль) → заказ в БД
    → заявка / пакет / protocol_meta JSON
```

1. **Заявки** — загрузить документ → марки и организации → проверить → подтвердить  
2. **Расчёты** — марка, испытания (picker / «из заявки» / из программы), итог  
3. **КП** — заказчик, вид испытаний, стиль, генерация Word  
4. **Заказы** — заявка на испытания, файлы, protocol_meta  
5. **Программы / нормы** — справочный контур для ПМИ и ТУ  

Правки оператора → `data/training/corrections/*.jsonl`.

---

## Архитектура

```
src/request_processor/
├── __init__.py, config.py, cli.py, models.py, logging_setup.py
├── extraction/           # PDF/DOCX, OCR, семьи, организации, марки
│   ├── pdf_extractor.py, periodic_letter_extractor.py, letter_extractor.py
│   ├── direction_table_extractor.py, organization_extractor.py
│   ├── ocr_mark_normalizer.py, ocr_text_normalizer.py, client_profiles.py
│   ├── families/registry.py
│   └── ocr/              # preprocess, table, confidence, benchmark
├── parsing/              # разбор марки кабеля
├── persistence/          # sqlite_repo (операционка), training_repo
├── generation/           # КП, заявка, пакет, протокол-макет, program_importer,
│                         # norm_text_import, protocol_meta_export, lab_profile
├── calculation/          # cost_calculator, test_rules, climatic_tests
├── mapping/              # requirement_mapper, program_price_matcher
├── validation/           # extraction_validator, eval_extraction
├── knowledge/            # synonyms и связанное
├── parse_compare/        # снимки парсинга
├── assistant/            # MarkCorrector, fuzzy, LLM provider, demo_marks
├── nlp/                  # NER (опционально)
├── training/             # prod_data export/import helpers
└── ui/
    ├── gui.py            # entry point
    ├── bootstrap.py      # splash → app → mainloop
    ├── app.py, state.py, theme.py
    ├── shell/            # app_shell, menubar
    ├── tabs/             # pdf, calc, kp, orders, marks, orgs, programs, …
    └── widgets/          # sidebar, splash, mousewheel, clipboard, components

data/                     # БД, шаблоны, кэш, training, generated (см. ниже)
tests/                    # ~205 pytest
scripts/                  # install, update, release zip, training helpers
docs/                     # паспорт, UPDATE, S4/S5, UI, protocol bridge
```

Точки входа после `pip install -e .`:

- `request-processor` — CLI  
- `request-processor-gui` / `python -m request_processor.ui.gui` — GUI  

---

## Каталог data/

| Путь | Назначение |
|------|------------|
| `data/app.db` | SQLite (операционка + training + программы + нормы) |
| `data/templates/` | Шаблоны Word (заявка, протокол) |
| `data/extracted/` | JSON после extract |
| `data/generated/` | КП, заявки, пакеты |
| `data/ocr_cache/` | Кэш OCR |
| `data/families/*.yaml` | Семейства документов |
| `data/client_profiles.local.yaml` | Локальные профили клиентов (**не в git**) |
| `data/lab_profile.yaml` | Реквизиты/лого лаборатории (**не в git**, см. example) |
| `data/logs/` | `app_*`, `scripts_*`, `tests_*` |
| `data/parse_snapshots/` | Снимки парсинга для сравнения |
| `data/knowledge/` | Корпус знаний / manufacturer (локально) |
| `data/training/` | inbox, labels, corrections, rag_corpus, exports |

### Обучающий контур (`data/training/`)

| Путь | Назначение |
|------|------------|
| `documents/inbox|registered|archived/` | Регистрация документов |
| `labels/{marks,organizations,requirements,ocr_pages}/` | Эталоны |
| `corrections/` | JSONL правок оператора |
| `exports/reports|jsonl/` | eval, benchmark, датасеты |
| `rag_corpus/{tu,gost,pmi,protocols,internal}/` | Корпус RAG (без embeddings) |

Инициализация: `scripts/init_training_folders.ps1`.

---

## База данных

`request-processor migrate-db` создаёт и обновляет схему **без wipe**.

### Операционные таблицы

| Таблица | Назначение |
|---------|------------|
| `test_items` | Прайс испытаний |
| `calculations` / `calculation_lines` | Расчёты |
| `cable_marks` | Накопленные марки |
| `organizations` | Организации (ИНН, адрес, ФСА, …) |
| `document_extractions` | Журнал заявок |
| `orders` / `order_marks` | Заказы (КП) |
| `test_applications` | Заявки на испытания |
| `test_mappings` | Фраза → код испытания |
| `generated_documents` | История файлов |
| `app_settings` | Настройки (климат, LLM, …) |

### Программы и нормы (S4–S5)

| Таблица | Назначение |
|---------|------------|
| `test_programs` / `test_program_items` | ПМИ/ПИ и позиции |
| `norm_documents` | Нормативные документы |
| `requirements` / `requirement_test_links` | Пункты требований |
| `test_aliases` | Синонимы названий → код/канон |

### Обучение и RAG

| Таблица | Назначение |
|---------|------------|
| `training_documents`, `training_labels` | Документы и эталоны |
| `document_families` | YAML-семейства в БД |
| `ocr_runs` | Журнал OCR |
| `training_corrections` | Правки оператора |
| `rag_documents` / `rag_chunks` | Корпус (embeddings — задел) |
| `assistant_sessions` | Сессии ассистента |

---

## Извлечение данных

Единая точка: `extract_from_document(path)` в `extraction/pdf_extractor.py`.

1. Классификация семейства (YAML)  
2. Специализированные паттерны (периодика, LAN, направления, серии)  
3. Общий `find_cable_marks()`  
4. OCR-фиксы по семейству + `ocr_mark_normalizer`  
5. Организации: `organization_extractor.py`  
6. Валидация: `extraction_validator.py` (`ValidationReport`, `block_confirm`)  

---

## OCR

Модуль `extraction/ocr/`.

- **preprocess v2:** grayscale → deskew → denoise → upscale → adaptive threshold  
- **table v0:** grid / row_strip  
- **confidence:** Tesseract `image_to_data`  
- **benchmark:** raw vs preprocessed, CER  
- **кэш:** hash + DPI + engine + preprocess tag → `data/ocr_cache/`  

```powershell
request-processor ocr-benchmark --pdf scan.pdf --page 1
request-processor demo-ocr-marks --pdf scan.pdf
```

---

## Обучение и оценка

```powershell
request-processor ingest-training-doc --file "path/to/letter.pdf" --family periodic_letter_v1
request-processor ingest-training-inbox
request-processor seed-training
request-processor import-label --file data/training/labels/marks/example.json
request-processor eval-extraction
request-processor sync-corrections
request-processor index-rag --folder data/training/rag_corpus/tu --kind tu
```

---

## Семейства документов

| ID | Файл | Тип | Описание |
|----|------|-----|----------|
| `periodic_letter_v1` | `periodic_table_v1.yaml` | `letter_periodic` | Таблица периодических испытаний |
| `lan_letter_v1` | `lan_letter_v1.yaml` | `letter_list` | Гарантийное / LAN-список |

Поля: `sender_patterns`, `detection`, `mark_patterns`, `ocr_phrase_fixes`, `row_sort`, `confidence_threshold`.

---

## Программы, нормы, КП, протоколы

| Область | Суть | Документ |
|---------|------|----------|
| **S4 Программы** | Импорт DOCX → `test_programs`, match с `test_items` | [docs/TEST_PROGRAMS.md](docs/TEST_PROGRAMS.md) |
| **S5 Нормы** | raw_text, aliases, seed примеров | [docs/REQUIREMENTS_BASE.md](docs/REQUIREMENTS_BASE.md) |
| **S6 w1 Каталог приёмки** | `acceptance_items` + clauses + external ГОСТ (CLI) | [docs/REQUIREMENTS_BASE.md](docs/REQUIREMENTS_BASE.md) |
| **КП** | стили, lab_profile, лого | `docs/lab_profile.example.yaml` |
| **Протокол** | `export-protocol-meta` → JSON для внешнего generator | [docs/PROTOCOL_GENERATOR_BRIDGE.md](docs/PROTOCOL_GENERATOR_BRIDGE.md) |

```powershell
request-processor import-test-program --file "ПМИ.docx"
request-processor match-program-price --program-id 1
request-processor import-norm-text --file norms.txt
request-processor export-protocol-meta --order-id 1
```

---

## Графический интерфейс

Запуск: `request-processor gui` или `request-processor-gui`.

При старте — **splash** (прогресс загрузки). Навигация — **левый sidebar** (не горизонтальный ряд из 9 вкладок).

| Раздел | Функции |
|--------|---------|
| **Заявки** | PDF/DOCX/текст, OCR, марки, организации, валидация, ассистент, подтверждение |
| **Расчёты** | Марка, picker испытаний, климат, «из заявки», итог |
| **КП** | Заказчик, вид испытаний, стиль КП, генерация |
| **Заказы** | Список, заявка, пакет, файлы, protocol_meta |
| **Марки** | Справочник, поиск, в расчёт |
| **Организации** | Справочник, дедуп/подтверждение |
| **Программы** | Импорт ПМИ, позиции, match с прайсом |
| **История** | Последние расчёты |
| **Сравнение** | Снимки парсинга |
| **Настройки** | Климат, mappings, LLM (opt-in), прочее |
| **Справочник** | Испытания (меню **Данные**, не в sidebar) |

Меню: **Файл / Вид / Данные / Сервис / Справка**. Логи: Сервис → просмотр / `data/logs/`.  
UI-архитектура: [docs/UI_ARCHITECTURE.md](docs/UI_ARCHITECTURE.md).

---

## CLI

Полный список: `request-processor --help`.

### База, prod, справочники

```powershell
request-processor init-db
request-processor migrate-db
request-processor prepare-prod-db --yes
request-processor load-data --price data/прайс.xlsx
request-processor import-tests --file tests.xlsx
request-processor list-tests
request-processor add-test-item --code ... --name ... --base-cost ... --category ...
request-processor list-cable-marks --search "ВВГ"
request-processor list-organizations --search "производитель"
request-processor set-climatic-hours --temp-low 48 --humidity 120
request-processor export-prod-data --out pack.zip
request-processor import-prod-data --file pack.zip
```

### Извлечение и валидация

```powershell
request-processor extract-pdf --pdf letter.pdf --show-marks
request-processor extract-pdf --pdf letter.pdf --dry-run
request-processor extract-pdf --pdf letter.pdf --validate
request-processor extract-pdf --pdf scan.pdf --ocr-dpi 300
request-processor process --input letter.pdf
request-processor save-parse-snapshot --file data/extracted/x.json
request-processor list-parse-snapshots
request-processor compare-parse-snapshots --a ID1 --b ID2
```

### Расчёт и документы

```powershell
request-processor calculate --mark "ВВГнг(А) 3х2,5" --tests "temp_low,humidity" --hour temp_low=48
request-processor history
request-processor suggest-tests --requirements "солнечного излучения"
request-processor generate-kp --customer "ООО …" --calc-ids "1,2,3"
request-processor generate-application --order-id 1
request-processor export-protocol-meta --order-id 1
request-processor list-orders
request-processor list-generated-documents --order-id 1
```

### Маппинг, алиасы, программы, нормы

```powershell
request-processor list-test-mappings
request-processor add-test-mapping --pattern "солнечн" --test-code solar_radiation
request-processor list-test-aliases
request-processor add-test-alias --alias "..." --test-code ...
request-processor import-aliases-yaml --file data/knowledge/...
request-processor import-test-program --file program.docx
request-processor list-test-programs
request-processor show-test-program --id 1
request-processor match-program-price --program-id 1
request-processor import-norm-text --file norms.txt
request-processor list-norm-documents
request-processor list-requirements
```

### Training, OCR, ассистент, GUI

```powershell
request-processor seed-training
request-processor eval-extraction
request-processor ocr-benchmark --pdf scan.pdf --page 1
request-processor demo-ocr-marks --pdf scan.pdf
request-processor assistant-llm-status
request-processor assistant-llm-test --mark "КСнг(А)"
request-processor gui
```

---

## Тесты

```powershell
pytest tests/ -q
pytest tests/test_program_importer.py tests/test_norm_text_import.py -v
```

| Группа | Примеры файлов |
|--------|----------------|
| Извлечение / марки | `test_find_cable_marks`, `test_periodic_letter_*`, `test_lan_letter_ocr`, `test_direction_*`, `test_series_cable_marks` |
| OCR | `test_ocr_*`, `test_table_ocr` |
| Валидация / eval | `test_extraction_validator`, `test_eval_extraction` |
| GUI | `test_gui_smoke`, `test_splash`, `test_window_fit`, `test_mousewheel` |
| S4 / S5 | `test_program_importer`, `test_program_price_match`, `test_norm_*` |
| Документы | `test_generated_documents`, `test_document_pack`, `test_kp_styles`, `test_protocol_meta_export` |
| Ассистент | `test_assistant_*`, `test_demo_ocr_marks` |
| Prod / DB | `test_prepare_prod_db`, `test_prod_data`, `test_delete_entities` |

Линтер: `ruff check src tests`  
Типы: `mypy src/request_processor` (strict)

---

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `start_gui.bat` | Запуск GUI |
| `start_gui_debug.bat` | GUI + лог `data/gui_launch.log` |
| `scripts/install.ps1` | Установка (venv, deps, БД, ярлык) |
| `scripts/update.ps1` | **Обновление in-place** (БД сохраняется) |
| `scripts/build_release_zip.ps1` | Zip-релиз |
| `scripts/create_desktop_shortcut.ps1` | Ярлык Lab_request |
| `scripts/init_training_folders.ps1` | Структура `data/training/` |
| `scripts/batch_extract_inbox.ps1` | Пакетное извлечение |
| `scripts/install_ollama.ps1` | Ollama (LLM opt-in) |
| `scripts/run_protocol_from_json.ps1` | Запуск внешнего protocol_generator |
| `scripts/cleanup_artifacts.ps1` | Очистка артефактов |

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -ZipPath ".\dist\request_processor_0.9.1_YYYYMMDD.zip"
```

---

## Дорожная карта

| Этап | Статус | Содержание |
|------|--------|------------|
| **0–1** | ✅ | Расчёт, GUI, SQLite, КП, заказы, mappings, human-in-the-loop |
| **1 training** | ✅ | documents, labels, families, eval, RAG registry |
| **2 OCR** | ✅ | preprocess v2, table OCR, confidence, benchmark |
| **S1–S3** | ✅ | UX Lab_request, KP styles, protocol_meta bridge |
| **S2.5** | ✅ | OCR marks demo + feedback |
| **S4** | ✅ | Программы DOCX + price match |
| **S5** | ✅ | Нормы raw_text + aliases |
| **Ops** | ✅ | install / update.ps1, prod-data, passport, FHD |
| **UI shell** | ✅ | sidebar, splash, menubar (docs: v0.10 redesign) |
| **3+** | 🔜 | Recall на сканах, больше семейств |
| **4 RAG** | 🔜 | Embeddings, поиск по ТУ/ГОСТ |
| **5 Assistant** | 🟡 | MarkCorrector в GUI; LLM opt-in (Ollama) |
| **6 Production** | 🟡 | Эксплуатация v0.9.1, polish под боевой ПК |
| **Cycle polish (27.07)** | ✅ | DOCX HITL, calc/KP/pack reliability, e2e tests, ops logs |

Карта S1–S5: [docs/ARCHITECTURE_ROADMAP.md](docs/ARCHITECTURE_ROADMAP.md).  
Журнал и планы: Obsidian `Python/Проект request-processor/` (сессия **66–68**, 2026-07-27).

---

## Документация

| Документ | Назначение |
|----------|------------|
| [INSTALL.md](INSTALL.md) | Установка на рабочий ПК |
| [docs/UPDATE.md](docs/UPDATE.md) | Обновление без сноса |
| [docs/UPDATE_WORK_PC_2026-07-21.md](docs/UPDATE_WORK_PC_2026-07-21.md) | Заметки конкретного релиза |
| [docs/44 - Паспорт…](docs/) | Паспорт и экспериментальная эксплуатация |
| [docs/UI_ARCHITECTURE.md](docs/UI_ARCHITECTURE.md) | UI: splash, sidebar, tabs |
| [docs/TEST_PROGRAMS.md](docs/TEST_PROGRAMS.md) | Программы испытаний (S4) |
| [docs/REQUIREMENTS_BASE.md](docs/REQUIREMENTS_BASE.md) | Нормы / aliases (S5) |
| [docs/PROTOCOL_GENERATOR_BRIDGE.md](docs/PROTOCOL_GENERATOR_BRIDGE.md) | JSON → protocol_generator |
| [docs/ARCHITECTURE_ROADMAP.md](docs/ARCHITECTURE_ROADMAP.md) | Карта S1–S5 |
| [docs/README.md](docs/README.md) | Индекс docs/ |
| [docs/DEV_AGENT_SETUP.md](docs/DEV_AGENT_SETUP.md) | VS Code + Grok: продуктивная работа агента |
| [AGENTS.md](AGENTS.md) | Правила для AI-агента (автозагрузка Grok) |
| **GitHub** | https://github.com/shocknik/request_processor |
| **Obsidian** | `Python/Проект request-processor/` (разработка) |

---

## Лицензия

MIT
