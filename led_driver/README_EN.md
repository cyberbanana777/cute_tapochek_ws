# led_driver

[Русская версия](README.md)

ROS 2 driver for an addressable LED strip. The node talks over serial to a board (Arduino Nano or ESP32) running the [`led_controller_arduino`](../led_controller_arduino/README_EN.md) firmware and lets you control the strip mode and brightness through topics.

The board communication protocol is specified in the [top-level README](../README_EN.md#led-strip-control-protocol).

## Features

- Switch strip modes by name or number.
- Set brightness in the 0–255 range.
- Publish the actual strip state on latched topics: a subscriber immediately gets the last value.
- Every command is acknowledged by the board and retried automatically on link errors.
- `LedSelectorLink` protocol class with no ROS dependency, usable from plain scripts.

## Node `led_driver`

Started by the `led_driver` executable. On start-up it opens the port, waits up to 3 s for the board to boot, then publishes the board's start-up state. If the board did not send it by itself, the node requests `STATUS`.

Only state acknowledged by the board with `OK` is published. If a command fails, the state topics do not change.

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `port` | string | `/dev/ttyUSB0` | Serial port of the board |
| `baud` | int | `115200` | Baud rate. Must match `BAUD` in the firmware |
| `brightness` | int | `-1` | Brightness set by the node at start-up. `-1` — leave unchanged |

### Subscriptions

| Topic | Type | Description |
|-------|------|-------------|
| `/led_driver/mode` | `std_msgs/String` | Mode name (`rainbow`, `dot`, `azure`, `green`, `orange`, `off`; case-insensitive) or its number `1`–`6` |
| `/led_driver/brightness` | `std_msgs/UInt8` | Brightness 0–255 |

### Publications

| Topic | Type | QoS | Description |
|-------|------|-----|-------------|
| `/led_driver/status` | `std_msgs/String` | TRANSIENT_LOCAL, depth 1 | Current mode, e.g. `GREEN` |
| `/led_driver/brightness_state` | `std_msgs/UInt8` | TRANSIENT_LOCAL, depth 1 | Current brightness |

To receive the last value on subscription, the subscriber must use `TRANSIENT_LOCAL` as well (see "Useful checks").

### Modes

| # | Name | Behaviour |
|---|------|-----------|
| 1 | `rainbow` | Running rainbow |
| 2 | `dot` | A green dot with a tail runs in a loop |
| 3 | `azure` | Turquoise-azure, LEDs light up one by one |
| 4 | `green` | Green, LEDs light up one by one |
| 5 | `orange` | Orange, the whole strip at once |
| 6 | `off` | Strip is off |

The mode list is the `MODES` tuple in `led_driver/led_driver.py`. Its contents and order must match the `MODE_NAMES` array in the firmware.

### Error handling

- The node rejects unknown modes itself: nothing is sent to the board, and a warning with the list of available modes is logged.
- If the board does not reply `OK` within 0.5 s, the command is retried, up to 3 attempts in total. After that an error is logged.
- If the port cannot be opened at start-up, the node exits with an exception.
- If the port disappears at runtime (e.g. the cable is unplugged), the error is logged at most once per 5 s. There is no automatic reconnection: plug the board back in and restart the node.

## Using without ROS

The `LedSelectorLink` class implements the protocol and does not import ROS:

```python
from led_driver.led_driver import LedSelectorLink

link = LedSelectorLink('/dev/ttyUSB0')
print(link.open())                 # ('RAINBOW', 80) — start-up state
print(link.set_mode('green'))      # (True, 'GREEN', 80)
print(link.set_mode(2))            # (True, 'DOT', 80)
print(link.set_brightness(150))    # (True, 'DOT', 150)
print(link.status())               # (True, 'DOT', 150)
link.close()
```

Every command returns `(ok, mode, brightness)`. On failure it returns `(False, error text, None)`, where the text is the board's last reply (`ERR ...`) or `TIMEOUT`.

| Constructor argument | Default | Description |
|----------------------|---------|-------------|
| `port` | — | Serial port |
| `baud` | `115200` | Baud rate |
| `timeout` | `0.5` | Reply timeout per attempt, s |
| `retries` | `3` | Number of attempts |
| `logger` | `None` | Logger with a `warn` method (e.g. a ROS node logger) |

## Launch

```bash
ros2 run led_driver led_driver --ros-args -p port:=/dev/ttyUSB0
ros2 run led_driver led_driver --ros-args -p port:=/dev/ttyUSB0 -p brightness:=60
```

Access to the port without `sudo` is granted by the `dialout` group:

```bash
sudo usermod -aG dialout $USER    # then log out and back in
```

An Arduino Nano (especially CH340 clones) usually shows up as `/dev/ttyUSB0`, an ESP32 as `/dev/ttyUSB0` or `/dev/ttyACM0`. With several devices connected, prefer a persistent name from `/dev/serial/by-id/`.

## Useful checks

```bash
# Available ports
ls /dev/ttyUSB* /dev/ttyACM* /dev/serial/by-id/

# Switch mode
ros2 topic pub --once /led_driver/mode std_msgs/msg/String "{data: azure}"
ros2 topic pub --once /led_driver/mode std_msgs/msg/String "{data: '2'}"

# Change brightness
ros2 topic pub --once /led_driver/brightness std_msgs/msg/UInt8 "{data: 150}"

# Current state (latched)
ros2 topic echo --qos-durability transient_local /led_driver/status
ros2 topic echo --qos-durability transient_local /led_driver/brightness_state
```

If the node cannot reach the board, test the board without ROS: open the Arduino IDE Serial Monitor at 115200 baud and send `STATUS`. The port must be free for that: stop the node.

## Dependencies

- ROS 2:
  - `rclpy`
  - `std_msgs`
- System:
  - `python3-serial` (pyserial)
- A board running the [`led_controller_arduino`](../led_controller_arduino/README_EN.md) firmware.

## Version

**0.1.0** — first version: strip modes and brightness, latched state topics, command retries on link errors.
