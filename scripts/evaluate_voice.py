"""Measure voice-command accuracy offline, without a microphone.

macOS's built-in `say` command speaks each test phrase into a WAV file in
several voices/accents. The clips go through the exact same grammar and
filtering the app uses, streamed in 0.25 s chunks like the live microphone.

Run:  python scripts/evaluate_voice.py        (macOS only; needs the voice model)
"""
import json
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vosk  # noqa: E402

from desktop_kitten.commands import VOICE_GRAMMAR  # noqa: E402
from desktop_kitten.voice import find_model, interpret_result  # noqa: E402

COMMANDS = {
    "kitten": "spawn_one", "kitty": "spawn_one", "hey kitten": "spawn_one",
    "more kittens": "spawn_many", "kittens please": "spawn_many",
    "bye kittens": "dismiss", "goodbye kittens": "dismiss", "bye bye kittens": "dismiss",
}
NOT_COMMANDS = [
    "mittens", "mitten", "more mittens", "bitten", "written", "it is written", "smitten", "kitchen",
    "chicken", "cat food", "kit kat", "button", "ticket please", "sit and listen", "listen to me",
    "sitting here", "the weather is nice today", "I am getting coffee", "bye for now", "get it done",
]
VOICES = ["Samantha", "Daniel", "Karen", "Moira", "Fred", "Rishi", "Tessa"]   # US, UK, AU, IE, US, IN, ZA
RATE = 16000


def speak(text, voice, folder):
    aiff, wav = folder / "clip.aiff", folder / "clip.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", "-c", "1", str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return w.readframes(w.getnframes())


def recognize(model, audio):
    rec = vosk.KaldiRecognizer(model, RATE, json.dumps(VOICE_GRAMMAR))
    rec.SetWords(True)
    data = b"\0" * RATE + audio + b"\0" * RATE * 2       # silence around the phrase
    found = []
    for i in range(0, len(data), RATE // 2):            # 0.25 s of 16-bit audio = 8000 bytes
        if rec.AcceptWaveform(data[i:i + RATE // 2]):
            found.append(interpret_result(rec.Result()))
    found.append(interpret_result(rec.FinalResult()))
    found = [c for c in found if c]
    return found[0].value if found else None


def main():
    model_dir = find_model()
    if model_dir is None:
        sys.exit("Voice model missing: python scripts/download_voice_model.py")
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(model_dir))
    correct, false_triggers, misses, false_list = 0, 0, [], []
    audio_seconds = compute = 0.0
    with tempfile.TemporaryDirectory() as tmp:
        for voice in VOICES:
            for phrase in list(COMMANDS) + NOT_COMMANDS:
                audio = speak(phrase, voice, Path(tmp))
                start = time.perf_counter()
                got = recognize(model, audio)
                compute += time.perf_counter() - start
                audio_seconds += len(audio) / (2 * RATE) + 3
                if phrase in COMMANDS:
                    correct += got == COMMANDS[phrase]
                    if got != COMMANDS[phrase]:
                        misses.append(f"{voice}: {phrase!r} -> {got}")
                elif got:
                    false_triggers += 1
                    false_list.append(f"{voice}: {phrase!r} -> {got}")
    n_cmd, n_not = len(COMMANDS) * len(VOICES), len(NOT_COMMANDS) * len(VOICES)
    print(f"Commands understood: {correct}/{n_cmd} ({correct / n_cmd:.0%})")
    print(f"False triggers:      {false_triggers}/{n_not} ({false_triggers / n_not:.0%})")
    print(f"Recognizer CPU:      {100 * compute / audio_seconds:.1f}% of one core")
    for line in misses:
        print("  missed:", line)
    for line in false_list:
        print("  false: ", line)


if __name__ == "__main__":
    main()
