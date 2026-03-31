import tkinter as tk
from gpi.ui.window import PromptApp
from gpi.ui.styles import apply_design_system

def main():
    root = tk.Tk()
    apply_design_system(root)
    app = PromptApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
