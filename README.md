# LOKO від Сільпо — MBR (Bolt Food UA)

**Live (GitHub Pages):** https://mykhailobrynchak-dev.github.io/loko-mbr-report/

Ця папка — **публічний репозиторій** `loko-mbr-report`. Після змін у `template.html` / `generate_report.py` агент (або ви) має:

1. Запустити `python generate_report.py` (потрібні змінні Databricks).
2. Закомітити й **push** `index.html` (+ `report_data.json`, якщо змінився) у `main`.

Тоді оновлення сторінки в браузері покаже новий звіт (як у CAFE RYNOK / HOP HEY).

## Файли

| Файл | Призначення |
|------|-------------|
| `index.html` | Готовий звіт на GitHub Pages |
| `template.html` | HTML-шаблон |
| `generate_report.py` | SQL → Databricks → `index.html` |
| `report_data.json` | JSON-дані (генерується скриптом) |

## Локальний перегляд

```bash
pip install -r requirements.txt
export DATABRICKS_HOST="..."
export DATABRICKS_TOKEN="..."
export DATABRICKS_WAREHOUSE_ID="..."
python generate_report.py
open index.html
```

## Автоматичне оновлення даних

Щопонеділка о 08:00 (Київ) — workflow у цьому репо (потрібні Secrets: `DATABRICKS_*`).

## Дубль у QBR Engine

Копія коду також є в `Reports/QBR Engine/loko/` для спільного workflow усіх брендів. **Джерело правди для публікації — ця папка (`Reports/LOKO/MBR`).**
