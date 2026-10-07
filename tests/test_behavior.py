"""The kitten state machine, driven with fake time and a seeded random generator."""
import random

import pytest

from desktop_kitten.behavior import (ANIMATION_FOR, CHASE_MAX_TIME, PURR_TIME, TRANSITIONS, Bounds,
                                     IllegalTransition, Kitten, State)
from desktop_kitten.sprites import ANIMATIONS

BOUNDS = Bounds(0, 0, 1000, 800)
SIZE = (72, 48)
DT = 1 / 30


def make(state=State.SIT, x=500, y=600, seed=0, duration=100.0):
    k = Kitten(x=x, y=y, coat="ginger", width=SIZE[0], height=SIZE[1], rng=random.Random(seed))
    k.state, k.state_duration = state, duration
    return k


def run(k, seconds, cursor=None, bounds=BOUNDS):
    for _ in range(int(seconds / DT)):
        k.update(DT, cursor, bounds)


def test_every_state_has_a_transition_entry_and_leave_is_final():
    assert set(TRANSITIONS) == set(State)
    assert TRANSITIONS[State.LEAVE] == set()
    # Everything can be sent away; nothing comes back from leaving.
    assert all(State.LEAVE in TRANSITIONS[s] for s in State if s is not State.LEAVE)


def test_every_state_has_an_animation():
    assert set(ANIMATION_FOR) == set(State)
    assert set(ANIMATION_FOR.values()) <= set(ANIMATIONS)


def test_illegal_transition_is_rejected():
    k = make(State.SLEEP)
    with pytest.raises(IllegalTransition):
        k._enter(State.CHASE)   # a sleeping kitten can't start chasing


def test_spawn_starts_offscreen_and_walks_in():
    k = Kitten.spawn(BOUNDS, "gray", SIZE, rng=random.Random(1))
    assert k.state is State.WALK
    assert k.x < BOUNDS.left or k.x > BOUNDS.right
    run(k, 30)
    assert BOUNDS.left <= k.x <= BOUNDS.right


def test_sit_ends_after_its_duration():
    k = make(State.SIT, duration=2.0)
    run(k, 1.9)
    assert k.state is State.SIT
    run(k, 0.2)
    assert k.state in (State.WALK, State.SLEEP)


def test_walk_moves_toward_target_and_faces_it():
    k = make(State.WALK, x=500)
    k.target = (100, 600)
    run(k, 1.0)
    assert 100 < k.x < 500
    assert k.facing_left


def test_click_makes_kitten_purr_with_hearts_then_sit():
    k = make(State.SLEEP)
    k.pet()
    assert k.state is State.PURR
    run(k, 1.0)
    assert any(p.kind == "heart" for p in k.particles)
    run(k, PURR_TIME)
    assert k.state is State.SIT


def test_sleeping_kitten_makes_zzz_and_ignores_cursor():
    k = make(State.SLEEP)
    for i in range(150):          # cursor wiggling right next to it for 5 seconds
        k.update(DT, (500 + i % 7, 580), BOUNDS)
    assert k.state is State.SLEEP
    assert any(p.kind == "zzz" for p in k.particles)


def test_moving_cursor_nearby_starts_a_chase():
    k = make(State.SIT, seed=3)
    for i in range(300):          # 10 seconds of a moving cursor
        k.update(DT, (520 + (i % 40), 500), BOUNDS)
        if k.state is State.CHASE:
            break
    assert k.state is State.CHASE


def test_still_cursor_does_not_start_a_chase():
    k = make(State.SIT, seed=3)
    run(k, 10, cursor=(520, 500))
    assert k.state is not State.CHASE


def test_far_away_cursor_is_ignored():
    k = make(State.SIT, x=50, y=750, seed=3)
    for i in range(300):
        k.update(DT, (990 - (i % 5), 10), BOUNDS)
    assert k.state is not State.CHASE


def test_chase_catches_cursor_then_sits_with_cooldown():
    k = make(State.CHASE, x=300, y=600)
    k._last_cursor, k._cursor_still_for = (600, 560), 0.0
    for i in range(int(5 / DT)):
        k.update(DT, (600 + (i % 2), 560), BOUNDS)   # jiggle so it counts as moving
        if k.state is not State.CHASE:
            break
    assert k.state is State.SIT
    assert abs(k.x - 600) < 80             # it ended up next to the cursor...
    assert not k.contains(600, 560)        # ...but not covering it, so clicks still reach the app below
    assert k.chase_cooldown > 0


def test_chase_gives_up_after_max_time():
    k = make(State.CHASE, x=0, y=700)
    k._last_cursor, k._cursor_still_for = (0, 0), 0.0
    # cursor keeps running away along the top, faster than the kitten
    for i in range(int((CHASE_MAX_TIME + 1) / DT)):
        k.update(DT, (1000 * ((i // 30) % 2), 0), BOUNDS)
    assert k.state is not State.CHASE


def test_leave_runs_offscreen_and_marks_gone():
    k = make(State.SIT, x=200)
    k.leave(BOUNDS)
    assert k.state is State.LEAVE
    run(k, 5)
    assert k.gone
    assert k.x < BOUNDS.left            # it took the nearest (left) edge


def test_petting_a_leaving_kitten_does_nothing():
    k = make(State.SIT)
    k.leave(BOUNDS)
    k.pet()
    assert k.state is State.LEAVE


def test_long_random_run_never_breaks_rules_and_stays_on_screen():
    rng = random.Random(42)
    k = Kitten.spawn(BOUNDS, "black", SIZE, rng=random.Random(7))
    for step in range(30 * 120):          # two simulated minutes with a wandering cursor
        cursor = (rng.uniform(0, 1000), rng.uniform(0, 800)) if (step // 90) % 2 else None
        k.update(DT, cursor, BOUNDS)      # an illegal transition would raise here
        if step > 30 * 20:                # after walking in, it should stay inside
            assert BOUNDS.left - 1 <= k.x <= BOUNDS.right + 1
            assert BOUNDS.top <= k.y <= BOUNDS.bottom + 1


def test_frame_index_advances_with_time():
    k = make(State.WALK)
    k.target = (900, 600)
    first = k.frame_index
    run(k, 0.5)
    assert k.frame_index != first
