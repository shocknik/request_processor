# Установка на рабочий ПК (Windows) — v0.9.1

Цель: GUI **без IDE**, **прайс и правила расчёта как сейчас**, марки и организации — **с нуля** в prod.

Полная инструкция (Obsidian): **«43 - Развёртывание на рабочий ПК…»**, паспорт: **«44 - Паспорт приложения…»**.

---

## Пошаговый чеклист (рекомендуемый сценарий)

### На ПК разработчика (один раз перед переносом)

| # | Шаг | Команда / действие |
|---|-----|-------------------|
| 1 | Актуальный код / zip | `git pull` или уже есть `dist\request_processor_0.9.1_*.zip` |
| 2 | Проверить прайс в БД | GUI → «7. Справочник» / CLI: в `test_items` полный прайс |
| 3 | **Очистить только марки и организации** (прайс остаётся) | см. ниже `prepare-prod-db` |
| 4 | Собрать zip **с** подготовленной БД | `build_release_zip.ps1 -IncludeAppDb` |
| 5 | Скопировать zip на рабочий ПК | флешка / сеть |

```powershell
cd D:\My_projects\request_processor
# backup + очистка cable_marks / organizations (+ заказы/расчёты-ссылки)
.\.venv\Scripts\request-processor.exe prepare-prod-db --yes
# zip с data\app.db (прайс внутри, марки/орг. пустые)
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1 -IncludeAppDb
```

### На рабочем ПК

| # | Шаг | Детали |
|---|-----|--------|
| 1 | Python 3.10+ (лучше 3.11/3.12) | [python.org](https://www.python.org/downloads/), галочка **Add to PATH** |
| 2 | Tesseract + `rus` + `eng` | Нужен для **PDF-сканов**. Для **Word .docx** OCR не обязателен |
| 3 | Распаковать zip | например `D:\apps\request_processor` |
| 4 | Установка | `powershell -ExecutionPolicy Bypass -File scripts\install.ps1` |
| 5 | **Не** перезатирать прайс `load-data`, если в zip уже был `data\app.db` после `prepare-prod-db` | Прайс уже в БД |
| 6 | Ярлык на рабочий стол | создаётся install.ps1; вручную — см. § «Ярлык» |
| 7 | Ollama (опц.) | уже стоит: путь `C:\Users\User\.ollama\models`, модель `llama3.2` |
| 8 | 1–2 реальные заявки Word/PDF | проверить марки и организации глазами |
| 9 | Раз в неделю | **10. Настройки** → **Экспорт данных prod (zip)** → разработчику |

---

## Ярлык на рабочий стол

`install.ps1` вызывает скрипт ярлыка автоматически.

Вручную:

```powershell
cd D:\apps\request_processor
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

| | |
|--|--|
| **Имя** | «Обработка заявок на испытания кабелей» |
| **Запуск** | `.venv\Scripts\pythonw.exe -m request_processor.ui.gui` |
| **Рабочая папка** | корень проекта |
| **Иконка** | `assets\app_icon.ico` |

Альтернатива: `start_gui.bat` в корне проекта.

---

## Экран 1920×1080

Главное окно занимает **~94%** рабочей области (не «плавает» как 1200×860).  
Окно **масштабируемое**; таблицы тянутся по ширине.  
Windows DPI awareness включается при запуске (чёткий шрифт на 100–150% масштабе).

Рекомендуемое разрешение: **1920×1080** (и выше). Минимум комфортной работы: ~1366×768.

---

## Что нужно на рабочем ПК

| Компонент | Обязательно | Примечание |
|-----------|-------------|------------|
| **Python 3.10+** | ✅ | Add to PATH |
| **Прайс в БД** | ✅ | из подготовленного `app.db` **или** `load-data` |
| **Tesseract** rus+eng | для PDF-сканов | Word .docx читается без OCR |
| **Ollama** | ❌ опционально | LLM-ассистент; модель **llama3.2** |
| Zip / git clone | ✅ | |
| Экран | 1920×1080 | рекомендуется |

---

## Word (.docx) vs PDF

| Формат | Как читается | Ожидание |
|--------|--------------|----------|
| **.docx** | `python-docx`: параграфы + таблицы | **Основной и более надёжный** путь: без OCR, без «кракозябр» скана. Марки и организации из текста/таблиц. |
| **PDF с текстом** | pdfplumber | Хорошо, если PDF «настоящий», не картинка |
| **PDF-скан** | PyMuPDF → Tesseract (DPI **400**) | Хуже Word: ошибки OCR, особенно организации |

**Вывод:** если большинство заявок в Word — парсинг должен быть **лучше**, чем на сканах. Всё равно **проверяйте** заказчика/производителя и марки перед «Подтвердить заявку».

Ограничения Word:

- только **.docx** (старый **.doc** — не поддерживается; сохраните как .docx);
- сложная вёрстка / текст в фигурах / вложенные объекты могут не попасть в извлечение;
- организации всё равно иногда требуют ручной правки (роль заказчик/производитель).

---

## БД: что оставить, что очистить

| Данные | При prod |
|--------|-------------------|
| **test_items** (прайс, base_cost, правила) | **оставить** |
| **test_mappings** (фразы → испытания) | **оставить** |
| **app_settings** (климатика, LLM, пути) | **оставить** |
| **cable_marks** | **очистить** — собирать с нуля |
| **organizations** | **очистить** — собирать с нуля |
| orders / calculations / extractions | очищаются вместе (ссылки на mark/org) |

```powershell
request-processor prepare-prod-db --yes
# → backup: data\app.db.pre_prod_YYYYMMDD_HHMMSS.db
```

Правила расчёта (`fixed`, `per_core`, `per_group`, `time_based`) — **в коде**, не в «мусорных» таблицах; прайс в `test_items` определяет цены и привязку.

---

## Обновление без удаления программы

**Не сносите папку.** Используйте `scripts/update.ps1` — сохранит `data/app.db` и опыт.

Подробно: **[docs/UPDATE.md](docs/UPDATE.md)**.

```powershell
cd D:\apps\request_processor
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -ZipPath "D:\inbox\request_processor_….zip"
```

Или: распаковать новый zip **в другую папку** → `-SourceRoot` на неё.  
Backup БД: `data\backups\update_*\app.db`.

---

## Ollama на рабочем ПК (ваш путь)

Уже установлено, модели:

```
C:\Users\User\.ollama\models
```

Это **стандартный** путь Ollama на Windows (`%USERPROFILE%\.ollama\models`).

| Параметр | Значение |
|----------|----------|
| URL API | `http://127.0.0.1:11434` |
| Каталог моделей | `C:\Users\User\.ollama\models` |
| Модель | **llama3.2** → `ollama pull llama3.2` |
| Вкл/выкл | GUI → **10. Настройки** → чекбокс (по умолчанию **выкл**) |

```powershell
ollama list
ollama pull llama3.2
request-processor assistant-llm-status
```

В GUI: **Каталог моделей** = `C:\Users\User\.ollama\models` → **Проверить Ollama** → Сохранить.

LLM **не обязателен** для цикла заявка → КП → пакет.

---

## Пути Tesseract (разные ПК)

1. `TESSERACT_CMD` / `TESSERACT_PATH`  
2. PATH  
3. `tools\Tesseract-OCR\tesseract.exe`  
4. Program Files  

```powershell
[Environment]::SetEnvironmentVariable(
  "TESSERACT_CMD",
  "C:\Program Files\Tesseract-OCR\tesseract.exe",
  "User"
)
```

---

## Установка (кратко)

```powershell
cd D:\apps\request_processor
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# если app.db НЕ был в zip — один раз:
request-processor load-data --price "data\Обновленная стоимость на 2026 год.xlsx"
# ярлык (если нужно)
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
start_gui.bat
```

---

## День 1 оператора

1. **1. Заявка** → Word/PDF → **Извлечь** (сканы: DPI **400**)  
2. Марки + организации — **проверить**  
3. Ассистент 💡 — Принять / Отклонить  
4. **Подтвердить заявку**  
5. **2. Расчёт** → **3. КП** → **4. Заказы** → пакет  
6. Раз в неделю: **Экспорт данных prod** → zip разработчику  

---

## Данные prod (кратко)

| | |
|--|--|
| **Что** | zip: corrections, parse_snapshots, assistant, test_mappings_used, manifest |
| **Зачем** | перенос правок на dev без полной app.db и PDF |
| **Как** | GUI «10. Настройки» → Экспорт / CLI `export-prod-data` |
| **На dev** | `import-prod-data` + `sync-corrections` |

Подробно — заметка **44** (паспорт) и **41**.

---

## Диагностика

| Проблема | Действие |
|----------|----------|
| Word не открывается | только `.docx`, не `.doc` |
| OCR пустой на PDF | Tesseract+rus; DPI 400 |
| Ollama недоступна | запустить Ollama; URL; `ollama pull llama3.2` |
| Нет цен | `load-data` или вернуть backup БД с прайсом |
| Нет ярлыка | `create_desktop_shortcut.ps1` |

---

**Версия:** 0.9.1 · **Репозиторий:** https://github.com/shocknik/request_processor  
**Модель LLM:** llama3.2 · **Ollama models:** `%USERPROFILE%\.ollama\models`
