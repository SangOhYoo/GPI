import sys
import re

with open('d:/GPI_New/gpi/ui/window.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add Remix Tab
remix_tab_str = '''
        # Tab 4: Prompt Remix [NEW]
        self.remix_tab = ttk.Frame(self.input_notebook)
        self.input_notebook.add(self.remix_tab, text="프롬프트 조합기")
        
        ttk.Label(self.remix_tab, text="히스토리 조각 조합:", font=FONTS["bold"]).pack(anchor="w", pady=(0, SPACING["xs"]))
        
        remix_container = ttk.Frame(self.remix_tab)
        remix_container.pack(fill="both", expand=True)
        
        # We will dynamically populate comboboxes for attributes
        self.remix_combos = {}
        self.remix_attributes = ["Background_Lighting", "Person", "Character_Expressions", "Pose", "Outfit", "Camera", "Mood_Color", "Style"]
        
        remix_canvas = tk.Canvas(remix_container, highlightthickness=0)
        remix_scrollbar = ttk.Scrollbar(remix_container, orient="vertical", command=remix_canvas.yview)
        self.remix_scrollable_frame = ttk.Frame(remix_canvas)
        
        self.remix_scrollable_frame.bind(
            "<Configure>",
            lambda e: remix_canvas.configure(
                scrollregion=remix_canvas.bbox("all")
            )
        )
        
        remix_canvas.create_window((0, 0), window=self.remix_scrollable_frame, anchor="nw")
        remix_canvas.configure(yscrollcommand=remix_scrollbar.set)
        
        remix_canvas.pack(side="left", fill="both", expand=True)
        remix_scrollbar.pack(side="right", fill="y")
        
        for attr in self.remix_attributes:
            lbl = ttk.Label(self.remix_scrollable_frame, text=attr.replace("_", "/"))
            lbl.pack(anchor="w", pady=(SPACING["xs"], 0))
            cb = ttk.Combobox(self.remix_scrollable_frame, values=[], state="normal")
            cb.pack(fill="x", pady=(0, SPACING["sm"]))
            self.remix_combos[attr] = cb
            
        remix_btn_frame = ttk.Frame(self.remix_tab)
        remix_btn_frame.pack(fill="x", pady=SPACING["sm"])
        ttk.Button(remix_btn_frame, text="내용 비우기", command=self.clear_remix).pack(side="right")
        ttk.Button(remix_btn_frame, text="목록 새로고침", command=self.refresh_remix_options).pack(side="left")
'''
content = content.replace('        # Bottom Options (Shared or common area)', remix_tab_str + '\n        # Bottom Options (Shared or common area)')

# 2. Add imports for generate_remix_logic
content = content.replace('generate_prompt_augmentation_logic\n)', 'generate_prompt_augmentation_logic,\n    generate_remix_logic\n)')

# 3. Add methods for Remix logic
methods_str = '''
    def clear_remix(self):
        for cb in self.remix_combos.values():
            cb.set("")
            
    def refresh_remix_options(self):
        fragments = {attr: set() for attr in self.remix_attributes}
        
        history = load_history()
        for item in history:
            en_text = item.get("en", "")
            lines = en_text.split("\\n")
            for line in lines:
                if ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip().replace(" ", "_").replace("/", "_")
                    val = val.strip()
                    if key in fragments and val:
                        fragments[key].add(val)
                        
        for attr in self.remix_attributes:
            opts = sorted(list(fragments[attr]))
            self.remix_combos[attr]["values"] = opts
'''
content = content.replace('    def _schedule_check_status(self):', methods_str + '\n    def _schedule_check_status(self):')

# 4. Modify handle_generate dispatcher
handle_generate_new = '''    def handle_generate(self):
        """Dispatches to either image, text, prompt, or remix generation based on active tab."""
        active_tab = self.input_notebook.index("current")
        if active_tab == 0: # Image Tab
            self.do_generate_prompt()
        elif active_tab == 1: # Text Tab
            self.do_generate_from_text()
        elif active_tab == 2: # Prompt Augmentation Tab
            self.do_generate_prompt_augmentation()
        elif active_tab == 3: # Prompt Remix Tab
            self.do_generate_remix()'''
            
content = re.sub(r'    def handle_generate\(self\):.*?elif active_tab == 2: # Prompt Augmentation Tab\n            self.do_generate_prompt_augmentation\(\)', handle_generate_new, content, flags=re.DOTALL)


# 5. Add do_generate_remix
do_generate_remix_str = '''
    def do_generate_remix(self):
        assembled_lines = []
        for attr in self.remix_attributes:
            val = self.remix_combos[attr].get().strip()
            if val:
                assembled_lines.append(f"{attr.replace('_', '/')}: {val}")
                
        if not assembled_lines:
            messagebox.showwarning("입력 필요", "리믹스할 항목을 하나 이상 선택하거나 입력하세요.", parent=self.root)
            self.on_cancel()
            return
            
        assembled_text = "\\n".join(assembled_lines)
        api_key, model_name, thinking_level, keyword_text = self._get_generation_params()
        if not api_key:
            return

        self.append_log("프롬프트 조합(Remix) 수정 작업을 시작합니다...")
        threading.Thread(target=self._run_remix_task, args=(assembled_text, api_key, model_name, thinking_level, keyword_text), daemon=True).start()

    def _run_remix_task(self, assembled_text, api_key, model_name, thinking_level, keyword_text):
        try:
            result, word_count = generate_remix_logic(
                assembled_text=assembled_text,
                api_key=api_key,
                model_name=model_name,
                thinking_level=thinking_level,
                keyword_text=keyword_text,
                on_chunk=self._on_chunk,
                cancel_check=lambda: self.is_cancelled,
                on_pass1_done=self._on_pass1_done,
                on_pass2_chunk=self._on_pass2_chunk
            )
            
            if self.is_cancelled:
                return

            self.root.after(0, self._on_generation_complete, result, word_count, {"type": "text_input", "value": assembled_text})
        except Exception as e:
            if not self.is_cancelled:
                self.root.after(0, self._on_generation_error, e)
'''

content = content.replace('    def _run_prompt_augmentation_task(self', do_generate_remix_str + '\n    def _run_prompt_augmentation_task(self')

# 6. Call refresh_remix_options on init
content = content.replace('self.refresh_characters_ui()', 'self.refresh_characters_ui()\n        self.refresh_remix_options()')


with open('d:/GPI_New/gpi/ui/window.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Updated window.py successfully.')
