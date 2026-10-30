"""Optional Windows backdrop and verified OpenGL photo rendering."""

from functools import lru_cache
import sys

from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat
from PySide6.QtWidgets import QApplication


def transparency_available():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22621


def set_window_shape(window, radius):
    """Apply the outer clip in native pixels, including Windows' backdrop."""
    window.setProperty("nativeOutlineActive", False)
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return
    import ctypes
    from ctypes import wintypes

    user = ctypes.WinDLL("user32")
    gdi = ctypes.WinDLL("gdi32")
    user.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
    gdi.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
    gdi.CreateRoundRectRgn.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    handle = int(window.winId())
    if sys.getwindowsversion().build >= 22000:
        # Mica is composed outside the Qt/GDI clip. Its corner preference must
        # also be explicit or Windows can fill a square behind our curved border.
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD,
                                             ctypes.c_void_p, wintypes.DWORD]
        preference = ctypes.c_int(2 if radius else 1)
        rounded = dwm.DwmSetWindowAttribute(handle, 33, ctypes.byref(preference), ctypes.sizeof(preference))
        # Let the compositor draw the curve and its single continuous border.
        # A GDI clip cuts through its antialiased pixels and makes arcs look dashed.
        border = wintypes.DWORD(0x005E5856 if radius else 0xFFFFFFFE)
        outlined = dwm.DwmSetWindowAttribute(handle, 34, ctypes.byref(border), ctypes.sizeof(border))
        if rounded == 0 and outlined == 0:
            window.setProperty("nativeOutlineActive", bool(radius))
            window.clearMask()
            user.SetWindowRgn(handle, None, True)
            return
    if radius:
        scale = window.devicePixelRatioF()
        diameter = round(radius * 2 * scale)
        region = gdi.CreateRoundRectRgn(0, 0, round(window.width() * scale) + 1,
                                       round(window.height() * scale) + 1, diameter, diameter)
        if region and not user.SetWindowRgn(handle, region, True):
            gdi.DeleteObject(region)
        # On success Windows owns the region; do not delete it.
    else:
        user.SetWindowRgn(handle, None, True)


def set_backdrop(window, enabled, light=False):
    """Windows 11 Mica; opaque fallback on other systems or a failed DWM call."""
    active = False
    if transparency_available() and QApplication.platformName() == "windows":
        import ctypes
        from ctypes import wintypes

        class Margins(ctypes.Structure):
            _fields_ = [(key, ctypes.c_int) for key in ("left", "right", "top", "bottom")]

        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        handle = int(window.winId())
        mode = ctypes.c_int(2 if enabled else 1)
        dark = ctypes.c_int(not light)
        dwm.DwmSetWindowAttribute(handle, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        result = dwm.DwmSetWindowAttribute(handle, 38, ctypes.byref(mode), ctypes.sizeof(mode))
        margins = Margins(*([-1] * 4 if enabled else [0] * 4))
        extended = dwm.DwmExtendFrameIntoClientArea(handle, ctypes.byref(margins))
        active = enabled and result == 0 and extended == 0
    window.setProperty("backdropActive", active)
    window.centralWidget().update()
    return active


@lru_cache(maxsize=1)
def gpu_available():
    app = QApplication.instance()
    if app is None or app.platformName() in ("offscreen", "minimal"):
        return False
    surface = QOffscreenSurface()
    surface.setFormat(QSurfaceFormat.defaultFormat())
    surface.create()
    context = QOpenGLContext()
    context.setFormat(surface.format())
    if not context.create() or not context.makeCurrent(surface):
        surface.destroy()
        return False
    try:
        # A software OpenGL implementation is not hardware acceleration.
        renderer = context.functions().glGetString(0x1F01)
        renderer = str(renderer).lower()
        return context.isValid() and not any(name in renderer for name in ("llvmpipe", "softpipe", "software", "gdi generic"))
    finally:
        context.doneCurrent()
        surface.destroy()
