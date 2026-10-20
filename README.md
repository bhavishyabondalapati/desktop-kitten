# Desktop Kitten

Pixel-art kittens that walk around on top of other windows on macOS, controlled by offline voice commands, global hotkeys, or a menu bar icon. Kittens wander, sit, nap, chase the mouse pointer, and purr when clicked. Clicks pass through to the windows underneath except on a kitten's visible pixels. Runs fully offline with no API keys or accounts.

![Demo](assets/demo.gif)

*Rendered by [`scripts/make_demo_gif.py`](scripts/make_demo_gif.py) using the app's own sprites and state machine on a drawn desktop; not a screen recording.*

| The five coats: walk, run, sit, sleep, purr |
|---|
| ![All sprites](assets/preview.png) |

All art is original and generated in code ([`sprites.py`](desktop_kitten/sprites.py)).

## Features

- **Transparent overlay**: a frameless, always-on-top window that appears on every Space and over full-screen apps, with no Dock icon.
- **Pixel-accurate click-through**: only a kitten's visible pixels capture clicks; transparent sprite corners do not.
- **Behavior state machine**: walk, sit, sleep, chase the pointer, purr when clicked, and run off screen when dismissed.
- **Three input methods**:

  | Command | Voice | Hotkey | Menu bar |
  |---|---|---|---|
  | Spawn one kitten | "kitten" / "kitty" / "hey kitten" | ⌃⌥K | Spawn a kitten |
  | Spawn several | "more kittens" / "kittens please" | ⌃⌥M | More kittens! |
  | Send them away | "bye kittens" / "goodbye kittens" | ⌃⌥B | Bye kittens |

- **Mood mode** (optional, off by default): uses the soft-label emotion CNN from [facial-expression-recognition](https://github.com/bhavishyabondalapati/facial-expression-recognition) to send a kitten after three seconds of a sad expression.
- **Low CPU**: 0.0% when no kittens are on screen (see [CPU use](#cpu-use)).

## Architecture

```
voice.py (Vosk, background thread) ─┐
hotkeys.py (Carbon, ctypes) ────────┼─► commands.py ──► Command ──► overlay.py ──► behavior.py
menu bar (app.py) ──────────────────┤                    (Qt main thread,   (pure-Python
mood.py (OpenCV + CNN, background) ─┘                     drawing, hit test)  state machine)
```

All input sources produce the same `Command` object, so the rest of the app has a single code path. Background threads communicate with the Qt main thread through Qt signals.

### State machine (`behavior.py`)

Each kitten is in exactly one of `WALK`, `SIT`, `SLEEP`, `CHASE`, `PURR`, or `LEAVE`.

```
           arrive (65%)           timer ends (30%)
   WALK ───────────────▶ SIT ─────────────────────▶ SLEEP
    ▲  ◀───────────────── │ ◀────────────────────── │
    │     timer ends (70%) │       timer ends         │
    │                      │ pointer moving nearby    │
    └── (35%) new spot     ▼                          │ click
                         CHASE ── caught / gave up ──▶ SIT
   click from WALK/SIT/SLEEP/CHASE ──▶ PURR ── 2.6 s ──▶ SIT
   "bye kittens" from any state ──▶ LEAVE ── off screen ──▶ removed
```

- Allowed transitions are declared in a `TRANSITIONS` table; any other transition raises `IllegalTransition`.
- The module has no Qt dependency. Time is passed in as `dt` (capped at 0.1 s to avoid jumps after system sleep) and randomness as an injected `random.Random`, so tests can simulate minutes of behavior deterministically.
- Chasing requires a moving pointer and has a cooldown.

### Overlay (`overlay.py`, `macos.py`)

- A single full-screen transparent window (`FramelessWindowHint`, `WA_TranslucentBackground`) at macOS's status window level, configured via ctypes to join all Spaces, avoid taking focus, and hide from the Dock.
- **Click-through**: macOS only supports whole-window `ignoresMouseEvents`. Each frame, the pointer position is tested against the kitten sprite grids, and the flag is toggled only when the result changes.
- **Rendering cost**: sprites are pre-rendered to `QPixmap`s, only the union of each kitten's old and new rectangles is repainted, and the timer runs at 30 fps while kittens move, 10 fps while all rest, and stops when no kittens are present.

### Voice (`voice.py`, `commands.py`)

- Vosk with the small English model (40 MB), restricted to a grammar of command phrases plus decoy words.
- Decoys (e.g. "mittens", "bitten", "chicken") give near-rhymes a better match than the commands; the parser discards them.
- A timing rule rejects `[unk]` + "kitten" pairs with no gap between them, a pattern typical of misheard rhymes.
- Words below 0.6 confidence are dropped. Audio is streamed in 0.25 s chunks and Vosk's endpointing finalizes each phrase.

### Mood mode (`mood.py`)

Webcam at 4 fps → OpenCV Haar face detector → 48×48 grayscale crop → CNN → sadness probability → exponential moving average → above 0.4 for 3 s → spawn a kitten, then a 90 s cooldown. Frames are not saved, and the camera is released when mood mode is turned off. The CNN definition is copied into this repo rather than imported from the other project.

### Tech stack

| Component | Role |
|---|---|
| PySide6 (`PySide6-Essentials`) | Transparent always-on-top window, menu bar icon, 2D drawing |
| Vosk | Offline, streaming, grammar-restricted speech recognition |
| sounddevice | Microphone input (PortAudio) |
| ctypes | macOS APIs not exposed by Qt (hotkeys, window level, click-through) without PyObjC |
| PyTorch, OpenCV (optional) | Mood mode only; kept in `requirements-mood.txt` |
| Pillow | Demo GIF rendering |
| pytest, GitHub Actions | 64 tests, run on macOS for every push |

## Results

### CPU use

Measured with `scripts/measure_cpu.py` on an M4 Pro (average of 40 one-second `top` samples after 15 s of warm-up; 100% = one core):

| Situation | App CPU |
|---|---|
| Idle: no kittens, voice off | 0.0% |
| Idle: no kittens, voice listening | 1.9% |
| 4 kittens animating, voice off | 2.1% |
| 4 kittens animating, voice listening | 4.4% |

WindowServer (compositor) usage was measured separately and showed no measurable change with four kittens versus none, since only small regions are redrawn. Background Spotlight indexing can make measurements noisy.

### Voice accuracy

From `scripts/evaluate_voice.py`: 8 command phrases and 20 non-command phrases, each spoken by 7 built-in macOS voices (US, UK, Australian, Irish, Indian, and South African English), streamed in 0.25 s chunks as from the microphone.

| Metric | Result |
|---|---|
| Commands recognized | 56/56 (100%) |
| False triggers on non-commands | 7/140 (5%), all from the single word "kitchen" |
| Recognizer CPU | ~0.4% of one core |

Approaches compared on the same test:

| Approach | Commands recognized | False triggers | CPU |
|---|---|---|---|
| Full vocabulary, no grammar | 12/40 | 3/60 | 10.7% |
| Grammar of command phrases only | 56/56 | 36/140 | 0.5% |
| + decoy words, including "kitchen" | 47/56 | 0/140 | 0.5% |
| **+ decoy words, without "kitchen" (used)** | **56/56** | **7/140** | **0.4%** |

Adding "kitchen" as a decoy eliminated its false triggers but also captured genuine "kitten" from the Australian, Irish, and South African voices, so it was left out in favor of never missing a real command. Synthetic voices are an approximation of real speakers in a real room.

### Mood model check

The copied CNN agrees with the human majority vote on 82.7% of 600 FER+ validation images. Faces that at least 60% of annotators labeled sad receive a mean sadness probability of 0.64, versus 0.03 for faces with no sad votes. The 0.4 threshold catches 86% of clearly sad faces and none of the faces with zero sad votes.

## Quickstart

```bash
conda create -n desktop-kitten python=3.12 -y
conda activate desktop-kitten
pip install -r requirements.txt
python scripts/download_voice_model.py     # one time, ~40 MB; optional if voice is not needed
python -m desktop_kitten
```

A kitten walks in and a kitten-head icon appears in the menu bar. Quit from the menu bar icon or with Ctrl+C.

```bash
python -m desktop_kitten --kittens 3     # start with 3 kittens (0 = none)
python -m desktop_kitten --no-voice      # do not use the microphone
python -m desktop_kitten --mood          # enable mood mode at start
python -m desktop_kitten -v              # print recognized speech with confidence
python -m desktop_kitten --help
```

### Mood mode

```bash
pip install -r requirements-mood.txt     # about 700 MB, mostly PyTorch
```

The model is loaded from `~/projects/facial-expression-recognition/weights/cnn_soft.pt` by default; override with `--mood-model PATH` or the `KITTEN_MOOD_MODEL` environment variable.

### macOS permissions

| Permission | Needed for | Notes |
|---|---|---|
| Microphone | Voice commands | Requested on first use. Can be enabled later under System Settings → Privacy & Security → Microphone for the launching terminal. Turning off "Voice commands" in the menu releases the microphone. |
| Camera | Mood mode only | Requested the first time mood mode is enabled; re-enable mood mode after allowing. |
| Accessibility / Input Monitoring | Not needed | Hotkeys use `RegisterEventHotKey`, which receives only the registered shortcuts rather than all keystrokes. |

Permissions are granted to the application that launches Python (Terminal, iTerm, VS Code, etc.).

## Running tests

```bash
python -m pytest
```

Tests run with Qt in offscreen mode and need no display, microphone, or camera. They cover state transitions and timing, a two-minute randomized simulation, command and hotkey parsing, voice result filtering and rhyme rejection, sprite sizes and hit testing, and the mood tracker with a fake camera.

Measurement scripts:

```bash
python scripts/evaluate_voice.py    # voice accuracy using macOS `say` (no microphone)
python scripts/measure_cpu.py       # CPU use (shows kittens on screen for ~2 minutes)
```

## Project structure

```
desktop-kitten/
├── desktop_kitten/
│   ├── __main__.py            Entry point for `python -m desktop_kitten`
│   ├── app.py                 Wiring: menu bar icon, hotkeys, voice, mood, CLI flags
│   ├── overlay.py             Transparent window: animation loop, drawing, click-through, petting
│   ├── behavior.py            Kitten state machine (pure Python)
│   ├── sprites.py             Pixel art as text grids, 5 coats, sprite sheets, pre-rendered images
│   ├── commands.py            Text-to-Command parsing; voice grammar and decoy words
│   ├── voice.py               Vosk recognition on a background thread
│   ├── hotkeys.py             Global shortcuts via the macOS Carbon API (ctypes)
│   ├── mood.py                Webcam → face → emotion CNN → sadness tracker
│   └── macos.py               Cocoa calls via ctypes: window level, Spaces, click-through, Dock
├── tests/
│   ├── conftest.py            Offscreen Qt setup
│   ├── test_behavior.py       Transitions, timing, chasing, petting, leaving, randomized run
│   ├── test_commands.py       Command parsing, voice phrases vs decoys, hotkey parsing
│   ├── test_voice.py          Confidence filtering, rhyme rejection, model lookup
│   ├── test_sprites.py        Frame sizes, colors, mirroring, sprite sheet round trip, hit testing
│   └── test_mood.py           Sadness tracker timing, missing-model handling, fake-camera loop
├── scripts/
│   ├── download_voice_model.py  Downloads the Vosk model into models/
│   ├── evaluate_voice.py        Voice accuracy using macOS `say` voices
│   ├── measure_cpu.py           CPU use in four scenarios
│   ├── export_sprites.py        Writes assets/sprites/*.png and assets/preview.png
│   └── make_demo_gif.py         Renders assets/demo.gif
├── assets/                    Sprite sheets (24×16 px frames), preview, demo GIF
├── .github/workflows/tests.yml  CI: pytest on macOS
├── requirements.txt
├── requirements-mood.txt      Extra dependencies for mood mode
└── pyproject.toml             pytest settings
```

`models/` is created by the download script and is not tracked.

## Design decisions

- **Vosk over Whisper.** Whisper is stronger at free-form transcription but processes fixed windows and cannot be restricted to a phrase list. For a few always-on commands, a streaming recognizer with a grammar is faster to react and far cheaper (0.4% vs 10.7% CPU without a grammar).
- **ctypes instead of PyObjC** for the handful of macOS calls Qt does not expose, keeping dependencies small.
- **`RegisterEventHotKey` instead of a keyboard listener**, so no Accessibility or Input Monitoring permission is needed.
- **Pure-Python state machine** with explicit transitions, separated from rendering, for deterministic tests.
- **Sprites built from shared parts.** Each pose combines one head with interchangeable bodies, legs, and tails, so the face is identical across frames. Pixels store roles (outline, fur, stripes, eyes) rather than colors, so all five coats share one set of grids.
- **Chasing kittens stop beside the pointer**, not under it, so they do not block the next click.
- **Camera opened on the main thread**, since macOS only shows the camera permission prompt in that case.

## Limitations and future work

- macOS only.
- Saying "kitchen" on its own can summon a kitten (see [Voice accuracy](#voice-accuracy)).
- Voice accuracy was measured with synthetic voices; real-room accuracy with a user's own voice has not been measured.
- Hotkey presses could not be tested by automation (macOS blocks scripted keystrokes); hotkey registration is tested.
- Mood mode's frame loop is tested with a fake camera; end-to-end use requires granting camera permission manually.
- The demo GIF is rendered rather than screen-recorded.
