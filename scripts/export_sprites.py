"""Export the code-drawn kittens as PNG sprite sheets, plus a big preview image.

Run:  python scripts/export_sprites.py
Writes assets/sprites/<coat>.png (one row per animation, 24x16 px frames) and
assets/preview.png (all coats, scaled up, for the README).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

from desktop_kitten.sprites import ANIMATIONS, COATS, H, W, build_sheet  # noqa: E402

PREVIEW_SCALE = 5
GAP = 8


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (Qt needs it alive)
    out = ROOT / "assets" / "sprites"
    out.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for coat in COATS:
        sheets[coat] = build_sheet(coat)
        sheets[coat].save(str(out / f"{coat}.png"))
        print(f"wrote {out / f'{coat}.png'}")

    # Preview: one column per coat showing walk, run, sit, sleep, purr (first frame each).
    names = list(ANIMATIONS)
    fw, fh = W * PREVIEW_SCALE, H * PREVIEW_SCALE
    img = QImage(len(COATS) * (fw + GAP) + GAP, len(names) * (fh + GAP) + GAP, QImage.Format.Format_ARGB32)
    img.fill(QColor("#cfe0f2"))
    p = QPainter(img)
    for c, coat in enumerate(COATS):
        for r, name in enumerate(names):
            col = 1 if name == "walk" else 0   # the walk's 2nd frame shows the stride better
            frame = sheets[coat].copy(col * W, r * H, W, H)
            p.drawImage(GAP + c * (fw + GAP), GAP + r * (fh + GAP),
                        frame.scaled(fw, fh, Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.FastTransformation))
    p.end()
    img.save(str(ROOT / "assets" / "preview.png"))
    print(f"wrote {ROOT / 'assets' / 'preview.png'}")


if __name__ == "__main__":
    main()
