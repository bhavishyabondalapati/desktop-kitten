"""Download the small offline English speech model for Vosk (about 40 MB, one time).

Run:  python scripts/download_voice_model.py
It is saved to models/ (ignored by git) and never needs internet again.
"""
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from desktop_kitten.voice import MODEL_NAME, MODELS_DIR  # noqa: E402

URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"


def main():
    target = MODELS_DIR / MODEL_NAME
    if target.exists():
        print(f"Already downloaded: {target}")
        return
    MODELS_DIR.mkdir(exist_ok=True)
    zip_path = MODELS_DIR / f"{MODEL_NAME}.zip"
    print(f"Downloading {URL}")

    def progress(blocks, block_size, total):
        done = blocks * block_size
        if total > 0 and (done // 1_000_000 != (done - block_size) // 1_000_000 or done >= total):
            print(f"\r  {min(done, total) / 1e6:5.1f} / {total / 1e6:.1f} MB", end="", flush=True)

    urllib.request.urlretrieve(URL, zip_path, progress)
    print("\nUnzipping...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(MODELS_DIR)
    zip_path.unlink()
    print(f"Done: {target}")


if __name__ == "__main__":
    main()
