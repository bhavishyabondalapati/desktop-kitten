"""Optional "mood mode": a kitten appears when you look sad for a few seconds.

It reuses the soft-label CNN trained in the facial-expression-recognition
project (FER+ dataset, 8 emotions). Because that model was trained on the
*share of votes* for each emotion, its "sadness" output reads like "how many
people would call this face sad", which is a good fit for a gentle trigger.

Pipeline (about 4 times per second, all on this Mac):
    webcam frame -> OpenCV face detector -> 48x48 grayscale crop -> CNN
    -> sadness probability -> SadnessTracker -> spawn a kitten

Off by default. If the model file, PyTorch or OpenCV is missing, the feature
turns itself off and says exactly what is missing. Frames are never saved.
"""
from __future__ import annotations

import importlib.util
import os
import threading
import time
from pathlib import Path
from typing import Callable

DEFAULT_MODEL = Path.home() / "projects" / "facial-expression-recognition" / "weights" / "cnn_soft.pt"
CLASSES = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
SADNESS = CLASSES.index("sadness")
FPS = 4


def model_path(path: str | Path | None = None) -> Path:
    """--mood-model, else $KITTEN_MOOD_MODEL, else the default project location."""
    return Path(path or os.environ.get("KITTEN_MOOD_MODEL") or DEFAULT_MODEL).expanduser()


def check_available(path: str | Path | None = None) -> tuple[bool, str]:
    """(ok, message). Cheap: checks files and packages without importing PyTorch."""
    p = model_path(path)
    if not p.is_file():
        return False, (f"Mood mode is off: trained model not found at {p}. Train it in the "
                       "facial-expression-recognition project or pass --mood-model PATH.")
    missing = [pkg for pkg, mod in (("torch", "torch"), ("opencv-python", "cv2"))
               if importlib.util.find_spec(mod) is None]
    if missing:
        return False, (f"Mood mode is off: missing {', '.join(missing)}. "
                       "Install with: pip install -r requirements-mood.txt")
    return True, f"Mood mode ready (model: {p})"


class SadnessTracker:
    """Decides when 'looking sad' has lasted long enough to deserve a kitten.

    * smooths the per-frame probability (one odd frame shouldn't count),
    * needs it above `threshold` continuously for `hold_seconds`,
    * then waits `cooldown` seconds before it can trigger again.
    Pure logic with explicit timestamps, so it is easy to test.
    """

    def __init__(self, threshold=0.4, hold_seconds=3.0, cooldown=90.0, alpha=0.5):
        self.threshold, self.hold, self.cooldown, self.alpha = threshold, hold_seconds, cooldown, alpha
        self.smoothed: float | None = None
        self.sad_since: float | None = None
        self.quiet_until = 0.0

    def update(self, now: float, sad_prob: float | None) -> bool:
        if sad_prob is None:                 # no face in view: start over
            self.smoothed = self.sad_since = None
            return False
        self.smoothed = sad_prob if self.smoothed is None else (
            self.alpha * sad_prob + (1 - self.alpha) * self.smoothed)
        if self.smoothed < self.threshold:
            self.sad_since = None
            return False
        if self.sad_since is None:
            self.sad_since = now
        if now - self.sad_since >= self.hold and now >= self.quiet_until:
            self.quiet_until = now + self.cooldown
            self.sad_since = None
            return True
        return False


def _build_cnn():
    """The ScratchCNN from facial-expression-recognition/src/models.py, copied here
    so this project doesn't import code from another repo. Layer names must match
    the checkpoint exactly for load_state_dict to work."""
    import torch.nn as nn

    fer_mean, fer_std = 0.508, 0.254

    def conv_block(c_in, c_out, dropout):
        return nn.Sequential(
            nn.Conv2d(c_in, c_out, 3, padding=1, bias=False), nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
            nn.Conv2d(c_out, c_out, 3, padding=1, bias=False), nn.BatchNorm2d(c_out), nn.ReLU(inplace=True),
            nn.MaxPool2d(2), nn.Dropout(dropout),
        )

    class ScratchCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(conv_block(1, 64, 0.1), conv_block(64, 128, 0.1),
                                          conv_block(128, 256, 0.2), conv_block(256, 512, 0.2))
            self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(),
                                      nn.Dropout(0.5), nn.Linear(512, len(CLASSES)))

        def forward(self, x):
            return self.head(self.features((x - fer_mean) / fer_std))

    return ScratchCNN()


class EmotionModel:
    """Loads the checkpoint and returns the 8 emotion probabilities for one face."""

    def __init__(self, path: str | Path | None = None):
        import torch

        torch.set_num_threads(1)   # a 48x48 image is tiny; one CPU thread keeps the fan quiet
        # weights_only=True: load tensors only, never run code stored in the file
        ckpt = torch.load(model_path(path), map_location="cpu", weights_only=True)
        if ckpt.get("model") != "cnn":
            raise ValueError(f"expected the scratch CNN checkpoint, got model={ckpt.get('model')!r}")
        self.net = _build_cnn()
        self.net.load_state_dict(ckpt["state_dict"])
        self.net.eval()
        self._torch = torch

    def probabilities(self, face_48x48) -> list[float]:
        """face: 48x48 uint8 grayscale array -> 8 probabilities (sum to 1)."""
        torch = self._torch
        x = torch.from_numpy(face_48x48).float().div(255).view(1, 1, 48, 48)
        with torch.no_grad():
            return torch.softmax(self.net(x), dim=1)[0].tolist()


class MoodWatcher:
    """Background thread: webcam -> face -> sadness -> on_sad() callback."""

    def __init__(self, on_sad: Callable[[], None], path: str | Path | None = None,
                 camera: int = 0, tracker: SadnessTracker | None = None):
        self.on_sad = on_sad
        self.path = path
        self.camera = camera
        self.tracker = tracker or SadnessTracker()
        self.error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Load the model and open the camera here, on the calling (GUI) thread:
        macOS only shows the camera permission prompt from the main thread.
        Then a background thread does the per-frame work."""
        ok, message = check_available(self.path)
        if not ok:
            self.error = message
            return False
        try:
            import cv2
            model = EmotionModel(self.path)
            detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            cap = cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                raise RuntimeError("could not open the camera. The first time, macOS asks for camera "
                                   "permission: click Allow, then turn Mood mode on again. If you said no "
                                   "before, enable your terminal in System Settings > Privacy & Security > Camera")
        except Exception as exc:
            self.error = f"Mood mode is off: {exc}"
            return False
        self.error = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(cv2, model, detector, cap),
                                        daemon=True, name="mood")
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._thread = None

    def _run(self, cv2, model, detector, cap):
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                ok, frame = cap.read()
                if ok:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
                    sad = None
                    if len(faces):
                        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])   # the biggest face = you
                        face = cv2.resize(gray[y:y + h, x:x + w], (48, 48), interpolation=cv2.INTER_AREA)
                        sad = model.probabilities(face)[SADNESS]
                    if self.tracker.update(time.monotonic(), sad):
                        self.on_sad()
                self._stop.wait(max(0.0, 1 / FPS - (time.monotonic() - started)))
        finally:
            cap.release()
