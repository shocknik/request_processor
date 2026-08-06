# Обновление Lab_request на рабочем ПК (без удаления программы)

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
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1
# → dist\request_processor_0.9.1_YYYYMMDD.zip
# НЕ включайте -IncludeAppDb для обновления боя (иначе соблазн перезаписать БД)
```

### Актуальный zip на work: **2026-08-06**

`dist\request_processor_0.9.1_20260806.zip` (**без** `app.db`)

Собрать на dev:

```powershell
cd D:\My_projects\request_processor
powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1
```

**В составе 06.08 (поверх 31.07 ТЗ 70 + 28.07 debt):**

| Тема | Что |
|------|-----|
| Org search | Unicode casefold: `тольят` находит «Тольяттинский…» |
| Clipboard | Ctrl+C на адресе = copy (RU/EN), не paste |
| Document field | «стоимостью» не считается ТУ/СТО |
| Марки / OCR | lookalike UТР→UTP, РVС→PVC; ЕВНЕ→FRHF; КСВПП/КССПП; LAN Cat 6 PVC нг… до размера |
| Extract | table + full text для DOCX direction; lexicon расширения |
| Старт | splash раньше; метрики `t_pre_splash` / `t_import`; bat-сообщение; без ico с UNC |
| Чеклист | `docs/CHECKLIST_TZ70_OPERATOR.md` (org filter, Ctrl+C, марки 06.08) |
| Тесты | ~322 passed |

**Ранее в той же линии 0.9.1:**

| Дата | Zip / тема |
|------|------------|
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
  -ZipPath "$env:TEMP\request_processor_0.9.1_20260806.zip"
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
