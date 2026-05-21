# Налаштування: Cursor сам оновлює звіт LOKO

Щоб після правок у Cursor **не** натискати Actions → Run workflow, потрібен **одноразовий** локальний доступ до Databricks і git push.

## Що ви робите один раз

### 1. Файл `.env` (секрети лише на вашому Mac)

```bash
cd "Reports/LOKO/MBR"
cp .env.example .env
```

Відкрийте `.env` і підставте **справжній** Databricks PAT (не рядок `your_databricks_pat_here` з прикладу):

```
DATABRICKS_HOST=bolt-common.cloud.databricks.com
DATABRICKS_TOKEN=dapixxxxxxxx...
DATABRICKS_WAREHOUSE_ID=b39957853740b21d
DATABRICKS_TLS_NO_VERIFY=1
```

Токен: Databricks → **User Settings** → **Developer** → **Access tokens** → **Generate new token** (довгий, починається з `dapi`).

Файл `.env` **не потрапляє в git** (див. `.gitignore`).

### 2. Python-залежності

```bash
pip3 install -r requirements.txt
```

### 3. Права на push у GitHub

Папка `Reports/LOKO/MBR` — клон `loko-mbr-report`. Переконайтесь, що `git push` працює без пароля щоразу (SSH або GitHub CLI / credential manager):

```bash
cd "Reports/LOKO/MBR"
git remote -v
git push origin main
```

Якщо push питає логін — налаштуйте [SSH key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh) або `gh auth login`.

### 4. Дозвіл скрипту (один раз)

```bash
chmod +x publish.sh
```

### 5. Помилка SSL на Mac (`CERTIFICATE_VERIFY_FAILED`)

Якщо `publish.sh` падає з `self-signed certificate in certificate chain` (часто через корпоративний VPN/проксі), додайте в `.env`:

```
DATABRICKS_TLS_NO_VERIFY=1
```

Це лише для **локального** Mac. GitHub Actions цього не потребує.

### 6. Перевірка вручну

```bash
./publish.sh
```

Якщо скрипт завершився без помилок — відкрийте  
https://mykhailobrynchak-dev.github.io/loko-mbr-report/  
і оновіть сторінку (**Cmd+Shift+R**).

---

## Що робить Cursor після цього

Правило `.cursor/rules/loko-mbr-report.mdc` зобов’язує агента після **будь-яких** змін у звіті LOKO:

1. Правити файли в **`Reports/LOKO/MBR/`**
2. Запускати **`./publish.sh`** (генерація + push)
3. Не просити вас Run workflow

Вам достатньо написати, наприклад: *«Онови звіт LOKO»* — агент сам виконає publish.

---

## Два канали оновлення (не конфліктують)

| Канал | Коли |
|--------|------|
| **Cursor + `publish.sh`** | Після ваших правок / запитів до агента |
| **GitHub Actions (понеділок)** | Автоматично о 08:00 — свіжі дані з Databricks |

Run workflow вручну **більше не потрібен**, якщо `publish.sh` працює.

---

## Якщо агент не публікує

- Немає `.env` → створіть з `.env.example`
- `git push` failed → налаштуйте SSH / `gh auth`
- Databricks помилка → перевірте token і warehouse id
