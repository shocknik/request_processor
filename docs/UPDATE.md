# Обновление Lab_request на рабочем ПК (без удаления программы)

**2026-10-12.** Ближайший перенос на IDM23060 — не этот сценарий. Диск `W:` после замены серверов ненадёжен, обновление поверх старой папки не делаем. Ставим заново в `C:\Lab_request` набором `dist\Lab_request_на_диск_C` (папка в git не хранится). Порядок для агента: [`AGENT_NEXT.md`](AGENT_NEXT.md). Ниже — как обновлять уже стоящую локальную копию, когда она есть.

**Цель:** поставить новую версию **поверх** текущей установки, сохранив:

| Сохраняем | Не трогаем |
|-----------|------------|
| `data/app.db` (заказы, прайс, программы, марки…) | `.venv` переиспользуем (только pip) |
| `data/training/corrections` | ярлык обновляем |
| `data/generated`, `logs`, `ocr_cache` | |
| `data/lab_profile.yaml` | |
| field data exports / snapshots | |

| Обновляем | |
|-----------|--|
| `src/`, `scripts/`, `docs/`, `tests/` | код |
| `pyproject.toml`, зависимости | `pip install -e .` |
| `data/templates`, `data/families` | merge |
| схема БД | `migrate-db` (новые таблицы, без wipe) |

---

## Рекомендуемый способ (zip)

### На dev

```powershell
cd D:\My_projects\request_processor
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1 -Slim
# → dist\request_processor_0.9.1_YYYYMMDD.zip (без tests и скриптов ТУ/Ollama)
# НЕ включайте -IncludeAppDb для обновления боя (иначе соблазн перезаписать БД)
```

### Актуальный zip на work: **2026-09-30**

`dist\request_processor_0.9.1_20260930.zip` (**без** `app.db`)

Собрать на dev (для рабочего ПК — `-Slim`, без pytest и скриптов ТУ/Ollama):

```powershell
cd D:\My_projects\request_processor
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1 -Slim
```

**Не ставить** старый `dist\request_processor_0.9.1_20260918.zip`: в нём письмо схлопывалось до уникальных марок, а `start_gui.bat` не умел сетевой путь без буквы диска.

**В составе 30.09 (feedback work 23–28.09, поверх 18.09):**

| Тема | Что |
|------|-----|
| Письмо | Строки заявки = пункты документа, в том же порядке, **включая одинаковые марки** с разным метражом. №1610 — 7 строк, не 2 |
| OCR | `НЕ` / `НF` → `HF`, `Cat Se` → `5e`, три написания КСБ → `КСБнг(А)-FRHF …`. Мусорные двойники в таблицу не попадают |
| Метраж | Колонка «Метраж» у строки («272 м, 100 м (проверочная бухта)») |
| Справочник | `cable_marks` по-прежнему без дублей: повтор в заявке не создаёт вторую карточку |
| Запуск | `start_gui.bat`: `pushd` вместо `cd /d` (сетевая папка `\\server\…`), кодировка консоли UTF-8, чтобы фраза «запуск…» читалась |
| Оценка снимка | Пока в списке есть `НЕ` или `КСБннг`, качество не ставится 1.0 |
| Из 18.09 | UNIQUE Спецкабеля и честный текст ошибки, логин не в подсказках, колонка № и копирование марки, нет зоны «перетащите», статусы журнала, склейка оптики `СП-\|` + `ОКС`, подсказка пометить базу `[WORK]` |

Журнал на work после установки: залипание полей (#1) можно отметить «сделано». Копирование марки (#2 и #13) — только когда оператор увидит его на IDM23060. Порядок письма (#12) не отмечать заранее формулировкой «двойников схлопнули».

**Ранее в той же линии 0.9.1:**

| Дата | Zip / тема |
|------|------------|
| 18.09 | UNIQUE org, оптика `СП-\|ОКС`, колонка №, журнал. **Не ставить:** письмо схлопывалось до 2 марок, `cd /d` на UNC |
| 14.08 | Combobox, КУНРС/СП-ОК, path-hint, empty KP, .doc |
| 06.08 | org filter, Ctrl+C, марки OCR/lexicon, splash, ~322 tests |
| 31.07 | ТЗ 70: free-text bg_job, org HITL, редактор марок, dual logs, feedback journal |
| 28.07 | `bg_job`/`modal`, org-адреса без cross-factory, `db-role`, ~283 tests |
| 27.07 | DOCX full text, HITL cycle, pack logs, e2e |

На work: zip → `W:\inbox\` (или `%TEMP%`) → `scripts\update.ps1 -ZipPath …` (**не** подменять `data\app.db`).  
После update: `request-processor db-role --set work --source "рабочий ПК"` (если ещё `[DEV]`).  
Прогон: [CHECKLIST_TZ70_OPERATOR.md](./CHECKLIST_TZ70_OPERATOR.md).

Скопируйте zip на рабочий ПК (флешка / сеть).

### На рабочем ПК

1. **Закройте** Lab_request (GUI).
2. Положите zip туда, **куда у вас есть полный доступ**:
   - **На work (IDM23060):** надёжный вариант — `W:\inbox\request_processor_….zip` (путь, с которого update 23.07 завершился OK).  
     `D:\inbox\…` на этом ПК может **не** открываться — скрипт стартует, но zip не читается.
   - Альтернативы: `%TEMP%`, Рабочий стол, или рядом с установкой (`W:\request_processor\_update.zip`).
   - Если `Test-Path` / обновление пишет **«Отказано в доступе»** — zip в папке без прав; переложите на локальный/`W:\inbox`.
3. Текущая установка, например: `W:\request_processor` или `D:\apps\request_processor`

```powershell
cd W:\request_processor_0.9.1
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -ZipPath "W:\inbox\request_processor_0.9.1_20260930.zip"
```

Или если уже распаковали рядом (надёжнее при проблемах с сетью):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -SourceRoot "C:\Users\ВАШ_ЛОГИН\Desktop\request_processor_0.9.1"
```

4. Запуск: ярлык **Lab_request** или `start_gui.bat`.

Backup БД автоматически:  
`data\backups\update_YYYYMMDD_HHMMSS\app.db`

---

## Через git

Репозиторий: https://github.com/shocknik/request_processor · ветка `main`.  
`data/` / `app.db` в git **не** хранятся — pull не затрёт рабочую БД.

### Уже есть `.git` в папке установки

```powershell
cd W:\request_processor_0.9.1
git pull
.\.venv\Scripts\python.exe -m pip install -e ".[cv]"
.\.venv\Scripts\request-processor.exe migrate-db
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

### На рабочем ПК git есть, но репозитория ещё нет (поставили из zip)

**Вариант A (безопаснее):** клон рядом → `update.ps1 -SourceRoot`:

```powershell
cd $env:USERPROFILE\Desktop
git clone https://github.com/shocknik/request_processor.git request_processor_src
cd W:\request_processor_0.9.1
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -SourceRoot "$env:USERPROFILE\Desktop\request_processor_src"
```

Повторно: `git pull` в `request_processor_src`, снова `update.ps1 -SourceRoot …`.

**Вариант B:** `git init` + `remote` + `checkout -f -B main origin/main` **внутри** папки установки (осторожно; сначала backup `data\app.db`).  
Полный разбор (access denied, install vs update, in-place git): Obsidian **«51 - Обновление…»**.

---

## Чего НЕ делать

| Действие | Почему плохо |
|----------|----------------|
| Удалить всю папку и поставить заново | Потеряете `app.db` без бэкапа |
| Распаковать zip **поверх** с заменой `data\app.db` | Затрёте рабочую БД, если в zip был IncludeAppDb |
| Копировать dev-`app.db` на рабочий ПК | Грязные марки/тестовые заказы |
| `prepare-prod-db` на рабочей БД «просто так» | Сотрёт заказы/марки |

---

## Роли БД: dev / work_copy / work

Файл по умолчанию `data/app.db`. Метка — `data/db_profile.local.yaml`  
(другие `*.db` → `*.db.profile.yaml`; см. `docs/db_profile.example.yaml`, версии — `docs/VERSIONING.md`).

| Роль | Назначение |
|------|------------|
| `dev` | Тестовая на ПК разработки — **не** источник истины |
| `work_copy` | Копия с рабочего ПК на dev — данные оператора авторитетны |
| `work` | Боевая БД на рабочем ПК |

```powershell
request-processor db-info
# на dev после привоза БД с работы:
request-processor db-role --set work_copy --source "рабочий ПК YYYY-MM-DD"
```

GUI показывает роль в заголовке окна. Без метки приложение считает БД тестовой.

---

## Откат

1. Восстановить `data\backups\update_…\app.db` → `data\app.db`  
2. При необходимости вернуть предыдущий zip через `update.ps1` снова.

---

## Чеклист после обновления

- [ ] GUI стартует (Lab_request)  
- [ ] Заказы / прайс на месте  
- [ ] `migrate-db` без ошибок (в логе / консоли update)  
- [ ] Новые вкладки/кнопки видны (Программы, JSON протокола, Журнал…)  
- [ ] При сбое — `start_gui_debug.bat`  

---

## Связанные скрипты

| Скрипт | Роль |
|--------|------|
| `scripts/install.ps1` | **первая** установка |
| `scripts/update.ps1` | **обновление** на месте |
| `scripts/build_release_zip.ps1` | сборка zip на dev |
| `scripts/create_desktop_shortcut.ps1` | Lab_request.lnk |

---

*Не путать с zip данных prod (`export-prod-data`) — тот переносит **corrections/snapshots**, а не код.*
