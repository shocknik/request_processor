# tools/

Внешние бинарники для рабочего ПК (не коммитятся в git как exe).

## Tesseract OCR (обязателен для сканов)

Положите portable-сборку сюда:

```
tools/Tesseract-OCR/tesseract.exe
tools/Tesseract-OCR/tessdata/rus.traineddata
tools/Tesseract-OCR/tessdata/eng.traineddata
```

Либо установите системно:

- https://github.com/UB-Mannheim/tesseract/wiki  
- пути: `C:\Program Files\Tesseract-OCR\tesseract.exe`

Приложение ищет tesseract в таком порядке: `PATH` → `tools/Tesseract-OCR` → Program Files.

## Рекомендации

- Default OCR: **Tesseract**, DPI сканов **400**
- EasyOCR / PyTorch — opt-in в GUI («torch-CV эксперимент»), на текущих A/B хуже Tesseract
