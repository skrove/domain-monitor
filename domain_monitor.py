import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import os
from datetime import datetime

try:
    import whois
except ImportError:
    whois = None

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None


DATA_FILE = "domains.json"


class DomainManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Монитор доменов")
        self.geometry("1000x500")

        self.domains = []
        self._load_domains()

        self._create_widgets()
        self._refresh_table()

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

        export_btn = ttk.Button(btn_frame, text="Экспорт в Excel", command=self.export_to_excel)
        export_btn.pack(side=tk.LEFT, padx=5)

        del_btn = ttk.Button(btn_frame, text="Удалить выбранный", command=self.delete_selected)
        del_btn.pack(side=tk.LEFT, padx=5)

        save_btn = ttk.Button(btn_frame, text="Сохранить список", command=self._save_domains)
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

    def _load_domains(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    self.domains = json.load(f)
            except Exception:
                self.domains = []

    def _save_domains(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.domains, f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Сохранено", "Список доменов сохранён.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")

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
            })

        self._refresh_table()
        self._save_domains()

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
        self._save_domains()

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

    def check_domains(self):
        if whois is None:
            messagebox.showerror(
                "Ошибка",
                "Модуль 'python-whois' не установлен.\nУстановите: pip install python-whois"
            )
            return

        now = datetime.now()
        for d in self.domains:
            domain_name = d.get("domain")
            if not domain_name:
                continue
            try:
                info = whois.whois(domain_name)
                exp = info.expiration_date

                # expiration_date может быть списком
                if isinstance(exp, list):
                    exp = min(e for e in exp if e is not None)

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
                    d["days_left"] = days_left
            except Exception as e:
                d["expiry"] = f"Ошибка: {e}"
                d["days_left"] = None

        self.sort_by_expiry()
        self._refresh_table()
        self._save_domains()

    def sort_by_expiry(self):
        # Сначала домены с минимальным days_left, None в конце
        self.domains.sort(
            key=lambda d: (
                d.get("days_left") is None,
                d.get("days_left") if d.get("days_left") is not None else 10**9
            )
        )
        self._refresh_table()

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


if __name__ == "__main__":
    app = DomainManagerApp()
    app.mainloop()
