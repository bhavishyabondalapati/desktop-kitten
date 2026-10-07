"""Original pixel-art kittens, drawn entirely in code.

Every frame is a small grid of characters. Each character is a *role*
(outline, fur, stripes, ...) rather than a color, so one drawing gives us
every coat color: a coat is just a mapping from role to color.

Frames are built from reusable "stamps" (head, body, legs, tail) placed on a
fixed-size canvas, so all poses share the same face and stay aligned.

This file has no Qt imports at the top, so the grids can be tested without a
display. The Qt helpers at the bottom import Qt lazily.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

W, H = 24, 16          # canvas size of every frame, in art pixels
TRANSPARENT = "."
SCALE = 3              # each art pixel is drawn as SCALE x SCALE screen pixels

# Roles used in the drawings:
#   o outline   b base fur   s stripes / shading   w white (muzzle, chest, paws)
#   e eyes      n pink (nose, inner ears)
ROLES = set("obswen")

# One color per role. Eye color is not the outline color, so black cats still have visible eyes.
COATS: dict[str, dict[str, str]] = {
    "ginger": {"o": "#3a2418", "b": "#f2a65a", "s": "#d9772b", "w": "#fff3e3", "e": "#2a1a12", "n": "#f49ab0"},
    "gray":   {"o": "#252a33", "b": "#9ea7b6", "s": "#6f7888", "w": "#eef1f5", "e": "#1d2027", "n": "#f2a0b5"},
    "black":  {"o": "#0b0b10", "b": "#34343f", "s": "#25252e", "w": "#e6e6ee", "e": "#c6e05e", "n": "#e889a3"},
    "cream":  {"o": "#4d3c2d", "b": "#f7e4c6", "s": "#e6c493", "w": "#fffaf0", "e": "#3a2c20", "n": "#f4a3b4"},
    "brown":  {"o": "#2b1c12", "b": "#a97c55", "s": "#6d4a30", "w": "#f4e8da", "e": "#1f140c", "n": "#ee98ab"},
}

# Hearts (purring) and z's (sleeping) use their own fixed colors.
PARTICLE_COLORS = {"o": "#5a1830", "n": "#ff6f9a", "w": "#ffd0de", "z": "#7d8cf0"}   # z: mid-blue, visible on light and dark

# ---------------------------------------------------------------- stamps ---
# Head faces the viewer (12 wide, 10 tall). The face is symmetric, so it works
# for both walking directions.
HEAD = (
    ".o........o.",
    "ono......ono",
    "onbo....obno",
    "onbboooobbno",
    "obbbbbbbbbbo",
    "obbebbbbebbo",
    "obbebbbbebbo",
    "obbbwnnwbbbo",
    ".obwwwwwwbo.",
    "..oooooooo..",
)
# Same head with closed, content eyes (sleeping and purring).
HEAD_CLOSED = HEAD[:5] + (
    "obbbbbbbbbbo",
    "oboobbbboobo",
) + HEAD[7:]

BODY = (
    "ooooooooooooooo",
    "obbsbbsbbsbbbbo",
    "obbsbbsbbsbbbbo",
    "obbbbbbbbbbwwbo",
    "ooooooooooooooo",
)
BODY_RUN = (
    "oooooooooooooooo",
    "obbsbbsbbsbbbbbo",
    "obbsbbsbbsbbbwbo",
    "oooooooooooooooo",
)
BODY_SIT = (
    "....ooooooo..",
    "...obbbbbbbo.",
    "..obsbbbbbwwo",
    ".obsbbbbbbwwo",
    ".obbsbbbbbwwo",
    "obbbbbbbbowwo",
    "obbbbbbbowwwo",
    "ooooooooooooo",
)
BODY_SLEEP = (
    "....oooooooo....",
    "..oobbbsbbbbboo.",
    ".obbbsbbbsbbbbbo",
    "obbbsbbbsbbbbbbo",
    "obbbbbbbbbbbbbbo",
    "obbbbbbbbbbbbbbo",
    ".oooooooooooooo.",
)
# Breathing in: the back rises by one pixel.
BODY_SLEEP_IN = (
    "...oooooooooo...",
    "..obbbbsbbbbbbo.",
) + BODY_SLEEP[2:]

# Legs are 5 rows tall and drawn from row 11, so they overlap the body's bottom
# edge even when the body bobs up a pixel. Feet end on row 15 in every pose.
LEG = ("obo", "obo", "obo", "owo", "ooo")            # near legs: fur color
LEG_FAR = ("oso", "oso", "oso", "owo", "ooo")        # far legs: shaded, gives depth
LEG_FWD = ("obo.", "obo.", "obo.", ".owo", ".ooo")   # foot swung forward
LEG_BACK = (".obo", ".obo", ".obo", "owo.", "ooo.")  # foot swung back
LEG_REACH_FWD = ("obo..", "obo..", ".obo.", "..owo", "..ooo")
LEG_REACH_BACK = ("..obo", "..obo", ".obo.", "owo..", "ooo..")
LEG_Y = 11

TAIL_UP = (".o...", "oso..", "oso..", ".oso.", "..oso", "...os")
TAIL_UP_2 = ("o....", "oso..", ".oso.", ".oso.", "..oso", "...os")
TAIL_RUN = ("oo....", "osoo..", ".ossoo", "..ooss")
TAIL_SIT = (".oooooo", "osssssso", ".ooooooo")
TAIL_SIT_FLICK = ("o......", "so.....", "osooooo", ".ossssso", "..oooooo")
TAIL_SLEEP = ("oooooooooo", "ssssssssso", "oooooooooo")

HEART = (
    ".oo.oo.",
    "onwonno",
    "onnnnno",
    ".onnno.",
    "..ono..",
    "...o...",
)
ZZZ = (
    "zzzz",
    "..z.",
    ".z..",
    "zzzz",
)


def blank() -> list[list[str]]:
    return [[TRANSPARENT] * W for _ in range(H)]


def stamp(canvas: list[list[str]], art: tuple[str, ...], x: int, y: int) -> None:
    """Draw art onto canvas with its top-left corner at (x, y). '.' is see-through."""
    for dy, row in enumerate(art):
        for dx, ch in enumerate(row):
            cx, cy = x + dx, y + dy
            if ch != TRANSPARENT and 0 <= cx < W and 0 <= cy < H:
                canvas[cy][cx] = ch


def compose(*parts: tuple[tuple[str, ...], int, int]) -> tuple[str, ...]:
    """Stamp parts in order (later parts cover earlier ones) -> frame as a tuple of strings."""
    canvas = blank()
    for art, x, y in parts:
        stamp(canvas, art, x, y)
    return tuple("".join(row) for row in canvas)


def mirror(frame: tuple[str, ...]) -> tuple[str, ...]:
    """Flip left-right. The drawings face right; mirrored frames face left."""
    return tuple(row[::-1] for row in frame)


# --------------------------------------------------------------- frames ---
def _walk(back_far, back_near, front_far, front_near, tail, bob=0):
    return compose(
        (tail, 0, 3 + bob),
        (back_far[0], back_far[1], LEG_Y), (front_far[0], front_far[1], LEG_Y),
        (BODY, 4, 7 + bob),
        (back_near[0], back_near[1], LEG_Y), (front_near[0], front_near[1], LEG_Y),
        (HEAD, 12, 1 + bob),
    )


def _run(extended: bool):
    if extended:
        legs = [(LEG_REACH_BACK, 2), (LEG_REACH_FWD, 16)]
    else:
        legs = [(LEG, 7), (LEG, 12)]
    parts = [(TAIL_RUN, 0, 6)]
    parts += [(art, x, LEG_Y) for art, x in legs]
    parts += [(BODY_RUN, 4, 9), (HEAD, 12, 2)]
    return compose(*parts)


def _sit(head, tail, head_y=0):
    return compose((BODY_SIT, 7, 8), (tail, 1, 13 if tail is TAIL_SIT else 11), (head, 11, head_y))


def _sleep(body):
    return compose((body, 2, 9), (HEAD_CLOSED, 11, 6), (TAIL_SLEEP, 1, 13))


@dataclass(frozen=True)
class Animation:
    frames: tuple[tuple[str, ...], ...]
    fps: float


ANIMATIONS: dict[str, Animation] = {
    "walk": Animation((
        _walk((LEG_FAR, 6), (LEG_BACK, 4), (LEG_FAR, 16), (LEG_FWD, 13), TAIL_UP),
        _walk((LEG_FAR, 5), (LEG, 5), (LEG_FAR, 15), (LEG, 14), TAIL_UP_2, bob=-1),
        _walk((LEG_FAR, 4), (LEG_FWD, 6), (LEG_FAR, 13), (LEG_BACK, 15), TAIL_UP),
        _walk((LEG_FAR, 5), (LEG, 5), (LEG_FAR, 15), (LEG, 14), TAIL_UP_2, bob=-1),
    ), fps=8),
    "run": Animation((_run(True), _run(False)), fps=10),
    "sit": Animation((
        _sit(HEAD, TAIL_SIT), _sit(HEAD, TAIL_SIT), _sit(HEAD, TAIL_SIT),
        _sit(HEAD, TAIL_SIT_FLICK),
    ), fps=2),
    "sleep": Animation((_sleep(BODY_SLEEP), _sleep(BODY_SLEEP_IN)), fps=1),
    "purr": Animation((
        _sit(HEAD_CLOSED, TAIL_SIT_FLICK), _sit(HEAD_CLOSED, TAIL_SIT, head_y=1),
    ), fps=4),
}


def frame_size(frame: tuple[str, ...]) -> tuple[int, int]:
    return len(frame[0]), len(frame)


def validate_frame(frame: tuple[str, ...], allowed: set[str] = ROLES) -> None:
    """Raise ValueError if the frame is ragged or uses an unknown role."""
    width = len(frame[0])
    for y, row in enumerate(frame):
        if len(row) != width:
            raise ValueError(f"row {y} has width {len(row)}, expected {width}")
        bad = set(row) - allowed - {TRANSPARENT}
        if bad:
            raise ValueError(f"row {y} uses unknown roles {sorted(bad)}")


# ------------------------------------------------------------ Qt helpers ---
# Imported lazily so the art above can be tested without a GUI.

def to_qimage(frame: tuple[str, ...], palette: dict[str, str], scale: int = 1):
    """Grid of roles -> QImage, each art pixel scaled up to a crisp scale x scale block."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage

    w, h = frame_size(frame)
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    colors = {role: QColor(hex_).rgba() for role, hex_ in palette.items()}
    for y, row in enumerate(frame):
        for x, ch in enumerate(row):
            if ch != TRANSPARENT:
                img.setPixel(x, y, colors[ch])
    if scale != 1:
        # FastTransformation = nearest neighbour, so pixels stay sharp instead of blurry
        img = img.scaled(w * scale, h * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.FastTransformation)
    return img


def build_sheet(coat: str):
    """One sprite sheet per coat: one row per animation, one column per frame (unscaled)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    names = list(ANIMATIONS)
    cols = max(len(ANIMATIONS[n].frames) for n in names)
    sheet = QImage(W * cols, H * len(names), QImage.Format.Format_ARGB32_Premultiplied)
    sheet.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sheet)
    for r, name in enumerate(names):
        for c, frame in enumerate(ANIMATIONS[name].frames):
            painter.drawImage(c * W, r * H, to_qimage(frame, COATS[coat]))
    painter.end()
    return sheet


def load_sheet(path: str | Path, frame_w: int = W, frame_h: int = H,
               counts: dict[str, int] | None = None):
    """Cut a sprite sheet PNG back into frames -> {animation: [QImage, ...]}.

    counts says how many frames each row has (default: the built-in animations),
    which lets a hand-drawn sheet replace the code-drawn art.
    """
    from PySide6.QtGui import QImage

    sheet = QImage(str(path))
    if sheet.isNull():
        raise FileNotFoundError(f"could not read sprite sheet {path}")
    counts = counts or {n: len(a.frames) for n, a in ANIMATIONS.items()}
    if sheet.height() < frame_h * len(counts):
        raise ValueError(f"sheet is {sheet.height()}px tall, needs {frame_h * len(counts)}px")
    return {name: [sheet.copy(c * frame_w, r * frame_h, frame_w, frame_h) for c in range(n)]
            for r, (name, n) in enumerate(counts.items())}


class SpriteBank:
    """Pre-rendered, pre-scaled QPixmaps for every coat x animation x direction.

    Rendering happens once at startup, so drawing a kitten each frame is just
    copying a ready-made image (cheap, which keeps CPU use low).
    """

    def __init__(self, scale: int = SCALE):
        from PySide6.QtGui import QPixmap

        self.scale = scale
        self._frames: dict[tuple[str, str, bool], list] = {}
        self._grids: dict[tuple[str, bool], tuple] = {}
        for coat, palette in COATS.items():
            for name, anim in ANIMATIONS.items():
                for facing_left in (False, True):
                    grids = tuple(mirror(f) if facing_left else f for f in anim.frames)
                    self._grids[name, facing_left] = grids
                    self._frames[coat, name, facing_left] = [
                        QPixmap.fromImage(to_qimage(g, palette, scale)) for g in grids
                    ]
        self.heart = QPixmap.fromImage(to_qimage(HEART, PARTICLE_COLORS, scale))
        self.zzz = QPixmap.fromImage(to_qimage(ZZZ, PARTICLE_COLORS, max(1, scale - 1)))

    def frame(self, coat: str, animation: str, index: int, facing_left: bool):
        frames = self._frames[coat, animation, facing_left]
        return frames[index % len(frames)]

    def opaque_at(self, coat: str, animation: str, index: int, facing_left: bool,
                  x: int, y: int) -> bool:
        """Is the pixel at (x, y) inside the scaled frame part of the kitten (not see-through)?
        Used so clicks on the empty corners of a sprite still reach the app below."""
        grids = self._grids[animation, facing_left]
        grid = grids[index % len(grids)]
        gx, gy = x // self.scale, y // self.scale
        return 0 <= gy < len(grid) and 0 <= gx < len(grid[0]) and grid[gy][gx] != TRANSPARENT

    @property
    def size(self) -> tuple[int, int]:
        return W * self.scale, H * self.scale
