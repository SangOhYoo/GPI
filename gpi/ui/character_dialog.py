import tkinter as tk
from tkinter import ttk, messagebox
import uuid
from .styles import SPACING, FONTS, COLORS
from ..core.character import load_characters, save_characters, create_character_template

class CharacterManagerDialog:
    def __init__(self, app):
        self.app = app
        self.dialog = tk.Toplevel(app.root)
        self.dialog.title("캐릭터 프로필 관리")
        self.dialog.geometry("800x600")
        self.dialog.transient(app.root)
        self.dialog.grab_set()
        
        self.characters = load_characters()
        
        main_container = ttk.Frame(self.dialog, padding=SPACING["lg"])
        main_container.pack(fill="both", expand=True)
        
        paned = ttk.PanedWindow(main_container, orient="horizontal")
        paned.pack(fill="both", expand=True)
        
        # Left Panel: Character List
        left_panel = ttk.Frame(paned)
        paned.add(left_panel, weight=1)
        
        ttk.Label(left_panel, text="캐릭터 목록", font=FONTS["bold"]).pack(anchor="w", pady=(0, SPACING["sm"]))
        
        list_frame = ttk.Frame(left_panel)
        list_frame.pack(fill="both", expand=True)
        
        self.listbox = tk.Listbox(list_frame, font=FONTS["main"], selectbackground=COLORS["accent"])
        self.listbox.pack(side="left", fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)
        
        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill="x", pady=SPACING["sm"])
        ttk.Button(btn_frame, text="새 캐릭터", command=self.on_new).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame, text="삭제", command=self.on_delete).pack(side="left", fill="x", expand=True, padx=(2, 0))
        
        # Right Panel: Character Editor
        self.right_panel = ttk.LabelFrame(paned, text="캐릭터 정보", padding=SPACING["md"])
        paned.add(self.right_panel, weight=3)
        
        self.current_index = -1
        self.create_editor_ui()
        
        self.refresh_list()
        
    def create_editor_ui(self):
        # Create a scrollable frame for the editor
        canvas = tk.Canvas(self.right_panel, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.right_panel, orient="vertical", command=canvas.yview)
        self.editor_frame = ttk.Frame(canvas)
        
        self.editor_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.editor_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Form fields
        self.vars = {}
        
        def add_field(row, label, key, height=1):
            ttk.Label(self.editor_frame, text=label).grid(row=row, column=0, sticky="nw", pady=2)
            if height == 1:
                var = tk.StringVar()
                entry = ttk.Entry(self.editor_frame, textvariable=var, width=50)
                entry.grid(row=row, column=1, sticky="ew", pady=2, padx=5)
                self.vars[key] = {"type": "entry", "var": var, "widget": entry}
            else:
                text = tk.Text(self.editor_frame, height=height, width=50, font=FONTS["main"])
                text.grid(row=row, column=1, sticky="ew", pady=2, padx=5)
                self.vars[key] = {"type": "text", "widget": text}
                
        add_field(0, "이름:", "name")
        
        ttk.Label(self.editor_frame, text="[인적사항]", font=FONTS["bold"]).grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 5))
        add_field(2, "나이:", "age")
        add_field(3, "성별:", "gender")
        add_field(4, "인종/국적:", "ethnicity")
        
        ttk.Label(self.editor_frame, text="[외형]", font=FONTS["bold"]).grid(row=5, column=0, columnspan=2, sticky="w", pady=(10, 5))
        add_field(6, "헤어스타일:", "hair")
        add_field(7, "이목구비:", "facial_features")
        add_field(8, "체형:", "body_type")
        
        ttk.Label(self.editor_frame, text="[기타 특징]", font=FONTS["bold"]).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 5))
        add_field(10, "기본 의상:", "default_outfit", height=2)
        add_field(11, "성격/시각적 단서:", "personality_cues", height=3)
        add_field(12, "주요 관계도:", "key_relationships", height=3)
        
        self.editor_frame.columnconfigure(1, weight=1)
        
        save_btn = ttk.Button(self.editor_frame, text="저장", command=self.on_save)
        save_btn.grid(row=13, column=1, sticky="e", pady=15, padx=5)
        
        self.clear_editor()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        for c in self.characters:
            name = c.get("name", "이름 없음")
            self.listbox.insert(tk.END, name)

    def clear_editor(self):
        for key, field in self.vars.items():
            if field["type"] == "entry":
                field["var"].set("")
            elif field["type"] == "text":
                field["widget"].delete("1.0", "end")
        self.current_index = -1

    def load_into_editor(self, index):
        if index < 0 or index >= len(self.characters):
            return
            
        c = self.characters[index]
        self.current_index = index
        
        def set_val(key, val):
            field = self.vars.get(key)
            if not field: return
            if field["type"] == "entry":
                field["var"].set(val or "")
            elif field["type"] == "text":
                field["widget"].delete("1.0", "end")
                if val:
                    field["widget"].insert("end", val)
                    
        set_val("name", c.get("name"))
        demo = c.get("demographics", {})
        set_val("age", demo.get("age"))
        set_val("gender", demo.get("gender"))
        set_val("ethnicity", demo.get("ethnicity"))
        
        app = c.get("appearance", {})
        set_val("hair", app.get("hair"))
        set_val("facial_features", app.get("facial_features"))
        set_val("body_type", app.get("body_type"))
        
        set_val("default_outfit", c.get("default_outfit"))
        set_val("personality_cues", c.get("personality_cues"))
        set_val("key_relationships", c.get("key_relationships"))

    def on_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            self.load_into_editor(sel[0])

    def on_new(self):
        self.clear_editor()
        self.listbox.selection_clear(0, tk.END)
        self.current_index = -1

    def on_delete(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.characters[idx].get("name", "이름 없음")
        if messagebox.askyesno("삭제 확인", f"'{name}' 캐릭터를 삭제하시겠습니까?"):
            del self.characters[idx]
            save_characters(self.characters)
            self.refresh_list()
            self.clear_editor()
            if hasattr(self.app, "refresh_characters_ui"):
                self.app.refresh_characters_ui()

    def on_save(self):
        def get_val(key):
            field = self.vars.get(key)
            if not field: return ""
            if field["type"] == "entry":
                return field["var"].get().strip()
            elif field["type"] == "text":
                return field["widget"].get("1.0", "end-1c").strip()
                
        name = get_val("name")
        if not name:
            messagebox.showwarning("입력 오류", "이름은 필수 입력 항목입니다.")
            return
            
        c = create_character_template() if self.current_index == -1 else self.characters[self.current_index]
        
        c["name"] = name
        c["demographics"] = {
            "age": get_val("age"),
            "gender": get_val("gender"),
            "ethnicity": get_val("ethnicity")
        }
        c["appearance"] = {
            "hair": get_val("hair"),
            "facial_features": get_val("facial_features"),
            "body_type": get_val("body_type")
        }
        c["default_outfit"] = get_val("default_outfit")
        c["personality_cues"] = get_val("personality_cues")
        c["key_relationships"] = get_val("key_relationships")
        
        if self.current_index == -1:
            self.characters.append(c)
        else:
            self.characters[self.current_index] = c
            
        save_characters(self.characters)
        self.refresh_list()
        
        # select the saved item
        idx = self.characters.index(c)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(idx)
        self.current_index = idx
        
        messagebox.showinfo("저장 완료", f"'{name}' 프로필이 저장되었습니다.")
        
        if hasattr(self.app, "refresh_characters_ui"):
            self.app.refresh_characters_ui()
