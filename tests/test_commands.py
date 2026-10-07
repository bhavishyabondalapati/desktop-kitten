"""Command parsing and hotkey parsing. No microphone or keyboard needed."""
import pytest

from desktop_kitten.commands import DECOYS, VOICE_PHRASES, Command, parse_command
from desktop_kitten.hotkeys import DEFAULT_HOTKEYS, KEYCODES, MODIFIERS, parse_hotkey, pretty


@pytest.mark.parametrize("text, expected", [
    ("kitten", Command.SPAWN_ONE),
    ("Kitty!", Command.SPAWN_ONE),
    ("hey kitten", Command.SPAWN_ONE),
    ("more kittens", Command.SPAWN_MANY),
    ("kittens please", Command.SPAWN_MANY),
    ("bye kittens", Command.DISMISS),
    ("Goodbye, kittens.", Command.DISMISS),
    ("bye-bye kitty", Command.DISMISS),
    ("[unk] more kittens", Command.SPAWN_MANY),
    ("", None),
    ("[unk]", None),
    ("the weather is nice", None),
    ("more mittens", None),
    ("bye for now", None),
])
def test_parse_command(text, expected):
    assert parse_command(text) is expected


def test_every_voice_phrase_is_a_command_and_no_decoy_is():
    for phrase in VOICE_PHRASES:
        if phrase != "[unk]":
            assert parse_command(phrase) is not None, phrase
    for decoy in DECOYS:
        assert parse_command(decoy) is None, decoy


def test_parse_hotkey():
    key, mods = parse_hotkey("ctrl+alt+k")
    assert key == KEYCODES["k"]
    assert mods == MODIFIERS["ctrl"] | MODIFIERS["alt"]
    assert parse_hotkey("Cmd + Shift + Space") == (KEYCODES["space"], MODIFIERS["cmd"] | MODIFIERS["shift"])


@pytest.mark.parametrize("bad", ["", "k", "ctrl+", "hyper+k", "ctrl+alt+F13"])
def test_parse_hotkey_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        parse_hotkey(bad)


def test_default_hotkeys_are_valid_and_cover_every_command():
    for spec in DEFAULT_HOTKEYS:
        parse_hotkey(spec)
    assert {Command(c) for c in DEFAULT_HOTKEYS.values()} == set(Command)
    assert pretty("ctrl+alt+k") == "⌃⌥K"
