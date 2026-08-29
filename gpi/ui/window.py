import threading
import tkinter as tk
import queue
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path

from .styles import COLORS, SPACING, FONTS
from .dialogs import ApiKeyDialog, JsonAttributeFavoriteDialog, PresetManagerDialog
from .character_dialog import CharacterManagerDialog
from .dnd import (
    setup_dnd, get_image_from_clipboard, WIN_DND_AVAILABLE,
    CF_FILEDESCRIPTORW, CF_FILEDESCRIPTORA, CF_FILECONTENTS,
    CF_URLW, CF_URLA, CF_PNG, CF_WEBP, CF_DIB
)
from ..core.config import (
    MODEL_OPTIONS, MODEL_THINKING_LEVELS, get_api_key, 
    CANCELLED_MESSAGE, load_api_keys, DEFAULT_KEYWORD,
    MIN_PROMPT_WORDS, MAX_PROMPT_WORDS, 
    HIGH_FIDELITY_MIN_WORDS, HIGH_FIDELITY_MAX_WORDS
)
from ..core.image import (
    prepare_image_bytes, detect_mime_from_bytes, 
    parse_file_group_descriptor, parse_dropfiles,
    read_istream_all
)
from ..core.api import download_image_from_url, validate_model_access, fetch_available_models, is_url
from ..core.prompt import (
    generate_prompt_logic, append_history, load_history, 
    save_all_history, delete_history_item_files,
    load_presets, save_presets, extract_pose_and_expression,
    extract_all_attributes, add_prompt_preset, add_attribute_preset,
    delete_preset, CATEGORY_KOREAN_NAMES,
    assemble_text_prompt
)
from ..core.utils import log_event
try:
    import pythoncom
    import win32con
except ImportError:
    pythoncom = None
    win32con = None
from PIL import Image, ImageTk
from io import BytesIO

class PromptApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GPI - Gemini Prompt Instrument")
        self.root.geometry("1200x1680")
        
        # State
        self.image_source = None
        self.preview_image = None
        self.generation_in_progress = False
        self.cancel_requested = False
        self.image_history_indices = []
        self.text_history_indices = []
        self.model_name = "gemini-1.5-flash"
        self.model_thinking_level = 0
        self.download_in_progress = False
        self.history = load_history()
        self.generation_queue = []
        self.queue_total_count = 0
        self.queue_processed_count = 0

        # Variable Initialization
        self.model_var = tk.StringVar(value=self.model_name)
        self.enable_thinking_var = tk.BooleanVar(value=True)
        self.api_key_name_var = tk.StringVar(value="Default")
        self.file_path_var = tk.StringVar(value="선택된 파일 없음")
        self.keyword_var = tk.StringVar(value=DEFAULT_KEYWORD)
        self.status_var = tk.StringVar(value="대기 중")
        
        # Fidelity and Word Count State
        self.high_fidelity_var = tk.BooleanVar(value=True)
        self.min_words_var = tk.IntVar(value=HIGH_FIDELITY_MIN_WORDS)
        self.max_words_var = tk.IntVar(value=HIGH_FIDELITY_MAX_WORDS)
        
        # History State
        self.image_history_indices = []
        self.text_history_indices = []
        self.current_history_index = None
        
        # OLE Drag and Drop State
        self._win_drop_data_obj = None
        self._win_drop_formats = {}
        self.drop_queue = queue.Queue()
        
        # Translation State
        self.translated_text = ""
        self.preview_image = None
        
        # OLE targets
        self._win_target = None
        self._win_com_target = None
        
        self.setup_ui()
        self.setup_dnd()
        self.refresh_history_list()
        self.refresh_favorites_tab()
        
        # Initial model fetch
        self.root.after(100, self.refresh_models)
        
        log_event("app_start")

    def refresh_models(self):
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not api_key:
            from gpi.core.config import get_local_llama_cpp_models
            local_models = get_local_llama_cpp_models()
            default_model = local_models[0] if local_models else "local-llama-cpp"
            self.model_combo["values"] = local_models if local_models else ["local-llama-cpp"]
            if not self.model_name.startswith("local-llama-cpp"):
                self.model_name = default_model
                self.model_var.set(default_model)
            return

        def fetch():
            try:
                models = fetch_available_models(api_key)
                if models:
                    self.root.after(0, lambda: self.update_model_list(models))
                    log_event("models_fetched", {"count": len(models)})
            except Exception as e:
                log_event("model_fetch_error", {"error": str(e)})

        threading.Thread(target=fetch, daemon=True).start()

    def update_model_list(self, models):
        from gpi.core.config import get_local_llama_cpp_models
        local_models = get_local_llama_cpp_models()
        for m in local_models:
            if m not in models:
                models.append(m)
        self.model_combo["values"] = models
        if self.model_name not in models:
            # Preferred order: flash-latest -> 2.0-flash -> 1.5-flash -> first available
            if "gemini-flash-latest" in models:
                self.model_name = "gemini-flash-latest"
            elif "gemini-2.0-flash" in models:
                self.model_name = "gemini-2.0-flash"
            elif "gemini-1.5-flash" in models:
                self.model_name = "gemini-1.5-flash"
            else:
                self.model_name = models[0]
            self.model_var.set(self.model_name)
            self.model_thinking_level = MODEL_THINKING_LEVELS.get(self.model_name)
        else:
            self.model_var.set(self.model_name)

    def open_character_manager(self):
        CharacterManagerDialog(self)
        
    def refresh_characters_ui(self):
        from gpi.core.character import load_characters
        chars = load_characters()
        
        if not hasattr(self, "char_inner_frame"):
            return
            
        for widget in self.char_inner_frame.winfo_children():
            widget.destroy()
            
        self.character_vars = {}
        
        if not chars:
            ttk.Label(self.char_inner_frame, text="등록된 캐릭터가 없습니다. '캐릭터 관리'에서 추가하세요.", foreground="gray").pack(side="left")
            return
            
        for c in chars:
            c_id = c.get("id")
            c_name = c.get("name", "Unknown")
            var = tk.BooleanVar(value=False)
            self.character_vars[c_id] = var
            cb = ttk.Checkbutton(self.char_inner_frame, text=c_name, variable=var)
            cb.pack(side="left", padx=5)

    def refresh_presets_combos(self):
        presets = load_presets()
        
        expr_names = sorted(list(presets.get("expressions", {}).keys()))
        self.preset_expression_combo["values"] = ["(사용 안 함)"] + expr_names
        if not self.preset_expression_var.get() or self.preset_expression_var.get() not in self.preset_expression_combo["values"]:
            self.preset_expression_var.set("(사용 안 함)")
            
        pose_names = sorted(list(presets.get("poses", {}).keys()))
        self.preset_pose_combo["values"] = ["(사용 안 함)"] + pose_names
        if not self.preset_pose_var.get() or self.preset_pose_var.get() not in self.preset_pose_combo["values"]:
            self.preset_pose_var.set("(사용 안 함)")

    def _get_override_presets(self):
        presets = load_presets()
        
        sel_expr_name = self.preset_expression_var.get()
        expression_override = None
        if sel_expr_name and sel_expr_name != "(사용 안 함)":
            expression_override = presets.get("expressions", {}).get(sel_expr_name)
            
        sel_pose_name = self.preset_pose_var.get()
        pose_override = None
        if sel_pose_name and sel_pose_name != "(사용 안 함)":
            pose_override = presets.get("poses", {}).get(sel_pose_name)
            
        return pose_override, expression_override

    def get_active_character_ids(self):
        if not hasattr(self, "character_vars"):
            return []
        return [c_id for c_id, var in self.character_vars.items() if var.get()]

    def setup_ui(self):
        main_container = ttk.Frame(self.root, style="App.TFrame", padding=SPACING["lg"])
        main_container.pack(fill="both", expand=True)
        
        # Top Panel: Control
        top_panel = ttk.Frame(main_container)
        top_panel.pack(fill="x", pady=(0, SPACING["lg"]))
        
        # Model Selection
        ttk.Label(top_panel, text="모델:", font=FONTS["bold"]).pack(side="left")
        self.model_var = tk.StringVar(value=self.model_name)
        self.model_combo = ttk.Combobox(top_panel, textvariable=self.model_var, values=MODEL_OPTIONS, state="readonly", width=40)
        self.model_combo.pack(side="left", padx=(0, 2))
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_change)
        
        ttk.Button(top_panel, text="🔄", width=3, command=self.refresh_models).pack(side="left", padx=(0, SPACING["sm"]))
        
        ttk.Label(top_panel, text="API 키:", font=FONTS["bold"]).pack(side="left", padx=(SPACING["md"], 0))
        self.api_key_name_var = tk.StringVar(value="Default")
        self.api_key_combo = ttk.Combobox(top_panel, textvariable=self.api_key_name_var, state="readonly", width=15)
        self.api_key_combo.pack(side="left", padx=SPACING["sm"])
        self.api_key_combo.bind("<<ComboboxSelected>>", self.on_api_key_change)

        self.thinking_check = ttk.Checkbutton(top_panel, text="추론 사용", variable=self.enable_thinking_var)
        self.thinking_check.pack(side="left", padx=(SPACING["md"], 0))
        
        ttk.Button(top_panel, text="즐겨찾기 관리", command=self.open_preset_manager).pack(side="right", padx=(0, SPACING["sm"]))
        ttk.Button(top_panel, text="캐릭터 관리", command=self.open_character_manager).pack(side="right", padx=(0, SPACING["sm"]))
        ttk.Button(top_panel, text="API 키 관리", command=lambda: ApiKeyDialog(self)).pack(side="right")
        
        self.refresh_api_keys()
        
        # Status Bar
        self.status_var = tk.StringVar(value="대기 중")
        self.status_bar = ttk.Label(main_container, textvariable=self.status_var, relief="sunken", anchor="w")
        self.status_bar.pack(fill="x", side="bottom", pady=(SPACING["md"], 0))
        
        # Middle: Image Input (Left) and Output (Right)
        middle_paned = ttk.PanedWindow(main_container, orient="horizontal")
        middle_paned.pack(fill="both", expand=True)
        
        left_side = ttk.Frame(middle_paned)
        right_side = ttk.Frame(middle_paned)
        middle_paned.add(left_side, weight=1)
        middle_paned.add(right_side, weight=2)
        
        # --- Left Side: Input (with Tabs) ---
        self.input_notebook = ttk.Notebook(left_side)
        self.input_notebook.pack(fill="both", expand=True)
        
        # Tab 1: Image Analysis
        self.image_tab = ttk.Frame(self.input_notebook, padding=SPACING["md"])
        self.input_notebook.add(self.image_tab, text="이미지 분석")
        
        # Drag & Drop Zone
        self.drop_label = tk.Label(
            self.image_tab, text="여기에 이미지를 드래그하거나\n클립보드 이미지를 붙여넣으세요 (Ctrl+V)",
            background=COLORS["surface_alt"], foreground=COLORS["text_secondary"],
            relief="groove", bd=1, height=8
        )
        self.drop_label.pack(fill="x", pady=(0, SPACING["md"]))
        self.drop_label.bind("<Enter>", self.on_drop_hover)
        self.drop_label.bind("<Leave>", self.on_drop_leave)
        
        file_frame = ttk.Frame(self.image_tab)
        file_frame.pack(fill="x")
        ttk.Button(file_frame, text="이미지 파일 선택", command=self.on_pick_file).pack(side="left")
        
        self.file_path_var = tk.StringVar(value="선택된 파일 없음")
        ttk.Label(self.image_tab, textvariable=self.file_path_var, font=FONTS["main"], foreground=COLORS["text_muted"]).pack(fill="x", pady=SPACING["xs"])
        
        # Preview Area inside Image Tab
        self.preview_frame = ttk.LabelFrame(self.image_tab, text="이미지 미리보기", style="Card.TLabelframe")
        self.preview_frame.pack(fill="both", expand=True, pady=SPACING["md"])
        
        self.preview_label = tk.Label(self.preview_frame, background=COLORS["surface_alt"])
        self.preview_label.pack(fill="both", expand=True, padx=SPACING["xs"], pady=SPACING["xs"])

        # Tab 2: Text Analysis [NEW]
        self.text_tab = ttk.Frame(self.input_notebook)
        self.input_notebook.add(self.text_tab, text="텍스트 분석")
        
        ttk.Label(self.text_tab, text="소설 구절 또는 추상적 묘사 입력:", font=FONTS["bold"]).pack(anchor="w", pady=(0, SPACING["xs"]))
        
        text_input_container = ttk.Frame(self.text_tab)
        text_input_container.pack(fill="both", expand=True)
        
        self.text_input = tk.Text(text_input_container, wrap="word", height=12, font=FONTS["main"], bd=1)
        self.text_input.pack(side="left", fill="both", expand=True)
        
        text_scroll = ttk.Scrollbar(text_input_container, orient="vertical", command=self.text_input.yview)
        text_scroll.pack(side="right", fill="y")
        self.text_input.config(yscrollcommand=text_scroll.set)
        
        text_btn_frame = ttk.Frame(self.text_tab)
        text_btn_frame.pack(fill="x", pady=SPACING["sm"])
        ttk.Button(text_btn_frame, text="텍스트 파일 불러오기", command=self.on_pick_text_file).pack(side="left")
        ttk.Button(text_btn_frame, text="내용 비우기", command=lambda: self.text_input.delete("1.0", "end")).pack(side="right")

        # Tab 3: Prompt Augmentation [NEW]
        self.prompt_tab = ttk.Frame(self.input_notebook)
        self.input_notebook.add(self.prompt_tab, text="프롬프트 증강")
        
        ttk.Label(self.prompt_tab, text="소설 구절 또는 묘사 입력:", font=FONTS["bold"]).pack(anchor="w", pady=(0, SPACING["xs"]))
        
        prompt_input_container = ttk.Frame(self.prompt_tab)
        prompt_input_container.pack(fill="both", expand=True)
        
        self.prompt_input = tk.Text(prompt_input_container, wrap="word", height=12, font=FONTS["main"], bd=1)
        self.prompt_input.pack(side="left", fill="both", expand=True)
        
        prompt_scroll = ttk.Scrollbar(prompt_input_container, orient="vertical", command=self.prompt_input.yview)
        prompt_scroll.pack(side="right", fill="y")
        self.prompt_input.config(yscrollcommand=prompt_scroll.set)
        
        prompt_btn_frame = ttk.Frame(self.prompt_tab)
        prompt_btn_frame.pack(fill="x", pady=SPACING["sm"])
        ttk.Button(prompt_btn_frame, text="텍스트 파일 불러오기", command=self.on_pick_prompt_file).pack(side="left")
        ttk.Button(prompt_btn_frame, text="내용 비우기", command=lambda: self.prompt_input.delete("1.0", "end")).pack(side="right")


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
        self.remix_fav_only_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(remix_btn_frame, text="즐겨찾기만 필터링", variable=self.remix_fav_only_var, command=self.refresh_remix_options).pack(side="left", padx=SPACING["md"])

        # Tab 5: JSON Editor [NEW]
        self.json_editor_tab = ttk.Frame(self.input_notebook)
        self.input_notebook.add(self.json_editor_tab, text="JSON 편집기")
        
        # -- Top: JSON Input Area --
        je_input_frame = ttk.LabelFrame(self.json_editor_tab, text="JSON 입력", style="Card.TLabelframe")
        je_input_frame.pack(fill="x", padx=SPACING["xs"], pady=(SPACING["xs"], SPACING["sm"]))
        
        je_btn_frame = ttk.Frame(je_input_frame)
        je_btn_frame.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 2))
        ttk.Button(je_btn_frame, text="JSON 파싱", command=self.on_parse_json_editor).pack(side="left")
        ttk.Button(je_btn_frame, text="현재 결과 불러오기", command=self.on_load_current_json).pack(side="left", padx=SPACING["sm"])
        ttk.Button(je_btn_frame, text="수정 JSON 미리보기", command=self.on_preview_edited_json).pack(side="right")
        ttk.Button(je_btn_frame, text="내용 비우기", command=self.on_clear_json_editor).pack(side="right", padx=(0, SPACING["sm"]))
        
        je_input_container = ttk.Frame(je_input_frame)
        je_input_container.pack(fill="x", padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        
        self.json_editor_input = tk.Text(
            je_input_container, wrap="word", height=6, font=FONTS["monospace"],
            bg=COLORS["surface_alt"], fg=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"], relief="flat",
            highlightthickness=1, highlightbackground=COLORS["surface_alt_strong"],
            highlightcolor=COLORS["accent"]
        )
        self.json_editor_input.pack(side="left", fill="both", expand=True)
        
        je_input_scroll = ttk.Scrollbar(je_input_container, orient="vertical", command=self.json_editor_input.yview)
        je_input_scroll.pack(side="right", fill="y")
        self.json_editor_input.config(yscrollcommand=je_input_scroll.set)
        
        # -- Bottom: Scrollable Attribute Editor --
        je_editor_frame = ttk.LabelFrame(self.json_editor_tab, text="속성 편집", style="Card.TLabelframe")
        je_editor_frame.pack(fill="both", expand=True, padx=SPACING["xs"], pady=(0, SPACING["xs"]))
        
        je_editor_container = ttk.Frame(je_editor_frame)
        je_editor_container.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        je_canvas = tk.Canvas(je_editor_container, highlightthickness=0, bg=COLORS["surface"])
        je_scrollbar = ttk.Scrollbar(je_editor_container, orient="vertical", command=je_canvas.yview)
        self.je_scrollable_frame = ttk.Frame(je_canvas)
        
        self.je_scrollable_frame.bind(
            "<Configure>",
            lambda e: je_canvas.configure(scrollregion=je_canvas.bbox("all"))
        )
        
        je_canvas.create_window((0, 0), window=self.je_scrollable_frame, anchor="nw")
        je_canvas.configure(yscrollcommand=je_scrollbar.set)
        
        # Enable mousewheel scrolling
        def _on_je_mousewheel(event):
            je_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        je_canvas.bind_all("<MouseWheel>", _on_je_mousewheel, add="+")
        
        je_canvas.pack(side="left", fill="both", expand=True)
        je_scrollbar.pack(side="right", fill="y")
        self.je_canvas = je_canvas
        
        # State for JSON editor
        self.json_editor_data = {}  # Parsed JSON dict
        self.json_editor_fields = {}  # {dotted_key: tk.Text widget}
        
        # Initial placeholder message
        self.je_placeholder = ttk.Label(
            self.je_scrollable_frame, 
            text="JSON을 입력하고 'JSON 파싱' 버튼을 클릭하면\n여기에 편집 가능한 속성이 표시됩니다.",
            foreground=COLORS["text_muted"], justify="center"
        )
        self.je_placeholder.pack(pady=40)

        # Bottom Options (Shared or common area)
        bottom_options = ttk.Frame(left_side)
        bottom_options.pack(fill="x", side="bottom")

        # Character Selection Frame
        self.char_frame = ttk.LabelFrame(bottom_options, text="등장 인물 (캐릭터 프로필 적용)", style="Card.TLabelframe")
        self.char_frame.pack(fill="x", pady=(0, SPACING["sm"]))
        self.char_inner_frame = ttk.Frame(self.char_frame)
        self.char_inner_frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["sm"])
        self.character_vars = {}
        self.refresh_characters_ui()

        # Pose & Expression Override Frame
        self.override_frame = ttk.LabelFrame(bottom_options, text="포즈/표정 고정 오버라이드", style="Card.TLabelframe")
        self.override_frame.pack(fill="x", pady=(0, SPACING["sm"]))
        
        override_inner = ttk.Frame(self.override_frame)
        override_inner.pack(fill="x", padx=SPACING["sm"], pady=SPACING["sm"])
        
        # Grid layout for two comboboxes
        override_inner.columnconfigure(1, weight=1)
        override_inner.columnconfigure(3, weight=1)
        
        # Expression Override
        ttk.Label(override_inner, text="표정:").grid(row=0, column=0, sticky="w", padx=(0, SPACING["xs"]))
        self.preset_expression_var = tk.StringVar(value="")
        self.preset_expression_combo = ttk.Combobox(override_inner, textvariable=self.preset_expression_var, state="readonly")
        self.preset_expression_combo.grid(row=0, column=1, sticky="ew", padx=(0, SPACING["xs"]))
        ttk.Button(override_inner, text="Clear", width=5, command=lambda: self.preset_expression_var.set("")).grid(row=0, column=2, padx=(0, SPACING["md"]))
        
        # Pose Override
        ttk.Label(override_inner, text="포즈:").grid(row=0, column=3, sticky="w", padx=(0, SPACING["xs"]))
        self.preset_pose_var = tk.StringVar(value="")
        self.preset_pose_combo = ttk.Combobox(override_inner, textvariable=self.preset_pose_var, state="readonly")
        self.preset_pose_combo.grid(row=0, column=4, sticky="ew", padx=(0, SPACING["xs"]))
        ttk.Button(override_inner, text="Clear", width=5, command=lambda: self.preset_pose_var.set("")).grid(row=0, column=5)

        self.refresh_presets_combos()
        self.refresh_remix_options()

        # Options
        opt_frame = ttk.LabelFrame(bottom_options, text="추가 옵션", style="Card.TLabelframe")
        opt_frame.pack(fill="x", pady=(0, SPACING["md"]))
        
        kw_header = ttk.Frame(opt_frame)
        kw_header.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 2))
        ttk.Label(kw_header, text="키워드 (선택):").pack(side="left")
        ttk.Button(kw_header, text="내용 비우기", command=self.on_clear_keyword).pack(side="right")
        ttk.Button(kw_header, text="기본값 불러오기", command=self.on_reset_default_keyword).pack(side="right", padx=(0, SPACING["xs"]))

        self.keyword_text = tk.Text(
            opt_frame, font=FONTS["main"], height=4,
            bg=COLORS["surface_alt"], fg=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"], relief="flat",
            highlightthickness=1, highlightbackground=COLORS["surface_alt_strong"],
            highlightcolor=COLORS["accent"]
        )
        self.keyword_text.pack(fill="x", padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        self.keyword_text.insert("1.0", DEFAULT_KEYWORD)
        
        # High Fidelity Checkbox (Mainly for image analysis)
        self.hf_check = ttk.Checkbutton(
            opt_frame, text="초고정밀 분석 (99.99% 재현)", 
            variable=self.high_fidelity_var, 
            command=self.on_high_fidelity_toggle
        )
        self.hf_check.pack(anchor="w", padx=SPACING["sm"], pady=SPACING["xs"])
        
        # Word Count Controls
        wc_frame = ttk.Frame(opt_frame)
        wc_frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["xs"])
        
        ttk.Label(wc_frame, text="Min:").pack(side="left")
        self.min_spin = ttk.Spinbox(wc_frame, from_=0, to=2000, width=5, textvariable=self.min_words_var)
        self.min_spin.pack(side="left", padx=(SPACING["xs"], SPACING["md"]))
        
        ttk.Label(wc_frame, text="Max:").pack(side="left")
        self.max_spin = ttk.Spinbox(wc_frame, from_=0, to=4000, width=5, textvariable=self.max_words_var)
        self.max_spin.pack(side="left", padx=SPACING["xs"])
        
        # Action Buttons
        btn_frame = ttk.Frame(bottom_options)
        btn_frame.pack(fill="x", pady=(0, SPACING["md"]))
        self.generate_button = ttk.Button(btn_frame, text="프롬프트 생성 / 분석 실행", style="Accent.TButton", command=self.on_smart_generate)
        self.generate_button.pack(fill="x", pady=SPACING["xs"])
        
        self.cancel_button = ttk.Button(btn_frame, text="중지", state="disabled", command=self.on_cancel)
        self.cancel_button.pack(fill="x")
        
        # --- Right Side: Output & History ---
        # Vertical split for English and Korean
        self.output_paned = ttk.PanedWindow(right_side, orient="vertical")
        self.output_paned.pack(fill="both", expand=True)
        
        # English Output
        en_frame = ttk.LabelFrame(self.output_paned, text="생성 결과 (English)", style="Card.TLabelframe")
        self.output_paned.add(en_frame, weight=1)
        
        # Copy Button for English
        en_toolbar = ttk.Frame(en_frame)
        en_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(en_toolbar, text="복사 (Copy)", command=self.on_copy_en).pack(side="right")
        ttk.Button(en_toolbar, text="저장 (Save)", command=self.on_save_edits).pack(side="right", padx=(0, SPACING["sm"]))
        ttk.Button(en_toolbar, text="⭐ 전체 프롬프트 즐겨찾기", command=self.on_favorite_current_prompt).pack(side="right", padx=(0, SPACING["sm"]))
        
        self.output_text = tk.Text(en_frame, wrap="word", height=8, font=FONTS["monospace"])
        self.output_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # Korean Translation
        ko_frame = ttk.LabelFrame(self.output_paned, text="한글 번역 (Korean)", style="Card.TLabelframe")
        self.output_paned.add(ko_frame, weight=1)
        
        # Copy Button for Korean
        ko_toolbar = ttk.Frame(ko_frame)
        ko_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(ko_toolbar, text="복사 (Copy)", command=self.on_copy_ko).pack(side="right")
        ttk.Button(ko_toolbar, text="저장 (Save)", command=self.on_save_edits).pack(side="right", padx=(0, SPACING["sm"]))
        
        self.translation_text = tk.Text(ko_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.translation_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # Chinese Translation
        zh_frame = ttk.LabelFrame(self.output_paned, text="중국어 번역 (Chinese)", style="Card.TLabelframe")
        self.output_paned.add(zh_frame, weight=1)
        
        # Copy Button for Chinese
        zh_toolbar = ttk.Frame(zh_frame)
        zh_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(zh_toolbar, text="복사 (Copy)", command=self.on_copy_zh).pack(side="right")
        ttk.Button(zh_toolbar, text="저장 (Save)", command=self.on_save_edits).pack(side="right", padx=(0, SPACING["sm"]))
        
        self.translation_zh_text = tk.Text(zh_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.translation_zh_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # KREA2 JSON Output
        json_frame = ttk.LabelFrame(self.output_paned, text="KREA2 JSON", style="Card.TLabelframe")
        self.output_paned.add(json_frame, weight=1)
        
        # Copy Button for JSON
        json_toolbar = ttk.Frame(json_frame)
        json_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(json_toolbar, text="복사 (Copy)", command=self.on_copy_json).pack(side="right")
        ttk.Button(json_toolbar, text="저장 (Save)", command=self.on_save_edits).pack(side="right", padx=(0, SPACING["sm"]))
        ttk.Button(json_toolbar, text="⭐ 속성 즐겨찾기", command=self.on_favorite_current_json_attributes).pack(side="right", padx=(0, SPACING["sm"]))
        ttk.Button(json_toolbar, text="📝 JSON 편집기로 내보내기", command=self.on_export_to_json_editor).pack(side="right", padx=(0, SPACING["sm"]))
        
        self.json_output_text = tk.Text(json_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.json_output_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # KREA2 JSON Korean Output
        json_ko_frame = ttk.LabelFrame(self.output_paned, text="KREA2 JSON (한국어)", style="Card.TLabelframe")
        self.output_paned.add(json_ko_frame, weight=1)
        
        # Copy Button for JSON Korean
        json_ko_toolbar = ttk.Frame(json_ko_frame)
        json_ko_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(json_ko_toolbar, text="복사 (Copy)", command=self.on_copy_json_ko).pack(side="right")
        ttk.Button(json_ko_toolbar, text="저장 (Save)", command=self.on_save_edits).pack(side="right", padx=(0, SPACING["sm"]))
        
        self.json_ko_output_text = tk.Text(json_ko_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.json_ko_output_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # History
        history_frame = ttk.LabelFrame(right_side, text="최근 히스토리", style="Card.TLabelframe")
        history_frame.pack(fill="both", expand=True, pady=(SPACING["md"], 0))
        
        # Tools/Actions frame
        btns_frame = ttk.Frame(history_frame)
        btns_frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["xs"])
        ttk.Button(btns_frame, text="선택 항목 삭제 (Del)", command=self.on_delete_history).pack(side="right")
        
        # History Tabs
        self.history_notebook = ttk.Notebook(history_frame)
        self.history_notebook.pack(fill="both", expand=True, padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        
        # Tab 1: Image History
        self.image_hist_tab = ttk.Frame(self.history_notebook)
        self.history_notebook.add(self.image_hist_tab, text="이미지")
        
        self.image_history_list = ttk.Treeview(self.image_hist_tab, columns=("filename", "text"), show="headings", height=8)
        self.image_history_list.heading("filename", text="파일명", command=lambda: self._treeview_sort_column(self.image_history_list, "filename", False))
        self.image_history_list.heading("text", text="내용", command=lambda: self._treeview_sort_column(self.image_history_list, "text", False))
        self.image_history_list.column("filename", width=120, stretch=False)
        self.image_history_list.column("text", width=400, stretch=True)
        self.image_history_list.pack(side="left", fill="both", expand=True)
        
        img_scroll = ttk.Scrollbar(self.image_hist_tab, orient="vertical", command=self.image_history_list.yview)
        img_scroll.pack(side="right", fill="y")
        self.image_history_list.configure(yscrollcommand=img_scroll.set)
        
        # Tab 2: Text History
        self.text_hist_tab = ttk.Frame(self.history_notebook)
        self.history_notebook.add(self.text_hist_tab, text="텍스트")
        
        self.text_history_list = ttk.Treeview(self.text_hist_tab, columns=("filename", "text"), show="headings", height=8)
        self.text_history_list.heading("filename", text="구분", command=lambda: self._treeview_sort_column(self.text_history_list, "filename", False))
        self.text_history_list.heading("text", text="내용", command=lambda: self._treeview_sort_column(self.text_history_list, "text", False))
        self.text_history_list.column("filename", width=120, stretch=False)
        self.text_history_list.column("text", width=400, stretch=True)
        self.text_history_list.pack(side="left", fill="both", expand=True)
        
        txt_scroll = ttk.Scrollbar(self.text_hist_tab, orient="vertical", command=self.text_history_list.yview)
        txt_scroll.pack(side="right", fill="y")
        self.text_history_list.configure(yscrollcommand=txt_scroll.set)

        # Tab 3: Favorites / Presets
        self.favorites_hist_tab = ttk.Frame(self.history_notebook)
        self.history_notebook.add(self.favorites_hist_tab, text="⭐ 즐겨찾기")
        
        fav_top_frame = ttk.Frame(self.favorites_hist_tab)
        fav_top_frame.pack(fill="x", padx=SPACING["xs"], pady=(SPACING["xs"], SPACING["xs"]))
        
        ttk.Label(fav_top_frame, text="분류:").pack(side="left", padx=(0, 2))
        self.fav_tab_cat_var = tk.StringVar(value="(전체)")
        self.fav_tab_cat_combo = ttk.Combobox(
            fav_top_frame, textvariable=self.fav_tab_cat_var, state="readonly", width=14,
            values=["(전체)", "전체 프롬프트", "표정", "포즈", "배경/조명", "인물", "의상", "카메라", "분위기/색상", "스타일", "기타 속성"]
        )
        self.fav_tab_cat_combo.pack(side="left", padx=(0, SPACING["xs"]))
        self.fav_tab_cat_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_favorites_tab())
        
        ttk.Button(fav_top_frame, text="적용", width=5, command=self.on_apply_selected_favorite).pack(side="right")
        ttk.Button(fav_top_frame, text="삭제", width=5, command=self.on_delete_selected_favorite).pack(side="right", padx=(0, 2))
        ttk.Button(fav_top_frame, text="🔄", width=3, command=self.refresh_favorites_tab).pack(side="right", padx=(0, 2))
        
        self.favorites_list = ttk.Treeview(self.favorites_hist_tab, columns=("category", "name", "text"), show="headings", height=8)
        self.favorites_list.heading("category", text="구분", command=lambda: self._treeview_sort_column(self.favorites_list, "category", False))
        self.favorites_list.heading("name", text="이름", command=lambda: self._treeview_sort_column(self.favorites_list, "name", False))
        self.favorites_list.heading("text", text="내용", command=lambda: self._treeview_sort_column(self.favorites_list, "text", False))
        self.favorites_list.column("category", width=90, stretch=False)
        self.favorites_list.column("name", width=120, stretch=False)
        self.favorites_list.column("text", width=310, stretch=True)
        self.favorites_list.pack(side="left", fill="both", expand=True)
        
        fav_scroll = ttk.Scrollbar(self.favorites_hist_tab, orient="vertical", command=self.favorites_list.yview)
        fav_scroll.pack(side="right", fill="y")
        self.favorites_list.configure(yscrollcommand=fav_scroll.set)
        
        # Bindings
        self.image_history_list.bind("<<TreeviewSelect>>", lambda e: self.on_history_select(e, "image"))
        self.text_history_list.bind("<<TreeviewSelect>>", lambda e: self.on_history_select(e, "text"))
        self.favorites_list.bind("<Double-1>", lambda e: self.on_apply_selected_favorite())
        self.image_history_list.bind("<Delete>", lambda e: self.on_delete_history())
        self.text_history_list.bind("<Delete>", lambda e: self.on_delete_history())
        self.favorites_list.bind("<Delete>", lambda e: self.on_delete_selected_favorite())
        self.image_history_list.bind("<Button-3>", lambda e: self.show_history_context_menu(e, "image"))
        self.text_history_list.bind("<Button-3>", lambda e: self.show_history_context_menu(e, "text"))
        self.favorites_list.bind("<Button-3>", self.show_favorites_context_menu)
        
        # Link Notebooks
        self.input_notebook.bind("<<NotebookTabChanged>>", self.on_input_tab_changed)
        self.history_notebook.bind("<<NotebookTabChanged>>", self.on_history_tab_changed)
        
        # Start drop queue poller
        self.root.after(100, self._poll_drop_queue)

    def _treeview_sort_column(self, tv, col, reverse):
        l = [(tv.set(k, col), k) for k in tv.get_children('')]
        l.sort(reverse=reverse)

        # rearrange items in sorted positions
        for index, (val, k) in enumerate(l):
            tv.move(k, '', index)

        # reverse sort next time
        tv.heading(col, command=lambda _col=col: \
                 self._treeview_sort_column(tv, _col, not reverse))

    def setup_dnd(self):
        if WIN_DND_AVAILABLE:
            self._win_drop_formats = {
                "hdrop": (win32con.CF_HDROP, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "filedesc_w": (CF_FILEDESCRIPTORW, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "filedesc_a": (CF_FILEDESCRIPTORA, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "filecontents": (CF_FILECONTENTS, None, pythoncom.DVASPECT_CONTENT, 0, pythoncom.TYMED_ISTREAM | pythoncom.TYMED_HGLOBAL | pythoncom.TYMED_FILE),
                "url_w": (CF_URLW, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "url_a": (CF_URLA, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "png": (CF_PNG, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "webp": (CF_WEBP, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "dib": (CF_DIB, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "text_w": (win32con.CF_UNICODETEXT, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
                "text_a": (win32con.CF_TEXT, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)
            }
        else:
            self._win_drop_formats = {}
        self.root.update_idletasks()
        self._win_target, self._win_com_target = setup_dnd(self.root, self.drop_label, self)
        self.root.bind_all("<Control-v>", lambda e: self.on_paste())
        self.root.bind_all("<F1>", lambda e: self.on_smart_generate())
    
    def on_high_fidelity_toggle(self):
        if self.high_fidelity_var.get():
            self.min_words_var.set(HIGH_FIDELITY_MIN_WORDS)
            self.max_words_var.set(HIGH_FIDELITY_MAX_WORDS)
            self.status_var.set("초고정밀 분석 모드 활성화 (고급 태스크 권장)")
        else:
            self.min_words_var.set(MIN_PROMPT_WORDS)
            self.max_words_var.set(MAX_PROMPT_WORDS)
            self.status_var.set("표준 분석 모드로 전환")

    def on_model_change(self, event=None):
        new_model = self.model_var.get()
        
        if new_model.startswith("local-llama-cpp"):
            current_values = list(self.api_key_combo["values"])
            if "llama.cpp" not in current_values:
                current_values.append("llama.cpp")
                self.api_key_combo["values"] = current_values
            self.api_key_name_var.set("llama.cpp")
        else:
            if self.api_key_name_var.get() == "llama.cpp":
                current_values = list(self.api_key_combo["values"])
                if "Default" in current_values:
                    self.api_key_name_var.set("Default")
                elif current_values and current_values[0] != "llama.cpp":
                    self.api_key_name_var.set(current_values[0])
                else:
                    self.api_key_name_var.set("")
        
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not new_model.startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "먼저 사용할 API 키를 설정하세요.")
            self.model_var.set(self.model_name)
            return

        def check():
            try:
                validate_model_access(new_model, api_key)
                self.model_name = new_model
                self.model_thinking_level = MODEL_THINKING_LEVELS.get(new_model)
                self.status_var.set(f"모델 변경 완료: {new_model}")
            except Exception as e:
                self.root.after(0, lambda err=str(e): messagebox.showerror("오류", err))
                self.root.after(0, lambda: self.model_var.set(self.model_name))
        
        threading.Thread(target=check, daemon=True).start()

    def on_api_key_change(self, event):
        self.refresh_models()

    def refresh_api_keys(self):
        keys = load_api_keys()
        names = list(keys.keys())
        self.api_key_combo.config(values=names)
        if names:
            if self.api_key_name_var.get() not in names:
                self.api_key_name_var.set(names[0])
        else:
            self.api_key_name_var.set("")
        self.refresh_models()

    def on_pick_file(self):
        path = filedialog.askopenfilename(filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.webp")])
        if path:
            self.set_image_source({"type": "file", "value": path})

    def on_paste(self):
        source = get_image_from_clipboard(self.root)
        if source:
            self.set_image_source(source)
        else:
            self.status_var.set("클립보드에 이미지가 없습니다.")

    def on_generate(self):
        if self.generation_in_progress:
            return
        
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        
        if not self.model_var.get().startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            if hasattr(self, 'generation_queue'):
                self.generation_queue.clear()
            return
        if not self.image_source:
            messagebox.showwarning("알림", "이미지를 먼저 선택하세요.")
            if hasattr(self, 'generation_queue'):
                self.generation_queue.clear()
            return

        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        self.json_output_text.delete("1.0", "end")
        self.json_ko_output_text.delete("1.0", "end")
        
        def worker():
            try:
                # 1. Prepare Image
                if self.image_source["type"] == "file":
                    data = Path(self.image_source["value"]).read_bytes()
                    mime = detect_mime_from_bytes(data, self.image_source["value"])
                else:
                    data = self.image_source["value"]
                    mime = self.image_source["mime_type"]
                
                if not mime:
                    raise ValueError("지원하지 않거나 손상된 이미지입니다.")
                
                is_llama = self.model_var.get().startswith("local-llama-cpp")
                prepared_data, _ = prepare_image_bytes(
                    data, mime, self.image_source["type"],
                    high_fidelity=self.high_fidelity_var.get(),
                    bypass_size_limit=is_llama
                )
                
                def chunk_handler(chunk):
                    self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                    self.root.after(0, lambda: self.output_text.see("end"))

                current_tag = None
                def pass2_chunk_handler(chunk):
                    nonlocal current_tag
                    while chunk:
                        # Order matters! [JSON_KO] must be before [JSON] to prevent substring matching
                        tags = {"[ENGLISH]": "en", "[KOREAN]": "ko", "[CHINESE]": "zh", "[JSON_KO]": "json_ko", "[JSON]": "json"}
                        first_tag_pos = -1
                        first_tag_str = ""
                        
                        for t in tags:
                            pos = chunk.find(t)
                            if pos != -1 and (first_tag_pos == -1 or pos < first_tag_pos):
                                first_tag_pos = pos
                                first_tag_str = t
                                
                        if first_tag_pos == -1:
                            if current_tag == "en":
                                self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                                self.root.after(0, lambda: self.output_text.see("end"))
                            elif current_tag == "ko":
                                self.root.after(0, lambda c=chunk: self.translation_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_text.see("end"))
                            elif current_tag == "zh":
                                self.root.after(0, lambda c=chunk: self.translation_zh_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_zh_text.see("end"))
                            elif current_tag == "json":
                                self.root.after(0, lambda c=chunk: self.json_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_output_text.see("end"))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda c=chunk: self.json_ko_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_ko_output_text.see("end"))
                            break
                            
                        pre_text = chunk[:first_tag_pos]
                        if pre_text:
                            if current_tag == "en":
                                self.root.after(0, lambda p=pre_text: self.output_text.insert("end", p))
                            elif current_tag == "ko":
                                self.root.after(0, lambda p=pre_text: self.translation_text.insert("end", p))
                            elif current_tag == "zh":
                                self.root.after(0, lambda p=pre_text: self.translation_zh_text.insert("end", p))
                            elif current_tag == "json":
                                self.root.after(0, lambda p=pre_text: self.json_output_text.insert("end", p))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda p=pre_text: self.json_ko_output_text.insert("end", p))
                                
                        current_tag = tags[first_tag_str]
                        if current_tag == "en":
                            self.root.after(0, lambda: self.output_text.delete("1.0", "end"))
                        elif current_tag == "ko":
                            self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        elif current_tag == "zh":
                            self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        elif current_tag == "json":
                            self.root.after(0, lambda: self.json_output_text.delete("1.0", "end"))
                        elif current_tag == "json_ko":
                            self.root.after(0, lambda: self.json_ko_output_text.delete("1.0", "end"))
                            
                        chunk = chunk[first_tag_pos + len(first_tag_str):]

                pose_override, expression_override = self._get_override_presets()
                result, count = generate_prompt_logic(
                    prepared_data, mime, api_key, 
                    self.model_name, self.model_thinking_level, 
                    self.keyword_text.get("1.0", "end-1c"),
                    min_words=self.min_words_var.get(),
                    max_words=self.max_words_var.get(),
                    high_fidelity=self.high_fidelity_var.get(),
                    on_chunk=chunk_handler,
                    on_pass2_chunk=pass2_chunk_handler,
                    cancel_check=lambda: self.cancel_requested,
                    active_character_ids=self.get_active_character_ids(),
                    pose_override=pose_override,
                    expression_override=expression_override,
                    enable_thinking=self.enable_thinking_var.get()
                )
                
                self.root.after(0, lambda: self.on_success(result, count))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def set_busy(self, busy):
        self.generation_in_progress = busy
        self.generate_button.config(state="disabled" if busy else "normal")
        self.cancel_button.config(state="normal" if busy else "disabled")
        self.status_var.set("처리 중..." if busy else "대기 중")
        if busy:
            self.cancel_requested = False

    def on_success(self, result, count):
        en_text = result["en"]
        ko_text = result["ko"]
        zh_text = result.get("zh", "")
        json_text = result.get("json", "")
        json_ko_text = result.get("json_ko", "")
        self.set_busy(False)
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", en_text)
        self.translation_text.delete("1.0", "end")
        self.translation_text.insert("1.0", ko_text)
        self.translation_zh_text.delete("1.0", "end")
        self.translation_zh_text.insert("1.0", zh_text)
        self.json_output_text.delete("1.0", "end")
        self.json_output_text.insert("1.0", json_text)
        self.json_ko_output_text.delete("1.0", "end")
        self.json_ko_output_text.insert("1.0", json_ko_text)
        
        entry = append_history(result, self.image_source)
        if entry:
            self.history.append(entry)
        else:
            self.history.append(result)
        self.current_history_index = len(self.history) - 1
        self.refresh_history_list()
        self.status_var.set("생성 및 번역 완료")
        
        if hasattr(self, 'generation_queue') and self.generation_queue and self.model_var.get().startswith("local-llama-cpp"):
            self.root.after(100, self.process_next_in_queue)

    def on_copy_en(self):
        text = self.output_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("영문 프롬프트가 클립보드에 복사되었습니다.")

    def on_copy_ko(self):
        text = self.translation_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("한글 번역이 클립보드에 복사되었습니다.")

    def on_copy_zh(self):
        text = self.translation_zh_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("중국어 번역이 클립보드에 복사되었습니다.")

    def on_copy_json(self):
        text = self.json_output_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("KREA2 JSON이 클립보드에 복사되었습니다.")

    def on_copy_json_ko(self):
        text = self.json_ko_output_text.get("1.0", "end-1c").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("KREA2 JSON (한국어)이 클립보드에 복사되었습니다.")

    def on_reset_default_keyword(self):
        self.keyword_text.delete("1.0", "end")
        self.keyword_text.insert("1.0", DEFAULT_KEYWORD)
        self.status_var.set("키워드가 기본값으로 복원되었습니다.")

    def on_clear_keyword(self):
        self.keyword_text.delete("1.0", "end")
        self.status_var.set("키워드가 지워졌습니다.")

    def on_save_edits(self):
        if getattr(self, 'current_history_index', None) is None:
            messagebox.showwarning("알림", "저장할 항목이 선택되지 않았습니다. 히스토리를 선택하거나 생성하세요.")
            return
            
        if self.current_history_index >= len(self.history):
            return
            
        en_text = self.output_text.get("1.0", "end-1c").strip()
        ko_text = self.translation_text.get("1.0", "end-1c").strip()
        zh_text = self.translation_zh_text.get("1.0", "end-1c").strip()
        json_text = self.json_output_text.get("1.0", "end-1c").strip()
        
        self.history[self.current_history_index]["en"] = en_text
        self.history[self.current_history_index]["ko"] = ko_text
        self.history[self.current_history_index]["zh"] = zh_text
        self.history[self.current_history_index]["json"] = json_text
        json_ko_text = self.json_ko_output_text.get("1.0", "end-1c").strip()
        self.history[self.current_history_index]["json_ko"] = json_ko_text
        
        from ..core.prompt import save_all_history
        if save_all_history(self.history):
            self.refresh_history_list()
            self.status_var.set("수정 사항이 성공적으로 저장되었습니다.")
            messagebox.showinfo("알림", "수정 사항이 성공적으로 저장되었습니다.")
        else:
            messagebox.showerror("오류", "저장에 실패했습니다.")

    def on_error(self, err):
        self.set_busy(False)
        if err != CANCELLED_MESSAGE:
            messagebox.showerror("오류", err)
        self.status_var.set("오류 발생" if err != CANCELLED_MESSAGE else "중단됨")
        
        if err == CANCELLED_MESSAGE:
            if hasattr(self, 'generation_queue'):
                self.generation_queue.clear()
        else:
            if hasattr(self, 'generation_queue') and self.generation_queue and self.model_var.get().startswith("local-llama-cpp"):
                self.root.after(1000, self.process_next_in_queue)

    def on_cancel(self):
        self.cancel_requested = True
        self.status_var.set("중단 요청 중...")

    def on_history_select(self, event, list_type="image"):
        listbox = self.image_history_list if list_type == "image" else self.text_history_list
        selected = listbox.selection()
        if not selected:
            return
            
        item_id = selected[0]
        tags = listbox.item(item_id, "tags")
        if not tags:
            return
            
        real_idx = int(tags[0])
        
        if real_idx >= len(self.history):
            return
            
        entry = self.history[real_idx]
        self.current_history_index = real_idx
        
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", entry["en"])
        self.translation_text.delete("1.0", "end")
        self.translation_text.insert("1.0", entry["ko"])
        self.translation_zh_text.delete("1.0", "end")
        self.translation_zh_text.insert("1.0", entry.get("zh", ""))
        self.json_output_text.delete("1.0", "end")
        self.json_output_text.insert("1.0", entry.get("json", ""))
        self.json_ko_output_text.delete("1.0", "end")
        self.json_ko_output_text.insert("1.0", entry.get("json_ko", ""))
        
        # Restore keyword if present
        keyword = entry.get("keyword", "")
        self.keyword_text.delete("1.0", "end")
        self.keyword_text.insert("1.0", keyword)
        
        # Switch input tab
        if list_type == "image":
            self.input_notebook.select(0)
        else:
            # Check if this was a Prompt Augment entry
            is_prompt_aug = False
            orig_text = entry.get("input_text", "")
            if entry.get("en") and not entry.get("image_path"):
                # If there's input_text, check if it was generated in Prompt Aug or Text Analysis.
                # In on_generate_prompt_aug, we set text_source value start with "증강: "
                # and when saving we might have distinct characteristics or we can just check if we have the prompt_input tab content.
                # Let's save a flag or check if the prompt_input has been used, or better:
                # We can store a metadata or type check. Actually, checking if "증강: " or similar prefix was in name/type,
                # but since we only saved it in result["input_text"], we can check if it starts with a certain character,
                # or we can look at the active tab when it was generated. But since history is loaded from file,
                # we can check if the entry has specific fields or check where the text came from.
                # A robust way is to save an identifier. But since it's already saved, let's check:
                # If the entry has "json_ko" keys specific to prompt augmentation or if we check if the entry's input_text is meant for prompt_input.
                # We can see in gpi_events.jsonl or history.txt.
                # Let's check: in history list refresh, we put "텍스트" for both.
                # We can check which notebook tab was active, or detect based on entry content.
                # Let's check if the entry has 'json' or 'json_ko' that matches the Prompt Aug schema (e.g. "characters" key).
                import json
                try:
                    js_data = json.loads(entry.get("json", "{}"))
                    if isinstance(js_data, dict) and ("scene_metadata" in js_data or "characters" in js_data):
                        is_prompt_aug = True
                except Exception:
                    pass

            if is_prompt_aug:
                self.input_notebook.select(2) # Prompt Aug Tab is at index 2
                if orig_text:
                    self.prompt_input.delete("1.0", "end")
                    self.prompt_input.insert("1.0", orig_text)
            else:
                self.input_notebook.select(1) # Text Tab is at index 1
                if orig_text:
                    self.text_input.delete("1.0", "end")
                    self.text_input.insert("1.0", orig_text)

        # Restore image if path exists
        image_rel_path = entry.get("image_path")
        if image_rel_path:
            from ..core.config import BASE_DIR
            full_path = BASE_DIR / image_rel_path
            if full_path.exists():
                self.set_image_source({"type": "file", "value": str(full_path)})
            else:
                self.preview_label.config(image="")
                self.preview_image = None
        else:
            self.preview_label.config(image="")
            self.preview_image = None
            self.file_path_var.set("텍스트 분석 내역")
        
        self.status_var.set(f"{'이미지' if list_type == 'image' else '텍스트'} 히스토리 항목이 복원되었습니다.")
    def show_history_context_menu(self, event, list_type):
        listbox = self.image_history_list if list_type == "image" else self.text_history_list
        item_id = listbox.identify_row(event.y)
        if not item_id:
            return
            
        listbox.selection_set(item_id)
        
        tags = listbox.item(item_id, "tags")
        if not tags:
            return
        real_idx = int(tags[0])
        if real_idx >= len(self.history):
            return
        entry = self.history[real_idx]
        
        menu = tk.Menu(self.root, tearoff=0)
        
        # 1. Full Prompt Favorite
        menu.add_command(
            label="⭐ 전체 프롬프트를 즐겨찾기에 추가", 
            command=lambda: self.add_history_full_prompt_to_preset(real_idx)
        )
        menu.add_separator()
        
        # 2. Cascading Submenu for Attributes
        attr_menu = tk.Menu(menu, tearoff=0)
        attr_data = extract_all_attributes(entry)
        attrs = attr_data["attributes"]
        
        category_labels = {
            "expressions": "🎭 표정 (Expression)",
            "poses": "🧍 포즈 (Pose)",
            "Background_Lighting": "🌅 배경/조명 (Background/Lighting)",
            "Person": "👤 인물 (Person)",
            "Outfit": "👗 의상 (Outfit)",
            "Camera": "📷 카메라 (Camera)",
            "Mood_Color": "🎨 분위기/색상 (Mood/Color)",
            "Style": "🖌️ 스타일 (Style)",
            "Skin_Body_Condition": "✨ 피부/신체 (Skin & Body)",
            "custom": "⚙️ 기타 JSON 속성"
        }
        
        has_attr = False
        for cat_key, cat_label in category_labels.items():
            cat_vals = attrs.get(cat_key, {})
            if cat_vals:
                has_attr = True
                for k, v in cat_vals.items():
                    preview = (v[:32] + '...') if len(v) > 32 else v
                    lbl = f"{cat_label}: {preview}"
                    attr_menu.add_command(
                        label=lbl,
                        command=lambda ck=cat_key, ak=k, val=v: self.add_attribute_to_preset(ck, ak, val)
                    )
        
        if has_attr:
            menu.add_cascade(label="⭐ 속성별 즐겨찾기에 추가 ▶", menu=attr_menu)
        
        # Direct quick access buttons for common ones
        menu.add_command(label="선택한 표정을 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("expression", list_type))
        menu.add_command(label="선택한 포즈를 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("pose", list_type))
        menu.add_command(label="선택한 배경/조명을 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("Background_Lighting", list_type))
        menu.add_command(label="선택한 의상을 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("Outfit", list_type))
        menu.add_command(label="선택한 카메라를 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("Camera", list_type))
        menu.add_command(label="선택한 스타일을 즐겨찾기에 추가", command=lambda: self.add_history_to_preset("Style", list_type))
        
        # JSON Detail dialog
        menu.add_command(label="🔍 JSON 전체 속성 탐색 및 즐겨찾기...", command=lambda: self.open_json_attribute_dialog(entry))
        
        menu.add_separator()
        menu.add_command(label="영문 프롬프트 복사", command=lambda: self._copy_text(entry.get("en", "")))
        menu.add_command(label="한글 번역 복사", command=lambda: self._copy_text(entry.get("ko", "")))
        menu.add_command(label="KREA2 JSON 복사", command=lambda: self._copy_text(entry.get("json", "")))
        menu.add_separator()
        menu.add_command(label="히스토리 항목 삭제", command=self.on_delete_history)
        
        menu.post(event.x_root, event.y_root)

    def add_history_to_preset(self, category, list_type="image"):
        listbox = self.image_history_list if list_type == "image" else self.text_history_list
        selected = listbox.selection()
        if not selected:
            return
            
        item_id = selected[0]
        tags = listbox.item(item_id, "tags")
        if not tags:
            return
            
        real_idx = int(tags[0])
        if real_idx >= len(self.history):
            return
            
        entry = self.history[real_idx]
        
        if category == "prompts":
            self.add_history_full_prompt_to_preset(real_idx)
            return

        attr_data = extract_all_attributes(entry)
        attrs = attr_data["attributes"]
        
        cat_key_map = {
            "expression": "expressions",
            "expressions": "expressions",
            "pose": "poses",
            "poses": "poses",
            "Background_Lighting": "Background_Lighting",
            "Person": "Person",
            "Outfit": "Outfit",
            "Camera": "Camera",
            "Mood_Color": "Mood_Color",
            "Style": "Style",
            "Skin_Body_Condition": "Skin_Body_Condition"
        }
        
        target_cat = cat_key_map.get(category, category)
        val = ""
        if attrs.get(target_cat):
            val = list(attrs[target_cat].values())[0]
        elif target_cat == "expressions" and attrs.get("Character_Expressions"):
            val = list(attrs["Character_Expressions"].values())[0]
        elif target_cat == "poses" and attrs.get("Pose"):
            val = list(attrs["Pose"].values())[0]
            
        if not val or not val.strip():
            cat_name = CATEGORY_KOREAN_NAMES.get(target_cat, target_cat)
            messagebox.showwarning("경고", f"선택한 히스토리 항목에서 {cat_name} 정보를 추출할 수 없습니다.", parent=self.root)
            return
            
        cat_title = CATEGORY_KOREAN_NAMES.get(target_cat, target_cat)
        default_name = val[:30] + "..." if len(val) > 30 else val
        name = simpledialog.askstring(f"{cat_title} 즐겨찾기 추가", "즐겨찾기 이름을 입력하세요:", initialvalue=default_name, parent=self.root)
        if name is not None:
            name = name.strip()
            if not name:
                name = default_name
                
            if add_attribute_preset(target_cat, name, val):
                self.refresh_presets_combos()
                self.refresh_remix_options()
                self.refresh_favorites_tab()
                self.status_var.set(f"'{name}'이(가) {cat_title} 즐겨찾기에 추가되었습니다.")
                messagebox.showinfo("완료", f"'{name}'이(가) 즐겨찾기에 추가되었습니다.", parent=self.root)
            else:
                messagebox.showerror("오류", "즐겨찾기 저장에 실패했습니다.", parent=self.root)

    def add_history_full_prompt_to_preset(self, real_idx):
        if real_idx >= len(self.history):
            return
        entry = self.history[real_idx]
        en_text = entry.get("en", "").strip()
        if not en_text:
            messagebox.showwarning("경고", "프롬프트 내용이 없습니다.", parent=self.root)
            return
            
        default_name = en_text.split("\n")[0][:30] if en_text else "즐겨찾기 프롬프트"
        name = simpledialog.askstring("전체 프롬프트 즐겨찾기 추가", "즐겨찾기 이름을 입력하세요:", initialvalue=default_name, parent=self.root)
        if name is not None:
            name = name.strip()
            if not name:
                name = default_name
            if add_prompt_preset(name, entry):
                self.refresh_favorites_tab()
                self.status_var.set(f"전체 프롬프트 '{name}'이(가) 즐겨찾기에 저장되었습니다.")
                messagebox.showinfo("완료", f"전체 프롬프트 '{name}'이(가) 즐겨찾기에 추가되었습니다.", parent=self.root)
            else:
                messagebox.showerror("오류", "즐겨찾기 저장에 실패했습니다.", parent=self.root)

    def add_attribute_to_preset(self, category, attr_key, val):
        if not val or not val.strip():
            return
        cat_title = CATEGORY_KOREAN_NAMES.get(category, category)
        default_name = val[:30] + "..." if len(val) > 30 else val
        name = simpledialog.askstring("속성 즐겨찾기 추가", f"'{attr_key}' 속성의 즐겨찾기 이름을 입력하세요:", initialvalue=default_name, parent=self.root)
        if name is not None:
            name = name.strip()
            if not name:
                name = default_name
            if add_attribute_preset(category, name, val):
                self.refresh_presets_combos()
                self.refresh_remix_options()
                self.refresh_favorites_tab()
                self.status_var.set(f"'{name}'이(가) {cat_title} 즐겨찾기에 추가되었습니다.")
                messagebox.showinfo("완료", f"'{name}'이(가) 즐겨찾기에 추가되었습니다.", parent=self.root)
            else:
                messagebox.showerror("오류", "즐겨찾기 저장에 실패했습니다.", parent=self.root)

    def open_json_attribute_dialog(self, entry=None):
        if entry is None:
            entry = {
                "en": self.output_text.get("1.0", "end-1c").strip(),
                "ko": self.translation_text.get("1.0", "end-1c").strip(),
                "zh": self.translation_zh_text.get("1.0", "end-1c").strip(),
                "json": self.json_output_text.get("1.0", "end-1c").strip(),
                "json_ko": self.json_ko_output_text.get("1.0", "end-1c").strip(),
                "keyword": self.keyword_text.get("1.0", "end-1c").strip() if hasattr(self, "keyword_text") else ""
            }
        JsonAttributeFavoriteDialog(self, entry)

    def open_preset_manager(self):
        PresetManagerDialog(self)

    def on_favorite_current_prompt(self):
        entry = {
            "en": self.output_text.get("1.0", "end-1c").strip(),
            "ko": self.translation_text.get("1.0", "end-1c").strip(),
            "zh": self.translation_zh_text.get("1.0", "end-1c").strip(),
            "json": self.json_output_text.get("1.0", "end-1c").strip(),
            "json_ko": self.json_ko_output_text.get("1.0", "end-1c").strip(),
            "keyword": self.keyword_text.get("1.0", "end-1c").strip() if hasattr(self, "keyword_text") else "",
            "image_path": getattr(self, "current_image_rel_path", "")
        }
        if not entry["en"]:
            messagebox.showwarning("알림", "즐겨찾기에 등록할 생성 결과 프롬프트가 없습니다.")
            return
            
        default_name = entry["en"].split("\n")[0][:30]
        name = simpledialog.askstring("전체 프롬프트 즐겨찾기", "즐겨찾기 이름을 입력하세요:", initialvalue=default_name, parent=self.root)
        if name is not None:
            name = name.strip()
            if not name:
                name = default_name
            if add_prompt_preset(name, entry):
                self.refresh_favorites_tab()
                self.status_var.set(f"전체 프롬프트 '{name}'이(가) 즐겨찾기에 등록되었습니다.")
                messagebox.showinfo("완료", f"전체 프롬프트 '{name}'이(가) 즐겨찾기에 추가되었습니다.")
            else:
                messagebox.showerror("오류", "즐겨찾기 저장에 실패했습니다.")

    def on_favorite_current_json_attributes(self):
        entry = {
            "en": self.output_text.get("1.0", "end-1c").strip(),
            "ko": self.translation_text.get("1.0", "end-1c").strip(),
            "zh": self.translation_zh_text.get("1.0", "end-1c").strip(),
            "json": self.json_output_text.get("1.0", "end-1c").strip(),
            "json_ko": self.json_ko_output_text.get("1.0", "end-1c").strip()
        }
        if not entry["json"] and not entry["en"]:
            messagebox.showwarning("알림", "즐겨찾기에 등록할 JSON 또는 프롬프트 결과가 없습니다.")
            return
        self.open_json_attribute_dialog(entry)

    def refresh_favorites_tab(self):
        if not hasattr(self, "favorites_list"):
            return
        for it in self.favorites_list.get_children():
            self.favorites_list.delete(it)
            
        presets = load_presets()
        selected_cat = self.fav_tab_cat_var.get() if hasattr(self, "fav_tab_cat_var") else "(전체)"
        
        cat_map = {
            "전체 프롬프트": "prompts",
            "표정": "expressions",
            "포즈": "poses",
            "배경/조명": "Background_Lighting",
            "인물": "Person",
            "의상": "Outfit",
            "카메라": "Camera",
            "분위기/색상": "Mood_Color",
            "스타일": "Style",
            "기타 속성": "custom"
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
                    preview = val.get("en", "")[:100].replace("\n", " ")
                else:
                    preview = str(val)[:100].replace("\n", " ")
                self.favorites_list.insert("", "end", values=(cat_label, name, preview), tags=(cat_key, name))

    def on_apply_selected_favorite(self):
        sel = self.favorites_list.selection()
        if not sel:
            messagebox.showwarning("알림", "적용할 즐겨찾기 항목을 선택하세요.")
            return
        tags = self.favorites_list.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        presets = load_presets()
        val = presets.get(cat_key, {}).get(name)
        if not val:
            return
            
        if cat_key == "prompts" and isinstance(val, dict):
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", val.get("en", ""))
            self.translation_text.delete("1.0", "end")
            self.translation_text.insert("1.0", val.get("ko", ""))
            self.translation_zh_text.delete("1.0", "end")
            self.translation_zh_text.insert("1.0", val.get("zh", ""))
            self.json_output_text.delete("1.0", "end")
            self.json_output_text.insert("1.0", val.get("json", ""))
            self.json_ko_output_text.delete("1.0", "end")
            self.json_ko_output_text.insert("1.0", val.get("json_ko", ""))
            if hasattr(self, "keyword_text") and val.get("keyword"):
                self.keyword_text.delete("1.0", "end")
                self.keyword_text.insert("1.0", val.get("keyword"))
            image_rel_path = val.get("image_path")
            if image_rel_path:
                from ..core.config import BASE_DIR
                full_path = BASE_DIR / image_rel_path
                if full_path.exists():
                    self.set_image_source({"type": "file", "value": str(full_path)})
            self.status_var.set(f"즐겨찾기 전체 프롬프트 '{name}'을(를) 불러왔습니다.")
        else:
            val_str = str(val)
            if cat_key in ["expressions", "Character_Expressions"]:
                self.preset_expression_var.set(name)
            elif cat_key in ["poses", "Pose"]:
                self.preset_pose_var.set(name)
            elif hasattr(self.app, "remix_combos") and cat_key in self.app.remix_combos:
                self.remix_combos[cat_key].set(val_str)
                self.input_notebook.select(self.remix_tab)
            self.root.clipboard_clear()
            self.root.clipboard_append(val_str)
            self.status_var.set(f"즐겨찾기 '{name}' 적용 및 복사 완료")

    def on_delete_selected_favorite(self):
        sel = self.favorites_list.selection()
        if not sel:
            return
        tags = self.favorites_list.item(sel[0], "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        if messagebox.askyesno("삭제 확인", f"'{name}' 즐겨찾기를 삭제하시겠습니까?"):
            delete_preset(cat_key, name)
            self.refresh_favorites_tab()
            self.refresh_presets_combos()
            self.refresh_remix_options()
            self.status_var.set(f"'{name}' 즐겨찾기가 삭제되었습니다.")

    def show_favorites_context_menu(self, event):
        item_id = self.favorites_list.identify_row(event.y)
        if not item_id:
            return
        self.favorites_list.selection_set(item_id)
        
        tags = self.favorites_list.item(item_id, "tags")
        if not tags or len(tags) < 2:
            return
        cat_key, name = tags[0], tags[1]
        
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="적용 / 불러오기", command=self.on_apply_selected_favorite)
        menu.add_command(label="클립보드 복사", command=lambda: self._copy_favorite_val(cat_key, name))
        menu.add_separator()
        menu.add_command(label="즐겨찾기에서 삭제", command=self.on_delete_selected_favorite)
        menu.post(event.x_root, event.y_root)

    def _copy_favorite_val(self, cat_key, name):
        presets = load_presets()
        val = presets.get(cat_key, {}).get(name)
        if not val: return
        text = val.get("en", "") if (cat_key == "prompts" and isinstance(val, dict)) else str(val)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set(f"'{name}' 내용이 클립보드에 복사되었습니다.")

    def _copy_text(self, text):
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("클립보드에 복사되었습니다.")

    def on_delete_history(self):
        active_tab = self.history_notebook.index("current")
        list_type = "image" if active_tab == 0 else "text"
        listbox = self.image_history_list if list_type == "image" else self.text_history_list
        
        selected = listbox.selection()
        if not selected:
            return
        
        if not messagebox.askyesno("확인", "선택한 히스토리 항목을 삭제하시겠습니까?"):
            return
            
        item_id = selected[0]
        tags = listbox.item(item_id, "tags")
        if not tags:
            return
            
        real_idx = int(tags[0])
        
        if 0 <= real_idx < len(self.history):
            entry = self.history[real_idx]
            from ..core.prompt import delete_history_item_files, save_all_history
            # Delete associated image file
            delete_history_item_files(entry)
            
            del self.history[real_idx]
            if save_all_history(self.history):
                self.refresh_history_list()
                self.status_var.set("히스토리 항목이 삭제되었습니다.")
            else:
                messagebox.showerror("오류", "히스토리 파일 저장 중 오류가 발생했습니다.")

    def refresh_history_list(self):
        for item in self.image_history_list.get_children():
            self.image_history_list.delete(item)
        for item in self.text_history_list.get_children():
            self.text_history_list.delete(item)
            
        # We need to process in reversed order to match the visual "most recent first"
        for i in range(len(self.history) - 1, -1, -1):
            h = self.history[i]
            label = h["en"][:100] + "..."
            
            orig_name = ""
            if h.get("image_path"):
                import os
                orig_name = os.path.basename(h.get("image_path"))
                
            if h.get("image_path"):
                self.image_history_list.insert("", "end", values=(orig_name, label), tags=(str(i),))
            else:
                self.text_history_list.insert("", "end", values=("텍스트", label), tags=(str(i),))

    def on_drop_hover(self, event=None):
        self.drop_label.configure(background=COLORS["surface_alt_strong"], relief="ridge", bd=2)

    def on_drop_leave(self, event=None):
        self.drop_label.configure(background=COLORS["surface_alt"], relief="groove", bd=1)

    # Windows DND Handlers
    def win_drop_query_format(self, data_obj, fmt):
        if not fmt or not data_obj:
            return False
        try:
            data_obj.QueryGetData(fmt)
            return True
        except Exception as e:
            print(f"DEBUG: QueryGetData failed for ID {fmt[0]}: {e}")
            return False

    def _win_drop_can_accept(self, data_obj):
        for fmt in self._win_drop_formats.values():
            if self.win_drop_query_format(data_obj, fmt):
                return True
        return False

    def win_drop_effect(self, data_obj):
        if not WIN_DND_AVAILABLE:
            return 0
        if data_obj:
            self._win_drop_data_obj = data_obj
        return 1 # DROPEFFECT_COPY

    def handle_win_drop_marshaled(self, stream_ptr):
        # Called from OLE background thread.
        # DO NOT call any Tkinter methods here (like root.after).
        # Use a thread-safe queue.
        self.drop_queue.put(stream_ptr)
        return 1

    def _poll_drop_queue(self):
        try:
            while not self.drop_queue.empty():
                stream_ptr = self.drop_queue.get_nowait()
                self._process_win_unmarshal(stream_ptr)
        except Exception:
            pass
        finally:
            self.root.after(300, self._poll_drop_queue)

    def _process_win_unmarshal(self, stream_ptr):
        try:
            # Unmarshal the data object on the main thread (thread-safe)
            data_obj = pythoncom.CoUnmarshalInterface(stream_ptr, pythoncom.IID_IDataObject)
            self._do_handle_win_drop(data_obj)
        except Exception as e:
            print(f"DEBUG: Unmarshal failed: {e}")
            self.status_var.set("드롭 데이터 처리 중 오류가 발생했습니다.")

    def _do_handle_win_drop(self, data_obj):
        if not data_obj:
            return
            
        try:
            dropped_sources = []
            
            # 1. Try Virtual Files (e.g. from Browser)
            descriptors = self._get_win_file_descriptors(data_obj)
            if descriptors:
                for idx, info in enumerate(descriptors):
                    data = self._get_win_file_content(data_obj, idx)
                    if data:
                        mime = detect_mime_from_bytes(data, info['name'])
                        if mime:
                            dropped_sources.append({
                                "type": "drop_data", "value": data, "mime_type": mime, "name": info['name']
                            })
            
            # 2. Try Direct Formats (PNG, WebP, DIB)
            if not dropped_sources:
                for fmt_key in ["png", "webp", "dib"]:
                    fmt = self._win_drop_formats.get(fmt_key)
                    if self.win_drop_query_format(data_obj, fmt):
                        try:
                            stg = data_obj.GetData(fmt)
                            raw = bytes(stg.data)
                            if fmt_key == "png" or fmt_key == "webp":
                                mime = "image/png" if fmt_key == "png" else "image/webp"
                                dropped_sources.append({"type": "drop_data", "value": raw, "mime_type": mime, "name": f"dropped.{fmt_key}"})
                            elif fmt_key == "dib":
                                from io import BytesIO
                                from PIL import Image
                                img = Image.open(BytesIO(raw))
                                buf = BytesIO()
                                img.save(buf, format="PNG")
                                dropped_sources.append({"type": "drop_data", "value": buf.getvalue(), "mime_type": "image/png", "name": "dropped.png"})
                            break
                        except Exception:
                            continue

            # 3. Try Local Files
            if not dropped_sources:
                paths = self._get_win_hdrop_paths(data_obj)
                if paths:
                    for path in paths:
                        dropped_sources.append({"type": "file", "value": path})
                
            # 4. Try Text/URL
            text = ""
            if not dropped_sources:
                text = self._get_win_text(data_obj)

            is_llama = self.model_var.get().startswith("local-llama-cpp")
            
            if is_llama:
                if dropped_sources:
                    self.add_to_generation_queue(dropped_sources)
                    return
                if text and is_url(text):
                    self.download_and_queue_url(text)
                    return
            else:
                if dropped_sources:
                    self.set_image_source(dropped_sources[0])
                    return
                if text and is_url(text):
                    self.start_url_download(text)
                    return
            
            self.status_var.set("이미지 파일이나 URL을 찾지 못했습니다.")
        except Exception as e:
            log_event("win_drop_error", {"error": str(e)})
            self.status_var.set("드롭 처리 중 오류가 발생했습니다.")

    def handle_win_drop(self, data_obj):
        return 0 # No longer used by newer dnd.py

    def _get_win_file_descriptors(self, data_obj):
        for fmt_key in ["filedesc_w", "filedesc_a"]:
            fmt = self._win_drop_formats.get(fmt_key)
            if self.win_drop_query_format(data_obj, fmt):
                try:
                    stg = data_obj.GetData(fmt)
                    return parse_file_group_descriptor(bytes(stg.data), wide=(fmt_key == "filedesc_w"))
                except Exception:
                    continue
        return []

    def _get_win_file_content(self, data_obj, idx):
        fmt = (CF_FILECONTENTS, None, pythoncom.DVASPECT_CONTENT, idx, pythoncom.TYMED_ISTREAM | pythoncom.TYMED_HGLOBAL | pythoncom.TYMED_FILE)
        try:
            stg = data_obj.GetData(fmt)
            print(f"DEBUG: GetData(FileContent) idx={idx} stg.tymed={stg.tymed}")
            if stg.tymed == pythoncom.TYMED_ISTREAM:
                return read_istream_all(stg.data)
            return bytes(stg.data)
        except Exception as e:
            print(f"DEBUG: GetData(FileContent) failed for idx {idx}: {e}")
            return None

    def _get_win_hdrop_paths(self, data_obj):
        fmt = self._win_drop_formats.get("hdrop")
        if self.win_drop_query_format(data_obj, fmt):
            try:
                stg = data_obj.GetData(fmt)
                return parse_dropfiles(bytes(stg.data))
            except Exception:
                pass
        return []

    def _get_win_text(self, data_obj):
        for fmt_key in ["url_w", "url_a", "text_w", "text_a"]:
            fmt = self._win_drop_formats.get(fmt_key)
            if self.win_drop_query_format(data_obj, fmt):
                try:
                    stg = data_obj.GetData(fmt)
                    raw = stg.data
                    if fmt_key in ["url_w", "text_w"]:
                        return raw.decode("utf-16le", errors="ignore").split('\x00')[0].strip()
                    return raw.decode("mbcs", errors="ignore").split('\x00')[0].strip()
                except Exception:
                    continue
        return ""

    def start_url_download(self, url):
        if not url:
            return
        self.download_in_progress = True
        self.status_var.set("이미지 다운로드 중...")
        
        def worker():
            try:
                is_llama = self.model_var.get().startswith("local-llama-cpp")
                data, mime = download_image_from_url(url, bypass_size_limit=is_llama)
                self.root.after(0, lambda: self.set_image_source({
                    "type": "url_data", "value": data, "mime_type": mime, "url": url
                }))
                self.root.after(0, lambda: self.status_var.set("다운로드 완료"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))
            finally:
                self.root.after(0, lambda: setattr(self, 'download_in_progress', False))
        
        threading.Thread(target=worker, daemon=True).start()

    def set_image_source(self, source):
        self.image_source = source
        if source["type"] == "file":
            self.file_path_var.set(Path(source["value"]).name)
        elif source["type"] == "url_data":
            self.file_path_var.set(f"URL: {source['url'][:50]}...")
        elif source["type"] == "drop_data":
            self.file_path_var.set(f"드롭 이미지: {source['name']}")
        elif source["type"] == "clipboard":
            self.file_path_var.set("클립보드 이미지")
        
        self._update_preview(source)
        self.status_var.set("이미지 준비됨")

    def _update_preview(self, source):
        try:
            if source["value"] is None:
                self.preview_label.config(image="")
                self.preview_image = None
                return

            if source["type"] == "file":
                img = Image.open(source["value"])
            else:
                img = Image.open(BytesIO(source["value"]))

            # Dynamically calculate max width based on the panel width
            # update_idletasks ensures the current layout is computed
            self.root.update_idletasks()
            max_w = self.preview_frame.winfo_width() - 20
            if max_w < 200: # Initial or collapsed state fallback
                max_w = 320
            
            w, h = img.size
            ratio = max_w / w
            
            # We scale to the available width, but cap the height if it's too insane
            # while strictly maintaining aspect ratio.
            new_w = max_w
            new_h = int(h * ratio)
            
            # If height is too large for the screen, cap it and scale width back
            max_screen_h = 600
            if new_h > max_screen_h:
                new_h = max_screen_h
                new_w = int(w * (max_screen_h / h))
            
            img = img.resize((new_w, new_h), Image.LANCZOS)

            self.preview_image = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.preview_image)
        except Exception as e:
            log_event("preview_error", {"error": str(e)})
            self.preview_label.config(image="")
            self.preview_image = None

    def on_input_tab_changed(self, event):
        """Syncs history notebook tab when input notebook tab changes."""
        if not hasattr(self, 'history_notebook'):
            return
        # Only process if triggered by the notebook itself, not a child
        if event.widget != self.input_notebook:
            return
            
        try:
            curr_idx = self.input_notebook.index("current")
            history_idx = curr_idx if curr_idx < len(self.history_notebook.tabs()) else 1
            if self.history_notebook.index("current") != history_idx:
                # Use after_idle to avoid disrupting the current event flow
                self.root.after_idle(lambda: self.history_notebook.select(history_idx))
        except Exception:
            pass

    def on_history_tab_changed(self, event):
        """Syncs input notebook tab when history notebook tab changes."""
        if not hasattr(self, 'input_notebook'):
            return
        if event.widget != self.history_notebook:
            return
            
        try:
            curr_idx = self.history_notebook.index("current")
            if curr_idx == 2:
                self.refresh_favorites_tab()
                return
            input_idx = self.input_notebook.index("current")
            if curr_idx == 1 and input_idx >= 1:
                return
            if input_idx != curr_idx:
                self.root.after_idle(lambda: self.input_notebook.select(curr_idx))
        except Exception:
            pass

    def on_smart_generate(self):
        """Dispatches to either image or text generation based on active tab."""
        active_tab = self.input_notebook.index("current")
        if active_tab == 0: # Image Tab
            self.on_generate()
        elif active_tab == 1: # Text Tab
            self.on_generate_from_text()
        elif active_tab == 2: # Prompt Aug Tab
            self.on_generate_prompt_aug()
        elif active_tab == 3: # Prompt Remix Tab
            self.on_generate_remix()
        elif active_tab == 4: # JSON Editor Tab
            self.on_generate_json_edit()

    def on_pick_prompt_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt;*.md;*.log")])
        if path:
            try:
                content = Path(path).read_text(encoding="utf-8")
                self.prompt_input.delete("1.0", "end")
                self.prompt_input.insert("1.0", content)
                self.status_var.set(f"텍스트 파일 로드 완료: {Path(path).name}")
            except Exception as e:
                messagebox.showerror("오류", f"파일을 읽을 수 없습니다: {e}")

    def on_generate_prompt_aug(self):
        if self.generation_in_progress:
            return
            
        text_content = self.prompt_input.get("1.0", "end-1c").strip()
        if not text_content:
            messagebox.showwarning("알림", "분석할 텍스트를 입력하세요.")
            return

        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not self.model_var.get().startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            return

        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        self.json_output_text.delete("1.0", "end")
        self.json_ko_output_text.delete("1.0", "end")

        def worker():
            try:
                from ..core.prompt import generate_prompt_augmentation_logic
                
                # Unified streaming handler (similar to image)
                def chunk_handler(chunk):
                    self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                    self.root.after(0, lambda: self.output_text.see("end"))

                current_tag = "ko"
                def pass2_chunk_handler(chunk):
                    nonlocal current_tag
                    while chunk:
                        # Order matters! [JSON_KO] must be before [JSON] to prevent substring matching
                        tags = {"[KOREAN]": "ko", "[CHINESE]": "zh", "[JSON_KO]": "json_ko", "[JSON]": "json"}
                        first_tag_pos = -1
                        first_tag_str = ""
                        
                        for t in tags:
                            pos = chunk.find(t)
                            if pos != -1 and (first_tag_pos == -1 or pos < first_tag_pos):
                                first_tag_pos = pos
                                first_tag_str = t
                                
                        if first_tag_pos == -1:
                            if current_tag == "ko":
                                self.root.after(0, lambda c=chunk: self.translation_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_text.see("end"))
                            elif current_tag == "zh":
                                self.root.after(0, lambda c=chunk: self.translation_zh_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_zh_text.see("end"))
                            elif current_tag == "json":
                                self.root.after(0, lambda c=chunk: self.json_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_output_text.see("end"))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda c=chunk: self.json_ko_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_ko_output_text.see("end"))
                            break
                            
                        pre_text = chunk[:first_tag_pos]
                        if pre_text:
                            if current_tag == "ko":
                                self.root.after(0, lambda p=pre_text: self.translation_text.insert("end", p))
                            elif current_tag == "zh":
                                self.root.after(0, lambda p=pre_text: self.translation_zh_text.insert("end", p))
                            elif current_tag == "json":
                                self.root.after(0, lambda p=pre_text: self.json_output_text.insert("end", p))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda p=pre_text: self.json_ko_output_text.insert("end", p))
                                
                        current_tag = tags[first_tag_str]
                        if current_tag == "ko":
                            self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        elif current_tag == "zh":
                            self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        elif current_tag == "json":
                            self.root.after(0, lambda: self.json_output_text.delete("1.0", "end"))
                        elif current_tag == "json_ko":
                            self.root.after(0, lambda: self.json_ko_output_text.delete("1.0", "end"))
                            
                        chunk = chunk[first_tag_pos + len(first_tag_str):]
                
                model_name = self.model_var.get()
                thinking_level = self.model_thinking_level
                pose_override, expression_override = self._get_override_presets()
                result, count = generate_prompt_augmentation_logic(
                    text_input=text_content,
                    api_key=api_key,
                    model_name=model_name,
                    thinking_level=thinking_level,
                    keyword_text=self.keyword_text.get("1.0", "end-1c").strip(),
                    on_chunk=chunk_handler,
                    on_pass2_chunk=pass2_chunk_handler,
                    cancel_check=lambda: self.cancel_requested,
                    active_character_ids=self.get_active_character_ids(),
                    pose_override=pose_override,
                    expression_override=expression_override,
                    enable_thinking=self.enable_thinking_var.get()
                )
                
                result["input_text"] = text_content
                text_source = {"type": "text_input", "value": "증강: " + text_content[:40] + "...", "name": "Prompt Aug"}
                self.image_source = text_source
                
                self.root.after(0, lambda: self.on_success(result, count))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))

        threading.Thread(target=worker, daemon=True).start()


    def on_pick_text_file(self):
        path = filedialog.askopenfilename(filetypes=[("Text Files", "*.txt;*.md;*.log")])
        if path:
            try:
                content = Path(path).read_text(encoding="utf-8")
                self.text_input.delete("1.0", "end")
                self.text_input.insert("1.0", content)
                self.status_var.set(f"텍스트 파일 로드 완료: {Path(path).name}")
            except Exception as e:
                messagebox.showerror("오류", f"파일을 읽을 수 없습니다: {e}")

    def on_generate_from_text(self):
        if self.generation_in_progress:
            return
            
        text_content = self.text_input.get("1.0", "end-1c").strip()
        if not text_content:
            messagebox.showwarning("알림", "분석할 텍스트를 입력하세요.")
            return

        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not self.model_var.get().startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            return

        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        self.json_output_text.delete("1.0", "end")
        self.json_ko_output_text.delete("1.0", "end")

        def worker():
            try:
                from ..core.prompt import generate_from_text_logic
                
                def chunk_handler(chunk):
                    self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                    self.root.after(0, lambda: self.output_text.see("end"))

                current_tag = "ko"
                def pass2_chunk_handler(chunk):
                    nonlocal current_tag
                    while chunk:
                        # Order matters! [JSON_KO] must be before [JSON] to prevent substring matching
                        tags = {"[KOREAN]": "ko", "[CHINESE]": "zh", "[JSON_KO]": "json_ko", "[JSON]": "json"}
                        first_tag_pos = -1
                        first_tag_str = ""
                        
                        for t in tags:
                            pos = chunk.find(t)
                            if pos != -1 and (first_tag_pos == -1 or pos < first_tag_pos):
                                first_tag_pos = pos
                                first_tag_str = t
                                
                        if first_tag_pos == -1:
                            if current_tag == "ko":
                                self.root.after(0, lambda c=chunk: self.translation_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_text.see("end"))
                            elif current_tag == "zh":
                                self.root.after(0, lambda c=chunk: self.translation_zh_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_zh_text.see("end"))
                            elif current_tag == "json":
                                self.root.after(0, lambda c=chunk: self.json_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_output_text.see("end"))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda c=chunk: self.json_ko_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_ko_output_text.see("end"))
                            break
                            
                        pre_text = chunk[:first_tag_pos]
                        if pre_text:
                            if current_tag == "ko":
                                self.root.after(0, lambda p=pre_text: self.translation_text.insert("end", p))
                            elif current_tag == "zh":
                                self.root.after(0, lambda p=pre_text: self.translation_zh_text.insert("end", p))
                            elif current_tag == "json":
                                self.root.after(0, lambda p=pre_text: self.json_output_text.insert("end", p))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda p=pre_text: self.json_ko_output_text.insert("end", p))
                                
                        current_tag = tags[first_tag_str]
                        if current_tag == "ko":
                            self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        elif current_tag == "zh":
                            self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        elif current_tag == "json":
                            self.root.after(0, lambda: self.json_output_text.delete("1.0", "end"))
                        elif current_tag == "json_ko":
                            self.root.after(0, lambda: self.json_ko_output_text.delete("1.0", "end"))
                            
                        chunk = chunk[first_tag_pos + len(first_tag_str):]
                
                pose_override, expression_override = self._get_override_presets()
                result, count = generate_from_text_logic(
                    text_content, api_key,
                    self.model_name, self.model_thinking_level,
                    self.keyword_text.get("1.0", "end-1c"),
                    on_chunk=chunk_handler,
                    on_pass2_chunk=pass2_chunk_handler,
                    cancel_check=lambda: self.cancel_requested,
                    active_character_ids=self.get_active_character_ids(),
                    pose_override=pose_override,
                    expression_override=expression_override,
                    enable_thinking=self.enable_thinking_var.get()
                )
                
                # Store original text in result
                result["input_text"] = text_content
                
                # We reuse on_success but need a mock image_source or handle it
                # Actually, let's create a special source for text
                text_source = {"type": "text_input", "value": text_content[:50] + "...", "name": "Text Input"}
                self.image_source = text_source # Temporarily to fit on_success / append_history
                
                self.root.after(0, lambda: self.on_success(result, count))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def add_to_generation_queue(self, sources):
        if not hasattr(self, 'generation_queue'):
            self.generation_queue = []
            self.queue_total_count = 0
            self.queue_processed_count = 0
            
        if not self.generation_queue:
            self.queue_total_count = 0
            self.queue_processed_count = 0
            
        self.generation_queue.extend(sources)
        self.queue_total_count += len(sources)
        
        self.status_var.set(f"대기열에 {len(sources)}개 이미지 추가됨 (총 {self.queue_total_count - self.queue_processed_count}개 대기 중)")
        
        if not self.generation_in_progress:
            self.process_next_in_queue()

    def download_and_queue_url(self, url):
        self.status_var.set("URL 다운로드 대기 중...")
        def worker():
            try:
                is_llama = self.model_var.get().startswith("local-llama-cpp")
                data, mime = download_image_from_url(url, bypass_size_limit=is_llama)
                source = {"type": "url_data", "value": data, "mime_type": mime, "url": url}
                self.root.after(0, lambda: self.add_to_generation_queue([source]))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))
        threading.Thread(target=worker, daemon=True).start()

    def process_next_in_queue(self):
        if not self.generation_queue:
            self.status_var.set("대기열 모든 이미지 처리 완료")
            self.set_busy(False)
            return
            
        if self.cancel_requested:
            self.generation_queue.clear()
            self.status_var.set("대기열 처리가 중단되었습니다.")
            self.set_busy(False)
            return
            
        source = self.generation_queue.pop(0)
        self.queue_processed_count += 1
        
        self.set_image_source(source)
        self.generation_in_progress = False 
        self.on_generate()
        
        source_name = ""
        if source["type"] == "file":
            source_name = Path(source["value"]).name
        elif source["type"] == "drop_data":
            source_name = source.get("name", "Dropped Image")
        elif source["type"] == "url_data":
            source_name = source.get("url", "URL Image")
            if "/" in source_name:
                source_name = source_name.split("/")[-1]
                
        self.status_var.set(f"대기열 처리 중 ({self.queue_processed_count}/{self.queue_total_count}) - {source_name}")

    # =========================================================================
    # JSON Editor Methods
    # =========================================================================
    
    def on_export_to_json_editor(self):
        """Export the current KREA2 JSON output to the JSON editor tab and switch to it."""
        # Use the existing on_load_current_json logic, then switch tab
        import json
        json_text = self.json_output_text.get("1.0", "end-1c").strip()
        en_text = self.output_text.get("1.0", "end-1c").strip()
        
        if not json_text and not en_text:
            messagebox.showwarning("알림", "내보낼 생성 결과가 없습니다. 먼저 프롬프트를 생성하세요.")
            return
        
        # Switch to JSON editor tab first
        self.input_notebook.select(self.json_editor_tab)
        
        # Then load the data (reuse on_load_current_json)
        self.on_load_current_json()
        self.status_var.set("KREA2 JSON을 JSON 편집기로 내보냈습니다.")
    
    def on_parse_json_editor(self):
        """Parse the JSON input and build editable attribute fields."""
        import json
        raw_text = self.json_editor_input.get("1.0", "end-1c").strip()
        if not raw_text:
            messagebox.showwarning("알림", "파싱할 JSON을 입력하세요.")
            return
        
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON 파싱 오류", f"올바른 JSON 형식이 아닙니다:\n{e}")
            return
        
        self.json_editor_data = data
        self._build_json_editor_fields(data)
        self.status_var.set("JSON 파싱 완료 - 속성을 편집하세요.")
    
    def on_load_current_json(self):
        """Load the current KREA2 JSON output into the JSON editor."""
        import json
        json_text = self.json_output_text.get("1.0", "end-1c").strip()
        en_text = self.output_text.get("1.0", "end-1c").strip()
        
        if not json_text and not en_text:
            messagebox.showwarning("알림", "불러올 생성 결과가 없습니다. 먼저 프롬프트를 생성하세요.")
            return
        
        # Try to reconstruct the full structure with text_prompt + krea2_json
        combined = {}
        
        # Parse text_prompt from English output
        if en_text:
            text_prompt_dict = {}
            for line in en_text.split("\n"):
                if ":" in line:
                    key_part, val_part = line.split(":", 1)
                    key_clean = key_part.strip().replace("/", "_").replace(" ", "_").replace("&", "")
                    # Map display labels back to keys
                    label_to_key = {
                        "Background_Lighting": "Background_Lighting",
                        "Person": "Person",
                        "Character_Expressions": "Character_Expressions",
                        "Pose": "Pose",
                        "Skin__Body_Condition": "Skin_Body_Condition",
                        "Skin_Body_Condition": "Skin_Body_Condition",
                        "Outfit": "Outfit",
                        "Camera": "Camera",
                        "Mood_Color": "Mood_Color",
                        "Style": "Style",
                        "Text__Layout_Instruction": "Text_Layout_Instruction",
                        "Text_Layout_Instruction": "Text_Layout_Instruction",
                        "Characters": "Characters",
                        "Interpersonal_Dynamics": "Interpersonal_Dynamics",
                        "Props__Environment_Details": "Props_Environment_Details",
                        "Camera__Composition": "Camera_Composition",
                        "Style__Texture": "Style_Texture",
                    }
                    actual_key = label_to_key.get(key_clean, key_clean)
                    text_prompt_dict[actual_key] = val_part.strip()
            if text_prompt_dict:
                combined["text_prompt"] = text_prompt_dict
        
        # Parse krea2_json
        if json_text:
            try:
                krea2_data = json.loads(json_text)
                combined["krea2_json"] = krea2_data
            except json.JSONDecodeError:
                pass
        
        if not combined:
            messagebox.showwarning("알림", "불러올 데이터가 없습니다.")
            return
        
        # Set the JSON editor input
        formatted = json.dumps(combined, indent=2, ensure_ascii=False)
        self.json_editor_input.delete("1.0", "end")
        self.json_editor_input.insert("1.0", formatted)
        
        # Parse it
        self.json_editor_data = combined
        self._build_json_editor_fields(combined)
        self.status_var.set("현재 결과를 JSON 편집기에 불러왔습니다.")
    
    def on_preview_edited_json(self):
        """Collect edited fields and update the JSON input area."""
        import json
        if not self.json_editor_fields:
            messagebox.showwarning("알림", "먼저 JSON을 파싱하세요.")
            return
        
        edited = self._collect_edited_json()
        formatted = json.dumps(edited, indent=2, ensure_ascii=False)
        self.json_editor_input.delete("1.0", "end")
        self.json_editor_input.insert("1.0", formatted)
        self.status_var.set("수정된 JSON이 입력 영역에 반영되었습니다.")
    
    def on_clear_json_editor(self):
        """Clear the JSON editor input and attribute fields."""
        self.json_editor_input.delete("1.0", "end")
        self.json_editor_data = {}
        self.json_editor_fields = {}
        for widget in self.je_scrollable_frame.winfo_children():
            widget.destroy()
        # Re-add placeholder
        self.je_placeholder = ttk.Label(
            self.je_scrollable_frame,
            text="JSON을 입력하고 'JSON 파싱' 버튼을 클릭하면\n여기에 편집 가능한 속성이 표시됩니다.",
            foreground=COLORS["text_muted"], justify="center"
        )
        self.je_placeholder.pack(pady=40)
        self.status_var.set("JSON 편집기가 초기화되었습니다.")
    
    def _build_json_editor_fields(self, data):
        """Dynamically build editable fields from parsed JSON dict."""
        # Clear existing widgets
        for widget in self.je_scrollable_frame.winfo_children():
            widget.destroy()
        self.json_editor_fields = {}
        
        section_labels = {
            "text_prompt": "📝 Text Prompt (텍스트 프롬프트)",
            "krea2_json": "🎨 KREA2 JSON"
        }
        
        field_labels = {
            "Background_Lighting": "🌅 배경/조명",
            "Person": "👤 인물",
            "Character_Expressions": "🎭 표정",
            "Pose": "🧍 포즈",
            "Skin_Body_Condition": "✨ 피부/신체",
            "Outfit": "👗 의상",
            "Camera": "📷 카메라",
            "Mood_Color": "🎨 분위기/색상",
            "Style": "🖌️ 스타일",
            "Text_Layout_Instruction": "📐 텍스트/레이아웃",
            "Characters": "👥 캐릭터",
            "Interpersonal_Dynamics": "🤝 대인 관계",
            "Props_Environment_Details": "🏠 소품/환경",
            "Camera_Composition": "📷 카메라/구도",
            "Style_Texture": "🖌️ 스타일/질감",
            "camera_3d_transform": "🎥 3D 카메라 좌표계 (Camera 3D Orbit)",
            "orbit_azimuth_deg": "🔄 수평 회전각 (Azimuth/Yaw 0°~360°)",
            "orbit_elevation_deg": "📐 수직 고도각 (Elevation/Pitch -90°~+90°)",
            "camera_distance": "📏 촬영 거리 (Camera Distance)",
            "z_index": "📶 깊이 레이어 (Z-Index / 1:전경, 2:중경, 3:배경)",
            "facing_direction_deg": "🧭 피사체 시선/방향 (Facing Direction 0°~360°)",
            "box_2d": "📦 바운딩 박스 (BBox [ymin, xmin, ymax, xmax])",
            "spatial_layout": "📐 공간 배치 / 레이아웃 (Spatial Layout)",
            "spatial_objects": "🎯 검출/배치 객체 (Spatial Objects)",
            "props_and_objects": "📦 소품 및 객체 (Props & Objects)",
            "category": "🏷️ 객체 분류 (Category)",
            "material": "🧱 재질 및 질감 (Material)",
            "state": "⚡ 상태 및 효과 (State & Effects)",
            "interaction": "🤝 상호작용 / 배치 (Interaction)",
            "attributes": "⚙️ 세부 속성 (Attributes)",
            "label": "📌 명칭 및 설명 (Label)",
            "subject": "👤 주요 피사체 (Subject)",
            "environment": "🏞️ 환경 및 배경 (Environment)",
            "composition_and_camera": "📷 구도 및 카메라 (Composition & Camera)",
            "lighting_and_atmosphere": "💡 조명 및 분위기 (Lighting & Atmosphere)",
            "art_style_and_materials": "🎨 스타일 및 재질 (Style & Materials)",
            "group_formation": "👥 그룹 대형 (Group Formation)",
            "scene_metadata": "🎬 장면 메타데이터 (Scene Metadata)",
            "photography_and_framing": "📸 촬영 및 프레이밍 (Photography & Framing)",
            "lighting_and_color": "🌈 조명 및 색상 (Lighting & Color)",
            "dynamism_and_texture": "✨ 동세 및 질감 (Dynamism & Texture)",
            "environment_and_props": "🏰 환경 및 소품 (Environment & Props)",
        }
        
        def add_section(parent, section_key, section_data, prefix=""):
            """Recursively add editable fields for a section."""
            if isinstance(section_data, dict):
                for key, value in section_data.items():
                    dotted_key = f"{prefix}.{key}" if prefix else key
                    
                    if isinstance(value, dict):
                        # Nested section - create a LabelFrame
                        label_text = field_labels.get(key, key.replace("_", " ").title())
                        nested_frame = ttk.LabelFrame(parent, text=label_text, style="Card.TLabelframe")
                        nested_frame.pack(fill="x", pady=(SPACING["xs"], SPACING["sm"]), padx=2)
                        add_section(nested_frame, key, value, dotted_key)
                    elif isinstance(value, list):
                        # List - show as JSON string for editing
                        import json
                        label_text = field_labels.get(key, key.replace("_", " ").title())
                        ttk.Label(parent, text=label_text, font=FONTS["bold"]).pack(anchor="w", padx=SPACING["xs"], pady=(SPACING["xs"], 0))
                        
                        text_widget = tk.Text(
                            parent, wrap="word", height=3, font=FONTS["main"],
                            bg=COLORS["surface_alt"], fg=COLORS["text_primary"],
                            insertbackground=COLORS["text_primary"], relief="flat",
                            highlightthickness=1, highlightbackground=COLORS["surface_alt_strong"],
                            highlightcolor=COLORS["accent"]
                        )
                        text_widget.pack(fill="x", padx=SPACING["xs"], pady=(0, SPACING["xs"]))
                        text_widget.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))
                        self.json_editor_fields[dotted_key] = ("list", text_widget)
                    else:
                        # Leaf value - create label + text input
                        label_text = field_labels.get(key, key.replace("_", " ").title())
                        ttk.Label(parent, text=label_text, font=FONTS["bold"]).pack(anchor="w", padx=SPACING["xs"], pady=(SPACING["xs"], 0))
                        
                        str_val = str(value) if value is not None else ""
                        # Determine height based on content length
                        line_count = max(2, min(5, len(str_val) // 80 + 1))
                        
                        text_widget = tk.Text(
                            parent, wrap="word", height=line_count, font=FONTS["main"],
                            bg=COLORS["surface_alt"], fg=COLORS["text_primary"],
                            insertbackground=COLORS["text_primary"], relief="flat",
                            highlightthickness=1, highlightbackground=COLORS["surface_alt_strong"],
                            highlightcolor=COLORS["accent"]
                        )
                        text_widget.pack(fill="x", padx=SPACING["xs"], pady=(0, SPACING["xs"]))
                        text_widget.insert("1.0", str_val)
                        self.json_editor_fields[dotted_key] = ("str", text_widget)
        
        # Build fields for each top-level section
        for section_key in ["text_prompt", "krea2_json"]:
            section_data = data.get(section_key)
            if section_data:
                section_label = section_labels.get(section_key, section_key)
                section_frame = ttk.LabelFrame(self.je_scrollable_frame, text=section_label, style="Card.TLabelframe")
                section_frame.pack(fill="x", pady=SPACING["sm"], padx=2)
                add_section(section_frame, section_key, section_data, section_key)
        
        # Handle any other top-level keys not in text_prompt or krea2_json
        other_keys = [k for k in data.keys() if k not in ("text_prompt", "krea2_json")]
        if other_keys:
            other_frame = ttk.LabelFrame(self.je_scrollable_frame, text="⚙️ 기타 속성", style="Card.TLabelframe")
            other_frame.pack(fill="x", pady=SPACING["sm"], padx=2)
            other_data = {k: data[k] for k in other_keys}
            add_section(other_frame, "other", other_data, "")
        
        # Force canvas scroll region update
        self.je_scrollable_frame.update_idletasks()
        self.je_canvas.configure(scrollregion=self.je_canvas.bbox("all"))
    
    def _collect_edited_json(self):
        """Collect current values from all editor fields into a dict."""
        import json
        result = {}
        
        for dotted_key, (val_type, widget) in self.json_editor_fields.items():
            parts = dotted_key.split(".")
            current = result
            
            # Navigate/create nested dicts
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            
            # Set the leaf value
            raw_val = widget.get("1.0", "end-1c").strip()
            if val_type == "list":
                try:
                    current[parts[-1]] = json.loads(raw_val)
                except json.JSONDecodeError:
                    current[parts[-1]] = raw_val
            else:
                # Try to preserve numeric types (z_index, orbit_azimuth_deg, etc.)
                if raw_val:
                    try:
                        # Try integer first (e.g. z_index: 2)
                        if raw_val.lstrip('-').isdigit():
                            current[parts[-1]] = int(raw_val)
                        else:
                            # Try float (e.g. some decimal value)
                            float_val = float(raw_val)
                            current[parts[-1]] = float_val
                    except (ValueError, AttributeError):
                        current[parts[-1]] = raw_val
                else:
                    current[parts[-1]] = raw_val
        
        return result
    
    def on_generate_json_edit(self):
        """Generate a polished prompt from the user-edited JSON."""
        import json
        
        if self.generation_in_progress:
            return
        
        # Collect edited JSON
        if self.json_editor_fields:
            edited_data = self._collect_edited_json()
        else:
            # Try parsing directly from input text
            raw_text = self.json_editor_input.get("1.0", "end-1c").strip()
            if not raw_text:
                messagebox.showwarning("알림", "편집할 JSON을 입력하고 'JSON 파싱' 버튼을 클릭하세요.")
                return
            try:
                edited_data = json.loads(raw_text)
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON 오류", f"올바른 JSON 형식이 아닙니다:\n{e}")
                return
        
        edited_json_text = json.dumps(edited_data, indent=2, ensure_ascii=False)
        
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not self.model_var.get().startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            return
        
        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        self.json_output_text.delete("1.0", "end")
        self.json_ko_output_text.delete("1.0", "end")
        
        def worker():
            try:
                from ..core.prompt import generate_json_edit_logic
                
                def chunk_handler(chunk):
                    self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                    self.root.after(0, lambda: self.output_text.see("end"))

                current_tag = "ko"
                def pass2_chunk_handler(chunk):
                    nonlocal current_tag
                    while chunk:
                        tags = {"[KOREAN]": "ko", "[CHINESE]": "zh", "[JSON_KO]": "json_ko", "[JSON]": "json"}
                        first_tag_pos = -1
                        first_tag_str = ""
                        
                        for t in tags:
                            pos = chunk.find(t)
                            if pos != -1 and (first_tag_pos == -1 or pos < first_tag_pos):
                                first_tag_pos = pos
                                first_tag_str = t
                                
                        if first_tag_pos == -1:
                            if current_tag == "ko":
                                self.root.after(0, lambda c=chunk: self.translation_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_text.see("end"))
                            elif current_tag == "zh":
                                self.root.after(0, lambda c=chunk: self.translation_zh_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_zh_text.see("end"))
                            elif current_tag == "json":
                                self.root.after(0, lambda c=chunk: self.json_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_output_text.see("end"))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda c=chunk: self.json_ko_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_ko_output_text.see("end"))
                            break
                            
                        pre_text = chunk[:first_tag_pos]
                        if pre_text:
                            if current_tag == "ko":
                                self.root.after(0, lambda p=pre_text: self.translation_text.insert("end", p))
                            elif current_tag == "zh":
                                self.root.after(0, lambda p=pre_text: self.translation_zh_text.insert("end", p))
                            elif current_tag == "json":
                                self.root.after(0, lambda p=pre_text: self.json_output_text.insert("end", p))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda p=pre_text: self.json_ko_output_text.insert("end", p))
                                
                        current_tag = tags[first_tag_str]
                        if current_tag == "ko":
                            self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        elif current_tag == "zh":
                            self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        elif current_tag == "json":
                            self.root.after(0, lambda: self.json_output_text.delete("1.0", "end"))
                        elif current_tag == "json_ko":
                            self.root.after(0, lambda: self.json_ko_output_text.delete("1.0", "end"))
                            
                        chunk = chunk[first_tag_pos + len(first_tag_str):]
                
                result, count = generate_json_edit_logic(
                    edited_json_text, api_key,
                    self.model_name, self.model_thinking_level,
                    self.keyword_text.get("1.0", "end-1c"),
                    on_chunk=chunk_handler,
                    on_pass2_chunk=pass2_chunk_handler,
                    cancel_check=lambda: self.cancel_requested,
                    active_character_ids=self.get_active_character_ids(),
                    enable_thinking=self.enable_thinking_var.get()
                )
                
                result["input_text"] = edited_json_text
                text_source = {"type": "text_input", "value": "JSON편집: " + edited_json_text[:40] + "...", "name": "JSON Edit"}
                self.image_source = text_source
                
                self.root.after(0, lambda: self.on_success(result, count))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.on_error(err))

        threading.Thread(target=worker, daemon=True).start()

    def clear_remix(self):
        for cb in self.remix_combos.values():
            cb.set("")

    def refresh_remix_options(self):
        import json
        history_file = Path("history.txt")
        options = {attr: set() for attr in self.remix_attributes}
        
        # Load presets for all attributes
        presets = load_presets()
        attr_favs = {}
        for attr in self.remix_attributes:
            fav_set = set()
            if attr in presets and isinstance(presets[attr], dict):
                fav_set.update(presets[attr].values())
            if attr == "Character_Expressions" and "expressions" in presets:
                fav_set.update(presets["expressions"].values())
            elif attr == "Pose" and "poses" in presets:
                fav_set.update(presets["poses"].values())
            attr_favs[attr] = fav_set
        
        if history_file.exists():
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if not line.strip(): continue
                        try:
                            data = json.loads(line)
                            json_out = data.get("json", "")
                            if json_out:
                                try:
                                    parsed = json.loads(json_out)
                                    for cat in ["scene_metadata", "characters", "environment_and_props", "photography_and_framing", "lighting_and_color", "dynamism_and_texture"]:
                                        if cat in parsed:
                                            val = parsed[cat]
                                            if isinstance(val, dict):
                                                for sub_k, sub_v in val.items():
                                                    if isinstance(sub_v, str) and sub_v:
                                                        if "light" in sub_k or "color" in sub_k:
                                                            options["Background_Lighting"].add(sub_v)
                                                        if "camera" in sub_k or "lens" in sub_k:
                                                            options["Camera"].add(sub_v)
                                            elif isinstance(val, list) and cat == "characters":
                                                for char_obj in val:
                                                    if isinstance(char_obj, dict):
                                                        pose = char_obj.get("individual_pose")
                                                        if pose:
                                                            options["Pose"].add(pose)
                                                        outfit = char_obj.get("outfit")
                                                        if isinstance(outfit, dict):
                                                            top = outfit.get("top")
                                                            if top:
                                                                options["Outfit"].add(top)
                                                        expr = char_obj.get("facial_expression")
                                                        if expr:
                                                            options["Character_Expressions"].add(expr)
                                except:
                                    pass
                            
                            en_text = data.get("en", "")
                            for ln in en_text.split('\n'):
                                if ':' in ln:
                                    parts = ln.split(':', 1)
                                    key = parts[0].strip().replace("/", "_").replace(" ", "_")
                                    val = parts[1].strip()
                                    if key in options and val:
                                        options[key].add(val)
                        except:
                            pass
            except Exception as e:
                print(f"Error reading history for remix: {e}")
                
        # Format values based on 'Favorites Only' checkbox
        favorites_only = getattr(self, "remix_fav_only_var", None) and self.remix_fav_only_var.get()
        
        try:
            for attr in self.remix_attributes:
                favs = attr_favs.get(attr, set())
                if favorites_only:
                    vals = [""] + sorted(list(favs))
                else:
                    # Show all, prioritizing favorites with '★ '
                    star_opts = []
                    regular_opts = []
                    for val in options[attr]:
                        if val.startswith("★ "):
                            val = val[2:]
                        if val in favs:
                            star_opts.append(f"★ {val}")
                        else:
                            regular_opts.append(val)
                            
                    # Add any presets not yet present in history
                    for val in favs:
                        if f"★ {val}" not in star_opts:
                            star_opts.append(f"★ {val}")
                                
                    vals = [""] + sorted(star_opts) + sorted(regular_opts)
                    
                if attr in self.remix_combos:
                    self.remix_combos[attr]['values'] = vals
        except Exception as e:
            print(f"Error sorting remix options: {e}")

    def on_generate_remix(self):
        if self.generation_in_progress:
            return
            
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        
        if not self.model_var.get().startswith("local-llama-cpp") and not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            return
            
        assembled_parts = []
        for attr in self.remix_attributes:
            val = self.remix_combos[attr].get().strip()
            if val:
                # Strip ★ prefix if present
                if val.startswith("★ "):
                    val = val[2:]
                assembled_parts.append(f"{attr.replace('_', '/')}: {val}")
                
        if not assembled_parts:
            messagebox.showwarning("알림", "조합할 항목을 하나 이상 선택하거나 입력하세요.")
            return
            
        assembled_text = "\n".join(assembled_parts)
        
        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        self.json_output_text.delete("1.0", "end")
        self.json_ko_output_text.delete("1.0", "end")
        
        def worker():
            try:
                from ..core.prompt import generate_remix_logic
                
                def chunk_handler(chunk):
                    self.root.after(0, lambda c=chunk: self.output_text.insert("end", c))
                    self.root.after(0, lambda: self.output_text.see("end"))

                current_tag = "ko"
                def pass2_chunk_handler(chunk):
                    nonlocal current_tag
                    while chunk:
                        tags = {"[KOREAN]": "ko", "[CHINESE]": "zh", "[JSON_KO]": "json_ko", "[JSON]": "json"}
                        first_tag_pos = -1
                        first_tag_str = ""
                        
                        for tag_str, tag_key in tags.items():
                            pos = chunk.find(tag_str)
                            if pos != -1 and (first_tag_pos == -1 or pos < first_tag_pos):
                                first_tag_pos = pos
                                first_tag_str = tag_str
                                
                        if first_tag_pos == -1:
                            if current_tag == "ko":
                                self.root.after(0, lambda c=chunk: self.translation_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_text.see("end"))
                            elif current_tag == "zh":
                                self.root.after(0, lambda c=chunk: self.translation_zh_text.insert("end", c))
                                self.root.after(0, lambda: self.translation_zh_text.see("end"))
                            elif current_tag == "json":
                                self.root.after(0, lambda c=chunk: self.json_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_output_text.see("end"))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda c=chunk: self.json_ko_output_text.insert("end", c))
                                self.root.after(0, lambda: self.json_ko_output_text.see("end"))
                            break
                            
                        pre_text = chunk[:first_tag_pos]
                        if pre_text:
                            if current_tag == "ko":
                                self.root.after(0, lambda p=pre_text: self.translation_text.insert("end", p))
                            elif current_tag == "zh":
                                self.root.after(0, lambda p=pre_text: self.translation_zh_text.insert("end", p))
                            elif current_tag == "json":
                                self.root.after(0, lambda p=pre_text: self.json_output_text.insert("end", p))
                            elif current_tag == "json_ko":
                                self.root.after(0, lambda p=pre_text: self.json_ko_output_text.insert("end", p))
                                
                        current_tag = tags[first_tag_str]
                        if current_tag == "ko":
                            self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        elif current_tag == "zh":
                            self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        elif current_tag == "json":
                            self.root.after(0, lambda: self.json_output_text.delete("1.0", "end"))
                        elif current_tag == "json_ko":
                            self.root.after(0, lambda: self.json_ko_output_text.delete("1.0", "end"))
                            
                        chunk = chunk[first_tag_pos + len(first_tag_str):]
                
                result, count = generate_remix_logic(
                    assembled_text, api_key,
                    self.model_name, self.model_thinking_level,
                    self.keyword_text.get("1.0", "end-1c"),
                    on_chunk=chunk_handler,
                    on_pass2_chunk=pass2_chunk_handler,
                    cancel_check=lambda: self.cancel_requested,
                    active_character_ids=self.get_active_character_ids(),
                    enable_thinking=self.enable_thinking_var.get()
                )
                
                result["input_text"] = assembled_text
                if hasattr(self, 'keyword_text'):
                    result["keyword"] = self.keyword_text.get("1.0", "end-1c")
                    
                self.root.after(0, self.on_success, result, count)
                
            except Exception as e:
                self.root.after(0, self.on_error, e)
                
        threading.Thread(target=worker, daemon=True).start()
