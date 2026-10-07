"""Turning words into commands.

Voice, hotkeys and the menu bar all produce the same three Commands, so the
rest of the app only has to handle one thing. parse_command() is pure string
logic, which keeps it easy to test without a microphone.
"""
from __future__ import annotations

import re
from enum import Enum


class Command(Enum):
    SPAWN_ONE = "spawn_one"
    SPAWN_MANY = "spawn_many"
    DISMISS = "dismiss"


KITTEN_ONE = {"kitten", "kitty"}
KITTEN_MANY = {"kittens", "kitties"}
MORE_WORDS = {"more", "many", "lots", "all", "several"}
BYE_WORDS = {"bye", "goodbye", "byebye", "away", "shoo", "leave"}

# Phrases the speech recognizer is allowed to hear. Limiting it to these makes
# a tiny model much more accurate; "[unk]" soaks up every other sound.
VOICE_PHRASES = ["kitten", "kitty", "kittens", "more kittens", "bye kittens",
                 "goodbye kittens", "bye bye kittens", "bye kitty",
                 "hey kitten", "oh kitten", "kittens please", "[unk]"]

# Decoys: words that *sound like* "kitten". Without them, a recognizer limited to
# the phrases above has to pick the closest match, so "mittens" became "kittens".
# Now it can pick the decoy instead, and parse_command ignores decoys.
# "kitchen" is deliberately NOT a decoy: in testing it also swallowed the real
# "kitten" for Australian, Irish and South African voices (see README).
DECOYS = ["mitten", "mittens", "bitten", "written", "smitten",
          "chicken", "sitting", "getting", "kidding", "ticket", "listen", "cotton",
          "button", "kit", "cat", "cats", "it", "get", "more", "bye", "hey"]
VOICE_GRAMMAR = VOICE_PHRASES[:-1] + DECOYS + ["[unk]"]


def parse_command(text: str) -> Command | None:
    """'more kittens!' -> SPAWN_MANY. Returns None if no kitten word was said."""
    words = re.findall(r"[a-z]+", text.lower().replace("bye-bye", "byebye"))
    if "unk" in words:          # vosk's [unk] marker: part of the phrase was not understood
        words = [w for w in words if w != "unk"]
    said = set(words)
    if not said & (KITTEN_ONE | KITTEN_MANY):
        return None
    if said & BYE_WORDS:        # check goodbyes first: "bye kittens" contains "kittens"
        return Command.DISMISS
    if said & MORE_WORDS or said & KITTEN_MANY:
        return Command.SPAWN_MANY
    return Command.SPAWN_ONE
