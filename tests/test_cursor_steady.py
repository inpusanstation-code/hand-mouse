"""2026-11-12 ("가상손 떨림을 줄임과 동시에 실시간 반응도"): the cursor filter opens more with speed, and a still hand's wobble
under BoxMapper.DEAD_PX is not shown. Numbers: src/virtual_hand.py RESPONSE, docs/virtual-hand.md."""
from types import SimpleNamespace as P

from src.virtual_hand import BoxMapper

BOX = (.2, .15, .8, .85)


def hand(nx, ny):
    return [P(x=BOX[0] + nx * (BOX[2] - BOX[0]), y=BOX[1] + ny * (BOX[3] - BOX[1]))] * 21


def test_a_still_hand_wobble_under_the_dead_zone_does_not_move_the_cursor():
    m = BoxMapper()
    t = 0.0
    for _ in range(30):                                   # settle
        t += 1 / 30
        m.target(hand(.5, .5), BOX, now=t)
    settled = m.pos
    for i in range(60):                                   # +-0.5 px wobble on 1920
        t += 1 / 30
        m.target(hand(.5 + (.5 / 1920) * (1 if i % 2 else -1), .5), BOX, now=t)
        assert m.pos == settled


def test_a_real_move_is_followed_quickly():
    m = BoxMapper()
    t, x = 0.0, .3
    for _ in range(30):
        t += 1 / 30
        m.target(hand(x, .5), BOX, now=t)
    for _ in range(15):                                   # 600 px/s on 1920
        t += 1 / 30
        x += 20 / 1920
        m.target(hand(x, .5), BOX, now=t)
    behind_ms = (x - m.pos[0]) * 1920 / 600 * 1000
    assert 0 <= behind_ms < 15


def test_the_edge_snap_is_only_at_the_box_edge():
    m = BoxMapper()
    t = 0.0
    for _ in range(30):
        t += 1 / 30
        m.target(hand(.5, .5), BOX, now=t)
    t += 1 / 30
    m.target(hand(.5 + 2.5 / 1920, .5), BOX, now=t)       # a 2.5 px wobble: past the dead zone, filtered, not raw
    assert abs(m.pos[0] - .5) * 1920 < 2.0
    for _ in range(40):                                   # at the edge it lands exactly on it
        t += 1 / 30
        m.target(hand(1.2, .5), BOX, now=t)
    assert m.pos[0] == 1.0


def test_a_still_drawn_joint_does_not_wobble_and_a_moving_one_follows():
    from src.virtual_hand import ViewSmoother
    v = ViewSmoother()
    base = [float(i) for i in range(42)]
    t = 0.0
    for _ in range(30):
        t += 1 / 30
        v(base, t)
    settled = v(base, t + 1 / 30)
    t += 1 / 30
    for i in range(60):                                   # +-1 px wobble on every joint
        t += 1 / 30
        w = 1.0 if i % 2 else -1.0
        assert v([p + w for p in base], t) == settled
    tip = list(base)
    for _ in range(15):                                   # the index tip moves 600 px/s
        t += 1 / 30
        tip[16] += 20
        out = v(tip, t)
    assert (tip[16] - out[16]) / 600 * 1000 < 15          # ms behind
    assert out[0] == settled[0]                           # the still wrist stays put
