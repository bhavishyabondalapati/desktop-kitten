"""Render assets/demo.gif: a short scripted scene using the app's real sprites and
state machine, drawn on a simple fake desktop (not a screen recording).

Run:  python scripts/make_demo_gif.py      (needs Pillow: pip install pillow)
"""
import io
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPolygon  # noqa: E402

from desktop_kitten.behavior import Bounds, Kitten, State  # noqa: E402
from desktop_kitten.sprites import SpriteBank  # noqa: E402

WIDTH, HEIGHT, FPS, SECONDS = 640, 340, 15, 13
BOUNDS = Bounds(0, 40, WIDTH, HEIGHT - 12)


def cursor_at(t):
    """Scripted mouse path: idle, then sweeps across the screen around t=4..7 s."""
    if 3.5 <= t < 7:
        u = (t - 3.5) / 3.5
        return 120 + 380 * u, 230 - 60 * (u * (1 - u)) * 4
    return (500, 230) if t >= 7 else (560, 90)


def draw_desktop(p):
    p.fillRect(0, 0, WIDTH, HEIGHT, QColor("#5b7fa8"))
    p.fillRect(0, 0, WIDTH, 22, QColor("#e9edf3"))                    # menu bar
    p.setPen(QColor("#333"))
    p.setFont(QFont("Helvetica", 11))
    p.drawText(12, 16, "  Finder   File   Edit   View")
    for x, y, w, h, title in [(30, 50, 300, 190, "notes.txt"), (360, 70, 250, 150, "Terminal")]:
        p.fillRect(x, y, w, h, QColor("#f7f7f7"))
        p.fillRect(x, y, w, 22, QColor("#dcdfe4"))
        p.setPen(QColor("#555"))
        p.drawText(x + 70, y + 15, title)
        for i, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPoint(x + 12 + i * 16, y + 11), 5, 5)
        p.setPen(QColor("#bbb"))
        for line in range(5):
            p.drawLine(x + 14, y + 42 + line * 24, x + w - 30 - (line * 37) % 80, y + 42 + line * 24)


def draw_cursor(p, x, y, clicking):
    arrow = QPolygon([QPoint(int(x) + dx, int(y) + dy) for dx, dy in
                      [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]])
    p.setBrush(QColor("white"))
    p.setPen(QColor("black"))
    p.drawPolygon(arrow)
    if clicking:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawEllipse(QPoint(int(x), int(y)), 12, 12)


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841
    bank = SpriteBank(scale=3)
    rng = random.Random(4)
    kittens = []
    frames = []
    dt = 1 / FPS
    for i in range(SECONDS * FPS):
        t = i * dt
        # Script: kittens arrive, one naps, cursor sweep starts a chase, a click, then "bye kittens".
        if i == 0:
            for coat in ("ginger", "gray"):
                kittens.append(Kitten.spawn(BOUNDS, coat, bank.size, rng=random.Random(rng.random())))
            kittens[0].x, kittens[0].target = -40, (200, 300)
            kittens[1].x, kittens[1].target = WIDTH + 40, (470, 290)
            kittens[0].y = 300
            kittens[1].y = 290
        if i == int(1.5 * FPS):
            k = Kitten.spawn(BOUNDS, "black", bank.size, rng=random.Random(9))
            k.x, k.y, k.target = -40, 255, (330, 255)
            kittens.append(k)
        if i == int(3.0 * FPS):
            kittens[1]._enter(State.SIT, duration=0.3)
            kittens[1]._enter(State.SLEEP, duration=30)
        if i == int(3.6 * FPS):
            kittens[0]._enter(State.SIT, duration=30)
            kittens[0]._enter(State.CHASE)
            kittens[0]._cursor_still_for = 0
        click = int(7.6 * FPS) <= i < int(7.9 * FPS)
        if i == int(7.6 * FPS):
            kittens[0].pet()
        if i == int(10.5 * FPS):
            for k in kittens:
                k.leave(BOUNDS)

        cx, cy = cursor_at(t)
        if 6.8 <= t < 9.5 and kittens:          # glide onto the ginger kitten and click it
            u = min(1.0, (t - 6.8) / 0.7)
            hx, hy = kittens[0].x + 6, kittens[0].y - 22
            cx, cy = cx + (hx - cx) * u, cy + (hy - cy) * u
        for k in kittens:
            if k.state in (State.WALK, State.SIT) and k is not kittens[0]:
                k.chase_cooldown = 99          # keep the script predictable
            k.update(dt, (cx, cy), BOUNDS)
        kittens = [k for k in kittens if not k.gone]

        img = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB32)
        p = QPainter(img)
        draw_desktop(p)
        for k in sorted(kittens, key=lambda k: k.y):
            left, top, _, _ = k.rect()
            p.drawPixmap(QPoint(round(left), round(top)), bank.frame(k.coat, k.animation, k.frame_index, k.facing_left))
            for part in k.particles:
                art = bank.heart if part.kind == "heart" else bank.zzz
                p.setOpacity(part.alpha)
                p.drawPixmap(QPoint(round(part.x - art.width() / 2), round(part.y - art.height() / 2)), art)
                p.setOpacity(1)
        draw_cursor(p, cx, cy, click)
        if t >= 10.0:
            p.setPen(QColor("white"))
            p.setFont(QFont("Helvetica", 16, QFont.Weight.Bold))
            p.drawText(QRect(0, HEIGHT - 40, WIDTH, 30), Qt.AlignmentFlag.AlignCenter, '"bye kittens!"')
        p.end()

        buf = QBuffer()
        buf.open(QBuffer.OpenModeFlag.ReadWrite)
        img.save(buf, "PNG")
        frames.append(Image.open(io.BytesIO(bytes(buf.data()))).convert("P", palette=Image.Palette.ADAPTIVE, colors=64))

    out = ROOT / "assets" / "demo.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, optimize=True)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
