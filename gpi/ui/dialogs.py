import tkinter as tk
from tkinter import ttk, messagebox
from .styles import SPACING
from ..core.config import load_api_keys, save_api_keys

class ApiKeyDialog:
    def __init__(self, app):
        self.app = app
        self.dialog = tk.Toplevel(app.root)
        self.dialog.title("API 키 관리")
        self.dialog.geometry("500x400")
        self.dialog.transient(app.root)
        self.dialog.grab_set()
        
        self.keys = load_api_keys()
        
        container = ttk.Frame(self.dialog, padding=(SPACING["lg"], SPACING["lg"]))
        container.pack(fill="both", expand=True)
        
        ttk.Label(container, text="등록된 API 키 목록", font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        
        # Treeview for Key List
        list_frame = ttk.Frame(container)
        list_frame.pack(fill="both", expand=True, pady=(SPACING["xs"], SPACING["md"]))
        
        self.tree = ttk.Treeview(list_frame, columns=("name", "key"), show="headings", height=8)
        self.tree.heading("name", text="키 이름")
        self.tree.heading("key", text="API 키")
        self.tree.column("name", width=100)
        self.tree.column("key", width=250)
        self.tree.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        
        # Entry fields for adding new key
        entry_frame = ttk.LabelFrame(container, text="키 추가/수정", padding=SPACING["sm"])
        entry_frame.pack(fill="x", pady=(0, SPACING["md"]))
        
        ttk.Label(entry_frame, text="키 이름:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(entry_frame, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, sticky="ew", padx=(SPACING["xs"], 0))
        
        ttk.Label(entry_frame, text="API 키:").grid(row=1, column=0, sticky="w", pady=(SPACING["xs"], 0))
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(entry_frame, textvariable=self.key_var, show="*")
        self.key_entry.grid(row=1, column=1, sticky="ew", padx=(SPACING["xs"], 0), pady=(SPACING["xs"], 0))
        
        entry_frame.columnconfigure(1, weight=1)
        
        # Buttons
        btn_row = ttk.Frame(container)
        btn_row.pack(fill="x")
        
        ttk.Button(btn_row, text="삭제", command=self.on_delete).pack(side="left")
        ttk.Button(btn_row, text="추가/갱신", command=self.on_add).pack(side="right")
        
        self.refresh_list()
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def refresh_list(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        for name, key in self.keys.items():
            masked_key = key[:4] + "*" * (len(key)-8) + key[-4:] if len(key) > 8 else "****"
            self.tree.insert("", "end", values=(name, masked_key))

    def on_select(self, event):
        selected = self.tree.selection()
        if selected:
            item = self.tree.item(selected[0])
            name = item["values"][0]
            self.name_var.set(name)
            self.key_var.set(self.keys.get(name, ""))

    def on_add(self):
        name = self.name_var.get().strip()
        key = self.key_var.get().strip()
        if not name or not key:
            messagebox.showwarning("알림", "이름과 키를 모두 입력하세요.")
            return
        
        self.keys[name] = key
        save_api_keys(self.keys)
        self.refresh_list()
        if hasattr(self.app, "refresh_api_keys"):
            self.app.refresh_api_keys()
        messagebox.showinfo("완료", f"'{name}' 키가 저장되었습니다.")

    def on_delete(self):
        selected = self.tree.selection()
        if not selected:
            return
        name = self.tree.item(selected[0])["values"][0]
        if messagebox.askyesno("확인", f"'{name}' 키를 삭제할까요?"):
            del self.keys[name]
            save_api_keys(self.keys)
            self.refresh_list()
            self.name_var.set("")
            self.key_var.set("")
            if hasattr(self.app, "refresh_api_keys"):
                self.app.refresh_api_keys()
