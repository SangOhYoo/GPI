import tkinter as tk
from tkinter import ttk

COLORS = {
    "surface": "#FDFDFD",
    "surface_alt": "#F8F9FA",
    "surface_alt_strong": "#E9ECEF",
    "text_primary": "#1A1A1A",
    "text_secondary": "#495057",
    "text_muted": "#868E96",
    "accent": "#4C6EF5",
    "accent_hover": "#3B5BDB",
    "border": "#DEE2E6",
    "border_strong": "#CED4DA",
    "success": "#37B24D",
    "error": "#F21F21",
}

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 20,
    "xl": 32,
}

FONTS = {
    "main": ("Malgun Gothic", 10),
    "bold": ("Malgun Gothic", 10, "bold"),
    "header": ("Malgun Gothic", 12, "bold"),
    "monospace": ("Consolas", 10),
}

def apply_design_system(root):
    style = ttk.Style(root)
    # Generic Frame
    style.configure("App.TFrame", background=COLORS["surface"])
    
    # Label
    style.configure("TLabel", background=COLORS["surface"], foreground=COLORS["text_primary"], font=FONTS["main"])
    style.configure("Header.TLabel", font=FONTS["header"])
    style.configure("Muted.TLabel", foreground=COLORS["text_muted"], font=("Malgun Gothic", 9))
    
    # Buttons
    style.configure("Accent.TButton", padding=(SPACING["md"], SPACING["sm"]))
    style.map("Accent.TButton", background=[("active", COLORS["accent_hover"]), ("!disabled", COLORS["accent"])])
    
    style.configure("Secondary.TButton", padding=(SPACING["md"], SPACING["sm"]))
    
    # Labelframe
    style.configure("Card.TLabelframe", background=COLORS["surface"], relief="flat", borderwidth=1)
    style.configure("Card.TLabelframe.Label", background=COLORS["surface"], foreground=COLORS["text_secondary"], font=FONTS["bold"], padding=(SPACING["sm"], 0))
    
    root.configure(background=COLORS["surface"])
