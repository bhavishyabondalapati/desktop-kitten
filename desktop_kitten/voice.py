"""Offline voice commands with Vosk.

Vosk runs a small (~40 MB) Kaldi speech model entirely on this Mac: audio
never leaves the computer and no account or API key is needed. We also give
the recognizer a *grammar*, the short list of phrases in VOICE_PHRASES, so it
only has to choose between "kitten", "more kittens", "bye kittens", ... and
"[unk]" (anything else). That makes a tiny model accurate and cheap to run.

The microphone is read on a background thread; recognized commands are
passed to on_command (the app forwards them safely to the GUI thread).
"""
from __future__ import annotations

import json
import queue
import threading
from pathlib import Path
from typing import Callable

from desktop_kitten.commands import KITTEN_MANY, KITTEN_ONE, VOICE_GRAMMAR, Command, parse_command

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MIN_CONFIDENCE = 0.6     # ignore words the recognizer itself is unsure about
BLOCK_SECONDS = 0.25     # audio chunk size handed to the recognizer
GLUE_GAP = 0.015         # seconds; see interpret_result


def find_model(path: str | Path | None = None) -> Path | None:
    """The given model folder, or the default one in models/. None if missing."""
    candidate = Path(path).expanduser() if path else MODELS_DIR / MODEL_NAME
    return candidate if (candidate / "conf").is_dir() or (candidate / "am").is_dir() else None


def interpret_result(result_json: str, min_confidence: float = MIN_CONFIDENCE) -> Command | None:
    """Turn one Vosk final result into a Command.

    With SetWords(True) Vosk returns per-word confidences:
      {"result": [{"word": "more", "conf": 0.97}, ...], "text": "more kittens"}
    Low-confidence words are dropped first, so a cough that vaguely sounds like
    "kitten" does not spawn one.
    """
    try:
        data = json.loads(result_json)
    except json.JSONDecodeError:
        return None
    words = data.get("result")
    if words:
        if _rhyme_with_kitten(words):
            return None
        text = " ".join(w["word"] for w in words if w.get("conf", 1.0) >= min_confidence)
    else:
        text = data.get("text", "")
    return parse_command(text)


def _rhyme_with_kitten(words: list[dict]) -> bool:
    """True if an unknown sound runs straight into a kitten word with no pause.

    Because the grammar only knows a few words, the recognizer splits a rhyme
    like "mittens" into "[unk]" (the m) + "kittens", with zero gap between them.
    Real speech ("oh, kitten") has a short pause, so we only reject the glued case.
    """
    for prev, word in zip(words, words[1:]):
        if (prev["word"] == "[unk]" and word["word"] in KITTEN_ONE | KITTEN_MANY
                and word.get("start", 0) - prev.get("end", 0) < GLUE_GAP):
            return True
    return False


class VoiceListener:
    def __init__(self, on_command: Callable[[Command], None], model_path: str | Path | None = None,
                 on_heard: Callable[[str], None] | None = None):
        self.on_command = on_command
        self.on_heard = on_heard
        self.model_path = model_path
        self.error: str | None = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._audio: queue.Queue[bytes] = queue.Queue(maxsize=50)
        self._model = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Open the microphone and start listening. On failure returns False and
        sets self.error to a message that says how to fix it."""
        if self.running:
            return True
        try:
            import sounddevice as sd
            import vosk
        except ImportError as exc:
            self.error = f"Voice needs the vosk and sounddevice packages ({exc.name} missing): pip install -r requirements.txt"
            return False

        model_dir = find_model(self.model_path)
        if model_dir is None:
            self.error = ("Voice model not found. Download it once (about 40 MB) with: "
                          "python scripts/download_voice_model.py")
            return False
        try:
            vosk.SetLogLevel(-1)
            if self._model is None:
                self._model = vosk.Model(str(model_dir))
            rate = int(sd.query_devices(kind="input")["default_samplerate"])
            recognizer = vosk.KaldiRecognizer(self._model, rate, json.dumps(VOICE_GRAMMAR))
            recognizer.SetWords(True)
            self._stream = sd.RawInputStream(samplerate=rate, blocksize=int(rate * BLOCK_SECONDS),
                                             dtype="int16", channels=1, callback=self._on_audio)
            self._stream.start()
        except Exception as exc:   # no mic, permission denied, broken model...
            self.error = (f"Could not start the microphone ({exc}). On macOS allow microphone access "
                          "for your terminal in System Settings > Privacy & Security > Microphone.")
            self._close_stream()
            return False

        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen, args=(recognizer,), daemon=True,
                                        name="voice")
        self._thread.start()
        return True

    def stop(self):
        """Stop listening and release the microphone (the orange mic dot goes away)."""
        self._stop.set()
        self._close_stream()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _close_stream(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _on_audio(self, data, frames, time_info, status):
        # Runs on PortAudio's audio thread: just hand the bytes over, never block.
        try:
            self._audio.put_nowait(bytes(data))
        except queue.Full:
            pass   # recognizer fell behind; dropping a chunk is better than lagging

    def _listen(self, recognizer):
        while not self._stop.is_set():
            try:
                chunk = self._audio.get(timeout=0.5)
            except queue.Empty:
                continue
            if recognizer.AcceptWaveform(chunk):   # True at the end of an utterance
                result = recognizer.Result()
                if self.on_heard:
                    words = json.loads(result).get("result", [])
                    self.on_heard(" ".join(f"{w['word']}({w.get('conf', 1):.2f})" for w in words))
                command = interpret_result(result)
                if command:
                    self.on_command(command)
