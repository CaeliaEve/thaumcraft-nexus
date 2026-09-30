"""Best-effort DWM styling while preserving all native window behavior."""
import sys


def theme_window(window):
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        hwnd = user32.GetAncestor(window.winfo_id(), 2)
        set_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        set_attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        set_attribute.restype = ctypes.c_long
        dark = ctypes.c_int(1)
        if set_attribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)) != 0:
            set_attribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        # COLORREF is 0x00BBGGRR. Unsupported attributes safely return E_INVALIDARG.
        for attribute, value in ((35, 0x10131B), (36, 0xB0C6D6)):
            color = wintypes.DWORD(value)
            set_attribute(hwnd, attribute, ctypes.byref(color), ctypes.sizeof(color))
    except (AttributeError, OSError):
        pass
