"""Wires everything together: overlay window, menu bar icon, hotkeys, voice, mood.

Voice and mood run on background threads, but Qt widgets may only be touched
from the main thread. So every command goes through CommandBus.command, a Qt
signal: emitting it from any thread queues the call onto the main thread.
"""
from __future__ import annotations

import argparse
import signal
import sys

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from desktop_kitten import macos, mood, voice
from desktop_kitten.commands import Command
from desktop_kitten.hotkeys import DEFAULT_HOTKEYS, HotkeyManager, pretty
from desktop_kitten.overlay import KittenOverlay
from desktop_kitten.sprites import HEAD, to_qimage


class CommandBus(QObject):
    command = Signal(object)   # a Command; safe to emit from any thread


def tray_icon() -> QIcon:
    """The kitten head as a black 'template' icon; macOS recolors it for light/dark menu bars."""
    black = {role: "#000000" for role in "obswen"}
    head = tuple(row.replace("w", ".").replace("b", ".").replace("s", ".") for row in HEAD)
    icon = QIcon(QPixmap.fromImage(to_qimage(head, black, scale=2)))
    icon.setIsMask(True)
    return icon


class KittenApp:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setApplicationName("Desktop Kitten")
        macos.hide_dock_icon()

        self.overlay = KittenOverlay(seed=args.seed, scale=args.scale)
        self.bus = CommandBus()
        self.bus.command.connect(self.handle, Qt.ConnectionType.QueuedConnection)

        self.voice = voice.VoiceListener(self.bus.command.emit, args.voice_model,
                                         on_heard=self._heard if args.verbose else None)
        self.mood = mood.MoodWatcher(lambda: self.bus.command.emit(Command.SPAWN_ONE), args.mood_model)
        self.hotkeys = HotkeyManager()
        self._build_tray()
        self._register_hotkeys()

        if not args.no_voice:
            self.set_voice(True)
        if args.mood:
            self.set_mood(True)
        else:
            self.log(mood.check_available(args.mood_model)[1].replace("ready", "available"))
        if args.kittens:
            self.overlay.spawn(args.kittens)
        self.overlay.show()

    # ------------------------------------------------------------ commands -
    def handle(self, command: Command):
        if command is Command.SPAWN_ONE:
            self.overlay.spawn(1)
        elif command is Command.SPAWN_MANY:
            self.overlay.spawn_many()
        elif command is Command.DISMISS:
            self.overlay.dismiss_all()
        if self.args.verbose:
            self.log(f"command: {command.value}")

    def log(self, message: str):
        print(f"[kitten] {message}", flush=True)
        self.status.setText(message if len(message) < 70 else message[:67] + "...")
        self.status.setToolTip(message)

    def _heard(self, text: str):
        if text:
            print(f"[voice] heard: {text!r}", flush=True)

    # ------------------------------------------------------------ features -
    def set_voice(self, on: bool):
        if on and not self.voice.start():
            self.log(self.voice.error)
            on = False
        elif on:
            self.log('Listening for "kitten", "more kittens", "bye kittens"')
        else:
            self.voice.stop()
            self.log("Voice commands off (microphone released)")
        self._sync(self.voice_action, on)

    def set_mood(self, on: bool):
        if on and not self.mood.start():
            self.log(self.mood.error)
            on = False
        elif on:
            self.log("Mood mode on: watching for a sad face (camera)")
        else:
            self.mood.stop()
            self.log("Mood mode off (camera released)")
        self._sync(self.mood_action, on)

    @staticmethod
    def _sync(action: QAction, on: bool):
        action.blockSignals(True)       # update the checkmark without re-triggering the toggle
        action.setChecked(on)
        action.blockSignals(False)

    # ------------------------------------------------------------ menu bar -
    def _build_tray(self):
        menu = QMenu()
        keys = {cmd: pretty(spec) for spec, cmd in DEFAULT_HOTKEYS.items()}
        for label, cmd in (("Spawn a kitten", Command.SPAWN_ONE),
                           ("More kittens!", Command.SPAWN_MANY),
                           ("Bye kittens", Command.DISMISS)):
            act = menu.addAction(f"{label}\t{keys[cmd.value]}")
            act.triggered.connect(lambda _=False, c=cmd: self.handle(c))
        menu.addSeparator()
        self.voice_action = menu.addAction("Voice commands")
        self.voice_action.setCheckable(True)
        self.voice_action.toggled.connect(self.set_voice)
        self.mood_action = menu.addAction("Mood mode (camera)")
        self.mood_action.setCheckable(True)
        self.mood_action.toggled.connect(self.set_mood)
        menu.addSeparator()
        self.status = menu.addAction("Starting...")
        self.status.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Quit").triggered.connect(self.quit)

        self.menu = menu    # keep a reference, or Python garbage-collects the menu
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("Desktop Kitten")
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _register_hotkeys(self):
        for spec, cmd in DEFAULT_HOTKEYS.items():
            ok = self.hotkeys.register(spec, lambda c=Command(cmd): self.handle(c))
            if not ok:
                print(f"[kitten] hotkey {pretty(spec)} unavailable: {self.hotkeys.error}", flush=True)

    def quit(self):
        self.voice.stop()
        self.mood.stop()
        self.hotkeys.unregister_all()
        self.qt.quit()

    def run(self) -> int:
        # Let Ctrl+C in the terminal quit: Python only handles signals while it runs
        # Python code, so a cheap timer hands control back twice a second.
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        poke = QTimer(timerType=Qt.TimerType.VeryCoarseTimer)
        poke.timeout.connect(lambda: None)
        poke.start(500)
        return self.qt.exec()


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m desktop_kitten",
                                description="Pixel-art kittens that walk around your desktop.")
    p.add_argument("--kittens", type=int, default=1, help="kittens to start with (default 1, 0 for none)")
    p.add_argument("--no-voice", action="store_true", help="start with voice commands off")
    p.add_argument("--voice-model", help="path to a Vosk model folder (default: models/...)")
    p.add_argument("--mood", action="store_true", help="turn on mood mode (uses the camera)")
    p.add_argument("--mood-model", help="path to cnn_soft.pt (default: ~/projects/facial-expression-recognition/weights/cnn_soft.pt)")
    p.add_argument("--scale", type=int, default=None, help="pixel size of the art (default 3)")
    p.add_argument("--seed", type=int, default=None, help="random seed, for repeatable behavior")
    p.add_argument("-v", "--verbose", action="store_true", help="print what the microphone hears")
    return p.parse_args(argv)


def main(argv=None) -> int:
    return KittenApp(parse_args(argv)).run()
