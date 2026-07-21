# Обновление Lab_request на рабочем ПК (2026-07-21)

**Zip:** `dist/request_processor_0.9.1_20260721.zip` (собрать заново: `scripts\build_release_zip.ps1`)  
**GitHub:** https://github.com/shocknik/request_processor · `main`  
**Полная инструкция:** [UPDATE.md](./UPDATE.md)

---

## Что нового в этом обновлении

| Область | Изменение |
|---------|-----------|
| Организации | Заказчик/производитель пишутся при «Подтвердить»; fuzzy-дедуп; «+ Добавить» |
| Направления ИК | Орган сертификации (ФаерЛаб) → заказчик; Кабель-Тест = lab_profile |
| Данные prod | Экспорт/импорт zip: `export-prod-data` / GUI Настройки |
| OCR | Нет EasyOCR → fallback Tesseract; галочка PyTorch снимается при ошибке |
| S2.5 | Настройки → «S2.5 Демо: 3 OCR-марки» |
| UI | Sidebar + обновлённая страница Заявки (если ещё не ставили) |

---

## Шаги на рабочем ПК

1. **Закрыть** Lab_request.  
2. Скопировать zip на локальный путь с правами (например `%TEMP%` или Рабочий стол).  
   Не из `W:\inbox`, если был Access Denied.  
3. Установка, например `W:\request_processor`:

```powershell
cd W:\request_processor
powershell -ExecutionPolicy Bypass -File scripts\update.ps1 `
  -ZipPath "$env:TEMP\request_processor_0.9.1_20260721.zip"
```

4. При необходимости ярлык:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
```

5. Запуск → чеклист:

- [ ] GUI стартует (Lab_request)  
- [ ] Прайс ~61 позиция  
- [ ] Заказы на месте (БД не затёрта)  
- [ ] Настройки → **Данные prod** / S2.5 демо  
- [ ] Одна тестовая заявка .docx → confirm → org в справочнике  

## Не делать

| Действие | Почему |
|----------|--------|
| `prepare-prod-db` на живой БД | Сотрёт заказы, марки, org |
| Подменить `data\app.db` из zip | Потеряете prod-данные |
| Ставить zip поверх без `update.ps1` | Можно затереть data |

## После работы (раз в неделю)

```powershell
cd W:\request_processor
.\.venv\Scripts\request-processor.exe export-prod-data --full --note "после update 21.07"
```

Zip → на ПК разработчика → `import-prod-data`.
