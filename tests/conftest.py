import os

# Let Qt draw into memory instead of a real screen, so tests run in CI without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
