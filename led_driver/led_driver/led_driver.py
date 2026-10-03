#!/usr/bin/env python3
"""ROS2-нода для прошивки led_driver (режимы и яркость ленты по Serial).

Топики (относительно имени ноды, по умолчанию /led_driver/...):
  ~/mode              std_msgs/String  (подписка) название или номер режима:
                                       "rainbow", "dot", "azure", "green", "orange", "off"
                                       или "1".."6"
  ~/brightness        std_msgs/UInt8   (подписка) яркость 0..255
  ~/status            std_msgs/String  (публикация, latched) текущий режим, например "GREEN"
  ~/brightness_state  std_msgs/UInt8   (публикация, latched) текущая яркость

Параметры:
  port        (str)  /dev/ttyUSB0
  baud        (int)  115200
  brightness  (int)  -1 — не трогать; 0..255 — выставить при запуске
"""

import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String, UInt8

import serial

# Порядок совпадает с прошивкой: номер режима = индекс + 1
MODES = ('RAINBOW', 'DOT', 'AZURE', 'GREEN', 'ORANGE', 'OFF')


def parse_state(payload):
    """'GREEN 120' -> ('GREEN', 120). Яркость None, если её нет в ответе."""
    parts = payload.split()
    mode = parts[0] if parts else ''
    bright = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return mode, bright


class LedSelectorLink:
    """Уровень протокола, без ROS — можно использовать и в обычном скрипте.

    Все команды возвращают (ok, mode, brightness) при успехе
    или (False, текст ошибки, None) при неудаче.
    """

    def __init__(self, port, baud=115200, timeout=0.5, retries=3, logger=None):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.retries = retries
        self.log = logger
        self.ser = None
        self.lock = threading.Lock()

    # ---------- соединение ----------
    def open(self, ready_wait=3.0):
        """Открыть порт и дождаться загрузки платы. Возвращает (mode, brightness) или None."""
        self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
        # Открытие порта перезагружает Nano (и часто ESP32).
        # При старте плата пишет READY, список режимов и "OK RAINBOW 80".
        state = None
        deadline = time.time() + ready_wait
        while time.time() < deadline:
            line = self._readline()
            if line.startswith('OK '):
                state = parse_state(line[3:])
                break
        self.ser.reset_input_buffer()
        if state is None:
            if self.log:
                self.log.warn('Плата не прислала стартовое состояние, спрашиваю STATUS')
            ok, mode, bright = self.status()
            state = (mode, bright) if ok else None
        return state

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    # ---------- команды ----------
    def set_mode(self, mode):
        """mode — название или номер режима."""
        return self._send(str(mode).strip().upper())

    def set_brightness(self, value):
        value = int(value)
        if not 0 <= value <= 255:
            return False, f'яркость вне диапазона 0..255: {value}', None
        return self._send(f'BRIGHT {value}')

    def status(self):
        return self._send('STATUS')

    # ---------- внутреннее ----------
    def _readline(self):
        return self.ser.readline().decode(errors='ignore').strip()

    def _wait_reply(self):
        """Ждём строку OK/ERR, пропуская прочий вывод (список режимов и т.п.)."""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            line = self._readline()
            if line.startswith('OK') or line.startswith('ERR'):
                return line
        return ''

    def _send(self, command):
        last = ''
        with self.lock:
            for _ in range(self.retries):
                self.ser.reset_input_buffer()
                # Пустая строка "будит" плату: она перестаёт обновлять ленту
                # на время приёма, и байты команды не теряются
                self.ser.write(b'\n')
                time.sleep(0.005)
                self.ser.write((command + '\n').encode('ascii'))
                last = self._wait_reply()
                if last.startswith('OK'):
                    mode, bright = parse_state(last[2:].strip())
                    return True, mode, bright
        return False, last or 'TIMEOUT', None


def normalize_mode(text):
    """Привести ввод к названию режима; None, если такого нет."""
    t = text.strip().upper()
    if t.isdigit() and 1 <= int(t) <= len(MODES):
        return MODES[int(t) - 1]
    return t if t in MODES else None


class LedSelectorNode(Node):

    def __init__(self):
        super().__init__('led_driver')
        port = self.declare_parameter('port', '/dev/ttyUSB0').value
        baud = self.declare_parameter('baud', 115200).value
        start_brightness = self.declare_parameter('brightness', -1).value

        # latched: кто подпишется позже, сразу получит текущее значение
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(String, '~/status', qos)
        self.bright_pub = self.create_publisher(UInt8, '~/brightness_state', qos)

        self.link = LedSelectorLink(port, baud, logger=self.get_logger())
        state = self.link.open()
        self.get_logger().info(f'Подключено к {port} @ {baud}')
        if state:
            self.publish_state(*state)

        if 0 <= start_brightness <= 255:
            self.apply('яркость', self.link.set_brightness, start_brightness)

        self.create_subscription(String, '~/mode', self.on_mode, 10)
        self.create_subscription(UInt8, '~/brightness', self.on_brightness, 10)

    def publish_state(self, mode, bright):
        if mode:
            self.status_pub.publish(String(data=mode))
        if bright is not None:
            self.bright_pub.publish(UInt8(data=bright))

    def apply(self, what, func, arg):
        """Выполнить команду, залогировать и опубликовать новое состояние."""
        try:
            ok, mode, bright = func(arg)
        except serial.SerialException as e:
            self.get_logger().error(f'Ошибка порта: {e}', throttle_duration_sec=5.0)
            return
        if ok:
            self.get_logger().info(f'Режим: {mode}, яркость: {bright}')
            self.publish_state(mode, bright)
        else:
            self.get_logger().error(f'Не удалось изменить {what} ({arg}): {mode}')

    # ---------- колбэки ----------
    def on_mode(self, msg):
        mode = normalize_mode(msg.data)
        if mode is None:
            self.get_logger().warn(
                f'Неизвестный режим "{msg.data}". Доступны: '
                + ', '.join(f'{i + 1}/{m.lower()}' for i, m in enumerate(MODES)))
            return
        self.apply('режим', self.link.set_mode, mode)

    def on_brightness(self, msg):
        self.apply('яркость', self.link.set_brightness, msg.data)

    def destroy_node(self):
        self.link.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = LedSelectorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
