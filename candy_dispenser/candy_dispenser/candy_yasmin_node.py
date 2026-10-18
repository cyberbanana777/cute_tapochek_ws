"""ROS 2-обёртка: топик команд, запуск машины, вьюер YASMIN (необязательно).

Команды с консоли (из другого терминала):
  ros2 topic pub --once /dispenser/command std_msgs/msg/String "{data: wave}"
  ros2 topic pub --once /dispenser/command std_msgs/msg/String "{data: give_candy}"
  ros2 topic pub --once /dispenser/command std_msgs/msg/String "{data: interrupt}"

Запуск без вьюера: ros2 run candy_dispenser candy_yasmin_node --no-viewer
"""
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from candy_dispenser.candy_sm import Bus, Ctx, E, FakeClipPlayer, build

COMMAND_BY_TEXT = {"wave": E.WAVE, "give_candy": E.GIVE_CANDY, "interrupt": E.INTERRUPT}


class CommandListener(Node):
    """Превращает строки из топика /dispenser/command в события шины."""

    def __init__(self, bus: Bus) -> None:
        super().__init__("candy_command_listener")
        self.bus = bus
        self.create_subscription(String, "/dispenser/command", self.on_command, 10)

    def on_command(self, msg: String) -> None:
        ev = COMMAND_BY_TEXT.get(msg.data.strip().lower())
        if ev is None:
            self.get_logger().warn(f"неизвестная команда: {msg.data!r}")
        else:
            self.bus.post(ev)


def main() -> None:
    rclpy.init()
    bus = Bus()
    ctx = Ctx(FakeClipPlayer(bus), bus)           # потом здесь будет настоящий ClipPlayer
    listener = CommandListener(bus)

    # ROS крутится в фоне, а машина работает в главном потоке
    threading.Thread(target=rclpy.spin, args=(listener,), daemon=True).start()

    # Ctrl+C: rclpy гасит себя, мы замечаем это и просим машину остановиться
    def watch_shutdown() -> None:
        while rclpy.ok():
            time.sleep(0.1)
        ctx.request_stop()
    threading.Thread(target=watch_shutdown, daemon=True).start()

    sm = build(ctx)
    viewer = None
    if "--no-viewer" not in sys.argv:
        from yasmin_viewer import YasminViewerPub
        viewer = YasminViewerPub(sm, "CANDY_DISPENSER")   # проверь порядок аргументов в своей версии

    try:
        print("машина остановлена:", sm())
    except KeyboardInterrupt:
        ctx.request_stop()
    finally:
        if viewer is not None:
            viewer.shutdown()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()