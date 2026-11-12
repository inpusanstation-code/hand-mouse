"""The other hand's speed dial (2026-11-12, "노즐 컨트롤 형식", src/speed_dial.py)."""
import math
import time

from src.gesture_engine import Point3D
from src.speed_dial import FIST_FRAMES, STEP_DEG, SpeedDial
from tests.test_gesture_mouse import make_real_hand

OPEN = make_real_hand(curled=False)
FIST = make_real_hand(curled=True)
# the test hand's own tilt; pose(0) is turned to the dial's middle (11 o'clock), so pose(deg) is `deg` from the middle
from src.speed_dial import CENTER_TILT, DIRECTION, tilt as _tilt  # noqa: E402
TO_MIDDLE = CENTER_TILT - _tilt(OPEN, 1280, 720)


def pose(deg=0.0, pinched=False, dx=0.0, hand=None):
    """The open hand turned `deg` towards the dial's "more" (DIRECTION: counter-clockwise on the screen since 2026-11-12)
    about its wrist; `pinched`: the thumb tip on the index tip."""
    pts = [Point3D(p.x, p.y, p.z) for p in (hand or OPEN)]
    if pinched:
        pts[4] = Point3D(pts[8].x, pts[8].y + .005, pts[8].z)
    w = pts[0]
    a = math.radians(DIRECTION * deg + TO_MIDDLE)
    out = []
    for p in pts:                                         # in pixels (1280 x 720) so the turn is a real screen angle
        x, y = (p.x - w.x) * 1280, (p.y - w.y) * 720
        rx, ry = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
        out.append(Point3D(w.x + rx / 1280 + dx, w.y + ry / 720, p.z))
    return out


def fist(deg=0.0, dx=0.0):
    return pose(deg, dx=dx, hand=FIST)


def run(dial, frames, t=0.0):
    """The dial's events over these frames, without "press" (the fingers closing: only the seek dial's caller uses it)."""
    events = []
    for lm in frames:
        events += [e for e in dial.step(t, lm) if e != "press"]
        t += 1 / 30
    return events, t


def tap(deg=0.0):
    """The pinch held long enough to open a dial (HOLD; it was a tap until 2026-11-12)."""
    return [pose(deg, pinched=True)] * 16 + [pose(deg)] * 2


def short_tap(deg=0.0):
    return [pose(deg, pinched=True)] * 4 + [pose(deg)] * 2


def test_a_held_pinch_opens_the_dial_turning_steps_it_and_a_fist_closes_it():
    d = SpeedDial()
    ev, t = run(d, [pose()] * 5 + tap())
    assert ev == ["on"] and d.active and d.steps == 0
    ev, t = run(d, [pose(a) for a in range(0, 26, 3)], t)        # 24 degrees clockwise: two steps faster
    assert ev == ["faster", "faster"] and d.steps == 2
    ev, t = run(d, [pose(a) for a in range(24, -16, -3)], t)     # back to -15: three steps slower
    assert ev == ["slower"] * 3 and d.steps == -1
    ev, t = run(d, tap(-15), t)                                  # the pinch again: it stays (2026-11-12)
    assert "off" not in ev and d.active
    ev, t = run(d, [fist(-15)] * (FIST_FRAMES - 1), t)           # not yet
    assert d.active
    ev, t = run(d, [fist(-15)], t)
    assert ev == ["off"] and not d.active


def test_the_gauge_is_shorter():
    """2026-11-12: "게이지가 너무 넓어서 번거로우니까 길이를 줄여" - 12 degrees a step (was 20)."""
    d = SpeedDial()
    run(d, tap())
    v = d.view()
    assert v["step_deg"] == STEP_DEG == 12.0
    assert (v["max"] - v["min"]) * v["step_deg"] == 60.0         # .75x .. 2x in 60 degrees of turn (was 100)


def test_no_flicker_at_a_step_edge():
    d = SpeedDial()
    ev, t = run(d, tap())
    edge = STEP_DEG / 2
    ev, t = run(d, [pose(edge + (2 if i % 2 else -2)) for i in range(30)], t)   # wobbling round the middle
    assert ev == [] and d.steps == 0


def test_the_dial_does_not_close_by_itself():
    """2026-11-12: "주먹으로 종료하기 전까지는 게이지가 이유없이 없어지지 않게" - it closed when the hand was out of view
    .6 s, after 3 s untouched and when the hand moved aside."""
    d = SpeedDial()
    ev, t = run(d, tap())
    ev, t = run(d, [None] * 150, t)                               # 5 s out of view
    assert ev == [] and d.active
    ev, t = run(d, [pose(40)] * 2, t)                             # back, turned meanwhile: no jump of the speed
    assert ev == [] and d.steps == 0
    ev, t = run(d, [pose(40)] * 300, t)                           # 10 s untouched
    assert ev == [] and d.active
    ev, t = run(d, [pose(40, dx=.02 * i) for i in range(10)], t)  # the hand moving aside
    assert ev == [] and d.active
    ev, t = run(d, [fist(40)] * FIST_FRAMES, t)
    assert ev == ["off"]


def test_closing_into_a_fist_does_not_turn_the_speed():
    d = SpeedDial()
    ev, t = run(d, tap())
    curling = []
    # the fingers curl while the hand turns 30 degrees clockwise on the screen (the way this test turned before the dial's
    # direction was swapped, 2026-11-12; turned the other way this test hand's step comes at curls 1.47/1.46/1.41, just
    # outside CURLING, and is not given back)
    for k in range(6):
        f = k / 5
        curling.append([Point3D(o.x + (c.x - o.x) * f, o.y + (c.y - o.y) * f, o.z + (c.z - o.z) * f)
                        for o, c in zip(pose(-k * 6), fist(-k * 6))])
    ev, t = run(d, curling + [fist(-30)] * FIST_FRAMES, t)
    # a step taken while curling is given back as the fist closes it
    assert ev[-1] == "off" and ev.count("faster") == ev.count("slower") and d.steps == 0


def test_it_opens_on_the_speed_it_was_closed_on():
    """2026-11-12: "엄지검지 배속 적용은 주먹으로 종료한 배속을 계속 적용"."""
    d = SpeedDial()
    ev, t = run(d, tap(40))                      # nothing known yet: 1x wherever the hand points, YouTube not set yet
    assert ev == ["on"] and d.speed() == 1.0 and not d.synced
    d.known_speed = 1.5                          # what the app set YouTube to, then closed on
    ev, t = run(d, [fist(40)] * FIST_FRAMES, t)
    ev, t = run(d, tap(-20), t)                  # opened again, the hand elsewhere: still 1.5x, known
    assert ev == ["on"] and d.speed() == 1.5 and d.synced
    ev, t = run(d, [pose(-20 + a) for a in range(0, 13, 3)], t)  # turned on from there
    assert ev == ["faster"] and d.speed() == 1.75


def two_hands(rt, left):
    from tests.test_other_hand_motion import TwoHands
    from src.hand_tracker import HandDetection

    class Hands(TwoHands):
        def detect(self, frame, roi=None):
            out = super(TwoHands, self).detect(frame, roi)
            if left["lm"] is not None:
                out.append(HandDetection(landmarks=left["lm"], handedness="Right", score=.95))
            return out
    rt.tracker = Hands()
    rt.tracker.dx = .25

    def run_for(seconds, make):
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            left["lm"] = make()
            rt._step()
            time.sleep(1 / 60)
    return run_for


def test_the_runtime_sends_youtube_speed_keys_keeps_the_speed_and_holds_the_swipes(tmp_path):
    from tests.test_qt_runtime import runtime
    import dataclasses
    rt = runtime(tmp_path)
    rt.paused = False
    rt.ui = dataclasses.replace(rt.ui, virtual_hand=True, use_index_pointer=False, other_motion=True)
    sent = []
    rt.mouse.send_motion_action = lambda a: sent.append(a) or True
    left = {"lm": pose(dx=-.15)}
    run_for = two_hands(rt, left)
    run_for(.2, lambda: pose(dx=-.15))
    run_for(.6, lambda: pose(dx=-.15, pinched=True))
    run_for(.1, lambda: pose(dx=-.15))
    log = rt.mouse.event_log
    assert rt.speed_dial.active and not any(e.startswith("youtube:yt_speed") for e in log)   # opening sends nothing
    start = time.perf_counter()
    run_for(.6, lambda: pose(min(30.0, (time.perf_counter() - start) * 120), dx=-.15))
    # the first step puts YouTube on the dial's speed from its floor (7 down to .25x, up to it), each next one more up
    assert log.count("youtube:yt_speed_down") == 7
    assert rt.speed_dial.speed() == 1.5 and log.count("youtube:yt_speed_up") == 5 and rt._yt_rate == 1.5
    assert sent == []                                            # no swipe while the dial has the hand
    run_for(1.0, lambda: None)                                   # the hand out of view: the gauge stays on the screen
    assert rt.speed_dial.active and rt._snap.other_hand and rt._snap.other_hand["dial"]
    run_for(.4, lambda: fist(30, dx=-.15))
    assert not rt.speed_dial.active and rt._yt_rate == 1.5
    keys = len([e for e in log if e.startswith("youtube:yt_speed")])
    run_for(.6, lambda: pose(-30, dx=-.15, pinched=True))        # opened again with the hand elsewhere: 1.5x, nothing sent
    run_for(.1, lambda: pose(-30, dx=-.15))
    assert rt.speed_dial.active and rt.speed_dial.speed() == 1.5
    assert len([e for e in log if e.startswith("youtube:yt_speed")]) == keys


def test_only_an_ok_sign_pinch_opens_it():
    """That day's left hand touched thumb to index 2.1 times a minute without meaning a tap: only the OK-sign pinch counts."""
    fist_tap = [[Point3D(p.x, p.y, p.z) for p in FIST] for _ in range(18)]
    for lm in fist_tap[:16]:
        lm[4] = Point3D(lm[8].x, lm[8].y + .005, lm[8].z)
    d = SpeedDial()
    ev, t = run(d, fist_tap)
    assert ev == [] and not d.active
    ev, t = run(d, tap(), t)
    assert d.active


def test_the_dial_runs_from_three_quarters_to_double_speed():
    """2026-11-12: "배속은 0.75~2.5까지" - YouTube's keys stop at 2x, so .75 .. 2."""
    d = SpeedDial()
    ev, t = run(d, tap())
    ev, t = run(d, [pose(a) for a in range(0, 151, 3)], t)       # far clockwise
    assert d.speed() == 2.0 and ev.count("faster") == 4
    ev, t = run(d, [pose(a) for a in range(150, -91, -3)], t)    # far the other way
    assert d.speed() == .75
    assert d.view()["min"] == -1 and d.view()["max"] == 4
    d.steps = 2
    assert d.sync_keys() == (7, 5)                               # 2x -> .25x, then up to 1.5x


def pose_finger(deg=0.0, finger=None, dx=0.0):
    """pose() with the thumb tip on `finger`'s tip (8 index, 12 middle)."""
    pts = pose(deg, dx=dx)
    if finger:
        tip = pts[finger]
        pts[4] = Point3D(tip.x, tip.y + .005, tip.z)
    return pts


def test_a_thumb_middle_pinch_opens_the_seek_dial_and_the_index_one_the_speed_one():
    """2026-11-12: "엄지중지 pinch하면 이제 같은 호밸브에 -+5 -+10 씩 조절"."""
    seek, speed = SpeedDial("seek"), SpeedDial()
    frames = [pose_finger(0, 12)] * 16 + [pose()] * 2
    t = 0.0
    for lm in frames:
        a, b = seek.step(t, lm), speed.step(t, lm)
        t += 1 / 30
    assert seek.active and not speed.active
    ev, t = run(seek, [pose(a) for a in range(0, 26, 3)], t)
    assert ev == ["faster", "faster"] and seek.view()["label"] == "+10초"
    assert seek.view()["lo_text"] == "-20초" and seek.view()["hi_text"] == "+20초"
    ev, t = run(seek, [fist(24)] * FIST_FRAMES, t)
    assert ev == ["off"] and not seek.active


def test_the_seek_dial_is_set_by_turning_and_sent_by_each_thumb_index_pinch(tmp_path):
    """2026-11-12: "엄지중지 밸브 상태에서 특정 숫자에 놓고 엄지검지를 pinch하면 해당 숫자만큼 빨리감기, 뒤로감기 …
    연속으로 pinch하면 연속으로 실행 … 엄지검지했다고 곧바로 배속 제어로 넘어가는게 아니라"."""
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.paused = False
    left = {"lm": pose(dx=-.15)}
    run_for = two_hands(rt, left)

    def pinch_index(deg):
        run_for(.15, lambda: pose_finger(deg, 8, dx=-.15))
        run_for(.12, lambda: pose(deg, dx=-.15))

    run_for(.2, lambda: pose(dx=-.15))
    run_for(.6, lambda: pose_finger(0, 12, dx=-.15))                                     # held: opens
    run_for(.1, lambda: pose(dx=-.15))
    assert rt.seek_dial.active and not rt.speed_dial.active
    start = time.perf_counter()
    run_for(.5, lambda: pose(min(38.0, (time.perf_counter() - start) * 160), dx=-.15))   # set to +15 s
    run_for(.8, lambda: pose(38.0, dx=-.15))                                             # resting sends nothing
    log = rt.mouse.event_log
    assert rt.seek_dial.seconds() == 15 and not any(e.startswith("youtube:yt_forward") for e in log)
    pinch_index(38.0)                                                                    # a pinch: 15 s forward
    assert log.count("youtube:yt_forward_10") == 1 and log.count("youtube:yt_forward_5") == 1
    assert rt.seek_dial.active and not rt.speed_dial.active                              # still the seek dial
    pinch_index(38.0)                                                                    # again: 15 s more
    assert log.count("youtube:yt_forward_10") == 2 and log.count("youtube:yt_forward_5") == 2
    run_for(.6, lambda: pose_finger(38.0, 12, dx=-.15))                                  # its own pinch: stays
    run_for(.1, lambda: pose(38.0, dx=-.15))
    assert rt.seek_dial.active
    run_for(.4, lambda: fist(38.0, dx=-.15))                                             # a fist closes it
    assert not rt.seek_dial.active
    run_for(.7, lambda: pose(0.0, dx=-.15))
    pinch_index(0.0)
    assert not rt.speed_dial.active                                                      # a short pinch opens nothing
    run_for(.6, lambda: pose_finger(0.0, 8, dx=-.15))
    run_for(.1, lambda: pose(0.0, dx=-.15))
    assert rt.speed_dial.active


def test_the_seek_dial_reads_where_the_hand_points_round_eleven_o_clock():
    """2026-11-12: "손을 위로 올렸을때 11시방향이 가운데 점이 되게 … 오른쪽으로 손목을 돌리기가 힘들다"."""
    seek = SpeedDial("seek")
    t = 0.0
    for lm in [pose_finger(40, 12)] * 16 + [pose(40)] * 2:
        seek.step(t, lm)
        t += 1 / 30
    assert seek.active and seek.view()["center"] == CENTER_TILT
    assert seek.view()["label"] == "+15초" and seek.view()["hi_text"] == "+20초"   # 40 degrees = 3 steps of 12
    ev, t = run(seek, [pose(a) for a in range(40, 81, 4)], t)
    assert seek.view()["label"] == "+20초"


def test_a_short_pinch_does_not_open_a_dial_only_a_held_one():
    """2026-11-12 (user's choice): a tap opened the seek dial 1.6 times a minute in passing; now the pinch is held .4 s."""
    d = SpeedDial()
    ev, t = run(d, short_tap() * 3)
    assert "on" not in ev and not d.active and ev.count("tap") == 3
    ev, t = run(d, tap(), t)
    assert ev == ["on"] and d.active
    ev, t = run(d, short_tap(), t)                               # a short one while open: a "tap", the dial stays
    assert ev == ["tap"] and d.active


def test_the_seek_gauge_says_the_real_jump_when_youtube_runs_faster():
    """YouTube's seek keys move their seconds x the playback speed (youtube.com, 2026-11-12: L = 10 s at 1x, 20 s at 2x)."""
    d = SpeedDial("seek")
    d.active, d.steps, d.origin = True, 2, 0
    assert d.view()["label"] == "+10초" and "실제" not in d.view()["caption"]
    d.rate_hint = 1.5
    assert d.view()["label"] == "+10초" and "1.5배속이라 실제 +15초" in d.view()["caption"]


def test_the_seek_dial_fires_on_every_pinch_and_a_held_one_does_not_switch_dials(tmp_path):
    """2026-11-12: "엄지중지로 빨리감기뒤로감기할때 연속으로 할수가 없다. 몇번 엄지검지로 pinch하면 엄지중지 감기 바가
    사라짐"."""
    from tests.test_qt_runtime import runtime
    rt = runtime(tmp_path)
    rt.paused = False
    left = {"lm": pose(dx=-.15)}
    run_for = two_hands(rt, left)
    run_for(.2, lambda: pose(14, dx=-.15))
    run_for(.6, lambda: pose_finger(14, 12, dx=-.15))           # the seek dial at +5 s (14 degrees = 1 step)
    run_for(.1, lambda: pose(14, dx=-.15))
    assert rt.seek_dial.active and rt.seek_dial.seconds() == 5
    for hold in (.15, .7, .2, 1.0, .15):                         # quick and long pinches, one after another
        run_for(hold, lambda: pose_finger(14, 8, dx=-.15))
        run_for(.15, lambda: pose(14, dx=-.15))
    assert rt.seek_dial.active and not rt.speed_dial.active
    assert rt.mouse.event_log.count("youtube:yt_forward_5") == 5


def test_turning_to_the_left_is_faster_and_forward():
    """2026-11-12: "왼손 다이얼 컨트롤 값 둘다를 좌우를 바꿔줘. 자주 쓰는 값을 왼쪽으로 두는게 맞는거 같다"."""
    assert DIRECTION == -1
    d = SpeedDial()
    ev, t = run(d, [pose()] * 5 + tap())
    left = [pose(a) for a in range(0, 26, 3)]                     # more = counter-clockwise on the screen
    assert _tilt(left[-1], 1280, 720) < _tilt(left[0], 1280, 720)
    ev, t = run(d, left, t)
    assert ev == ["faster", "faster"] and d.view()["dir"] == -1
    seek = SpeedDial("seek")
    ev, t = run(seek, [pose_finger(-30, 12)] * 16 + [pose(-30)] * 2)   # clockwise of 11 o'clock: back
    assert seek.active and seek.seconds() < 0
