"""The kitten's brain: a small finite state machine.

Each kitten is always in exactly one State. Every frame, update(dt, cursor)
runs the logic for the current state and may switch to another one. Only the
switches listed in TRANSITIONS are allowed, and _enter() checks this, so a bug
can't put a kitten into a nonsense state (e.g. waking up after it left).

This module knows nothing about Qt or windows: positions are plain numbers in
screen pixels, randomness comes from an injected random.Random and time from
dt. That makes the behavior fully testable and repeatable.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum

from desktop_kitten.sprites import ANIMATIONS


class State(Enum):
    WALK = "walk"      # stroll to a random spot
    SIT = "sit"        # rest for a few seconds
    SLEEP = "sleep"    # nap; z's float up
    CHASE = "chase"    # run after the mouse cursor
    PURR = "purr"      # was clicked: happy face and hearts
    LEAVE = "leave"    # run off the nearest screen edge, then disappear


TRANSITIONS: dict[State, set[State]] = {
    State.WALK:  {State.WALK, State.SIT, State.CHASE, State.PURR, State.LEAVE},
    State.SIT:   {State.WALK, State.SLEEP, State.CHASE, State.PURR, State.LEAVE},
    State.SLEEP: {State.SIT, State.PURR, State.LEAVE},
    State.CHASE: {State.SIT, State.PURR, State.LEAVE},
    State.PURR:  {State.SIT, State.LEAVE},
    State.LEAVE: set(),   # final: the kitten is removed once it is off screen
}

ANIMATION_FOR = {
    State.WALK: "walk", State.SIT: "sit", State.SLEEP: "sleep",
    State.CHASE: "run", State.PURR: "purr", State.LEAVE: "run",
}

# Tuning knobs (pixels and seconds)
WALK_SPEED = 55
CHASE_SPEED = 190
LEAVE_SPEED = 260
SIT_TIME = (3.0, 8.0)           # random duration range
SLEEP_TIME = (12.0, 25.0)
PURR_TIME = 2.6
CHASE_MAX_TIME = 6.0
CHASE_RADIUS = 350              # only notice the cursor when it is this close
CHASE_CHANCE_PER_SEC = 0.6      # how eager a nearby kitten is to start chasing
CHASE_COOLDOWN = 8.0            # rest time between chases
CURSOR_STILL_AFTER = 1.5        # cursor counts as "not moving" after this long
CAUGHT_DISTANCE = 26
SLEEP_CHANCE = 0.3              # chance that a finished sit turns into a nap
HEART_EVERY = 0.3
ZZZ_EVERY = 1.4


class IllegalTransition(Exception):
    pass


@dataclass
class Bounds:
    """The area kittens roam in, in screen pixels. (x, y) of a kitten is its feet."""
    left: float
    top: float
    right: float
    bottom: float


@dataclass
class Particle:
    kind: str          # "heart" or "zzz"
    x: float
    y: float
    vx: float
    vy: float
    life: float        # seconds left
    max_life: float

    @property
    def alpha(self) -> float:
        """1 when new, fading to 0 when it expires."""
        return max(0.0, min(1.0, self.life / self.max_life))


@dataclass
class Kitten:
    x: float
    y: float
    coat: str
    width: float                       # sprite size on screen, for hit tests and edges
    height: float
    rng: random.Random = field(default_factory=random.Random)
    state: State = State.WALK
    facing_left: bool = False
    target: tuple[float, float] | None = None
    state_time: float = 0.0            # seconds spent in the current state
    state_duration: float = 0.0        # how long SIT/SLEEP/PURR should last
    anim_time: float = 0.0
    chase_cooldown: float = 0.0
    particle_timer: float = 0.0
    gone: bool = False                 # True once it has left the screen
    particles: list[Particle] = field(default_factory=list)
    _last_cursor: tuple[float, float] | None = None
    _cursor_still_for: float = 0.0

    # ---------------------------------------------------------- creation ---
    @classmethod
    def spawn(cls, bounds: Bounds, coat: str, size: tuple[float, float],
              rng: random.Random | None = None) -> "Kitten":
        """Create a kitten just outside the left or right edge, walking in."""
        rng = rng or random.Random()
        w, h = size
        from_left = rng.random() < 0.5
        x = bounds.left - w / 2 if from_left else bounds.right + w / 2
        y = rng.uniform(bounds.top + h, bounds.bottom)
        kitten = cls(x=x, y=y, coat=coat, width=w, height=h, rng=rng)
        kitten.target = (kitten._random_spot(bounds)[0], y)
        kitten.facing_left = not from_left
        return kitten

    # ---------------------------------------------------------- queries ----
    @property
    def animation(self) -> str:
        return ANIMATION_FOR[self.state]

    @property
    def frame_index(self) -> int:
        return int(self.anim_time * ANIMATIONS[self.animation].fps)

    @property
    def is_busy(self) -> bool:
        """True when something on screen changes quickly (moving, hearts, z's).
        The overlay uses this to pick a fast or slow redraw rate."""
        return self.state in (State.WALK, State.CHASE, State.LEAVE, State.PURR) or bool(self.particles)

    def rect(self) -> tuple[float, float, float, float]:
        """(left, top, width, height) of the sprite on screen."""
        return self.x - self.width / 2, self.y - self.height, self.width, self.height

    def contains(self, px: float, py: float) -> bool:
        left, top, w, h = self.rect()
        return left <= px < left + w and top <= py < top + h

    # ---------------------------------------------------------- commands ---
    def pet(self) -> None:
        """The user clicked this kitten."""
        if self.state is not State.LEAVE:
            self._enter(State.PURR, duration=PURR_TIME)

    def leave(self, bounds: Bounds) -> None:
        """Run off through the nearest left/right edge."""
        if self.state is State.LEAVE:
            return
        go_left = (self.x - bounds.left) < (bounds.right - self.x)
        exit_x = bounds.left - self.width if go_left else bounds.right + self.width
        self._enter(State.LEAVE)
        self.target = (exit_x, self.y)

    # ---------------------------------------------------------- the loop ---
    def update(self, dt: float, cursor: tuple[float, float] | None, bounds: Bounds) -> None:
        self.state_time += dt
        self.anim_time += dt
        self.chase_cooldown = max(0.0, self.chase_cooldown - dt)
        self._track_cursor(dt, cursor)
        self._update_particles(dt)

        handler = {
            State.WALK: self._walk, State.SIT: self._sit, State.SLEEP: self._sleep,
            State.CHASE: self._chase, State.PURR: self._purr, State.LEAVE: self._leave,
        }[self.state]
        handler(dt, cursor, bounds)

    def _walk(self, dt, cursor, bounds):
        if self._maybe_start_chase(dt, cursor):
            return
        if self.target is None or self._move_towards(self.target, WALK_SPEED, dt):
            # Arrived: usually rest, sometimes keep exploring.
            if self.rng.random() < 0.65:
                self._enter(State.SIT, duration=self.rng.uniform(*SIT_TIME))
            else:
                self._enter(State.WALK)
                self.target = self._random_spot(bounds)

    def _sit(self, dt, cursor, bounds):
        if self._maybe_start_chase(dt, cursor):
            return
        if self.state_time >= self.state_duration:
            if self.rng.random() < SLEEP_CHANCE:
                self._enter(State.SLEEP, duration=self.rng.uniform(*SLEEP_TIME))
            else:
                self._enter(State.WALK)
                self.target = self._random_spot(bounds)

    def _sleep(self, dt, cursor, bounds):
        # Sleeping kittens ignore the cursor; only time (or a click) wakes them.
        self._emit_every(dt, ZZZ_EVERY, "zzz")
        if self.state_time >= self.state_duration:
            self._enter(State.SIT, duration=self.rng.uniform(*SIT_TIME))

    def _chase(self, dt, cursor, bounds):
        too_long = self.state_time >= CHASE_MAX_TIME
        cursor_stopped = self._cursor_still_for >= CURSOR_STILL_AFTER
        if cursor is None or too_long or cursor_stopped:
            self._end_chase()
            return
        # Stop just beside the pointer, not under it, so the kitten never blocks your
        # next click on the app below. Kept inside the roaming area.
        side = 1 if cursor[0] >= self.x else -1
        tx = min(max(cursor[0] - side * self.width * 0.6, bounds.left), bounds.right)
        ty = min(max(cursor[1] + self.height * 0.9, bounds.top + self.height), bounds.bottom)
        if self._move_towards((tx, ty), CHASE_SPEED, dt, arrive=CAUGHT_DISTANCE):
            self._end_chase()   # "caught" it: sit and look pleased

    def _purr(self, dt, cursor, bounds):
        self._emit_every(dt, HEART_EVERY, "heart")
        if self.state_time >= self.state_duration:
            self._enter(State.SIT, duration=self.rng.uniform(*SIT_TIME))

    def _leave(self, dt, cursor, bounds):
        self._move_towards(self.target, LEAVE_SPEED, dt, arrive=1)
        left, _, w, _ = self.rect()
        if left + w < bounds.left or left > bounds.right:
            self.gone = True

    # ---------------------------------------------------------- helpers ----
    def _enter(self, new: State, duration: float = 0.0) -> None:
        if new not in TRANSITIONS[self.state]:
            raise IllegalTransition(f"{self.state.name} -> {new.name}")
        if new is not self.state:
            self.anim_time = 0.0
        self.state = new
        self.state_time = 0.0
        self.state_duration = duration
        self.particle_timer = 0.0
        if new is not State.WALK:
            self.target = None

    def _end_chase(self):
        self.chase_cooldown = CHASE_COOLDOWN
        self._enter(State.SIT, duration=self.rng.uniform(*SIT_TIME))

    def _maybe_start_chase(self, dt, cursor) -> bool:
        if cursor is None or self.chase_cooldown > 0 or self._cursor_still_for >= CURSOR_STILL_AFTER:
            return False
        if math.dist((self.x, self.y - self.height / 2), cursor) > CHASE_RADIUS:
            return False
        if self.rng.random() < CHASE_CHANCE_PER_SEC * dt:
            self._enter(State.CHASE)
            return True
        return False

    def _track_cursor(self, dt, cursor):
        if cursor is None or cursor != self._last_cursor:
            self._cursor_still_for = 0.0 if cursor is not None else math.inf
        else:
            self._cursor_still_for += dt
        if self._last_cursor is None and cursor is not None:
            # First sighting: we don't know if it is moving yet, so assume it is still.
            self._cursor_still_for = CURSOR_STILL_AFTER
        self._last_cursor = cursor

    def _move_towards(self, target, speed, dt, arrive=2.0) -> bool:
        """Step toward target. Returns True when within `arrive` pixels."""
        dx, dy = target[0] - self.x, target[1] - self.y
        dist = math.hypot(dx, dy)
        if dist <= arrive:
            return True
        step = min(speed * dt, dist)
        self.x += dx / dist * step
        self.y += dy / dist * step
        if abs(dx) > 0.5:
            self.facing_left = dx < 0
        return False

    def _random_spot(self, bounds: Bounds) -> tuple[float, float]:
        inset = self.width / 2
        return (self.rng.uniform(bounds.left + inset, bounds.right - inset),
                self.rng.uniform(bounds.top + self.height, bounds.bottom))

    def _emit_every(self, dt, every, kind):
        self.particle_timer += dt
        while self.particle_timer >= every:
            self.particle_timer -= every
            self._emit(kind)

    def _emit(self, kind):
        # Hearts pop out above the head; z's drift up from the sleeping face.
        head_x = self.x + (-self.width * 0.2 if self.facing_left else self.width * 0.2)
        if kind == "heart":
            p = Particle(kind, head_x + self.rng.uniform(-14, 14), self.y - self.height,
                         vx=self.rng.uniform(-12, 12), vy=-45, life=1.2, max_life=1.2)
        else:
            p = Particle(kind, head_x, self.y - self.height * 0.6,
                         vx=8 if not self.facing_left else -8, vy=-18, life=2.2, max_life=2.2)
        self.particles.append(p)

    def _update_particles(self, dt):
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
