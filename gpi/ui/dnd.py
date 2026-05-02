import os

try:
    import pythoncom
    import win32com.server.util
    import win32clipboard
    WIN_DND_AVAILABLE = True
    
    # OLE Clipboard Formats
    CF_FILEDESCRIPTORW = win32clipboard.RegisterClipboardFormat("FileGroupDescriptorW")
    CF_FILEDESCRIPTORA = win32clipboard.RegisterClipboardFormat("FileGroupDescriptor")
    CF_FILECONTENTS = win32clipboard.RegisterClipboardFormat("FileContents")
    CF_URLW = win32clipboard.RegisterClipboardFormat("UniformResourceLocatorW")
    CF_URLA = win32clipboard.RegisterClipboardFormat("UniformResourceLocator")
    CF_PNG = win32clipboard.RegisterClipboardFormat("PNG")
    CF_WEBP = win32clipboard.RegisterClipboardFormat("webp")
    CF_DIB = 8 # win32con.CF_DIB
except ImportError:
    WIN_DND_AVAILABLE = False
    CF_FILEDESCRIPTORW = None
    CF_FILEDESCRIPTORA = None
    CF_FILECONTENTS = None
    CF_URLW = None
    CF_URLA = None
    CF_PNG = None
    CF_WEBP = None
    CF_DIB = None

class WindowsDropTarget:
    _com_interfaces_ = [pythoncom.IID_IDropTarget] if WIN_DND_AVAILABLE else []
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]
    
    def __init__(self, callback_handler):
        self._handler = callback_handler

    def DragEnter(self, data_obj, key_state, pt, effect):
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
        return self._handler.win_drop_effect(data_obj)

    def DragOver(self, key_state, pt, effect):
        return self._handler.win_drop_effect(None)
        # handler should manage state

    def DragLeave(self):
        return None

    def Drop(self, data_obj, key_state, pt, effect):
        try:
            pythoncom.CoInitialize()
            # Marshal the IDataObject to transfer it safely to the main thread
            # returns an IStream pointer
            stream = pythoncom.CoMarshalInterThreadInterfaceInStream(pythoncom.IID_IDataObject, data_obj)
            self._handler.handle_win_drop_marshaled(stream)
            return 1 # DROPEFFECT_COPY
        except Exception as e:
            print(f"DEBUG: Drop marshalling failed: {e}")
            return 0

def setup_dnd(root, drop_label, handler):
    if not WIN_DND_AVAILABLE:
        return False
    
    try:
        pythoncom.OleInitialize()
        hwnd = drop_label.winfo_id()
        target = WindowsDropTarget(handler)
        com_target = win32com.server.util.wrap(target, pythoncom.IID_IDropTarget)
        pythoncom.RegisterDragDrop(hwnd, com_target)
        return target, com_target
    except Exception as e:
        print(f"Windows DND registration failed: {e}")
        return None, None

def get_image_from_clipboard(root):
    try:
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
        if isinstance(data, list):
            for item in data:
                if os.path.exists(item):
                    return {"type": "file", "value": item}
        elif data:
            from io import BytesIO
            buffer = BytesIO()
            data.save(buffer, format="PNG")
            return {"type": "clipboard", "value": buffer.getvalue(), "mime_type": "image/png"}
    except Exception:
        pass
    return None
