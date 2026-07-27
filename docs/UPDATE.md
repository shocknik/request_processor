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

Актуальный релиз **2026-07-27:** `dist\request_processor_0.9.1_20260727.zip`  
(calc filter, extract Queue, DOCX perf, prod-hot marks).  
На work: положить в `W:\inbox\`, затем `scripts\update.ps1 -ZipPath …`.

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
  -ZipPath "$env:TEMP\request_processor_0.9.1_20260715.zip"
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
