import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
import sys
from datetime import datetime, date
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import urllib.error


try:
    import whois
except ImportError:
    whois = None

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


def get_app_dir() -> str:
    """
    Возвращает папку приложения.
    - Для PyInstaller (frozen) — папка, где лежит .exe
    - Для запуска .py — папка, где лежит этот файл
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = get_app_dir()
DATA_FILE = os.path.join(APP_DIR, "domains.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")


DEFAULT_SETTINGS = {
    "notify_days_threshold": 30,   # за сколько дней до окончания слать уведомления
    "email": {
        "enabled": False,
        "smtp_server": "",
        "smtp_port": 587,
        "use_tls": True,
        "use_ssl": False,
        "username": "",
        "password": "",
        "from_addr": "",
        "to_addrs": []
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": ""
    }
}


def deep_merge(base: dict, patch: dict) -> dict:
    """Аккуратно дополняет base значениями из patch (с сохранением структуры)."""
    result = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def normalize_domain_for_whois(raw: str) -> str:
    """
    Приводит введённое значение к домену для WHOIS.
    Поддерживает:
      - example.com
      - https://example.com/path
      - example.com/path
    """
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = parsed.netloc or parsed.path.split("/")[0]
        host = host.strip()
        # убрать порт
        if ":" in host:
            host = host.split(":", 1)[0]
        return host.lower()
    except Exception:
        return raw


class DomainManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Монитор доменов")
        self.geometry("1000x540")

        self.domains = []
        self.settings = dict(DEFAULT_SETTINGS)

        self._load_domains()
        self._load_settings()

        self._create_widgets()
        self._refresh_table()

    # -----------------------------
    # UI
    # -----------------------------
    def _create_widgets(self):
        top_frame = ttk.Frame(self)
        top_frame.pack(fill=tk.X, padx=10, pady=5)

        # Поля ввода
        ttk.Label(top_frame, text="Домен:").grid(row=0, column=0, sticky="w")
        self.domain_entry = ttk.Entry(top_frame, width=30)
        self.domain_entry.grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(top_frame, text="Ссылка:").grid(row=0, column=2, sticky="w")
        self.link_entry = ttk.Entry(top_frame, width=30)
        self.link_entry.grid(row=0, column=3, padx=5, pady=2)

        ttk.Label(top_frame, text="Логин:").grid(row=1, column=0, sticky="w")
        self.login_entry = ttk.Entry(top_frame, width=30)
        self.login_entry.grid(row=1, column=1, padx=5, pady=2)

        ttk.Label(top_frame, text="Пароль:").grid(row=1, column=2, sticky="w")
        self.password_entry = ttk.Entry(top_frame, width=30, show="*")
        self.password_entry.grid(row=1, column=3, padx=5, pady=2)

        add_btn = ttk.Button(top_frame, text="Добавить/обновить домен", command=self.add_or_update_domain)
        add_btn.grid(row=0, column=4, rowspan=2, padx=10)

        # Кнопки управления
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=10, pady=5)

        check_btn = ttk.Button(btn_frame, text="Проверить домены (WHOIS)", command=self.check_domains)
        check_btn.pack(side=tk.LEFT, padx=5)

        sort_btn = ttk.Button(btn_frame, text="Отсортировать по дате окончания", command=self.sort_by_expiry)
        sort_btn.pack(side=tk.LEFT, padx=5)

        notify_btn = ttk.Button(btn_frame, text="Настройки уведомлений", command=self.open_notification_settings)
        notify_btn.pack(side=tk.LEFT, padx=5)

        export_btn = ttk.Button(btn_frame, text="Экспорт в Excel", command=self.export_to_excel)
        export_btn.pack(side=tk.LEFT, padx=5)

        del_btn = ttk.Button(btn_frame, text="Удалить выбранный", command=self.delete_selected)
        del_btn.pack(side=tk.LEFT, padx=5)

        save_btn = ttk.Button(btn_frame, text="Сохранить список", command=lambda: self._save_domains(show_message=True))
        save_btn.pack(side=tk.RIGHT, padx=5)

        # Таблица
        columns = ("domain", "link", "login", "password", "expiry", "days_left")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("domain", text="Домен")
        self.tree.heading("link", text="Ссылка")
        self.tree.heading("login", text="Логин")
        self.tree.heading("password", text="Пароль")
        self.tree.heading("expiry", text="Дата окончания")
        self.tree.heading("days_left", text="Дней до конца")

        self.tree.column("domain", width=150)
        self.tree.column("link", width=200)
        self.tree.column("login", width=100)
        self.tree.column("password", width=100)
        self.tree.column("expiry", width=120)
        self.tree.column("days_left", width=100, anchor="center")

        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Оформление строк по сроку
        self.tree.tag_configure("red", background="#f8d7da")    # < 30 дней
        self.tree.tag_configure("yellow", background="#fff3cd") # < 60 дней

        # При выборе строки заполняем форму
        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)

        # Статус
        self.status_var = tk.StringVar(value="")
        status = ttk.Label(self, textvariable=self.status_var, anchor="w")
        status.pack(fill=tk.X, padx=10, pady=(0, 8))

    def _set_status(self, text: str):
        self.status_var.set(text or "")

    # -----------------------------
    # Data (domains/settings)
    # -----------------------------
    def _load_domains(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.domains = json.load(f)
            except Exception:
                self.domains = []

    def _save_domains(self, show_message: bool = True):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.domains, f, ensure_ascii=False, indent=2)
            if show_message:
                messagebox.showinfo("Сохранено", f"Список доменов сохранён.\nФайл: {DATA_FILE}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")

    def _load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    user_settings = json.load(f)
                self.settings = deep_merge(DEFAULT_SETTINGS, user_settings)
            except Exception:
                self.settings = dict(DEFAULT_SETTINGS)
        else:
            self.settings = dict(DEFAULT_SETTINGS)

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить настройки: {e}")

    def _refresh_table(self):
        # очистка
        for row in self.tree.get_children():
            self.tree.delete(row)

        # заполнение
        for i, d in enumerate(self.domains):
            tags = ()
            days_left = d.get("days_left")
            if isinstance(days_left, int):
                if days_left < 30:
                    tags = ("red",)
                elif days_left < 60:
                    tags = ("yellow",)

            self.tree.insert(
                "", "end", iid=str(i),
                values=(
                    d.get("domain", ""),
                    d.get("link", ""),
                    d.get("login", ""),
                    d.get("password", ""),
                    d.get("expiry", ""),
                    days_left if days_left is not None else ""
                ),
                tags=tags
            )

    # -----------------------------
    # CRUD
    # -----------------------------
    def add_or_update_domain(self):
        domain = self.domain_entry.get().strip()
        link = self.link_entry.get().strip()
        login = self.login_entry.get().strip()
        password = self.password_entry.get().strip()

        if not domain:
            messagebox.showwarning("Внимание", "Поле 'Домен' не может быть пустым.")
            return

        # Проверяем, есть ли уже такой домен
        for d in self.domains:
            if d.get("domain") == domain:
                d["link"] = link
                d["login"] = login
                d["password"] = password
                break
        else:
            self.domains.append({
                "domain": domain,
                "link": link,
                "login": login,
                "password": password,
                "expiry": "",
                "days_left": None,
                "last_notified": None,  # YYYY-MM-DD
            })

        self._refresh_table()
        self._save_domains(show_message=True)

    def delete_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        # Удаляем с конца, чтобы индексы не смещались
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
        iid = selected[0]
        idx = int(iid)
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

    # -----------------------------
    # WHOIS check
    # -----------------------------
    def check_domains(self):
        if whois is None:
            messagebox.showerror(
                "Ошибка",
                "Модуль 'python-whois' не установлен.\nУстановите: pip install python-whois"
            )
            return

        self._set_status("Проверяю домены (WHOIS)...")
        self.update_idletasks()

        now = datetime.now()
        for d in self.domains:
            raw_domain = d.get("domain")
            if not raw_domain:
                continue

            domain_name = normalize_domain_for_whois(raw_domain)

            try:
                info = whois.whois(domain_name)
                exp = info.expiration_date

                # expiration_date может быть списком
                if isinstance(exp, list):
                    exp = min(e for e in exp if e is not None) if any(exp) else None

                if exp is None:
                    d["expiry"] = "Неизвестно"
                    d["days_left"] = None
                else:
                    if hasattr(exp, "date"):
                        exp_date = exp.date()
                    else:
                        exp_date = exp
                    days_left = (exp_date - now.date()).days
                    d["expiry"] = exp_date.strftime("%Y-%m-%d")
                    d["days_left"] = int(days_left)
            except Exception as e:
                d["expiry"] = f"Ошибка: {e}"
                d["days_left"] = None

        self.sort_by_expiry()
        self._save_domains(show_message=False)

        # Уведомления (если настроены)
        try:
            self._send_expiry_notifications_if_needed()
        finally:
            self._set_status("Проверка завершена.")

    def sort_by_expiry(self):
        # Сначала домены с минимальным days_left, None в конце
        self.domains.sort(
            key=lambda d: (
                d.get("days_left") is None,
                d.get("days_left") if d.get("days_left") is not None else 10**9
            )
        )
        self._refresh_table()

    # -----------------------------
    # Export
    # -----------------------------
    def export_to_excel(self):
        if Workbook is None:
            messagebox.showerror(
                "Ошибка",
                "Модуль 'openpyxl' не установлен.\nУстановите: pip install openpyxl"
            )
            return

        if not self.domains:
            messagebox.showinfo("Экспорт", "Список доменов пуст.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel файлы", "*.xlsx"), ("Все файлы", "*.*")]
        )
        if not file_path:
            return

        wb = Workbook()
        ws = wb.active
        ws.title = "Домены"

        headers = ["Домен", "Ссылка", "Логин", "Пароль", "Дата окончания", "Дней до конца"]
        ws.append(headers)

        for d in self.domains:
            ws.append([
                d.get("domain", ""),
                d.get("link", ""),
                d.get("login", ""),
                d.get("password", ""),
                d.get("expiry", ""),
                d.get("days_left", "")
            ])

        try:
            wb.save(file_path)
            messagebox.showinfo("Экспорт", f"Файл успешно сохранён:\n{file_path}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")

    # -----------------------------
    # Notifications
    # -----------------------------
    def open_notification_settings(self):
        win = tk.Toplevel(self)
        win.title("Настройки уведомлений")
        win.geometry("650x420")
        win.transient(self)
        win.grab_set()

        # --- General
        general = ttk.LabelFrame(win, text="Общие")
        general.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(general, text="Порог уведомления (дней до окончания):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        threshold_var = tk.StringVar(value=str(self.settings.get("notify_days_threshold", 30)))
        threshold_entry = ttk.Entry(general, textvariable=threshold_var, width=10)
        threshold_entry.grid(row=0, column=1, sticky="w", padx=5, pady=5)

        # --- Email
        email_frame = ttk.LabelFrame(win, text="Email (SMTP)")
        email_frame.pack(fill=tk.X, padx=10, pady=5)

        email_cfg = self.settings.get("email", {})
        email_enabled = tk.BooleanVar(value=bool(email_cfg.get("enabled", False)))
        ttk.Checkbutton(email_frame, text="Включить email-уведомления", variable=email_enabled).grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        smtp_server_var = tk.StringVar(value=str(email_cfg.get("smtp_server", "")))
        smtp_port_var = tk.StringVar(value=str(email_cfg.get("smtp_port", 587)))
        email_user_var = tk.StringVar(value=str(email_cfg.get("username", "")))
        email_pass_var = tk.StringVar(value=str(email_cfg.get("password", "")))
        email_from_var = tk.StringVar(value=str(email_cfg.get("from_addr", "")))
        email_to_var = tk.StringVar(value=", ".join(email_cfg.get("to_addrs", []) or []))
        use_tls_var = tk.BooleanVar(value=bool(email_cfg.get("use_tls", True)))
        use_ssl_var = tk.BooleanVar(value=bool(email_cfg.get("use_ssl", False)))

        ttk.Label(email_frame, text="SMTP сервер:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=smtp_server_var, width=35).grid(row=1, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(email_frame, text="Порт:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=smtp_port_var, width=10).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        ttk.Checkbutton(email_frame, text="TLS (STARTTLS)", variable=use_tls_var).grid(row=3, column=0, sticky="w", padx=5, pady=2)
        ttk.Checkbutton(email_frame, text="SSL", variable=use_ssl_var).grid(row=3, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(email_frame, text="Логин:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=email_user_var, width=35).grid(row=4, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(email_frame, text="Пароль:").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=email_pass_var, show="*", width=35).grid(row=5, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(email_frame, text="От (From):").grid(row=6, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=email_from_var, width=35).grid(row=6, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(email_frame, text="Кому (To), через запятую:").grid(row=7, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(email_frame, textvariable=email_to_var, width=35).grid(row=7, column=1, sticky="w", padx=5, pady=2)

        # --- Telegram
        tg_frame = ttk.LabelFrame(win, text="Telegram")
        tg_frame.pack(fill=tk.X, padx=10, pady=5)

        tg_cfg = self.settings.get("telegram", {})
        tg_enabled = tk.BooleanVar(value=bool(tg_cfg.get("enabled", False)))
        ttk.Checkbutton(tg_frame, text="Включить Telegram-уведомления", variable=tg_enabled).grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        tg_token_var = tk.StringVar(value=str(tg_cfg.get("bot_token", "")))
        tg_chat_var = tk.StringVar(value=str(tg_cfg.get("chat_id", "")))

        ttk.Label(tg_frame, text="Bot token:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tg_frame, textvariable=tg_token_var, width=45).grid(row=1, column=1, sticky="w", padx=5, pady=2)

        ttk.Label(tg_frame, text="Chat ID:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tg_frame, textvariable=tg_chat_var, width=45).grid(row=2, column=1, sticky="w", padx=5, pady=2)

        # --- Buttons
        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=10, pady=10)

        def save_settings_from_ui():
            # threshold
            try:
                threshold = int(threshold_var.get().strip())
                if threshold < 0:
                    raise ValueError
            except Exception:
                messagebox.showerror("Ошибка", "Порог уведомления должен быть целым числом >= 0.")
                return

            # email
            try:
                port = int(smtp_port_var.get().strip())
                if port <= 0:
                    raise ValueError
            except Exception:
                messagebox.showerror("Ошибка", "SMTP порт должен быть целым числом > 0.")
                return

            to_list = [x.strip() for x in (email_to_var.get() or "").split(",") if x.strip()]

            # Важно: SSL и TLS одновременно обычно не включают
            if use_ssl_var.get() and use_tls_var.get():
                # не запрещаем жестко, но предупредим
                if not messagebox.askyesno("Подтверждение", "Одновременно включены SSL и TLS.\nОбычно выбирают что-то одно.\nСохранить как есть?"):
                    return

            self.settings["notify_days_threshold"] = threshold
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
            messagebox.showinfo("Сохранено", f"Настройки сохранены.\nФайл: {SETTINGS_FILE}")

        def test_email():
            save_settings_from_ui()
            if not self.settings.get("email", {}).get("enabled"):
                messagebox.showwarning("Email", "Email-уведомления выключены (галочка 'Включить' не стоит).")
                return
            try:
                self._send_email("Тест: Монитор доменов", "Это тестовое сообщение.\nЕсли вы его получили — SMTP настроен правильно.")
                messagebox.showinfo("Email", "Тестовое письмо отправлено.")
            except Exception as e:
                messagebox.showerror("Email", f"Не удалось отправить тестовое письмо:\n{e}")

        def test_telegram():
            save_settings_from_ui()
            if not self.settings.get("telegram", {}).get("enabled"):
                messagebox.showwarning("Telegram", "Telegram-уведомления выключены (галочка 'Включить' не стоит).")
                return
            try:
                self._send_telegram("Тест: Монитор доменов\nЕсли вы это видите — Telegram настроен правильно.")
                messagebox.showinfo("Telegram", "Тестовое сообщение отправлено.")
            except Exception as e:
                messagebox.showerror("Telegram", f"Не удалось отправить тестовое сообщение:\n{e}")

        ttk.Button(btns, text="Сохранить", command=save_settings_from_ui).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Тест Email", command=test_email).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Тест Telegram", command=test_telegram).pack(side=tk.LEFT, padx=5)
        ttk.Button(btns, text="Закрыть", command=win.destroy).pack(side=tk.RIGHT, padx=5)

    def _collect_domains_for_notification(self) -> list:
        threshold = int(self.settings.get("notify_days_threshold", 30))
        today_str = date.today().strftime("%Y-%m-%d")

        alerts = []
        for d in self.domains:
            days_left = d.get("days_left")
            if not isinstance(days_left, int):
                continue
            if days_left > threshold:
                continue
            # дедуп: не слать повторно в тот же день
            if d.get("last_notified") == today_str:
                continue
            alerts.append(d)

        return alerts

    def _build_notification_text(self, alerts: list) -> str:
        threshold = int(self.settings.get("notify_days_threshold", 30))
        lines = [
            f"Монитор доменов: найдено {len(alerts)} домен(ов) с окончанием <= {threshold} дн.",
            ""
        ]
        for d in alerts:
            domain = d.get("domain", "")
            expiry = d.get("expiry", "")
            days_left = d.get("days_left", "")
            link = d.get("link", "")
            line = f"- {domain} — истекает {expiry} (через {days_left} дн.)"
            if link:
                line += f" | {link}"
            lines.append(line)
        lines.append("")
        lines.append(f"Дата проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return "\n".join(lines)

    def _send_expiry_notifications_if_needed(self):
        alerts = self._collect_domains_for_notification()
        if not alerts:
            return

        text = self._build_notification_text(alerts)
        subject = "Монитор доменов: домены скоро истекают"

        email_enabled = bool(self.settings.get("email", {}).get("enabled"))
        tg_enabled = bool(self.settings.get("telegram", {}).get("enabled"))

        if not email_enabled and not tg_enabled:
            # Уведомления не включены — просто выходим
            return

        errors = []
        sent_channels = []

        if email_enabled:
            try:
                self._send_email(subject, text)
                sent_channels.append("Email")
            except Exception as e:
                errors.append(f"Email: {e}")

        if tg_enabled:
            try:
                self._send_telegram(text)
                sent_channels.append("Telegram")
            except Exception as e:
                errors.append(f"Telegram: {e}")

        if sent_channels:
            today_str = date.today().strftime("%Y-%m-%d")
            for d in alerts:
                d["last_notified"] = today_str
            self._save_domains(show_message=False)

        if errors:
            messagebox.showerror("Уведомления", "Не удалось отправить часть уведомлений:\n" + "\n".join(errors))
        elif sent_channels:
            messagebox.showinfo("Уведомления", "Уведомления отправлены: " + ", ".join(sent_channels))

    def _send_email(self, subject: str, body: str):
        cfg = self.settings.get("email", {})
        smtp_server = (cfg.get("smtp_server") or "").strip()
        smtp_port = int(cfg.get("smtp_port", 587))
        use_tls = bool(cfg.get("use_tls", True))
        use_ssl = bool(cfg.get("use_ssl", False))
        username = (cfg.get("username") or "").strip()
        password = cfg.get("password") or ""
        from_addr = (cfg.get("from_addr") or "").strip() or username
        to_addrs = cfg.get("to_addrs") or []

        if not smtp_server:
            raise ValueError("SMTP сервер не указан.")
        if not to_addrs:
            raise ValueError("Не указан получатель (To).")
        if not from_addr:
            raise ValueError("Не указан отправитель (From) и нет логина.")

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

    def _send_telegram(self, text: str):
        cfg = self.settings.get("telegram", {})
        token = (cfg.get("bot_token") or "").strip()
        chat_id = str(cfg.get("chat_id") or "").strip()

        if not token:
            raise ValueError("Telegram bot token не указан.")
        if not chat_id:
            raise ValueError("Telegram chat_id не указан.")

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True
        }

        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"})
        try:
            with urlopen(req, timeout=25) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
            raise RuntimeError(f"HTTP {e.code}: {body}") from e
        except Exception as e:
            raise RuntimeError(str(e)) from e

        # Telegram обычно возвращает JSON с ok=true/false
        try:
            parsed = json.loads(resp_body)
            if not parsed.get("ok", False):
                raise RuntimeError(resp_body)
        except json.JSONDecodeError:
            # если не JSON — всё равно считаем ошибкой
            raise RuntimeError(resp_body)


if __name__ == "__main__":
    app = DomainManagerApp()
    app.mainloop()
