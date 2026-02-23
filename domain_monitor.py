"""Domain Monitor

Monitors domain expiration via WHOIS, stores the list in domains.json
and can send notifications via Email (SMTP) and Telegram.

Two ways to automate:
- Keep the GUI app running and enable daily auto-check at a specified time.
- Use Windows Task Scheduler (or cron) to run one check and exit:
    domain_monitor(.exe) --check

Files are stored next to this script (or next to the EXE when bundled).
"""

from __future__ import annotations

import json
import os
import re
import smtplib
import ssl
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import urllib.error


# -----------------------------
# Headless mode flag (for Task Scheduler / cron)
# -----------------------------
HEADLESS_MODE = "--check" in sys.argv


# -----------------------------
# Optional dependencies
# -----------------------------
try:
    import whois  # type: ignore
except ImportError:
    whois = None

try:
    from openpyxl import Workbook  # type: ignore
except ImportError:
    Workbook = None


# Tkinter is only needed for GUI mode
if not HEADLESS_MODE:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog


# -----------------------------
# Paths
# -----------------------------

def get_app_dir() -> str:
    """Return app directory.

    - When bundled with PyInstaller (frozen) -> folder where .exe lives
    - When running as .py -> folder where this file lives
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()
DATA_FILE = os.path.join(APP_DIR, "domains.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
LOG_FILE = os.path.join(APP_DIR, "domain_monitor.log")


# -----------------------------
# i18n
# -----------------------------

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # App
        "app_title": "Domain Monitor",
        "label_domain": "Domain:",
        "label_link": "Link:",
        "label_login": "Login:",
        "label_password": "Password:",
        "btn_add_update": "Add/Update domain",
        "btn_check": "Check domains (WHOIS)",
        "btn_sort": "Sort by expiry date",
        "btn_settings": "Settings",
        "btn_export": "Export to Excel",
        "btn_delete": "Delete selected",
        "btn_save": "Save list",
        # Columns
        "col_domain": "Domain",
        "col_link": "Link",
        "col_login": "Login",
        "col_password": "Password",
        "col_expiry": "Expiry date",
        "col_days_left": "Days left",
        # Status
        "status_checking": "Checking domains (WHOIS)...",
        "status_done": "Done.",
        "status_scheduled": "Next auto-check: {dt}",
        "status_autocheck_running": "Auto-check is running...",
        # Common titles
        "title_saved": "Saved",
        "title_error": "Error",
        "title_warning": "Warning",
        "title_export": "Export",
        "title_notifications": "Notifications",
        # Messages
        "msg_domains_saved": "Domain list saved.\nFile: {file}",
        "msg_save_failed": "Failed to save file: {err}",
        "msg_settings_saved": "Settings saved.\nFile: {file}",
        "warn_domain_empty": "Field 'Domain' cannot be empty.",
        "err_whois_missing": "Module 'python-whois' is not installed.\nInstall: pip install python-whois",
        "err_openpyxl_missing": "Module 'openpyxl' is not installed.\nInstall: pip install openpyxl",
        "msg_export_empty": "Domain list is empty.",
        "msg_export_saved": "File saved:\n{file}",
        "msg_export_failed": "Failed to save file: {err}",
        "unknown": "Unknown",
        "error_prefix": "Error: {err}",
        # Settings window
        "settings_title": "Settings",
        "tab_general": "General",
        "tab_notifications": "Notifications",
        "tab_automation": "Automation",
        "language_label": "Language:",
        "language_en": "English",
        "language_ru": "Russian",
        "notify_threshold_label": "Notify when days left ≤",
        # Email
        "email_frame": "Email (SMTP)",
        "email_enabled": "Enable email notifications",
        "smtp_server": "SMTP server:",
        "smtp_port": "Port:",
        "smtp_tls": "TLS (STARTTLS)",
        "smtp_ssl": "SSL",
        "smtp_user": "Username:",
        "smtp_pass": "Password:",
        "smtp_from": "From:",
        "smtp_to": "To (comma-separated):",
        "btn_test_email": "Test Email",
        # Telegram
        "tg_frame": "Telegram",
        "tg_enabled": "Enable Telegram notifications",
        "tg_token": "Bot token:",
        "tg_chat": "Chat ID:",
        "btn_test_tg": "Test Telegram",
        # Automation
        "auto_enabled": "Enable daily auto-check inside app",
        "auto_time": "Time (HH:MM):",
        "scheduler_help_title": "Windows Task Scheduler (optional)",
        # Buttons
        "btn_save_settings": "Save",
        "btn_close": "Close",
        # Validation
        "err_threshold": "Threshold must be an integer ≥ 0.",
        "err_port": "SMTP port must be an integer > 0.",
        "warn_ssl_tls": "Both SSL and TLS are enabled. Usually you choose only one. Save anyway?",
        "warn_email_disabled": "Email notifications are disabled.",
        "warn_tg_disabled": "Telegram notifications are disabled.",
        "err_time_format": "Time must be in HH:MM format (00:00–23:59).",
        # Tests
        "test_email_subject": "Test: Domain Monitor",
        "test_email_body": "This is a test message.\nIf you received it — SMTP is configured correctly.",
        "test_tg_text": "Test: Domain Monitor\nIf you see this — Telegram is configured correctly.",
        "msg_test_email_sent": "Test email sent.",
        "msg_test_tg_sent": "Test message sent.",
        "err_test_email": "Failed to send test email:\n{err}",
        "err_test_tg": "Failed to send test message:\n{err}",
        # Notifications
        "notif_subject": "Domain Monitor: domains expiring soon",
        "notif_header": "Domain Monitor: {count} domain(s) expiring in ≤ {threshold} day(s).",
        "notif_line": "- {domain} — expires {expiry} (in {days_left} day(s))",
        "notif_checked_at": "Checked at: {dt}",
        "notif_sent": "Notifications sent via: {channels}",
        "notif_partial_fail": "Failed to send some notifications:\n{errors}",
    },
    "ru": {
        # App
        "app_title": "Монитор доменов",
        "label_domain": "Домен:",
        "label_link": "Ссылка:",
        "label_login": "Логин:",
        "label_password": "Пароль:",
        "btn_add_update": "Добавить/обновить домен",
        "btn_check": "Проверить домены (WHOIS)",
        "btn_sort": "Отсортировать по дате окончания",
        "btn_settings": "Настройки",
        "btn_export": "Экспорт в Excel",
        "btn_delete": "Удалить выбранный",
        "btn_save": "Сохранить список",
        # Columns
        "col_domain": "Домен",
        "col_link": "Ссылка",
        "col_login": "Логин",
        "col_password": "Пароль",
        "col_expiry": "Дата окончания",
        "col_days_left": "Дней до конца",
        # Status
        "status_checking": "Проверяю домены (WHOIS)...",
        "status_done": "Готово.",
        "status_scheduled": "Следующая автопроверка: {dt}",
        "status_autocheck_running": "Идёт автопроверка...",
        # Common titles
        "title_saved": "Сохранено",
        "title_error": "Ошибка",
        "title_warning": "Внимание",
        "title_export": "Экспорт",
        "title_notifications": "Уведомления",
        # Messages
        "msg_domains_saved": "Список доменов сохранён.\nФайл: {file}",
        "msg_save_failed": "Не удалось сохранить файл: {err}",
        "msg_settings_saved": "Настройки сохранены.\nФайл: {file}",
        "warn_domain_empty": "Поле 'Домен' не может быть пустым.",
        "err_whois_missing": "Модуль 'python-whois' не установлен.\nУстановите: pip install python-whois",
        "err_openpyxl_missing": "Модуль 'openpyxl' не установлен.\nУстановите: pip install openpyxl",
        "msg_export_empty": "Список доменов пуст.",
        "msg_export_saved": "Файл успешно сохранён:\n{file}",
        "msg_export_failed": "Не удалось сохранить файл: {err}",
        "unknown": "Неизвестно",
        "error_prefix": "Ошибка: {err}",
        # Settings window
        "settings_title": "Настройки",
        "tab_general": "Общие",
        "tab_notifications": "Уведомления",
        "tab_automation": "Автоматизация",
        "language_label": "Язык:",
        "language_en": "English",
        "language_ru": "Русский",
        "notify_threshold_label": "Порог уведомления (дней до окончания) ≤",
        # Email
        "email_frame": "Email (SMTP)",
        "email_enabled": "Включить email-уведомления",
        "smtp_server": "SMTP сервер:",
        "smtp_port": "Порт:",
        "smtp_tls": "TLS (STARTTLS)",
        "smtp_ssl": "SSL",
        "smtp_user": "Логин:",
        "smtp_pass": "Пароль:",
        "smtp_from": "От (From):",
        "smtp_to": "Кому (To), через запятую:",
        "btn_test_email": "Тест Email",
        # Telegram
        "tg_frame": "Telegram",
        "tg_enabled": "Включить Telegram-уведомления",
        "tg_token": "Bot token:",
        "tg_chat": "Chat ID:",
        "btn_test_tg": "Тест Telegram",
        # Automation
        "auto_enabled": "Включить ежедневную автопроверку в приложении",
        "auto_time": "Время (HH:MM):",
        "scheduler_help_title": "Планировщик заданий Windows (необязательно)",
        # Buttons
        "btn_save_settings": "Сохранить",
        "btn_close": "Закрыть",
        # Validation
        "err_threshold": "Порог уведомления должен быть целым числом ≥ 0.",
        "err_port": "SMTP порт должен быть целым числом > 0.",
        "warn_ssl_tls": "Одновременно включены SSL и TLS. Обычно выбирают что-то одно. Сохранить как есть?",
        "warn_email_disabled": "Email-уведомления выключены.",
        "warn_tg_disabled": "Telegram-уведомления выключены.",
        "err_time_format": "Время должно быть в формате HH:MM (00:00–23:59).",
        # Tests
        "test_email_subject": "Тест: Монитор доменов",
        "test_email_body": "Это тестовое сообщение.\nЕсли вы его получили — SMTP настроен правильно.",
        "test_tg_text": "Тест: Монитор доменов\nЕсли вы это видите — Telegram настроен правильно.",
        "msg_test_email_sent": "Тестовое письмо отправлено.",
        "msg_test_tg_sent": "Тестовое сообщение отправлено.",
        "err_test_email": "Не удалось отправить тестовое письмо:\n{err}",
        "err_test_tg": "Не удалось отправить тестовое сообщение:\n{err}",
        # Notifications
        "notif_subject": "Монитор доменов: домены скоро истекают",
        "notif_header": "Монитор доменов: найдено {count} домен(ов) с окончанием ≤ {threshold} дн.",
        "notif_line": "- {domain} — истекает {expiry} (через {days_left} дн.)",
        "notif_checked_at": "Дата проверки: {dt}",
        "notif_sent": "Уведомления отправлены: {channels}",
        "notif_partial_fail": "Не удалось отправить часть уведомлений:\n{errors}",
    },
}


def tr(lang: str, key: str, **kwargs: Any) -> str:
    """Translate a key using the selected language (fallback to English)."""
    lang_map = TRANSLATIONS.get(lang) or TRANSLATIONS["en"]
    text = lang_map.get(key) or TRANSLATIONS["en"].get(key) or key
    try:
        return text.format(**kwargs) if kwargs else text
    except Exception:
        # If placeholders mismatch, return raw to avoid crashing
        return text


# -----------------------------
# Settings / data
# -----------------------------

DEFAULT_SETTINGS: Dict[str, Any] = {
    "language": "en",  # default UI + notifications language
    "notify_days_threshold": 30,
    "automation": {
        "auto_check_enabled": False,
        "auto_check_time": "09:00",  # HH:MM
    },
    "email": {
        "enabled": False,
        "smtp_server": "",
        "smtp_port": 587,
        "use_tls": True,
        "use_ssl": False,
        "username": "",
        "password": "",
        "from_addr": "",
        "to_addrs": [],
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
    },
}


def deep_merge(base: Dict[str, Any], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge patch into base (recursive for dicts)."""
    result = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_json(path: str, default: Any) -> Any:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_domains() -> List[Dict[str, Any]]:
    data = load_json(DATA_FILE, [])
    return data if isinstance(data, list) else []


def save_domains(domains: List[Dict[str, Any]]) -> None:
    save_json(DATA_FILE, domains)


def load_settings() -> Dict[str, Any]:
    user = load_json(SETTINGS_FILE, {})
    if not isinstance(user, dict):
        user = {}
    return deep_merge(DEFAULT_SETTINGS, user)


def save_settings(settings: Dict[str, Any]) -> None:
    save_json(SETTINGS_FILE, settings)


# -----------------------------
# Helpers
# -----------------------------

def normalize_domain_for_whois(raw: str) -> str:
    """Normalize user input to a bare domain for WHOIS."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = parsed.netloc or parsed.path.split("/")[0]
        host = host.strip()
        if ":" in host:
            host = host.split(":", 1)[0]
        return host.lower()
    except Exception:
        return raw


def parse_hhmm(value: str) -> Optional[Tuple[int, int]]:
    value = (value or "").strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def log_line(text: str) -> None:
    """Append a line to domain_monitor.log (best-effort)."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except Exception:
        pass


# -----------------------------
# WHOIS check
# -----------------------------

def perform_whois_update(domains: List[Dict[str, Any]], lang: str) -> None:
    """Update each domain dict in-place: expiry + days_left."""
    if whois is None:
        raise RuntimeError("python-whois is not installed")

    today = date.today()

    for d in domains:
        raw_domain = d.get("domain")
        if not raw_domain:
            continue

        domain_name = normalize_domain_for_whois(str(raw_domain))
        if not domain_name:
            continue

        try:
            info = whois.whois(domain_name)
            exp = getattr(info, "expiration_date", None)

            # expiration_date can be a list
            if isinstance(exp, list):
                exp = min((e for e in exp if e is not None), default=None)

            if exp is None:
                d["expiry"] = tr(lang, "unknown")
                d["days_left"] = None
            else:
                if hasattr(exp, "date"):
                    exp_date = exp.date()
                else:
                    exp_date = exp
                days_left = (exp_date - today).days
                d["expiry"] = exp_date.strftime("%Y-%m-%d")
                d["days_left"] = int(days_left)
        except Exception as e:
            d["expiry"] = tr(lang, "error_prefix", err=str(e))
            d["days_left"] = None


def sort_domains_by_expiry(domains: List[Dict[str, Any]]) -> None:
    domains.sort(
        key=lambda d: (
            d.get("days_left") is None,
            d.get("days_left") if isinstance(d.get("days_left"), int) else 10**9,
        )
    )


# -----------------------------
# Notifications
# -----------------------------

def collect_domains_for_notification(domains: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    threshold = int(settings.get("notify_days_threshold", 30))
    today_str = date.today().strftime("%Y-%m-%d")

    alerts: List[Dict[str, Any]] = []
    for d in domains:
        days_left = d.get("days_left")
        if not isinstance(days_left, int):
            continue
        if days_left > threshold:
            continue
        if d.get("last_notified") == today_str:
            continue
        alerts.append(d)

    return alerts


def build_notification_text(alerts: List[Dict[str, Any]], settings: Dict[str, Any], lang: str) -> str:
    threshold = int(settings.get("notify_days_threshold", 30))

    lines = [
        tr(lang, "notif_header", count=len(alerts), threshold=threshold),
        "",
    ]
    for d in alerts:
        domain = str(d.get("domain", ""))
        expiry = str(d.get("expiry", ""))
        days_left = d.get("days_left", "")
        link = str(d.get("link", "") or "")
        base = tr(lang, "notif_line", domain=domain, expiry=expiry, days_left=days_left)
        if link:
            base += f" | {link}"
        lines.append(base)
    lines.append("")
    lines.append(tr(lang, "notif_checked_at", dt=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    return "\n".join(lines)


def send_email(settings: Dict[str, Any], subject: str, body: str) -> None:
    cfg = settings.get("email", {}) or {}
    smtp_server = (cfg.get("smtp_server") or "").strip()
    smtp_port = int(cfg.get("smtp_port", 587))
    use_tls = bool(cfg.get("use_tls", True))
    use_ssl = bool(cfg.get("use_ssl", False))
    username = (cfg.get("username") or "").strip()
    password = cfg.get("password") or ""
    from_addr = (cfg.get("from_addr") or "").strip() or username
    to_addrs = cfg.get("to_addrs") or []

    if not smtp_server:
        raise ValueError("SMTP server is empty")
    if not to_addrs:
        raise ValueError("Recipients list (To) is empty")
    if not from_addr:
        raise ValueError("From is empty and username is empty")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body, subtype="plain", charset="utf-8")

    if use_ssl:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=25) as smtp:
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=25) as smtp:
            smtp.ehlo()
            if use_tls:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
                smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(msg)


def send_telegram(settings: Dict[str, Any], text: str) -> None:
    cfg = settings.get("telegram", {}) or {}
    token = (cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()

    if not token:
        raise ValueError("Telegram bot token is empty")
    if not chat_id:
        raise ValueError("Telegram chat_id is empty")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})

    try:
        with urlopen(req, timeout=25) as resp:
            resp_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"HTTP {e.code}: {body}") from e

    try:
        parsed = json.loads(resp_body)
        if not parsed.get("ok", False):
            raise RuntimeError(resp_body)
    except json.JSONDecodeError:
        raise RuntimeError(resp_body)


def send_expiry_notifications(
    domains: List[Dict[str, Any]],
    settings: Dict[str, Any],
    lang: str,
) -> Tuple[List[str], List[str], int]:
    """Send notifications if needed.

    Returns: (sent_channels, errors, alerts_count)

    NOTE: Updates domains[*]['last_notified'] in-place when something was sent.
    """

    alerts = collect_domains_for_notification(domains, settings)
    if not alerts:
        return [], [], 0

    email_enabled = bool((settings.get("email") or {}).get("enabled"))
    tg_enabled = bool((settings.get("telegram") or {}).get("enabled"))

    if not email_enabled and not tg_enabled:
        return [], [], 0

    text = build_notification_text(alerts, settings, lang)
    subject = tr(lang, "notif_subject")

    errors: List[str] = []
    sent: List[str] = []

    if email_enabled:
        try:
            send_email(settings, subject, text)
            sent.append("Email")
        except Exception as e:
            errors.append(f"Email: {e}")

    if tg_enabled:
        try:
            send_telegram(settings, text)
            sent.append("Telegram")
        except Exception as e:
            errors.append(f"Telegram: {e}")

    if sent:
        today_str = date.today().strftime("%Y-%m-%d")
        for d in alerts:
            d["last_notified"] = today_str

    return sent, errors, len(alerts)


# -----------------------------
# Headless run (Task Scheduler)
# -----------------------------

def run_headless_check() -> int:
    settings = load_settings()
    lang = str(settings.get("language") or "en")

    if whois is None:
        log_line("FATAL: python-whois is not installed")
        print(tr(lang, "err_whois_missing"), file=sys.stderr)
        return 1

    domains = load_domains()
    if not domains:
        log_line("No domains to check (domains.json is empty)")

    try:
        perform_whois_update(domains, lang)
        sort_domains_by_expiry(domains)
        save_domains(domains)
    except Exception as e:
        log_line(f"FATAL: WHOIS check failed: {e}")
        print(f"WHOIS check failed: {e}", file=sys.stderr)
        return 1

    sent, errors, alerts_count = send_expiry_notifications(domains, settings, lang)
    if sent:
        try:
            save_domains(domains)
        except Exception as e:
            log_line(f"WARNING: could not update last_notified in domains.json: {e}")

    log_line(f"Checked {len(domains)} domains. Alerts: {alerts_count}. Sent: {sent}. Errors: {errors}.")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2

    return 0


# -----------------------------
# GUI
# -----------------------------

if not HEADLESS_MODE:

    class DomainManagerApp(tk.Tk):
        def __init__(self):
            super().__init__()

            self.domains: List[Dict[str, Any]] = []
            self.settings: Dict[str, Any] = dict(DEFAULT_SETTINGS)
            self.lang: str = "en"

            self._auto_job: Optional[str] = None

            self._load_domains()
            self._load_settings()

            self.lang = str(self.settings.get("language") or "en")

            self._create_widgets()
            self._refresh_table()
            self._restart_auto_check_scheduler()

        # ---------- i18n ----------
        def t(self, key: str, **kwargs: Any) -> str:
            return tr(self.lang, key, **kwargs)

        # ---------- UI ----------
        def _create_widgets(self):
            self.title(self.t("app_title"))
            self.geometry("1000x560")

            top_frame = ttk.Frame(self)
            top_frame.pack(fill=tk.X, padx=10, pady=5)

            self.lbl_domain = ttk.Label(top_frame, text=self.t("label_domain"))
            self.lbl_domain.grid(row=0, column=0, sticky="w")
            self.domain_entry = ttk.Entry(top_frame, width=30)
            self.domain_entry.grid(row=0, column=1, padx=5, pady=2)

            self.lbl_link = ttk.Label(top_frame, text=self.t("label_link"))
            self.lbl_link.grid(row=0, column=2, sticky="w")
            self.link_entry = ttk.Entry(top_frame, width=30)
            self.link_entry.grid(row=0, column=3, padx=5, pady=2)

            self.lbl_login = ttk.Label(top_frame, text=self.t("label_login"))
            self.lbl_login.grid(row=1, column=0, sticky="w")
            self.login_entry = ttk.Entry(top_frame, width=30)
            self.login_entry.grid(row=1, column=1, padx=5, pady=2)

            self.lbl_password = ttk.Label(top_frame, text=self.t("label_password"))
            self.lbl_password.grid(row=1, column=2, sticky="w")
            self.password_entry = ttk.Entry(top_frame, width=30, show="*")
            self.password_entry.grid(row=1, column=3, padx=5, pady=2)

            self.btn_add_update = ttk.Button(top_frame, text=self.t("btn_add_update"), command=self.add_or_update_domain)
            self.btn_add_update.grid(row=0, column=4, rowspan=2, padx=10)

            # Buttons row
            btn_frame = ttk.Frame(self)
            btn_frame.pack(fill=tk.X, padx=10, pady=5)

            self.btn_check = ttk.Button(btn_frame, text=self.t("btn_check"), command=lambda: self.check_domains(show_success_dialog=True))
            self.btn_check.pack(side=tk.LEFT, padx=5)

            self.btn_sort = ttk.Button(btn_frame, text=self.t("btn_sort"), command=self.sort_by_expiry)
            self.btn_sort.pack(side=tk.LEFT, padx=5)

            self.btn_settings = ttk.Button(btn_frame, text=self.t("btn_settings"), command=self.open_settings)
            self.btn_settings.pack(side=tk.LEFT, padx=5)

            self.btn_export = ttk.Button(btn_frame, text=self.t("btn_export"), command=self.export_to_excel)
            self.btn_export.pack(side=tk.LEFT, padx=5)

            self.btn_delete = ttk.Button(btn_frame, text=self.t("btn_delete"), command=self.delete_selected)
            self.btn_delete.pack(side=tk.LEFT, padx=5)

            self.btn_save = ttk.Button(btn_frame, text=self.t("btn_save"), command=lambda: self._save_domains(show_message=True))
            self.btn_save.pack(side=tk.RIGHT, padx=5)

            # Table
            columns = ("domain", "link", "login", "password", "expiry", "days_left")
            self.tree = ttk.Treeview(self, columns=columns, show="headings")
            self.tree.heading("domain", text=self.t("col_domain"))
            self.tree.heading("link", text=self.t("col_link"))
            self.tree.heading("login", text=self.t("col_login"))
            self.tree.heading("password", text=self.t("col_password"))
            self.tree.heading("expiry", text=self.t("col_expiry"))
            self.tree.heading("days_left", text=self.t("col_days_left"))

            self.tree.column("domain", width=150)
            self.tree.column("link", width=200)
            self.tree.column("login", width=110)
            self.tree.column("password", width=110)
            self.tree.column("expiry", width=130)
            self.tree.column("days_left", width=90, anchor="center")

            self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

            # Row coloring
            self.tree.tag_configure("red", background="#f8d7da")
            self.tree.tag_configure("yellow", background="#fff3cd")

            self.tree.bind("<<TreeviewSelect>>", self.on_select_row)

            # Status
            self.status_var = tk.StringVar(value="")
            status = ttk.Label(self, textvariable=self.status_var, anchor="w")
            status.pack(fill=tk.X, padx=10, pady=(0, 8))

        def _update_ui_texts(self):
            self.title(self.t("app_title"))

            self.lbl_domain.configure(text=self.t("label_domain"))
            self.lbl_link.configure(text=self.t("label_link"))
            self.lbl_login.configure(text=self.t("label_login"))
            self.lbl_password.configure(text=self.t("label_password"))

            self.btn_add_update.configure(text=self.t("btn_add_update"))
            self.btn_check.configure(text=self.t("btn_check"))
            self.btn_sort.configure(text=self.t("btn_sort"))
            self.btn_settings.configure(text=self.t("btn_settings"))
            self.btn_export.configure(text=self.t("btn_export"))
            self.btn_delete.configure(text=self.t("btn_delete"))
            self.btn_save.configure(text=self.t("btn_save"))

            self.tree.heading("domain", text=self.t("col_domain"))
            self.tree.heading("link", text=self.t("col_link"))
            self.tree.heading("login", text=self.t("col_login"))
            self.tree.heading("password", text=self.t("col_password"))
            self.tree.heading("expiry", text=self.t("col_expiry"))
            self.tree.heading("days_left", text=self.t("col_days_left"))

        def _set_status(self, text: str):
            self.status_var.set(text or "")

        # ---------- Data ----------
        def _load_domains(self):
            self.domains = load_domains()

        def _save_domains(self, show_message: bool = True):
            try:
                save_domains(self.domains)
                if show_message:
                    messagebox.showinfo(self.t("title_saved"), self.t("msg_domains_saved", file=DATA_FILE))
            except Exception as e:
                messagebox.showerror(self.t("title_error"), self.t("msg_save_failed", err=str(e)))

        def _load_settings(self):
            self.settings = load_settings()

        def _save_settings(self):
            try:
                save_settings(self.settings)
            except Exception as e:
                messagebox.showerror(self.t("title_error"), self.t("msg_save_failed", err=str(e)))

        # ---------- CRUD ----------
        def add_or_update_domain(self):
            domain = self.domain_entry.get().strip()
            link = self.link_entry.get().strip()
            login = self.login_entry.get().strip()
            password = self.password_entry.get().strip()

            if not domain:
                messagebox.showwarning(self.t("title_warning"), self.t("warn_domain_empty"))
                return

            for d in self.domains:
                if d.get("domain") == domain:
                    d["link"] = link
                    d["login"] = login
                    d["password"] = password
                    break
            else:
                self.domains.append(
                    {
                        "domain": domain,
                        "link": link,
                        "login": login,
                        "password": password,
                        "expiry": "",
                        "days_left": None,
                        "last_notified": None,  # YYYY-MM-DD
                    }
                )

            self._refresh_table()
            self._save_domains(show_message=True)

        def delete_selected(self):
            selected = self.tree.selection()
            if not selected:
                return
            idx_list = sorted((int(iid) for iid in selected), reverse=True)
            for idx in idx_list:
                if 0 <= idx < len(self.domains):
                    self.domains.pop(idx)
            self._refresh_table()
            self._save_domains(show_message=True)

        def on_select_row(self, event):
            selected = self.tree.selection()
            if not selected:
                return
            idx = int(selected[0])
            if 0 <= idx < len(self.domains):
                d = self.domains[idx]
                self.domain_entry.delete(0, tk.END)
                self.domain_entry.insert(0, d.get("domain", ""))
                self.link_entry.delete(0, tk.END)
                self.link_entry.insert(0, d.get("link", ""))
                self.login_entry.delete(0, tk.END)
                self.login_entry.insert(0, d.get("login", ""))
                self.password_entry.delete(0, tk.END)
                self.password_entry.insert(0, d.get("password", ""))

        def _refresh_table(self):
            for row in self.tree.get_children():
                self.tree.delete(row)

            for i, d in enumerate(self.domains):
                tags: Tuple[str, ...] = ()
                days_left = d.get("days_left")
                if isinstance(days_left, int):
                    if days_left < 30:
                        tags = ("red",)
                    elif days_left < 60:
                        tags = ("yellow",)

                self.tree.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        d.get("domain", ""),
                        d.get("link", ""),
                        d.get("login", ""),
                        d.get("password", ""),
                        d.get("expiry", ""),
                        days_left if days_left is not None else "",
                    ),
                    tags=tags,
                )

        # ---------- WHOIS ----------
        def check_domains(self, show_success_dialog: bool = True, *, _auto: bool = False):
            if whois is None:
                messagebox.showerror(self.t("title_error"), self.t("err_whois_missing"))
                return

            self._set_status(self.t("status_autocheck_running") if _auto else self.t("status_checking"))
            self.update_idletasks()

            try:
                perform_whois_update(self.domains, self.lang)
            except Exception as e:
                messagebox.showerror(self.t("title_error"), str(e))
                self._set_status("")
                return

            self.sort_by_expiry()
            self._save_domains(show_message=False)

            sent, errors, _ = send_expiry_notifications(self.domains, self.settings, self.lang)
            if sent:
                self._save_domains(show_message=False)

            if errors:
                messagebox.showerror(self.t("title_notifications"), self.t("notif_partial_fail", errors="\n".join(errors)))
            elif sent and show_success_dialog:
                messagebox.showinfo(self.t("title_notifications"), self.t("notif_sent", channels=", ".join(sent)))

            self._set_status(self.t("status_done"))

        def sort_by_expiry(self):
            sort_domains_by_expiry(self.domains)
            self._refresh_table()

        # ---------- Export ----------
        def export_to_excel(self):
            if Workbook is None:
                messagebox.showerror(self.t("title_error"), self.t("err_openpyxl_missing"))
                return

            if not self.domains:
                messagebox.showinfo(self.t("title_export"), self.t("msg_export_empty"))
                return

            file_path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excel", "*.xlsx"), ("All files", "*.*")],
            )
            if not file_path:
                return

            wb = Workbook()
            ws = wb.active
            ws.title = "Domains" if self.lang == "en" else "Домены"

            headers = [
                self.t("col_domain"),
                self.t("col_link"),
                self.t("col_login"),
                self.t("col_password"),
                self.t("col_expiry"),
                self.t("col_days_left"),
            ]
            ws.append(headers)

            for d in self.domains:
                ws.append(
                    [
                        d.get("domain", ""),
                        d.get("link", ""),
                        d.get("login", ""),
                        d.get("password", ""),
                        d.get("expiry", ""),
                        d.get("days_left", ""),
                    ]
                )

            try:
                wb.save(file_path)
                messagebox.showinfo(self.t("title_export"), self.t("msg_export_saved", file=file_path))
            except Exception as e:
                messagebox.showerror(self.t("title_error"), self.t("msg_export_failed", err=str(e)))

        # ---------- Settings ----------
        def open_settings(self):
            win = tk.Toplevel(self)
            win.title(self.t("settings_title"))
            win.geometry("760x560")
            win.transient(self)
            win.grab_set()

            nb = ttk.Notebook(win)
            nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            tab_general = ttk.Frame(nb)
            tab_notif = ttk.Frame(nb)
            tab_auto = ttk.Frame(nb)

            nb.add(tab_general, text=self.t("tab_general"))
            nb.add(tab_notif, text=self.t("tab_notifications"))
            nb.add(tab_auto, text=self.t("tab_automation"))

            # --- Variables (init from current settings)
            lang_var = tk.StringVar(value=str(self.settings.get("language") or "en"))

            threshold_var = tk.StringVar(value=str(self.settings.get("notify_days_threshold", 30)))

            email_cfg = self.settings.get("email", {}) or {}
            email_enabled = tk.BooleanVar(value=bool(email_cfg.get("enabled", False)))
            smtp_server_var = tk.StringVar(value=str(email_cfg.get("smtp_server", "")))
            smtp_port_var = tk.StringVar(value=str(email_cfg.get("smtp_port", 587)))
            use_tls_var = tk.BooleanVar(value=bool(email_cfg.get("use_tls", True)))
            use_ssl_var = tk.BooleanVar(value=bool(email_cfg.get("use_ssl", False)))
            email_user_var = tk.StringVar(value=str(email_cfg.get("username", "")))
            email_pass_var = tk.StringVar(value=str(email_cfg.get("password", "")))
            email_from_var = tk.StringVar(value=str(email_cfg.get("from_addr", "")))
            email_to_var = tk.StringVar(value=", ".join(email_cfg.get("to_addrs", []) or []))

            tg_cfg = self.settings.get("telegram", {}) or {}
            tg_enabled = tk.BooleanVar(value=bool(tg_cfg.get("enabled", False)))
            tg_token_var = tk.StringVar(value=str(tg_cfg.get("bot_token", "")))
            tg_chat_var = tk.StringVar(value=str(tg_cfg.get("chat_id", "")))

            auto_cfg = self.settings.get("automation", {}) or {}
            auto_enabled_var = tk.BooleanVar(value=bool(auto_cfg.get("auto_check_enabled", False)))
            auto_time_var = tk.StringVar(value=str(auto_cfg.get("auto_check_time", "09:00")))

            # --- General tab
            general_box = ttk.LabelFrame(tab_general, text=self.t("tab_general"))
            general_box.pack(fill=tk.X, padx=10, pady=10)

            ttk.Label(general_box, text=self.t("language_label")).grid(row=0, column=0, sticky="w", padx=5, pady=5)

            lang_options = {
                "en": self.t("language_en"),
                "ru": self.t("language_ru"),
            }

            # show localized names, but store code
            lang_menu = ttk.Combobox(general_box, state="readonly", width=20)
            lang_menu["values"] = [lang_options["en"], lang_options["ru"]]
            # set display value
            lang_menu.set(lang_options.get(lang_var.get(), lang_options["en"]))

            def _lang_menu_changed(event=None):
                # map display back to code
                val = lang_menu.get()
                for code, name in lang_options.items():
                    if name == val:
                        lang_var.set(code)
                        break

            lang_menu.bind("<<ComboboxSelected>>", _lang_menu_changed)
            lang_menu.grid(row=0, column=1, sticky="w", padx=5, pady=5)

            # --- Notifications tab
            notif_general = ttk.LabelFrame(tab_notif, text=self.t("tab_notifications"))
            notif_general.pack(fill=tk.X, padx=10, pady=10)

            ttk.Label(notif_general, text=self.t("notify_threshold_label")).grid(row=0, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(notif_general, textvariable=threshold_var, width=10).grid(row=0, column=1, sticky="w", padx=5, pady=5)

            email_frame = ttk.LabelFrame(tab_notif, text=self.t("email_frame"))
            email_frame.pack(fill=tk.X, padx=10, pady=5)

            ttk.Checkbutton(email_frame, text=self.t("email_enabled"), variable=email_enabled).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5
            )

            ttk.Label(email_frame, text=self.t("smtp_server")).grid(row=1, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=smtp_server_var, width=40).grid(row=1, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(email_frame, text=self.t("smtp_port")).grid(row=2, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=smtp_port_var, width=10).grid(row=2, column=1, sticky="w", padx=5, pady=2)

            ttk.Checkbutton(email_frame, text=self.t("smtp_tls"), variable=use_tls_var).grid(row=3, column=0, sticky="w", padx=5, pady=2)
            ttk.Checkbutton(email_frame, text=self.t("smtp_ssl"), variable=use_ssl_var).grid(row=3, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(email_frame, text=self.t("smtp_user")).grid(row=4, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=email_user_var, width=40).grid(row=4, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(email_frame, text=self.t("smtp_pass")).grid(row=5, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=email_pass_var, show="*", width=40).grid(row=5, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(email_frame, text=self.t("smtp_from")).grid(row=6, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=email_from_var, width=40).grid(row=6, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(email_frame, text=self.t("smtp_to")).grid(row=7, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(email_frame, textvariable=email_to_var, width=40).grid(row=7, column=1, sticky="w", padx=5, pady=2)

            tg_frame = ttk.LabelFrame(tab_notif, text=self.t("tg_frame"))
            tg_frame.pack(fill=tk.X, padx=10, pady=5)

            ttk.Checkbutton(tg_frame, text=self.t("tg_enabled"), variable=tg_enabled).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5
            )

            ttk.Label(tg_frame, text=self.t("tg_token")).grid(row=1, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(tg_frame, textvariable=tg_token_var, width=55).grid(row=1, column=1, sticky="w", padx=5, pady=2)

            ttk.Label(tg_frame, text=self.t("tg_chat")).grid(row=2, column=0, sticky="w", padx=5, pady=2)
            ttk.Entry(tg_frame, textvariable=tg_chat_var, width=55).grid(row=2, column=1, sticky="w", padx=5, pady=2)

            # --- Automation tab
            auto_box = ttk.LabelFrame(tab_auto, text=self.t("tab_automation"))
            auto_box.pack(fill=tk.X, padx=10, pady=10)

            ttk.Checkbutton(auto_box, text=self.t("auto_enabled"), variable=auto_enabled_var).grid(
                row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5
            )

            ttk.Label(auto_box, text=self.t("auto_time")).grid(row=1, column=0, sticky="w", padx=5, pady=5)
            ttk.Entry(auto_box, textvariable=auto_time_var, width=10).grid(row=1, column=1, sticky="w", padx=5, pady=5)

            help_box = ttk.LabelFrame(tab_auto, text=self.t("scheduler_help_title"))
            help_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            if self.lang == "en":
                help_text = (
                    "To run daily checks even when the app is NOT running, use Windows Task Scheduler:\n\n"
                    "1) Win + R → taskschd.msc\n"
                    "2) Create Basic Task…\n"
                    "3) Trigger: Daily (choose time)\n"
                    "4) Action: Start a program\n"
                    "   - Program/script: path to domain_monitor.exe\n"
                    "   - Add arguments: --check\n"
                    "   - Start in: folder where the EXE is located\n\n"
                    "If you run via Python:\n"
                    "   Program/script: C:\\Path\\python.exe\n"
                    "   Add arguments: C:\\Path\\domain_monitor.py --check\n"
                    "   Start in: C:\\Path\\\n\n"
                    "In --check mode the app runs one WHOIS check, sends notifications and exits.\n"
                    "Log file: domain_monitor.log (next to the EXE/script)."
                )
            else:
                help_text = (
                    "Чтобы проверки выполнялись ежедневно даже когда программа НЕ запущена, используйте Планировщик:\n\n"
                    "1) Win + R → taskschd.msc\n"
                    "2) Создать простую задачу…\n"
                    "3) Триггер: Ежедневно (выберите время)\n"
                    "4) Действие: Запуск программы\n"
                    "   - Program/script: путь к domain_monitor.exe\n"
                    "   - Аргументы: --check\n"
                    "   - Папка (Start in): папка где лежит EXE\n\n"
                    "Если запускаете через Python:\n"
                    "   Program/script: C:\\Path\\python.exe\n"
                    "   Аргументы: C:\\Path\\domain_monitor.py --check\n"
                    "   Start in: C:\\Path\\\n\n"
                    "В режиме --check приложение делает одну проверку WHOIS, отправляет уведомления и закрывается.\n"
                    "Лог: domain_monitor.log (рядом с EXE/скриптом)."
                )

            txt = tk.Text(help_box, height=14, wrap="word")
            txt.insert("1.0", help_text)
            txt.configure(state="disabled")
            txt.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            # --- Buttons (bottom)
            btns = ttk.Frame(win)
            btns.pack(fill=tk.X, padx=10, pady=(0, 10))

            def save_settings_from_ui() -> bool:
                # threshold
                try:
                    threshold = int(threshold_var.get().strip())
                    if threshold < 0:
                        raise ValueError
                except Exception:
                    messagebox.showerror(self.t("title_error"), self.t("err_threshold"))
                    return False

                # email port
                try:
                    port = int(smtp_port_var.get().strip())
                    if port <= 0:
                        raise ValueError
                except Exception:
                    messagebox.showerror(self.t("title_error"), self.t("err_port"))
                    return False

                # auto time
                if auto_enabled_var.get():
                    if parse_hhmm(auto_time_var.get()) is None:
                        messagebox.showerror(self.t("title_error"), self.t("err_time_format"))
                        return False

                to_list = [x.strip() for x in (email_to_var.get() or "").split(",") if x.strip()]

                if use_ssl_var.get() and use_tls_var.get():
                    if not messagebox.askyesno(self.t("title_warning"), self.t("warn_ssl_tls")):
                        return False

                # Update settings
                new_lang = str(lang_var.get() or "en")
                self.settings["language"] = new_lang
                self.settings["notify_days_threshold"] = threshold

                self.settings["automation"] = {
                    "auto_check_enabled": bool(auto_enabled_var.get()),
                    "auto_check_time": auto_time_var.get().strip() or "09:00",
                }

                self.settings["email"] = {
                    "enabled": bool(email_enabled.get()),
                    "smtp_server": smtp_server_var.get().strip(),
                    "smtp_port": port,
                    "use_tls": bool(use_tls_var.get()),
                    "use_ssl": bool(use_ssl_var.get()),
                    "username": email_user_var.get().strip(),
                    "password": email_pass_var.get(),
                    "from_addr": email_from_var.get().strip(),
                    "to_addrs": to_list,
                }
                self.settings["telegram"] = {
                    "enabled": bool(tg_enabled.get()),
                    "bot_token": tg_token_var.get().strip(),
                    "chat_id": tg_chat_var.get().strip(),
                }

                self._save_settings()

                # Apply language
                self.lang = new_lang
                self._update_ui_texts()

                # Restart auto scheduler
                self._restart_auto_check_scheduler()

                messagebox.showinfo(self.t("title_saved"), self.t("msg_settings_saved", file=SETTINGS_FILE))
                return True

            def test_email_btn():
                if not save_settings_from_ui():
                    return
                if not self.settings.get("email", {}).get("enabled"):
                    messagebox.showwarning(self.t("title_warning"), self.t("warn_email_disabled"))
                    return
                try:
                    send_email(self.settings, self.t("test_email_subject"), self.t("test_email_body"))
                    messagebox.showinfo("Email", self.t("msg_test_email_sent"))
                except Exception as e:
                    messagebox.showerror("Email", self.t("err_test_email", err=str(e)))

            def test_tg_btn():
                if not save_settings_from_ui():
                    return
                if not self.settings.get("telegram", {}).get("enabled"):
                    messagebox.showwarning(self.t("title_warning"), self.t("warn_tg_disabled"))
                    return
                try:
                    send_telegram(self.settings, self.t("test_tg_text"))
                    messagebox.showinfo("Telegram", self.t("msg_test_tg_sent"))
                except Exception as e:
                    messagebox.showerror("Telegram", self.t("err_test_tg", err=str(e)))

            ttk.Button(btns, text=self.t("btn_save_settings"), command=save_settings_from_ui).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text=self.t("btn_test_email"), command=test_email_btn).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text=self.t("btn_test_tg"), command=test_tg_btn).pack(side=tk.LEFT, padx=5)
            ttk.Button(btns, text=self.t("btn_close"), command=win.destroy).pack(side=tk.RIGHT, padx=5)

        # ---------- Auto-check scheduler ----------
        def _cancel_auto_job(self):
            if self._auto_job is not None:
                try:
                    self.after_cancel(self._auto_job)
                except Exception:
                    pass
                self._auto_job = None

        def _restart_auto_check_scheduler(self):
            self._cancel_auto_job()

            auto_cfg = self.settings.get("automation", {}) or {}
            enabled = bool(auto_cfg.get("auto_check_enabled", False))
            if not enabled:
                return

            time_str = str(auto_cfg.get("auto_check_time", "09:00"))
            hm = parse_hhmm(time_str)
            if hm is None:
                # invalid time => do not schedule
                self._set_status(self.t("err_time_format"))
                return

            self._schedule_next_auto_check(hm[0], hm[1])

        def _schedule_next_auto_check(self, hour: int, minute: int):
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)

            delay_ms = int((target - now).total_seconds() * 1000)
            delay_ms = max(1000, min(delay_ms, 24 * 60 * 60 * 1000))

            self._set_status(self.t("status_scheduled", dt=target.strftime("%Y-%m-%d %H:%M")))
            self._auto_job = self.after(delay_ms, self._auto_check_callback)

        def _auto_check_callback(self):
            # Do the check silently (no success popup), then schedule next run
            try:
                self.check_domains(show_success_dialog=False, _auto=True)
            finally:
                auto_cfg = self.settings.get("automation", {}) or {}
                time_str = str(auto_cfg.get("auto_check_time", "09:00"))
                hm = parse_hhmm(time_str)
                if hm is not None and bool(auto_cfg.get("auto_check_enabled", False)):
                    self._schedule_next_auto_check(hm[0], hm[1])


# -----------------------------
# Entrypoint
# -----------------------------

def main() -> None:
    if HEADLESS_MODE:
        code = run_headless_check()
        sys.exit(code)

    app = DomainManagerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
