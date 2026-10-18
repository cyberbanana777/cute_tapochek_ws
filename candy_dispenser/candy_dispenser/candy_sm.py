"""Машина состояний раздатчика конфет на YASMIN (ROS 2 Humble).

Версия без зрения и без IK: команды приходят с консоли (топиком), а вместо
движения к ладони проигрываются записанные клипы.

Общая структура файла (блоки идут сверху вниз):
  1. E            - события (что может «прийти» в машину)
  2. Config       - времена и случайные диапазоны
  3. Bus и Ctx    - очередь событий и общий контекст, который видят все состояния
  4. ClipPlayer   - интерфейс «проигрывателя клипов» + поддельная реализация
  5. Состояния    - Step (общая часть), Watch, Bored, Stop, ClipStep, Cooldown
  6. build()      - сборка схемы: какое состояние при каком исходе ведёт куда
"""
from __future__ import annotations

import queue
import random
import threading
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Protocol

from yasmin import State, StateMachine


# ============================================================ 1. СОБЫТИЯ
class E(Enum):
    WAVE = auto()          # команда «помахал»
    GIVE_CANDY = auto()    # команда «протянули ладонь»
    INTERRUPT = auto()     # прерывание с консоли
    CLIP_DONE = auto()     # клип доигран
    CLIP_FAILED = auto()   # клип упал или завис
    HOME_REACHED = auto()  # рука пришла в домашнюю позу
    HOME_FAILED = auto()   # не удалось вернуться домой
    PHRASE_DONE = auto()   # фраза доиграна (или озвучка не удалась)


COMMANDS = (E.WAVE, E.GIVE_CANDY)


# ============================================================ 2. НАСТРОЙКИ
@dataclass
class Config:
    head_period: float = 60.0                 # с, как часто крутит головой
    bored_range: tuple = (10.0, 20.0)       # с, случайное время до «скучает»
    cooldown_s: float = 5.0                   # с, считается от прихода домой
    poll_s: float = 0.05                      # с, как часто состояние проверяет таймеры
    bored_clips: tuple = ("sigh", "sad_remark")
    dispensers: int = 3                       # сколько диспенсеров с конфетами


# ============================================================ 3. ШИНА И КОНТЕКСТ
class Bus:
    """Потокобезопасная очередь событий: в неё пишут все, читают состояния."""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()

    def post(self, ev: E) -> None:
        self._q.put(ev)

    def get(self, timeout: float):
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain(self) -> list:
        """Выбросить всё, что накопилось, и вернуть выброшенное."""
        dropped = []
        while True:
            try:
                dropped.append(self._q.get_nowait())
            except queue.Empty:
                return dropped


class ClipPlayer(Protocol):
    """Интерфейс clip_manager. События приходят в Bus.

    Контракт:
      - play(clip): позже CLIP_DONE или CLIP_FAILED;
      - stop(): останавливает клип и фразу, после него события от них не приходят;
      - go_home(): медленно домой, позже HOME_REACHED или HOME_FAILED
        (если рука уже дома, HOME_REACHED приходит сразу);
      - say(group): позже PHRASE_DONE (и при сбое озвучки тоже, по таймауту);
      - set_led(mode): ничего не ждёт.
    """

    def play(self, clip: str) -> None: ...
    def stop(self) -> None: ...
    def go_home(self) -> None: ...
    def say(self, phrase_group: str) -> None: ...
    def set_led(self, mode: str) -> None: ...


class Ctx:
    """Общий контекст: его получает каждое состояние при создании."""

    def __init__(self, player: ClipPlayer, bus: Bus, cfg: Config | None = None,
                 rng: random.Random | None = None,
                 log: Callable[[str], None] = print) -> None:
        self.p = player
        self.bus = bus
        self.cfg = cfg or Config()
        self.rng = rng or random.Random()
        self.log = log
        self.pending: E | None = None   # какую команду запомнили (WAVE или GIVE_CANDY)
        self.dispenser = 1              # из какого диспенсера сейчас берём конфету
        self.phrase = False             # нужна ли фраза «О! Вы пришли…» в STOP
        self._led: str | None = None
        self._stop = threading.Event()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def set_led(self, mode: str) -> None:
        if mode != self._led:           # не дёргаем ленту, если цвет не менялся
            self._led = mode
            self.p.set_led(mode)

    def select_dispenser(self, arg: str) -> int | None:
        """Выбрать диспенсер: "1".."N" или "next" (по кругу). None - команда непонятна."""
        total = self.cfg.dispensers
        if arg == "next":
            number = self.dispenser % total + 1
        elif arg.isdigit() and 1 <= int(arg) <= total:
            number = int(arg)
        else:
            return None
        self.dispenser = number
        self.log(f"диспенсер: {number}")
        return number

    def wait(self) -> E | None:
        """Ждать следующее событие не дольше poll_s. None - ничего не пришло.

        При остановке программы возвращает INTERRUPT: так любое состояние
        выходит по своему обычному исходу «interrupt».
        """
        if self.stopping:
            return E.INTERRUPT
        return self.bus.get(self.cfg.poll_s)


class FakeClipPlayer:
    """Поддельный проигрыватель: «играет» клипы заданное время и шлёт события."""

    def __init__(self, bus: Bus, clip_s: float = 3.0, home_s: float = 4.0,
                 phrase_s: float = 2.0, log: Callable[[str], None] = print) -> None:
        self.bus, self.log = bus, log
        self.clip_s, self.home_s, self.phrase_s = clip_s, home_s, phrase_s
        self._timers: list[threading.Timer] = []
        self._lock = threading.Lock()

    def _later(self, dt: float, ev: E) -> None:
        t = threading.Timer(dt, self.bus.post, args=(ev,))
        t.daemon = True
        with self._lock:
            self._timers.append(t)
        t.start()

    def play(self, clip: str) -> None:
        self.log(f"  [clip] {clip}")
        self._later(self.clip_s, E.CLIP_DONE)

    def stop(self) -> None:
        self.log("  [stop]")
        with self._lock:
            for t in self._timers:
                t.cancel()
            self._timers.clear()

    def go_home(self) -> None:
        self.log("  [go home, slow]")
        self._later(self.home_s, E.HOME_REACHED)

    def say(self, phrase_group: str) -> None:
        self.log(f"  [say] {phrase_group}")
        self._later(self.phrase_s, E.PHRASE_DONE)

    def set_led(self, mode: str) -> None:
        self.log(f"  [led] {mode}")


# ============================================================ 5. СОСТОЯНИЯ
class Step(State):
    """Общая часть всех состояний.

    У каждого состояния кроме своих исходов есть два общих: «interrupt»
    (прерывание с консоли) и «failed» (сбой клипа). В build() оба ведут
    в COOLDOWN.
    """
    NAME = "?"

    def __init__(self, ctx: Ctx, outcomes: list, universal: bool = True) -> None:
        extra = ["interrupt", "failed"] if universal else []
        super().__init__(list(outcomes) + extra)
        self.ctx = ctx

    def enter(self, led: str | None = None) -> None:
        self.ctx.log(f"-> {self.NAME}")
        if led:
            self.ctx.set_led(led)

    def common(self, ev: E | None) -> str | None:
        """Обработка событий, общих для всех состояний. None - событие не наше."""
        if ev is E.INTERRUPT:
            self.ctx.log("прерывание")
            return "interrupt"
        if ev is E.CLIP_FAILED:
            self.ctx.log(f"сбой клипа в {self.NAME}")
            return "failed"
        if ev in COMMANDS:
            self.ctx.log(f"занято ({self.NAME}): команда {ev.name} проигнорирована")
        return None


class Watch(Step):
    """Наблюдает: раз в head_period крутит головой, через случайное время скучает."""
    NAME = "WATCH"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx, ["command", "bored"])

    def execute(self, blackboard) -> str:
        c = self.ctx
        self.enter("rainbow")
        bored_at = time.monotonic() + c.rng.uniform(*c.cfg.bored_range)
        head_playing = False
        next_head = time.monotonic() + c.cfg.head_period
        while True:
            now = time.monotonic()
            if not head_playing:
                if now >= bored_at:
                    return "bored"
                if now >= next_head:
                    head_playing = True
                    c.p.play("watch_head")
            ev = c.wait()
            if ev in COMMANDS:
                c.pending, c.phrase = ev, False
                return "command"
            if ev is E.CLIP_DONE:
                head_playing = False
                next_head = time.monotonic() + c.cfg.head_period
                continue
            result = self.common(ev)
            if result:
                return result


class Bored(Step):
    """Скучает: один случайный клип, потом обратно в WATCH."""
    NAME = "BORED"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx, ["command", "done"])

    def execute(self, blackboard) -> str:
        c = self.ctx
        self.enter("rainbow")
        c.p.play(c.rng.choice(c.cfg.bored_clips))
        while True:
            ev = c.wait()
            if ev in COMMANDS:
                c.pending, c.phrase = ev, True      # из «скучает» говорим «О! Вы пришли…»
                return "command"
            if ev is E.CLIP_DONE:
                return "done"
            result = self.common(ev)
            if result:
                return result


class Stop(Step):
    """Остановка: стоп клипа, медленно домой; выходим, когда рука дома И фраза доиграна."""
    NAME = "STOP"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx, ["wave", "give"])

    def execute(self, blackboard) -> str:
        c = self.ctx
        self.enter("azure")
        c.p.stop()
        c.p.go_home()
        home_ok = False
        phrase_ok = not c.phrase
        if c.phrase:
            c.p.say("oh_you_came")
        while not (home_ok and phrase_ok):
            ev = c.wait()
            if ev is E.HOME_REACHED:
                home_ok = True
            elif ev is E.PHRASE_DONE:
                phrase_ok = True
            elif ev is E.HOME_FAILED:
                c.log("не удалось вернуться домой")
                return "failed"
            else:
                result = self.common(ev)
                if result:
                    return result
        return "wave" if c.pending is E.WAVE else "give"


class ClipStep(Step):
    """Состояние «сыграть один клип и выйти». Так сделаны GREET, TAKE, GIVE, LEAVE."""

    def __init__(self, ctx: Ctx, name: str, clip: str, led: str) -> None:
        super().__init__(ctx, ["done"])
        self.NAME, self.clip, self.led = name, clip, led

    def execute(self, blackboard) -> str:
        c = self.ctx
        self.enter(self.led)
        clip = self.clip(c) if callable(self.clip) else self.clip
        c.p.play(clip)
        while True:
            ev = c.wait()
            if ev is E.CLIP_DONE:
                return "done"
            result = self.common(ev)
            if result:
                return result


class Cooldown(Step):
    """Кулдаун: стоп, медленно домой, потом пауза cooldown_s с момента прихода."""
    NAME = "COOLDOWN"

    def __init__(self, ctx: Ctx) -> None:
        super().__init__(ctx, ["done", "quit"], universal=False)

    def execute(self, blackboard) -> str:
        c = self.ctx
        self.enter("orange")
        c.p.stop()
        dropped = c.bus.drain()
        if dropped:
            c.log(f"отброшено событий: {len(dropped)}")
        c.p.go_home()
        until = None
        while True:
            if c.stopping:
                c.p.stop()
                return "quit"
            if until is not None and time.monotonic() >= until:
                return "done"
            ev = c.wait()
            if ev is E.HOME_REACHED:
                until = time.monotonic() + c.cfg.cooldown_s
            elif ev is E.HOME_FAILED:
                c.log("не удалось вернуться домой: нужна помощь")
                until = None
            elif ev is E.INTERRUPT:
                c.log("прерывание в COOLDOWN: возврат домой заново")
                c.p.stop()
                c.p.go_home()
                until = None
            elif ev in COMMANDS:
                c.log(f"занято (COOLDOWN): команда {ev.name} проигнорирована")


# ============================================================ 6. СБОРКА СХЕМЫ
def build(ctx: Ctx) -> StateMachine:
    alarm = {"interrupt": "COOLDOWN", "failed": "COOLDOWN"}

    # контейнер «Ожидание»: внутри WATCH и BORED
    waiting = StateMachine(outcomes=["command", "interrupt", "failed"])
    waiting.add_state("WATCH", Watch(ctx), transitions={
        "bored": "BORED", "command": "command",
        "interrupt": "interrupt", "failed": "failed"})
    waiting.add_state("BORED", Bored(ctx), transitions={
        "done": "WATCH", "command": "command",
        "interrupt": "interrupt", "failed": "failed"})
    waiting.set_start_state("WATCH")

    # верхний уровень
    sm = StateMachine(outcomes=["stopped"])
    sm.add_state("WAITING", waiting, transitions={"command": "STOP", **alarm})
    sm.add_state("STOP", Stop(ctx), transitions={"wave": "GREET", "give": "TAKE", **alarm})
    sm.add_state("GREET", ClipStep(ctx, "GREET", "wave", "green"),
                 transitions={"done": "COOLDOWN", **alarm})
    sm.add_state("TAKE", ClipStep(ctx, "TAKE", lambda c: f"take_candy_{c.dispenser}", "green"),
                 transitions={"done": "GIVE", **alarm})
    sm.add_state("GIVE", ClipStep(ctx, "GIVE", "put_on_palm", "green"),
                 transitions={"done": "LEAVE", **alarm})
    sm.add_state("LEAVE", ClipStep(ctx, "LEAVE", "leave", "green"),
                 transitions={"done": "COOLDOWN", **alarm})
    sm.add_state("COOLDOWN", Cooldown(ctx),
                 transitions={"done": "WAITING", "quit": "stopped"})
    sm.set_start_state("WAITING")
    return sm