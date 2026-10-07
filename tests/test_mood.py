"""Mood mode logic with fake timestamps and a fake camera. No webcam or PyTorch needed."""
import threading

import pytest

from desktop_kitten import mood
from desktop_kitten.mood import SadnessTracker


def feed(tracker, values, start=0.0, step=0.25):
    """Feed one probability per frame; return the times at which it triggered."""
    return [start + i * step for i, v in enumerate(values) if tracker.update(start + i * step, v)]


def test_triggers_after_hold_time_of_sadness():
    t = SadnessTracker(threshold=0.4, hold_seconds=3.0)
    fired = feed(t, [0.8] * 20)               # 5 seconds of a sad face
    assert fired == [3.0]


def test_brief_sad_moment_does_not_trigger():
    t = SadnessTracker(threshold=0.4, hold_seconds=3.0, alpha=1.0)
    assert feed(t, [0.9] * 8 + [0.05] * 4 + [0.9] * 8) == []   # never 3 s in a row


def test_losing_the_face_resets():
    t = SadnessTracker(hold_seconds=3.0, alpha=1.0)
    assert feed(t, [0.9] * 10 + [None] + [0.9] * 10) == []


def test_cooldown_between_kittens():
    t = SadnessTracker(hold_seconds=1.0, cooldown=10.0, alpha=1.0)
    fired = feed(t, [0.9] * 80)               # 20 seconds of sadness
    assert fired == [1.0, 11.0]


def test_smoothing_ignores_a_single_spike():
    t = SadnessTracker(threshold=0.4, hold_seconds=0.0, alpha=0.3)
    assert feed(t, [0.05, 0.05, 0.9, 0.05]) == []


def test_missing_model_turns_feature_off_with_clear_message(tmp_path):
    ok, msg = mood.check_available(tmp_path / "nope.pt")
    assert not ok
    assert "not found" in msg and "nope.pt" in msg
    watcher = mood.MoodWatcher(lambda: None, path=tmp_path / "nope.pt")
    assert watcher.start() is False
    assert "not found" in watcher.error and not watcher.running


def test_env_var_overrides_default_model(monkeypatch, tmp_path):
    monkeypatch.setenv("KITTEN_MOOD_MODEL", str(tmp_path / "x.pt"))
    assert mood.model_path() == tmp_path / "x.pt"
    assert mood.model_path("given.pt").name == "given.pt"   # explicit path wins


def test_sadness_index_matches_fer_plus_order():
    assert mood.CLASSES[mood.SADNESS] == "sadness" and len(mood.CLASSES) == 8


class FakeCv2:
    COLOR_BGR2GRAY = INTER_AREA = 0

    @staticmethod
    def cvtColor(frame, _):
        return frame

    @staticmethod
    def resize(img, size, interpolation=None):
        return img


class FakeGray:
    def __getitem__(self, _):
        return self


def test_watcher_loop_with_fake_camera_calls_on_sad():
    """Run the real frame loop with a fake camera, face detector and model."""
    class Cap:
        released = False
        def read(self): return True, FakeGray()
        def release(self): self.released = True

    class Detector:
        def detectMultiScale(self, *a, **k): return [(10, 10, 100, 100)]

    class Model:
        def probabilities(self, face): return [0.1, 0, 0, 0.9, 0, 0, 0, 0]

    fired = threading.Event()
    watcher = mood.MoodWatcher(fired.set, tracker=SadnessTracker(hold_seconds=0.5))
    cap = Cap()
    thread = threading.Thread(target=watcher._run, args=(FakeCv2, Model(), Detector(), cap))
    thread.start()
    assert fired.wait(timeout=5)
    watcher._stop.set()
    thread.join(timeout=3)
    assert cap.released


@pytest.mark.skipif(not mood.check_available()[0], reason="trained model or torch not installed")
def test_real_model_loads_and_returns_probabilities():
    import numpy as np
    probs = mood.EmotionModel().probabilities(np.full((48, 48), 128, dtype=np.uint8))
    assert len(probs) == 8 and abs(sum(probs) - 1) < 1e-4
