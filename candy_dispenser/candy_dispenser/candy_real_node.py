"""Машина состояний + настоящая рука. Запуск: ros2 run candy_dispenser candy_real_node [--no-viewer]

Кнопки в терминале, где запущена нода (нажимать без Enter):
  1 2 3  - из какого диспенсера брать конфету      n - следующий диспенсер
  w - помахать   g - дать конфету   i - прервать
"""
import select
import sys
import threading
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor

from candy_dispenser.candy_sm import Bus, Ctx, E, build
from candy_dispenser.candy_sm_node import CommandListener
from candy_dispenser.ros_player import RosClipPlayer

HELP = "кнопки: 1/2/3 - диспенсер, n - следующий, w - помахать, g - дать конфету, i - прервать"


class Keyboard:
    """Читает одиночные нажатия из терминала (без Enter). Ctrl+C продолжает работать."""

    def __init__(self, ctx: Ctx, bus: Bus) -> None:
        self.ctx, self.bus = ctx, bus
        self._done = threading.Event()
        self._thread = None
        self._saved = None

    def start(self) -> None:
        if not sys.stdin.isatty():
            print("клавиатура отключена: нода запущена не из терминала")
            return
        import termios
        import tty
        fd = sys.stdin.fileno()
        self._saved = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(HELP)

    def stop(self) -> None:
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._saved is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved)
            self._saved = None

    def _loop(self) -> None:
        events = {"w": E.WAVE, "g": E.GIVE_CANDY, "i": E.INTERRUPT}
        while not self._done.is_set():
            if not select.select([sys.stdin], [], [], 0.2)[0]:
                continue
            key = sys.stdin.read(1).lower()
            if key.isdigit():
                self.ctx.select_dispenser(key)
            elif key == "n":
                self.ctx.select_dispenser("next")
            elif key in events:
                self.bus.post(events[key])


def main() -> None:
    rclpy.init()
    bus = Bus()
    player = RosClipPlayer(bus)
    ctx = Ctx(player, bus)
    listener = CommandListener(bus)

    ex = MultiThreadedExecutor()
    ex.add_node(player)
    ex.add_node(listener)
    threading.Thread(target=ex.spin, daemon=True).start()

    def watch_shutdown() -> None:
        while rclpy.ok():
            time.sleep(0.1)
        ctx.request_stop()
    threading.Thread(target=watch_shutdown, daemon=True).start()

    keyboard = Keyboard(ctx, bus)
    keyboard.start()

    sm = build(ctx)
    viewer = None
    if "--no-viewer" not in sys.argv:
        from yasmin_viewer import YasminViewerPub
        viewer = YasminViewerPub(sm, "CANDY_DISPENSER")
    try:
        print("машина остановлена:", sm())
    except KeyboardInterrupt:
        ctx.request_stop()
    finally:
        keyboard.stop()
        player.stop()
        if viewer is not None:
            viewer.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()