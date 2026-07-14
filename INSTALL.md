# Установка на рабочий ПК (Windows)

Цель: запустить GUI **без** среды разработчика (IDE, исходников в голове).

## Что нужно

1. **Python 3.10+** (лучше 3.11/3.12) — [python.org](https://www.python.org/downloads/), галочка *Add to PATH*
2. **Tesseract OCR** с языками `rus` + `eng`  
   - системно: [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)  
   - или portable: `tools/Tesseract-OCR/tesseract.exe` (см. `tools/README.md`)
3. Этот проект (git clone **или** zip-релиз из `scripts/build_release_zip.ps1`)

## Установка (один скрипт)

```powershell
cd D:\apps\request_processor   # ваш путь
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Скрипт:

- создаёт `.venv`
- ставит зависимости (включая OpenCV-preprocess; **без** тяжёлого PyTorch)
- создаёт `data/…`
- инициализирует БД
- кладёт ярлык «Испытания кабелей» на рабочий стол

Опционально EasyOCR/torch (эксперимент, обычно **хуже** Tesseract):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -WithOcrExtra
```

## Запуск

- `start_gui.bat`
- или ярлык на рабочем столе
- или `.venv\Scripts\request-processor-gui.exe`

## День 1 оператора

| Шаг | Действие |
|-----|----------|
| 1 | Вкладка **1. Заявка** → Обзор → PDF/Word → **Извлечь** |
| 2 | DPI для сканов: **400** (по умолчанию) |
| 3 | Проверить марки; **Ассистент** — автоправки OCR; при речи заказчика — **Текст…** |
| 4 | **Подтвердить заявку** |
| 5 | **2. Расчёт** → выбрать испытания → рассчитать |
| 6 | **3. КП** → сформировать |
| 7 | **4. Заказы** → **Сформировать заявку** / **Пакет документов** (заявка + КП + макет протокола) |

### Важно

- **torch-CV / EasyOCR** — только эксперимент (A/B: заметно хуже default на наших сканах)
- CLI (`request-processor …`) остаётся для eval/migrate/агента — основной UX в GUI
- Правки оператора пишутся в corrections → обучение «в бою»

## Сборка zip для другого ПК (на машине разработчика)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1
```

Архив: `dist/request_processor_<version>_YYYYMMDD.zip`  
На целевом: распаковать → `scripts\install.ps1`.

## North Star (куда идём)

**Вход:** текст/речь, оф. документ, запрос по ТУ  
**Выход:** заявка по форме, расчёт/КП, тех. комплект, макет протокола  

Сейчас v0.9: полный цикл до пакета + ассистент + свободный текст.  
Выдержки из ТУ/ПМИ и «толстый» RAG — следующие итерации.
