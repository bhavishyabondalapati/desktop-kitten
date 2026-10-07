"""Sprite art and loading. Qt runs 'offscreen', so no window or display is needed."""
import os

import pytest

from desktop_kitten import sprites

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    return QGuiApplication.instance() or QGuiApplication([])


def test_every_frame_is_full_size_and_uses_known_roles():
    for name, anim in sprites.ANIMATIONS.items():
        assert anim.frames and anim.fps > 0
        for frame in anim.frames:
            assert sprites.frame_size(frame) == (sprites.W, sprites.H), name
            sprites.validate_frame(frame)


def test_feet_touch_the_same_ground_line_in_every_pose():
    # If one pose's bottom row were empty, the kitten would hop when changing state.
    for name, anim in sprites.ANIMATIONS.items():
        for frame in anim.frames:
            assert set(frame[-1]) != {sprites.TRANSPARENT}, name


def test_every_coat_colors_every_role():
    for coat, palette in sprites.COATS.items():
        assert set(palette) == sprites.ROLES, coat
        assert palette["e"] != palette["b"], f"{coat}: eyes would vanish into the fur"


def test_validate_frame_catches_mistakes():
    with pytest.raises(ValueError):
        sprites.validate_frame(("ob", "o"))          # ragged
    with pytest.raises(ValueError):
        sprites.validate_frame(("oX",))              # unknown role


def test_mirror_flips_and_is_its_own_inverse():
    frame = sprites.ANIMATIONS["walk"].frames[0]
    flipped = sprites.mirror(frame)
    assert flipped[5] == frame[5][::-1]
    assert sprites.mirror(flipped) == frame


def test_stamp_skips_transparent_and_clips_at_edges():
    canvas = sprites.blank()
    sprites.stamp(canvas, ("o.o",), sprites.W - 2, 0)      # last pixel falls off the canvas
    assert canvas[0][sprites.W - 2] == "o"
    assert canvas[0][sprites.W - 1] == sprites.TRANSPARENT


def test_to_qimage_colors_and_scales(qapp):
    from PySide6.QtGui import QColor
    img = sprites.to_qimage(("ob", ".."), sprites.COATS["ginger"], scale=3)
    assert (img.width(), img.height()) == (6, 6)
    assert img.pixelColor(0, 0) == QColor(sprites.COATS["ginger"]["o"])
    assert img.pixelColor(5, 2) == QColor(sprites.COATS["ginger"]["b"])
    assert img.pixelColor(0, 5).alpha() == 0                # '.' stays transparent


def test_sprite_sheet_round_trip(qapp, tmp_path):
    """Save a sheet as PNG, load it back, and get identical frames."""
    from desktop_kitten.sprites import ANIMATIONS, COATS, build_sheet, load_sheet, to_qimage
    path = tmp_path / "gray.png"
    assert build_sheet("gray").save(str(path))
    frames = load_sheet(path)
    assert set(frames) == set(ANIMATIONS)
    for name, anim in ANIMATIONS.items():
        assert len(frames[name]) == len(anim.frames)
        expected = to_qimage(anim.frames[-1], COATS["gray"])
        got = frames[name][-1].convertToFormat(expected.format())
        assert got == expected, name


def test_load_sheet_errors(qapp, tmp_path):
    with pytest.raises(FileNotFoundError):
        sprites.load_sheet(tmp_path / "missing.png")
    from PySide6.QtGui import QImage
    small = tmp_path / "small.png"
    QImage(24, 16, QImage.Format.Format_ARGB32).save(str(small))
    with pytest.raises(ValueError):
        sprites.load_sheet(small)


def test_committed_sheets_match_the_code(qapp):
    """assets/sprites/*.png are exported from the code; they must not drift apart."""
    from pathlib import Path
    folder = Path(__file__).resolve().parent.parent / "assets" / "sprites"
    for coat in sprites.COATS:
        frames = sprites.load_sheet(folder / f"{coat}.png")
        expected = sprites.to_qimage(sprites.ANIMATIONS["sit"].frames[0], sprites.COATS[coat])
        assert frames["sit"][0].convertToFormat(expected.format()) == expected, coat


def test_sprite_bank_frames_and_hit_testing(qapp):
    bank = sprites.SpriteBank(scale=2)
    assert bank.size == (sprites.W * 2, sprites.H * 2)
    pix = bank.frame("black", "walk", 5, facing_left=True)    # index wraps around
    assert (pix.width(), pix.height()) == bank.size
    assert not bank.opaque_at("ginger", "sit", 0, False, 0, 0)        # empty corner: click passes through
    frame = sprites.ANIMATIONS["sit"].frames[0]
    y, x = next((y, x) for y, row in enumerate(frame) for x, ch in enumerate(row) if ch != ".")
    assert bank.opaque_at("ginger", "sit", 0, False, x * 2, y * 2)
