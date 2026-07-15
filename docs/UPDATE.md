# Обновление Lab_request на рабочем ПК (без удаления программы)

**Цель:** поставить новую версию **поверх** текущей установки, сохранив:

| Сохраняем | Не трогаем |
|-----------|------------|
| `data/app.db` (заказы, прайс, программы, марки…) | `.venv` переиспользуем (только pip) |
| `data/training/corrections` | ярлык обновляем |
| `data/generated`, `logs`, `ocr_cache` | |
| `data/lab_profile.yaml` | |
| battle exports / snapshots | |

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

Скопируйте zip на рабочий ПК (флешка / сеть).

### На рабочем ПК

1. **Закройте** Lab_request (GUI).
2. Положите zip, например: `D:\inbox\request_processor_….zip`
3. Текущая установка, например: `D:\apps\request_processor`

```powershell
cd D:\apps\request_processor
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -ZipPath "D:\inbox\request_processor_0.9.1_20260715.zip"
```

Или если уже распаковали рядом:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -SourceRoot "D:\inbox\request_processor_0.9.1"
```

4. Запуск: ярлык **Lab_request** или `start_gui.bat`.

Backup БД автоматически:  
`data\backups\update_YYYYMMDD_HHMMSS\app.db`

---

## Через git (если на рабочем есть git)

```powershell
cd D:\apps\request_processor
git pull
.\.venv\Scripts\python.exe -m pip install -e ".[cv]"
.\.venv\Scripts\request-processor.exe migrate-db
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

`data/` в git **не** хранится — pull не затрёт БД.

---

## Чего НЕ делать

| Действие | Почему плохо |
|----------|----------------|
| Удалить всю папку и поставить заново | Потеряете `app.db` без бэкапа |
| Распаковать zip **поверх** с заменой `data\app.db` | Затрёте боевую БД, если в zip был IncludeAppDb |
| Копировать dev-`app.db` на бой | Грязные марки/тестовые заказы |
| `prepare-battle-db` на боевой БД «просто так» | Сотрёт заказы/марки |

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

*Не путать с battle-experience zip — тот переносит **опыт** (corrections), а не код.*
