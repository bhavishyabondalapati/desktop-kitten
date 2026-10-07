"""The see-through window the kittens live in.

One frameless, transparent, always-on-top window covers the main screen.
Clicks normally pass straight through it to your other apps. Every frame we
check where the mouse is: only while it is over a kitten's (non-transparent)
pixels does the window start accepting clicks, so you can pet that kitten.

To keep CPU use low:
  * the timer stops completely when there are no kittens,
  * it runs at ~30 fps while something moves and ~10 fps when all kittens rest,
  * only the small areas around kittens are repainted, not the whole screen.
"""
from __future__ import annotations

import random

from PySide6.QtCore import QElapsedTimer, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from desktop_kitten import macos
from desktop_kitten.behavior import Bounds, Kitten, State
from desktop_kitten.sprites import COATS, SpriteBank

FAST_MS = 33          # ~30 fps while kittens move
SLOW_MS = 100         # 10 fps while every kitten sits or sleeps
MAX_KITTENS = 12
MANY = 4              # how many "more kittens" adds


class KittenOverlay(QWidget):
    def __init__(self, seed: int | None = None, scale: int | None = None):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        self.rng = random.Random(seed)
        self.sprites = SpriteBank(scale) if scale else SpriteBank()
        self.kittens: list[Kitten] = []
        self._timer = QTimer(self, timerType=Qt.TimerType.CoarseTimer)
        self._timer.timeout.connect(self._tick)
        self._clock = QElapsedTimer()
        self._ns_window = None
        self._click_through = None

        screen = QGuiApplication.primaryScreen()
        screen.geometryChanged.connect(self._fit_screen)
        screen.availableGeometryChanged.connect(self._fit_screen)
        self._fit_screen()

    # ------------------------------------------------------------ setup ----
    def _fit_screen(self, *_):
        screen = QGuiApplication.primaryScreen()
        self.setGeometry(screen.geometry())
        avail = screen.availableGeometry().translated(-screen.geometry().topLeft())
        # Kittens roam the area not covered by the menu bar and Dock.
        self.bounds = Bounds(avail.left(), avail.top(), avail.right(), avail.bottom())

    def showEvent(self, event):
        super().showEvent(event)
        if macos.IS_MAC and self._ns_window is None:
            macos.configure_overlay(int(self.winId()))
            self._ns_window = macos.ns_window(int(self.winId()))
        self._set_click_through(True)

    def _set_click_through(self, on: bool):
        if on == self._click_through:
            return
        self._click_through = on
        if self._ns_window:
            macos.set_click_through(self._ns_window, on)
        elif self.windowHandle():
            self.windowHandle().setFlag(Qt.WindowType.WindowTransparentForInput, on)

    # ---------------------------------------------------------- commands ---
    def spawn(self, count: int = 1) -> int:
        """Add up to `count` kittens (capped at MAX_KITTENS). Returns how many were added."""
        added = 0
        for _ in range(count):
            if len(self.alive) >= MAX_KITTENS:
                break
            # Prefer a coat that isn't on screen yet, so a group looks varied.
            used = {k.coat for k in self.alive}
            coat = self.rng.choice([c for c in COATS if c not in used] or list(COATS))
            kitten = Kitten.spawn(self.bounds, coat, self.sprites.size,
                                  rng=random.Random(self.rng.random()))
            self.kittens.append(kitten)
            added += 1
        if added:
            self._wake()
        return added

    def spawn_many(self) -> int:
        return self.spawn(MANY)

    def dismiss_all(self):
        for k in self.kittens:
            k.leave(self.bounds)
        self._wake()

    @property
    def alive(self) -> list[Kitten]:
        """Kittens that are not on their way out."""
        return [k for k in self.kittens if k.state is not State.LEAVE]

    # ------------------------------------------------------------- loop ----
    def _wake(self):
        if not self.isVisible():
            self.show()
        if not self._timer.isActive():
            self._clock.start()
            self._timer.start(FAST_MS)

    def _tick(self):
        dt = min(self._clock.restart() / 1000.0, 0.1)   # clamp: no huge jumps after a stall
        pos = self.mapFromGlobal(QCursor.pos())
        cursor = (pos.x(), pos.y()) if self.rect().contains(pos) else None

        dirty = QRegion()
        for k in self.kittens:
            dirty += self._paint_rect(k)
            k.update(dt, cursor, self.bounds)
        self.kittens = [k for k in self.kittens if not k.gone]
        for k in self.kittens:
            dirty += self._paint_rect(k)
        self.update(dirty)

        self._set_click_through(not (cursor and self._kitten_at(*cursor)))

        if not self.kittens:
            self._timer.stop()          # nothing to animate: use zero CPU until the next command
            self._set_click_through(True)
            return
        interval = FAST_MS if any(k.is_busy for k in self.kittens) else SLOW_MS
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)

    def _paint_rect(self, k: Kitten) -> QRect:
        left, top, w, h = k.rect()
        rect = QRect(int(left), int(top), int(w), int(h))
        for p in k.particles:
            rect = rect.united(QRect(int(p.x) - 16, int(p.y) - 16, 32, 32))
        return rect.adjusted(-2, -2, 2, 2)

    def _kitten_at(self, x: float, y: float) -> Kitten | None:
        """Topmost kitten with a visible pixel under (x, y)."""
        for k in sorted(self.kittens, key=lambda k: k.y, reverse=True):
            if k.contains(x, y):
                left, top, _, _ = k.rect()
                if self.sprites.opaque_at(k.coat, k.animation, k.frame_index, k.facing_left,
                                          int(x - left), int(y - top)):
                    return k
        return None

    # ---------------------------------------------------------- drawing ----
    def paintEvent(self, event):
        painter = QPainter(self)
        # Clear the repainted area to fully transparent, then draw on top.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for k in sorted(self.kittens, key=lambda k: k.y):   # lower on screen = in front
            left, top, _, _ = k.rect()
            pix = self.sprites.frame(k.coat, k.animation, k.frame_index, k.facing_left)
            painter.drawPixmap(QPoint(round(left), round(top)), pix)
            for p in k.particles:
                art = self.sprites.heart if p.kind == "heart" else self.sprites.zzz
                painter.setOpacity(p.alpha)
                painter.drawPixmap(QPoint(round(p.x - art.width() / 2), round(p.y - art.height() / 2)), art)
                painter.setOpacity(1.0)
        painter.end()

    # ------------------------------------------------------------ input ----
    def mousePressEvent(self, event):
        kitten = self._kitten_at(event.position().x(), event.position().y())
        if kitten:
            kitten.pet()
            self._wake()
        else:
            event.ignore()
