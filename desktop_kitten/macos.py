"""Small macOS-only tweaks Qt does not expose, done by calling Cocoa directly.

Objective-C methods are called through objc_msgSend with ctypes, which avoids
a dependency on PyObjC. Every function quietly does nothing on other systems
or if a call fails, so the app still runs (just with Qt's defaults).
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys

IS_MAC = sys.platform == "darwin"

NS_APP_ACTIVATION_POLICY_ACCESSORY = 1   # no Dock icon, no app menu; menu bar icon only
NS_STATUS_WINDOW_LEVEL = 25              # above normal windows and the Dock, below menus
NS_NONACTIVATING_PANEL = 1 << 7          # clicking the window doesn't steal focus
# Show on every desktop (Space), stay put when switching, and also over full-screen apps.
NS_COLLECTION = (1 << 0) | (1 << 4) | (1 << 6) | (1 << 8)

_objc = None
_msg_send = None


def _load() -> bool:
    global _objc, _msg_send
    if not IS_MAC:
        return False
    if _objc is None:
        _objc = ctypes.CDLL(ctypes.util.find_library("objc"))
        ctypes.CDLL(ctypes.util.find_library("AppKit"))   # makes NSApplication etc. available
        _objc.objc_getClass.restype = ctypes.c_void_p
        _objc.objc_getClass.argtypes = [ctypes.c_char_p]
        _objc.sel_registerName.restype = ctypes.c_void_p
        _objc.sel_registerName.argtypes = [ctypes.c_char_p]
        _msg_send = ctypes.cast(_objc.objc_msgSend, ctypes.c_void_p).value
    return True


def _send(obj, selector: str, *args, restype=ctypes.c_void_p, argtypes=()):
    """[obj selector:args...] - the C function type must match the method's signature."""
    fn = ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(_msg_send)
    return fn(obj, _objc.sel_registerName(selector.encode()), *args)


def hide_dock_icon() -> None:
    """Run as a menu bar 'accessory' app: no Dock icon, no Cmd-Tab entry."""
    if not _load():
        return
    try:
        app = _send(_objc.objc_getClass(b"NSApplication"), "sharedApplication")
        _send(app, "setActivationPolicy:", NS_APP_ACTIVATION_POLICY_ACCESSORY,
              restype=ctypes.c_bool, argtypes=(ctypes.c_long,))
    except Exception as exc:
        print(f"[macos] could not hide dock icon: {exc}", file=sys.stderr)


def ns_window(win_id: int):
    """Qt's winId() on macOS is an NSView*; return its NSWindow*."""
    if not _load() or not win_id:
        return None
    return _send(ctypes.c_void_p(win_id), "window")


def configure_overlay(win_id: int) -> bool:
    """Float above other apps, on every Space, without a shadow or stealing focus."""
    window = ns_window(win_id)
    if not window:
        return False
    try:
        _send(window, "setLevel:", NS_STATUS_WINDOW_LEVEL, restype=None, argtypes=(ctypes.c_long,))
        _send(window, "setCollectionBehavior:", NS_COLLECTION, restype=None, argtypes=(ctypes.c_ulong,))
        _send(window, "setHasShadow:", False, restype=None, argtypes=(ctypes.c_bool,))
        panel_cls = _objc.objc_getClass(b"NSPanel")
        is_panel = _send(window, "isKindOfClass:", panel_cls, restype=ctypes.c_bool,
                         argtypes=(ctypes.c_void_p,))
        if is_panel:
            mask = _send(window, "styleMask", restype=ctypes.c_ulong)
            _send(window, "setStyleMask:", mask | NS_NONACTIVATING_PANEL, restype=None,
                  argtypes=(ctypes.c_ulong,))
        return True
    except Exception as exc:
        print(f"[macos] could not configure overlay window: {exc}", file=sys.stderr)
        return False


def set_click_through(window, on: bool) -> None:
    """on=True: mouse clicks pass straight through to the apps underneath."""
    if window:
        _send(window, "setIgnoresMouseEvents:", on, restype=None, argtypes=(ctypes.c_bool,))
