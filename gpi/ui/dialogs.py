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


from ..core.prompt import (
    load_presets, save_presets, extract_all_attributes, 
    add_prompt_preset, add_attribute_preset, delete_preset,
    CATEGORY_KOREAN_NAMES
)
from tkinter import simpledialog
from .styles import FONTS, COLORS

class JsonAttributeFavoriteDialog:
    def __init__(self, app, entry):
        self.app = app
        self.entry = entry
        self.dialog = tk.Toplevel(app.root)
        self.dialog.title("JSON 속성 탐색 및 즐겨찾기")
        self.dialog.geometry("780x580")
        self.dialog.transient(app.root)
        self.dialog.grab_set()
        
        container = ttk.Frame(self.dialog, padding=SPACING["lg"])
        container.pack(fill="both", expand=True)
        
        ttk.Label(container, text="JSON 및 프롬프트 세부 속성 목록", font=FONTS["bold"]).pack(anchor="w", pady=(0, SPACING["xs"]))
        ttk.Label(container, text="속성을 선택하여 즐겨찾기(프리셋)에 등록하거나 값을 복사할 수 있습니다.", foreground=COLORS["text_secondary"]).pack(anchor="w", pady=(0, SPACING["sm"]))
        
        # Search Frame
        search_frame = ttk.Frame(container)
        search_frame.pack(fill="x", pady=(0, SPACING["sm"]))
        ttk.Label(search_frame, text="검색/필터:").pack(side="left", padx=(0, SPACING["xs"]))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING["sm"]))
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_list())
        ttk.Button(search_frame, text="초기화", command=lambda: (self.search_var.set(""), self.filter_list())).pack(side="right")
        
        # Treeview
        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill="both", expand=True, pady=(0, SPACING["md"]))
        
        self.tree = ttk.Treeview(tree_frame, columns=("category", "key", "value"), show="headings", height=14)
        self.tree.heading("category", text="분류 (Category)")
        self.tree.heading("key", text="속성명 (Key/Path)")
        self.tree.heading("value", text="내용 (Value)")
        
        self.tree.column("category", width=140, stretch=False)
        self.tree.column("key", width=220, stretch=False)
        self.tree.column("value", width=360, stretch=True)
        
        self.tree.pack(side="left", fill="both", expand=True)
        
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        
        # Buttons
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x")
        
        ttk.Button(btn_frame, text="⭐ 선택 속성 즐겨찾기 추가", style="Accent.TButton", command=self.on_add_favorite).pack(side="left")
        ttk.Button(btn_frame, text="📋 내용 복사", command=self.on_copy_value).pack(side="left", padx=(SPACING["sm"], 0))
        ttk.Button(btn_frame, text="닫기", command=self.dialog.destroy).pack(side="right")
        
        self.all_items = []
        self._load_data()
        self.filter_list()
        
        self.tree.bind("<Double-1>", lambda e: self.on_add_favorite())

    def _load_data(self):
        attr_data = extract_all_attributes(self.entry)
        attrs = attr_data["attributes"]
        flat_json = attr_data["flat_json"]
        
        seen = set()
        
        # Structured attributes
        for cat_key, cat_dict in attrs.items():
            cat_label = CATEGORY_KOREAN_NAMES.get(cat_key, cat_key)
            for k, val in cat_dict.items():
                if val:
                    pair = (cat_key, k, val)
                    if pair not in seen:
                        seen.add(pair)
                        self.all_items.append({
                            "category": cat_label,
                            "cat_key": cat_key,
                            "key": k,
                            "value": val
                        })
                        
        # Flat JSON items
        for path, val in flat_json:
            pair = ("custom", path, val)
            if pair not in seen:
                seen.add(pair)
                self.all_items.append({
                    "category": "JSON 세부",
                    "cat_key": "custom",
                    "key": path,
                    "value": val
                })

    def filter_list(self):
        query = self.search_var.get().lower().strip()
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for it in self.all_items:
            cat = it["category"]
            key = it["key"]
            val = it["value"]
            if not query or query in cat.lower() or query in key.lower() or query in val.lower():
                self.tree.insert("", "end", values=(cat, key, val), tags=(it["cat_key"],))

    def on_add_favorite(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("알림", "즐겨찾기에 추가할 속성을 선택하세요.", parent=self.dialog)
            return
            
        item = self.tree.item(sel[0])
        vals = item["values"]
        tags = item.get("tags", ())
        cat_key = tags[0] if tags else "custom"
        attr_key = str(vals[1])
        val = str(vals[2]).strip()
        
        default_name = (val[:30] + "...") if len(val) > 30 else val
        name = simpledialog.askstring("즐겨찾기 추가", f"'{attr_key}' 속성의 즐겨찾기 이름을 입력하세요:", initialvalue=default_name, parent=self.dialog)
        if name is not None:
            name = name.strip()
            if not name:
                name = default_name
            if add_attribute_preset(cat_key, name, val):
                messagebox.showinfo("완료", f"'{name}' 즐겨찾기가 저장되었습니다.", parent=self.dialog)
                if hasattr(self.app, "refresh_presets_combos"):
                    self.app.refresh_presets_combos()
                if hasattr(self.app, "refresh_remix_options"):
                    self.app.refresh_remix_options()
                if hasattr(self.app, "refresh_favorites_tab"):
                    self.app.refresh_favorites_tab()
            else:
                messagebox.showerror("오류", "즐겨찾기 저장에 실패했습니다.", parent=self.dialog)

    def on_copy_value(self):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        val = str(item["values"][2])
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(val)
        messagebox.showinfo("복사 완료", "클립보드에 복사되었습니다.", parent=self.dialog)


class PresetManagerDialog:
    def __init__(self, app):
        self.app = app
        self.dialog = tk.Toplevel(app.root)
        self.dialog.title("즐겨찾기 및 프리셋 관리")
        self.dialog.geometry("880x620")
        self.dialog.transient(app.root)
        self.dialog.grab_set()
        
        container = ttk.Frame(self.dialog, padding=SPACING["lg"])
        container.pack(fill="both", expand=True)
        
        top_bar = ttk.Frame(container)
        top_bar.pack(fill="x", pady=(0, SPACING["md"]))
        
        ttk.Label(top_bar, text="카테고리 분류:", font=FONTS["bold"]).pack(side="left", padx=(0, SPACING["xs"]))
        self.cat_var = tk.StringVar(value="(전체)")
        self.cat_combo = ttk.Combobox(
            top_bar, textvariable=self.cat_var, state="readonly", width=28,
            values=["(전체)", "전체 프롬프트 (prompts)", "표정 (expressions)", "포즈 (poses)", 
                    "배경/조명 (Background_Lighting)", "인물 (Person)", "의상 (Outfit)", 
                    "카메라 (Camera)", "분위기/색상 (Mood_Color)", "스타일 (Style)", "기타 JSON 속성 (custom)"]
        )
        self.cat_combo.pack(side="left", padx=(0, SPACING["md"]))
        self.cat_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_list())
        
        ttk.Button(top_bar, text="새로고침", command=self.refresh_list).pack(side="left")
        
        # Treeview
        tree_frame = ttk.Frame(container)
        tree_frame.pack(fill="both", expand=True, pady=(0, SPACING["md"]))
        
        self.tree = ttk.Treeview(tree_frame, columns=("category", "name", "preview"), show="headings", height=15)
        self.tree.heading("category", text="카테고리")
        self.tree.heading("name", text="즐겨찾기 이름")
        self.tree.heading("preview", text="내용 / 영문 프롬프트")
        
        self.tree.column("category", width=140, stretch=False)
        self.tree.column("name", width=180, stretch=False)
        self.tree.column("preview", width=480, stretch=True)
        
        self.tree.pack(side="left", fill="both", expand=True)
        
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        
        # Action Buttons
        btn_frame = ttk.Frame(container)
        btn_frame.pack(fill="x")
        
        ttk.Button(btn_frame, text="적용 / 불러오기", style="Accent.TButton", command=self.on_apply).pack(side="left")
        ttk.Button(btn_frame, text="내용 복사", command=self.on_copy).pack(side="left", padx=SPACING["sm"])
        ttk.Button(btn_frame, text="이름 수정", command=self.on_rename).pack(side="left")
        ttk.Button(btn_frame, text="삭제", command=self.on_delete).pack(side="left", padx=SPACING["sm"])
        ttk.Button(btn_frame, text="닫기", command=self.dialog.destroy).pack(side="right")
        
        self.refresh_list()
        self.tree.bind("<Double-1>", lambda e: self.on_apply())
        
    def refresh_list(self):
        for it in self.tree.get_children():
            self.tree.delete(it)
            
        presets = load_presets()
        selected_cat = self.cat_var.get()
        
        cat_map = {
            "전체 프롬프트 (prompts)": "prompts",
            "표정 (expressions)": "expressions",
            "포즈 (poses)": "poses",
            "배경/조명 (Background_Lighting)": "Background_Lighting",
            "인물 (Person)": "Person",
            "의상 (Outfit)": "Outfit",
            "카메라 (Camera)": "Camera",
            "분위기/색상 (Mood_Color)": "Mood_Color",
            "스타일 (Style)": "Style",
            "기타 JSON 속성 (custom)": "custom"
        }
        
        filter_key = cat_map.get(selected_cat, None)
        
        for cat_key, items in presets.items():
            if filter_key and cat_key != filter_key:
                continue
            if not isinstance(items, dict):
                continue
                
            cat_label = CATEGORY_KOREAN_NAMES.get(cat_key, cat_key)
            for name, val in sorted(items.items()):
                if cat_key == "prompts" and isinstance(val, dict):
                    preview = val.get("en", "")[:80].replace("\n", " ")
                else:
                    preview = str(val)[:80].replace("\n", " ")
                    
                self.tree.insert("", "end", values=(cat_label, name, preview), tags=(cat_key, name))

    def on_apply(self):
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        presets = load_presets()
        val = presets.get(cat_key, {}).get(name)
        if not val:
            return
            
        if cat_key == "prompts" and isinstance(val, dict):
            # Load full prompt into app outputs
            self.app.output_text.delete("1.0", "end")
            self.app.output_text.insert("1.0", val.get("en", ""))
            self.app.translation_text.delete("1.0", "end")
            self.app.translation_text.insert("1.0", val.get("ko", ""))
            self.app.translation_zh_text.delete("1.0", "end")
            self.app.translation_zh_text.insert("1.0", val.get("zh", ""))
            self.app.json_output_text.delete("1.0", "end")
            self.app.json_output_text.insert("1.0", val.get("json", ""))
            self.app.json_ko_output_text.delete("1.0", "end")
            self.app.json_ko_output_text.insert("1.0", val.get("json_ko", ""))
            if hasattr(self.app, "keyword_text") and val.get("keyword"):
                self.app.keyword_text.delete("1.0", "end")
                self.app.keyword_text.insert("1.0", val.get("keyword"))
            self.app.status_var.set(f"즐겨찾기 프롬프트 '{name}'을(를) 불러왔습니다.")
            messagebox.showinfo("불러오기 완료", f"전체 프롬프트 '{name}'을(를) 결과창에 불러왔습니다.", parent=self.dialog)
        else:
            val_str = str(val)
            if cat_key in ["expressions", "Character_Expressions"]:
                self.app.preset_expression_var.set(name)
            elif cat_key in ["poses", "Pose"]:
                self.app.preset_pose_var.set(name)
            elif hasattr(self.app, "remix_combos") and cat_key in self.app.remix_combos:
                self.app.remix_combos[cat_key].set(val_str)
                
            self.dialog.clipboard_clear()
            self.dialog.clipboard_append(val_str)
            self.app.status_var.set(f"즐겨찾기 '{name}' 적용 및 복사 완료")
            messagebox.showinfo("적용 완료", f"'{name}' 값이 적용되었으며 클립보드에 복사되었습니다.", parent=self.dialog)

    def on_copy(self):
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        presets = load_presets()
        val = presets.get(cat_key, {}).get(name)
        if not val:
            return
        if cat_key == "prompts" and isinstance(val, dict):
            text = val.get("en", "")
        else:
            text = str(val)
        self.dialog.clipboard_clear()
        self.dialog.clipboard_append(text)
        messagebox.showinfo("복사 완료", "클립보드에 복사되었습니다.", parent=self.dialog)

    def on_rename(self):
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, old_name = tags[0], tags[1]
        new_name = simpledialog.askstring("이름 수정", "새 이름을 입력하세요:", initialvalue=old_name, parent=self.dialog)
        if new_name and new_name.strip() and new_name.strip() != old_name:
            new_name = new_name.strip()
            presets = load_presets()
            if cat_key in presets and old_name in presets[cat_key]:
                presets[cat_key][new_name] = presets[cat_key].pop(old_name)
                save_presets(presets)
                self.refresh_list()
                if hasattr(self.app, "refresh_presets_combos"):
                    self.app.refresh_presets_combos()
                if hasattr(self.app, "refresh_remix_options"):
                    self.app.refresh_remix_options()
                if hasattr(self.app, "refresh_favorites_tab"):
                    self.app.refresh_favorites_tab()

    def on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        tags = self.tree.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        if messagebox.askyesno("삭제 확인", f"'{name}' 즐겨찾기를 삭제하시겠습니까?", parent=self.dialog):
            delete_preset(cat_key, name)
            self.refresh_list()
            if hasattr(self.app, "refresh_presets_combos"):
                self.app.refresh_presets_combos()
            if hasattr(self.app, "refresh_remix_options"):
                self.app.refresh_remix_options()
            if hasattr(self.app, "refresh_favorites_tab"):
                self.app.refresh_favorites_tab()
