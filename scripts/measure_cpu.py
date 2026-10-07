"""Measure the app's CPU use in a few situations, the way Activity Monitor does.

Starts the app, waits for it to settle, then samples `top` once per second.
Run:  python scripts/measure_cpu.py         (macOS only; opens real kittens on screen)
"""
import statistics
import subprocess
import sys
import time

SCENARIOS = [
    ("Idle: no kittens, voice off", ["--kittens", "0", "--no-voice"]),
    ("Idle: no kittens, voice listening", ["--kittens", "0"]),
    ("4 kittens, voice off", ["--kittens", "4", "--no-voice"]),
    ("4 kittens, voice listening", ["--kittens", "4"]),
]
SETTLE, SAMPLES = 15, 40


def sample_cpu(pid, n):
    out = subprocess.run(["top", "-l", str(n + 1), "-s", "1", "-pid", str(pid), "-stats", "pid,cpu"],
                         capture_output=True, text=True).stdout
    values = [float(line.split()[1]) for line in out.splitlines()
              if line.strip().startswith(str(pid))]
    return values[1:]   # top's first sample has no previous reading to compare with


def main():
    for name, args in SCENARIOS:
        proc = subprocess.Popen([sys.executable, "-m", "desktop_kitten", "--seed", "1", *args],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(SETTLE)
            values = sample_cpu(proc.pid, SAMPLES)
            print(f"{name:36s} mean {statistics.mean(values):4.1f}%  max {max(values):4.1f}%  (of one core)")
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    main()
