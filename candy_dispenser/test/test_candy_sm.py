"""Тесты логики (python3 test_candy_sm.py).

Если настоящий yasmin не установлен, подставляется маленькая заглушка с тем же
интерфейсом (State, StateMachine, add_state, set_start_state, sm()). Заглушка
проверяет, что каждый исход каждого состояния куда-то ведёт, как и настоящая.
С установленным yasmin тесты идут на настоящей библиотеке.
"""
import random
import sys
import threading
import time
import types

try:
    import yasmin  # noqa: F401
    USING_STUB = False
except ImportError:
    USING_STUB = True
    stub = types.ModuleType("yasmin")

    class State:
        def __init__(self, outcomes):
            self._outcomes = list(outcomes)

        def is_canceled(self):
            return False

        def __call__(self, blackboard=None):
            out = self.execute(blackboard)
            assert out in self._outcomes, f"исход {out!r} не объявлен: {self._outcomes}"
            return out

    class StateMachine(State):
        def __init__(self, outcomes, handle_sigint=False):
            super().__init__(outcomes)
            self._states, self._start = {}, None

        def add_state(self, name, state, transitions=None, remappings=None):
            self._states[name] = (state, dict(transitions or {}))
            if self._start is None:
                self._start = name

        def set_start_state(self, name):
            self._start = name

        def validate(self):
            for name, (st, tr) in self._states.items():
                for o in st._outcomes:
                    assert o in tr, f"{name}: исход {o!r} никуда не ведёт"
                for o, target in tr.items():
                    assert target in self._states or target in self._outcomes, \
                        f"{name}: цель {target!r} не существует"

        def execute(self, blackboard):
            self.validate()
            cur = self._start
            while True:
                st, tr = self._states[cur]
                target = tr[st(blackboard)]
                if target in self._outcomes:
                    return target
                cur = target

    stub.State, stub.StateMachine = State, StateMachine
    sys.modules["yasmin"] = stub

from candy_dispenser.candy_sm import Bus, Config, Ctx, E, FakeClipPlayer, build  # noqa: E402


def wait_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class Rig:
    def __init__(self, bored=(60.0, 60.0), phrase_s=0.05):
        self.log = []
        self.bus = Bus()
        self.player = FakeClipPlayer(self.bus, clip_s=0.1, home_s=0.15,
                                     phrase_s=phrase_s, log=self.log.append)
        cfg = Config(head_period=0.3, bored_range=bored, cooldown_s=0.2, poll_s=0.01)
        self.ctx = Ctx(self.player, self.bus, cfg, rng=random.Random(0), log=self.log.append)
        self.sm = build(self.ctx)
        self.result = []
        self.thread = threading.Thread(target=lambda: self.result.append(self.sm()), daemon=True)
        self.thread.start()

    def trace(self):
        return [l[3:] for l in self.log if l.startswith("->")]

    def reached(self, state, count=1, timeout=5.0):
        return wait_until(lambda: self.trace().count(state) >= count, timeout)

    def close(self):
        self.ctx.request_stop()
        self.thread.join(timeout=3)
        assert self.result == ["stopped"], self.result


def test_give_candy_full_cycle():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.GIVE_CANDY)
    assert r.reached("WATCH", count=2)
    assert r.trace()[:7] == ["WATCH", "STOP", "TAKE", "GIVE", "LEAVE", "COOLDOWN", "WATCH"], r.trace()
    r.close()


def test_wave_full_cycle():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.WAVE)
    assert r.reached("WATCH", count=2)
    assert r.trace()[:5] == ["WATCH", "STOP", "GREET", "COOLDOWN", "WATCH"], r.trace()
    r.close()


def test_bored_and_return():
    r = Rig(bored=(0.5, 0.5))
    assert r.reached("WATCH", count=2)
    assert r.trace()[:3] == ["WATCH", "BORED", "WATCH"], r.trace()
    r.close()


def test_wave_from_bored_has_phrase():
    r = Rig(bored=(0.5, 0.5))
    assert r.reached("BORED")
    r.bus.post(E.WAVE)
    assert r.reached("GREET")
    assert any("oh_you_came" in l for l in r.log)
    r.close()


def test_no_phrase_from_watch():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.WAVE)
    assert r.reached("GREET")
    assert not any("oh_you_came" in l for l in r.log)
    r.close()


def test_stop_waits_for_long_phrase():
    r = Rig(bored=(0.5, 0.5), phrase_s=0.6)       # фраза длиннее возврата домой
    assert r.reached("BORED")
    r.bus.post(E.WAVE)
    assert r.reached("STOP")
    time.sleep(0.3)                               # рука уже дома, фраза ещё идёт
    assert r.trace()[-1] == "STOP", r.trace()
    assert r.reached("GREET")
    r.close()


def test_interrupt_during_give():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.GIVE_CANDY)
    assert r.reached("GIVE")
    r.bus.post(E.INTERRUPT)
    assert r.reached("COOLDOWN")
    assert r.reached("WATCH", count=2)
    assert "LEAVE" not in r.trace(), r.trace()
    r.close()


def test_commands_ignored_when_busy():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.GIVE_CANDY)
    assert r.reached("TAKE")
    r.bus.post(E.WAVE)
    assert r.reached("WATCH", count=2)
    assert any("занято" in l for l in r.log)
    assert "GREET" not in r.trace(), r.trace()
    r.close()


def test_clip_failure_goes_to_cooldown():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.GIVE_CANDY)
    assert r.reached("TAKE")
    r.bus.post(E.CLIP_FAILED)
    assert r.reached("COOLDOWN")
    assert "GIVE" not in r.trace(), r.trace()
    r.close()


def test_interrupt_in_cooldown_restarts_return():
    r = Rig()
    assert r.reached("WATCH")
    r.bus.post(E.WAVE)
    assert r.reached("COOLDOWN")
    r.bus.post(E.INTERRUPT)
    assert wait_until(lambda: sum("прерывание в COOLDOWN" in l for l in r.log) == 1)
    assert r.reached("WATCH", count=2)
    r.close()


def test_quit_ends_machine():
    r = Rig()
    assert r.reached("WATCH")
    r.close()


if __name__ == "__main__":
    print("yasmin:", "ЗАГЛУШКА" if USING_STUB else "настоящий")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok ", t.__name__)
    print(f"всего: {len(tests)}")