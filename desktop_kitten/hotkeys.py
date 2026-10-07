"""Global keyboard shortcuts that work while any app is in front.

On macOS this uses the Carbon RegisterEventHotKey API through ctypes (no extra
package). It is the same API many menu bar utilities use: macOS delivers only
the registered key combination to us, so it does not watch your other typing
and does not need the Accessibility or Input Monitoring permission.

parse_hotkey() is plain string logic and is tested; HotkeyManager only does
real work on macOS and reports a clear message elsewhere.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Callable

# Carbon modifier flags (Events.h)
MODIFIERS = {
    "cmd": 1 << 8, "command": 1 << 8,
    "shift": 1 << 9,
    "alt": 1 << 11, "option": 1 << 11, "opt": 1 << 11,
    "ctrl": 1 << 12, "control": 1 << 12,
}

# macOS virtual key codes for an ANSI keyboard (they are positions, not letters).
KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "9": 25, "7": 26, "8": 28, "0": 29,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45, "m": 46,
    "space": 49,
}

DEFAULT_HOTKEYS = {
    "ctrl+alt+k": "spawn_one",
    "ctrl+alt+m": "spawn_many",
    "ctrl+alt+b": "dismiss",
}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+k' -> (key code, modifier bit mask). Raises ValueError if invalid."""
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("empty hotkey")
    *mods, key = parts
    if key not in KEYCODES:
        raise ValueError(f"unknown key '{key}' in '{spec}'")
    if not mods:
        raise ValueError(f"'{spec}' needs at least one modifier, or it would steal a normal key")
    mask = 0
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f"unknown modifier '{m}' in '{spec}'")
        mask |= MODIFIERS[m]
    return KEYCODES[key], mask


def pretty(spec: str) -> str:
    """'ctrl+alt+k' -> '⌃⌥K' for menus."""
    symbols = {"ctrl": "⌃", "control": "⌃", "alt": "⌥", "option": "⌥", "opt": "⌥",
               "shift": "⇧", "cmd": "⌘", "command": "⌘"}
    *mods, key = spec.lower().split("+")
    return "".join(symbols[m] for m in mods) + key.upper()


# ----------------------------------------------------------- Carbon glue ---
class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
K_EVENT_CLASS_KEYBOARD = _fourcc("keyb")
K_EVENT_HOTKEY_PRESSED = 5
K_EVENT_PARAM_DIRECT_OBJECT = _fourcc("----")
TYPE_EVENT_HOTKEY_ID = _fourcc("hkid")
SIGNATURE = _fourcc("KITN")


class HotkeyManager:
    """Registers global hotkeys. Callbacks run on the main (GUI) thread,
    because macOS delivers them through the normal app event loop."""

    def __init__(self):
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._refs = []
        self._handler = None
        self.error: str | None = None
        if sys.platform != "darwin":
            self.error = "Global hotkeys are only implemented for macOS."
            return
        try:
            self._carbon = ctypes.CDLL(ctypes.util.find_library("Carbon"))
            self._setup_handler()
        except (OSError, AttributeError) as exc:
            self.error = f"Could not load the Carbon hotkey API: {exc}"

    def _setup_handler(self):
        c = self._carbon
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_uint32,
                                          ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                          ctypes.c_void_p]
        c.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                        ctypes.c_void_p]
        c.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID,
                                          ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]

        def on_event(_call_ref, event, _user_data):
            hk = _EventHotKeyID()
            c.GetEventParameter(event, K_EVENT_PARAM_DIRECT_OBJECT, TYPE_EVENT_HOTKEY_ID, None,
                                ctypes.sizeof(hk), None, ctypes.byref(hk))
            callback = self._callbacks.get(hk.id)
            if callback:
                try:
                    callback()
                except Exception as exc:  # never let an exception cross into C code
                    print(f"[hotkeys] callback failed: {exc}", file=sys.stderr)
            return 0

        self._handler = _HANDLER(on_event)   # keep a reference so it isn't garbage collected
        spec = _EventTypeSpec(K_EVENT_CLASS_KEYBOARD, K_EVENT_HOTKEY_PRESSED)
        status = c.InstallEventHandler(c.GetApplicationEventTarget(), self._handler, 1,
                                       ctypes.byref(spec), None, None)
        if status != 0:
            raise OSError(f"InstallEventHandler returned {status}")

    def register(self, spec: str, callback: Callable[[], None]) -> bool:
        """Register one shortcut. Returns False (and sets self.error) on failure."""
        if self.error and not self._handler:
            return False
        keycode, mods = parse_hotkey(spec)
        hk_id = len(self._callbacks) + 1
        ref = ctypes.c_void_p()
        status = self._carbon.RegisterEventHotKey(keycode, mods, _EventHotKeyID(SIGNATURE, hk_id),
                                                  self._carbon.GetApplicationEventTarget(), 0,
                                                  ctypes.byref(ref))
        if status != 0:
            self.error = f"{pretty(spec)} is already used by another app (error {status})."
            return False
        self._callbacks[hk_id] = callback
        self._refs.append(ref)
        return True

    def unregister_all(self):
        for ref in self._refs:
            self._carbon.UnregisterEventHotKey(ref)
        self._refs.clear()
        self._callbacks.clear()
