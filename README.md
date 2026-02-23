# Domain Monitor — Email + Telegram notifications (EN/RU)

This app checks domain expiration via **WHOIS**, stores your list in `domains.json`, and can send notifications:
- **Email (SMTP)**
- **Telegram**

✅ **Default language:** English (can be changed to Russian in Settings).

---

## How notifications work

When a WHOIS check is executed, the app:
1) updates `expiry` and `days_left` for each domain;
2) if a domain has `days_left ≤ threshold` (default 30 days) — it sends notifications.

Anti-spam: a domain is notified **max once per day** (`last_notified` field in `domains.json`).

---

## Automation options

### Option A — Daily auto-check inside the app (GUI)

Open **Settings → Automation** and enable **daily auto-check** + set the time.

⚠️ The app must be **running** for this option.

### Option B — Windows Task Scheduler (recommended)

This option works even when the app is **not running**.

1) `Win + R` → `taskschd.msc`
2) Create a task (daily)
3) Action: **Start a program**
   - **Program/script:** path to `domain_monitor.exe`
   - **Add arguments:** `--check`
   - **Start in:** folder where the EXE is located

If you run via Python:
- Program/script: `C:\\Path\\python.exe`
- Add arguments: `C:\\Path\\domain_monitor.py --check`
- Start in: `C:\\Path\\`

In `--check` mode the app runs one WHOIS check, sends notifications and exits.
A log file is written: `domain_monitor.log`.

---

## Configuration

Use **Settings** and fill:
- Notification threshold
- Email SMTP settings
- Telegram bot token + chat ID

Settings are saved to `settings.json` next to the script/EXE.

### Telegram: get chat_id

1) Create a bot via `@BotFather` and get `bot_token`.
2) Send a message to your bot.
3) Open in browser:

```text
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```

Find `chat: { id: ... }`.

---

## Files

- `domains.json` — your domain list
- `settings.json` — your settings (contains secrets)

Both are saved **next to** `domain_monitor.py` (or next to the EXE).

---

# RU (Кратко)

Приложение проверяет домены по WHOIS и умеет слать уведомления в **Email** и **Telegram**.

## Автоматизация

- **Автопроверка внутри программы**: Settings → Automation (нужно, чтобы программа была запущена).
- **Планировщик Windows (рекомендовано)**: запускать `domain_monitor.exe --check` 1 раз в день.

Лог: `domain_monitor.log`.

## Важно

`settings.json` хранит пароль SMTP и токен Telegram — **не коммитьте** его в GitHub.
