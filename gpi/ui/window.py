import threading
import tkinter as tk
import queue
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

from .styles import COLORS, SPACING, FONTS
from .dialogs import ApiKeyDialog
from .dnd import (
    setup_dnd, get_image_from_clipboard, WIN_DND_AVAILABLE,
    CF_FILEDESCRIPTORW, CF_FILEDESCRIPTORA, CF_FILECONTENTS,
    CF_URLW, CF_URLA, CF_PNG, CF_DIB
)
from ..core.config import (
    MODEL_OPTIONS, MODEL_THINKING_LEVELS, get_api_key, 
    CANCELLED_MESSAGE, load_api_keys,
    MIN_PROMPT_WORDS, MAX_PROMPT_WORDS, 
    HIGH_FIDELITY_MIN_WORDS, HIGH_FIDELITY_MAX_WORDS
)
from ..core.image import (
    prepare_image_bytes, detect_mime_from_bytes, 
    parse_file_group_descriptor, parse_dropfiles,
    read_istream_all
)
from ..core.api import download_image_from_url, validate_model_access, fetch_available_models, is_url
from ..core.prompt import generate_prompt_logic, append_history, load_history, save_all_history, delete_history_item_files
from ..core.utils import log_event
import pythoncom
import win32con
from PIL import Image, ImageTk
from io import BytesIO

class PromptApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GPI - Gemini Prompt Instrument")
        self.root.geometry("1100x900")
        
        # State
        self.image_source = None
        self.model_name = "gemini-flash-latest" # User preferred default
        self.model_thinking_level = None
        self.generation_in_progress = False
        self.download_in_progress = False
        self.cancel_requested = False
        self.history = load_history()
        
        # Variable Initialization
        self.model_var = tk.StringVar(value=self.model_name)
        self.api_key_name_var = tk.StringVar(value="Default")
        self.file_path_var = tk.StringVar(value="선택된 파일 없음")
        self.keyword_var = tk.StringVar()
        self.status_var = tk.StringVar(value="대기 중")
        
        # Fidelity and Word Count State
        self.high_fidelity_var = tk.BooleanVar(value=True)
        self.min_words_var = tk.IntVar(value=HIGH_FIDELITY_MIN_WORDS)
        self.max_words_var = tk.IntVar(value=HIGH_FIDELITY_MAX_WORDS)
        
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
        
        # Initial model fetch
        self.root.after(100, self.refresh_models)
        
        log_event("app_start")

    def refresh_models(self):
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not api_key:
            self.model_combo["values"] = []
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
        self.model_combo.pack(side="left", padx=SPACING["sm"])
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_change)
        
        ttk.Label(top_panel, text="API 키:", font=FONTS["bold"]).pack(side="left", padx=(SPACING["md"], 0))
        self.api_key_name_var = tk.StringVar(value="Default")
        self.api_key_combo = ttk.Combobox(top_panel, textvariable=self.api_key_name_var, state="readonly", width=15)
        self.api_key_combo.pack(side="left", padx=SPACING["sm"])
        self.api_key_combo.bind("<<ComboboxSelected>>", self.on_api_key_change)
        
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
        
        # --- Left Side: Input ---
        # Drag & Drop Zone
        self.drop_label = tk.Label(
            left_side, text="여기에 이미지를 드래그하거나\n클립보드 이미지를 붙여넣으세요 (Ctrl+V)",
            background=COLORS["surface_alt"], foreground=COLORS["text_secondary"],
            relief="groove", bd=1, height=10
        )
        self.drop_label.pack(fill="x", pady=(0, SPACING["md"]))
        self.drop_label.bind("<Enter>", self.on_drop_hover)
        self.drop_label.bind("<Leave>", self.on_drop_leave)
        
        file_frame = ttk.Frame(left_side)
        file_frame.pack(fill="x")
        ttk.Button(file_frame, text="이미지 파일 선택", command=self.on_pick_file).pack(side="left")
        
        self.file_path_var = tk.StringVar(value="선택된 파일 없음")
        ttk.Label(left_side, textvariable=self.file_path_var, font=FONTS["main"], foreground=COLORS["text_muted"]).pack(fill="x", pady=SPACING["xs"])
        
        # Options
        opt_frame = ttk.LabelFrame(left_side, text="추가 옵션", style="Card.TLabelframe")
        opt_frame.pack(fill="x", pady=SPACING["md"])
        
        ttk.Label(opt_frame, text="키워드 (선택):").pack(anchor="w", padx=SPACING["sm"])
        self.keyword_var = tk.StringVar()
        self.keyword_entry = ttk.Entry(opt_frame, textvariable=self.keyword_var)
        self.keyword_entry.pack(fill="x", padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        
        # High Fidelity Checkbox
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
        btn_frame = ttk.Frame(left_side)
        btn_frame.pack(fill="x", pady=SPACING["md"])
        self.generate_button = ttk.Button(btn_frame, text="프롬프트 생성 (F1)", style="Accent.TButton", command=self.on_generate)
        self.generate_button.pack(fill="x", pady=SPACING["xs"])
        
        self.cancel_button = ttk.Button(btn_frame, text="중지", state="disabled", command=self.on_cancel)
        self.cancel_button.pack(fill="x")
        
        # Preview Area at the bottom
        self.preview_frame = ttk.LabelFrame(left_side, text="이미지 미리보기", style="Card.TLabelframe")
        self.preview_frame.pack(side="bottom", fill="x", pady=(SPACING["md"], 0))
        
        self.preview_label = tk.Label(self.preview_frame, background=COLORS["surface_alt"])
        self.preview_label.pack(fill="both", expand=True, padx=SPACING["xs"], pady=SPACING["xs"])
        
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
        
        self.output_text = tk.Text(en_frame, wrap="word", height=8, font=FONTS["monospace"])
        self.output_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # Korean Translation
        ko_frame = ttk.LabelFrame(self.output_paned, text="한글 번역 (Korean)", style="Card.TLabelframe")
        self.output_paned.add(ko_frame, weight=1)
        
        # Copy Button for Korean
        ko_toolbar = ttk.Frame(ko_frame)
        ko_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(ko_toolbar, text="복사 (Copy)", command=self.on_copy_ko).pack(side="right")
        
        self.translation_text = tk.Text(ko_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.translation_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # Chinese Translation
        zh_frame = ttk.LabelFrame(self.output_paned, text="중국어 번역 (Chinese)", style="Card.TLabelframe")
        self.output_paned.add(zh_frame, weight=1)
        
        # Copy Button for Chinese
        zh_toolbar = ttk.Frame(zh_frame)
        zh_toolbar.pack(fill="x", padx=SPACING["sm"], pady=(SPACING["xs"], 0))
        ttk.Button(zh_toolbar, text="복사 (Copy)", command=self.on_copy_zh).pack(side="right")
        
        self.translation_zh_text = tk.Text(zh_frame, wrap="word", height=8, font=FONTS["monospace"], foreground=COLORS["text_secondary"])
        self.translation_zh_text.pack(fill="both", expand=True, padx=SPACING["sm"], pady=SPACING["sm"])
        
        # History
        history_frame = ttk.LabelFrame(right_side, text="최근 히스토리", style="Card.TLabelframe")
        history_frame.pack(fill="both", expand=True, pady=(SPACING["md"], 0))
        
        # Tools/Actions frame above the list for visibility
        btns_frame = ttk.Frame(history_frame)
        btns_frame.pack(fill="x", padx=SPACING["sm"], pady=SPACING["xs"])
        ttk.Button(btns_frame, text="선택 항목 삭제 (Del)", command=self.on_delete_history).pack(side="right")
        
        list_container = ttk.Frame(history_frame)
        list_container.pack(fill="both", expand=True, padx=SPACING["sm"], pady=(0, SPACING["sm"]))
        
        self.history_list = tk.Listbox(list_container, height=8) # Slightly smaller height to balance
        self.history_list.pack(side="left", fill="both", expand=True)
        
        scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.history_list.yview)
        scrollbar.pack(side="right", fill="y")
        self.history_list.configure(yscrollcommand=scrollbar.set)
        
        self.history_list.bind("<<ListboxSelect>>", self.on_history_select)
        self.history_list.bind("<Delete>", lambda e: self.on_delete_history())
        
        # Start drop queue poller
        self.root.after(100, self._poll_drop_queue)

    def setup_dnd(self):
        self._win_drop_formats = {
            "hdrop": (win32con.CF_HDROP, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "filedesc_w": (CF_FILEDESCRIPTORW, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "filedesc_a": (CF_FILEDESCRIPTORA, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "filecontents": (CF_FILECONTENTS, None, pythoncom.DVASPECT_CONTENT, 0, pythoncom.TYMED_ISTREAM | pythoncom.TYMED_HGLOBAL | pythoncom.TYMED_FILE),
            "url_w": (CF_URLW, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "url_a": (CF_URLA, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "png": (CF_PNG, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "dib": (CF_DIB, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "text_w": (win32con.CF_UNICODETEXT, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL),
            "text_a": (win32con.CF_TEXT, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)
        }
        self.root.update_idletasks()
        self._win_target, self._win_com_target = setup_dnd(self.root, self.drop_label, self)
        self.root.bind_all("<Control-v>", lambda e: self.on_paste())
        self.root.bind_all("<F1>", lambda e: self.on_generate())
    
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
        key_name = self.api_key_name_var.get()
        api_key = get_api_key(key_name)
        if not api_key:
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
        
        if not api_key:
            messagebox.showwarning("알림", "사용할 API 키를 선택하거나 설정하세요.")
            return
        if not self.image_source:
            messagebox.showwarning("알림", "이미지를 먼저 선택하세요.")
            return

        self.set_busy(True)
        self.output_text.delete("1.0", "end")
        self.translation_text.delete("1.0", "end")
        self.translation_zh_text.delete("1.0", "end")
        
        def worker():
            try:
                # 1. Prepare Image
                if self.image_source["type"] == "file":
                    data = Path(self.image_source["value"]).read_bytes()
                    mime = detect_mime_from_bytes(data, self.image_source["value"])
                else:
                    data = self.image_source["value"]
                    mime = self.image_source["mime_type"]
                
                prepared_data, _ = prepare_image_bytes(data, mime, self.image_source["type"])
                
                # Unified streaming handler for three languages
                current_tag = "en"
                
                def chunk_handler(chunk):
                    nonlocal current_tag
                    
                    if "[KOREAN]" in chunk:
                        parts = chunk.split("[KOREAN]")
                        if parts[0].strip():
                            self.root.after(0, lambda p=parts[0]: self.output_text.insert("end", p))
                        current_tag = "ko"
                        self.root.after(0, lambda: self.translation_text.delete("1.0", "end"))
                        if len(parts) > 1 and parts[1].strip():
                            self.root.after(0, lambda p=parts[1]: self.translation_text.insert("end", p))
                    elif "[CHINESE]" in chunk:
                        parts = chunk.split("[CHINESE]")
                        if parts[0].strip():
                            self.root.after(0, lambda p=parts[0]: self.translation_text.insert("end", p))
                        current_tag = "zh"
                        self.root.after(0, lambda: self.translation_zh_text.delete("1.0", "end"))
                        if len(parts) > 1 and parts[1].strip():
                            self.root.after(0, lambda p=parts[1]: self.translation_zh_text.insert("end", p))
                    else:
                        clean_chunk = chunk.replace("[ENGLISH]", "")
                        if current_tag == "en":
                            self.root.after(0, lambda c=clean_chunk: self.output_text.insert("end", c))
                            self.root.after(0, lambda: self.output_text.see("end"))
                        elif current_tag == "ko":
                            self.root.after(0, lambda c=clean_chunk: self.translation_text.insert("end", c))
                            self.root.after(0, lambda: self.translation_text.see("end"))
                        else:
                            self.root.after(0, lambda c=clean_chunk: self.translation_zh_text.insert("end", c))
                            self.root.after(0, lambda: self.translation_zh_text.see("end"))

                result, count = generate_prompt_logic(
                    prepared_data, mime, api_key, 
                    self.model_name, self.model_thinking_level, 
                    self.keyword_var.get(),
                    min_words=self.min_words_var.get(),
                    max_words=self.max_words_var.get(),
                    high_fidelity=self.high_fidelity_var.get(),
                    on_chunk=chunk_handler,
                    cancel_check=lambda: self.cancel_requested
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
        self.set_busy(False)
        self.output_text.delete("1.0", "end")
        self.output_text.insert("1.0", en_text)
        self.translation_text.delete("1.0", "end")
        self.translation_text.insert("1.0", ko_text)
        self.translation_zh_text.delete("1.0", "end")
        self.translation_zh_text.insert("1.0", zh_text)
        
        entry = append_history(result, self.image_source)
        if entry:
            self.history.append(entry)
        else:
            self.history.append(result)
        self.refresh_history_list()
        self.status_var.set("생성 및 번역 완료")

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

    def on_error(self, err):
        self.set_busy(False)
        if err != CANCELLED_MESSAGE:
            messagebox.showerror("오류", err)
        self.status_var.set("오류 발생" if err != CANCELLED_MESSAGE else "중단됨")

    def on_cancel(self):
        self.cancel_requested = True
        self.status_var.set("중단 요청 중...")

    def on_history_select(self, event):
        idx = self.history_list.curselection()
        if idx:
            # Historical list is reversed, so we must calculate the correct index
            real_idx = len(self.history) - 1 - idx[0]
            if real_idx < 0 or real_idx >= len(self.history):
                return
            entry = self.history[real_idx]
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", entry["en"])
            self.translation_text.delete("1.0", "end")
            self.translation_text.insert("1.0", entry["ko"])
            self.translation_zh_text.delete("1.0", "end")
            self.translation_zh_text.insert("1.0", entry.get("zh", ""))
            
            # Restore image if path exists
            image_rel_path = entry.get("image_path")
            if image_rel_path:
                from ..core.config import BASE_DIR
                full_path = BASE_DIR / image_rel_path
                if full_path.exists():
                    self.set_image_source({"type": "file", "value": str(full_path)})
            
            self.status_var.set("히스토리 항목과 이미지가 복원되었습니다.")

    def on_delete_history(self):
        idx = self.history_list.curselection()
        if not idx:
            return
        
        if not messagebox.askyesno("확인", "선택한 히스토리 항목을 삭제하시겠습니까?"):
            return
            
        # Historical list is reversed
        real_idx = len(self.history) - 1 - idx[0]
        if 0 <= real_idx < len(self.history):
            entry = self.history[real_idx]
            # Delete associated image file
            delete_history_item_files(entry)
            
            del self.history[real_idx]
            if save_all_history(self.history):
                self.refresh_history_list()
                self.status_var.set("히스토리 항목과 이미지가 삭제되었습니다.")
            else:
                messagebox.showerror("오류", "히스토리 파일 저장 중 오류가 발생했습니다.")

    def refresh_history_list(self):
        self.history_list.delete(0, "end")
        for h in reversed(self.history):
            self.history_list.insert("end", h["en"][:100] + "...")

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
            self.root.after(100, self._poll_drop_queue)

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
            # 1. Try Virtual Files (e.g. from Browser)
            descriptors = self._get_win_file_descriptors(data_obj)
            if descriptors:
                for idx, info in enumerate(descriptors):
                    data = self._get_win_file_content(data_obj, idx)
                    if data:
                        mime = detect_mime_from_bytes(data, info['name'])
                        if mime:
                            self.set_image_source({
                                "type": "drop_data", "value": data, "mime_type": mime, "name": info['name']
                            })
                            return
            
            # 2. Try Direct Formats (PNG, DIB)
            for fmt_key in ["png", "dib"]:
                fmt = self._win_drop_formats.get(fmt_key)
                if self.win_drop_query_format(data_obj, fmt):
                    try:
                        stg = data_obj.GetData(fmt)
                        raw = bytes(stg.data)
                        if fmt_key == "png":
                            self.set_image_source({"type": "drop_data", "value": raw, "mime_type": "image/png", "name": "dropped.png"})
                        elif fmt_key == "dib":
                            from io import BytesIO
                            from PIL import Image
                            img = Image.open(BytesIO(raw))
                            buf = BytesIO()
                            img.save(buf, format="PNG")
                            self.set_image_source({"type": "drop_data", "value": buf.getvalue(), "mime_type": "image/png", "name": "dropped.png"})
                        return
                    except Exception:
                        continue

            # 3. Try Local Files
            paths = self._get_win_hdrop_paths(data_obj)
            if paths:
                self.set_image_source({"type": "file", "value": paths[0]})
                return
                
            # 4. Try Text/URL
            text = self._get_win_text(data_obj)
            if text:
                if is_url(text):
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
                data, mime = download_image_from_url(url)
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
