"""Turning Vosk results into commands. Uses fake recognizer output, no microphone."""
import json

from desktop_kitten.commands import Command
from desktop_kitten.voice import find_model, interpret_result


def vosk_json(*words):
    """Fake Vosk result: (word, conf, start, end) tuples."""
    return json.dumps({"result": [{"word": w, "conf": c, "start": s, "end": e} for w, c, s, e in words],
                       "text": " ".join(w[0] for w in words)})


def test_interpret_result_uses_confident_words_only():
    assert interpret_result(vosk_json(("more", 0.95, 0.0, 0.2), ("kittens", 0.99, 0.2, 0.7))) is Command.SPAWN_MANY
    # "kittens" itself was a guess -> nothing happens
    assert interpret_result(vosk_json(("kittens", 0.3, 0.0, 0.5))) is None
    # unsure "bye" is dropped, so it does not dismiss... but the confident "kittens" still counts
    assert interpret_result(vosk_json(("bye", 0.2, 0.0, 0.2), ("kittens", 0.99, 0.3, 0.8))) is Command.SPAWN_MANY


def test_interpret_result_rejects_rhymes_glued_to_kitten():
    # "mittens" heard as [unk] (the m) + "kittens" with no gap between them
    assert interpret_result(vosk_json(("[unk]", 0.9, 0.0, 0.09), ("kittens", 1.0, 0.09, 0.54))) is None
    # "oh, kitten": a real pause between the words -> accepted
    assert interpret_result(vosk_json(("[unk]", 0.9, 0.0, 0.18), ("kitten", 1.0, 0.24, 0.66))) is Command.SPAWN_ONE


def test_interpret_result_handles_text_only_and_bad_json():
    assert interpret_result('{"text": "kitten"}') is Command.SPAWN_ONE
    assert interpret_result("not json") is None


def test_find_model_missing(tmp_path):
    assert find_model(tmp_path / "nope") is None
    (tmp_path / "m" / "conf").mkdir(parents=True)
    assert find_model(tmp_path / "m") == tmp_path / "m"
