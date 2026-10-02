# cute_tapochek

[Русская версия](README.md)

An interactive robot built on the SO-ARM101 manipulator. The robot plays back motions recorded in advance from the leader arm and shows its state with an addressable LED strip.

The repository is a set of ROS 2 packages plus microcontroller firmware. The arm bringup itself (ros2_control, controllers, teleoperation) lives in the separate `soarm101` repository and is not part of this one.

## Repository contents

| Directory | Type | Purpose |
|-----------|------|---------|
| [`cute_tapochek_interfaces`](cute_tapochek_interfaces/README_EN.md) | ROS 2, ament_cmake | Action, services and messages of the motion subsystem |
| [`cute_tapochek_motion`](cute_tapochek_motion/README_EN.md) | ROS 2, ament_python | `motion_server` node: motion library, recording from the leader, playback on the follower |
| [`cute_tapochek_gui`](cute_tapochek_gui/README_EN.md) | ROS 2, ament_python | "Motion Studio" rqt plugin for recording and playing motions |
| [`led_driver`](led_driver/README_EN.md) | ROS 2, ament_python | ROS 2 driver of the LED strip: topics → serial commands |
| [`led_controller_arduino`](led_controller_arduino/README_EN.md) | Arduino sketch | Arduino Nano / ESP32 firmware driving a WS2812B strip |
| `motions/` | data | Motion library: one CSV file per motion, kept in git |
| `text_to_voice/` | — | Robot voice, work in progress |

## Architecture

```
 leader arm ──/leader/joint_states──┐
                                    ▼
 Motion Studio (rqt) ──services──► motion_server ──FollowJointTrajectory──► follower arm
 behaviour FSM       ──/play_motion─┘    │   └────GripperCommand──────────► gripper
                                         │
                                         └──/arm_relay/set_enabled──► teleoperation (soarm101)
                                             /gripper_relay/set_enabled

 any node ──/led_selector/mode, /brightness──► led_driver ══USB serial══► board ──► WS2812B strip
```

- `motion_server` owns the motion library. Everything done with it (recording, saving, playback, deletion) goes through its services and action, so the GUI, the terminal and a behaviour state machine all work the same way.
- `led_driver` is a thin bridge between ROS 2 and the strip firmware. All effect logic lives on the microcontroller; the PC only picks the mode and brightness.

## Requirements

- Ubuntu 22.04, ROS 2 Humble.
- The `soarm101` repository with the `soarm101_teleop_pause.patch` patch (the `~/set_enabled` pause service on `arm_relay` and `gripper_relay`) and `open_loop_control: true` for `joint_trajectory_controller` in `real_controllers.yaml`.
- `python3-serial` for `led_driver`.
- Arduino IDE or `arduino-cli` and the FastLED library to flash the strip firmware.

## Build

```bash
cd ~/cute_ws
rosdep install --from-paths src --ignore-src -y
colcon build --symlink-install
source install/setup.bash
rqt --force-discover    # once after the first build, so that rqt finds Motion Studio
```

`--symlink-install` lets `motion_server.launch.py` find the `motions/` folder in the source tree on its own. Details are in the [`cute_tapochek_motion` README](cute_tapochek_motion/README_EN.md).

colcon skips `led_controller_arduino` (it has no `package.xml`). The firmware is built separately, see [its README](led_controller_arduino/README_EN.md).

## Quick start

**Motions:**

```bash
# terminal 1: arms and teleoperation
ros2 launch soarm101_teleoperate teleoperate.launch.py
# terminal 2: motion server
ros2 launch cute_tapochek_motion motion_server.launch.py
# terminal 3: GUI
ros2 run cute_tapochek_gui motion_studio
```

Playback from code or a terminal:

```bash
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: ahe}" --feedback
```

**LED strip:**

```bash
ros2 run led_driver led_driver --ros-args -p port:=/dev/ttyUSB0
ros2 topic pub --once /led_selector/mode std_msgs/msg/String "{data: green}"
ros2 topic pub --once /led_selector/brightness std_msgs/msg/UInt8 "{data: 150}"
```

## LED strip control protocol

The protocol connects `led_driver` (host) and the `led_controller_arduino` firmware (device). It is line-based plain text, so the board can be tested by hand from any terminal, e.g. the Arduino IDE Serial Monitor.

### Physical layer

| Parameter | Value |
|-----------|-------|
| Interface | UART over USB (the board's virtual COM port) |
| Baud rate | 115200 (`BAUD` in the firmware, `baud` parameter of `led_driver`) |
| Frame format | 8N1 |
| Encoding | ASCII |

### Command framing

- A command ends with `\n` or `\r`; `\r\n` works too.
- Without a line ending, a command is considered complete after 50 ms of silence following the last byte (`LINE_TIMEOUT_MS`). So any "line ending" setting of the Serial Monitor works.
- Before parsing, the board removes all spaces from the command and converts it to upper case: `bright 120`, `BRIGHT 120` and `Bright120` are equivalent.
- Only the first 15 significant characters are kept; the rest are silently dropped.
- An empty line is ignored and gets no reply. The host uses it as a "wake-up" (see "Delivery reliability").

### Commands

| Command | Example | Action |
|---------|---------|--------|
| `<NAME>` | `GREEN` | Switch to a mode by name |
| `<NUMBER>` | `4` | Switch to a mode by number: a single digit `1`–`6` |
| `BRIGHT <0-255>` | `BRIGHT 120` | Set brightness. The space after `BRIGHT` is optional |
| `STATUS` | `STATUS` | Request the current state without changing anything |

Switching to a mode always restarts the effect from a blank strip, even if that mode is already active: e.g. sending `GREEN` again lights the LEDs one by one again. Changing brightness does not restart the effect.

### Modes

| # | Name | Behaviour |
|---|------|-----------|
| 1 | `RAINBOW` | Running rainbow |
| 2 | `DOT` | A green dot with a fading tail runs in a loop: after the last LED it goes back to the first |
| 3 | `AZURE` | LEDs light up turquoise-azure one by one, then the strip stays lit |
| 4 | `GREEN` | Same, in green |
| 5 | `ORANGE` | The whole strip lights up orange at once |
| 6 | `OFF` | The strip goes dark |

A mode number is its position in the firmware's `MODE_NAMES` array plus one. The order of modes in the firmware and in the `MODES` tuple of `led_driver` must match.

### Replies

Every reply line ends with `\r\n`. The host must ignore any line that does not start with `OK` or `ERR`: these are help and service messages.

| Reply | When | Example |
|-------|------|---------|
| `OK <MODE> <BRIGHTNESS>` | Any successful command, including `STATUS` | `OK GREEN 120` |
| `ERR <command>` | Unknown command or invalid value. Contains the command after normalisation (no spaces, upper case) | `ERR BRIGHT300` |

An `OK` reply always carries the device's full actual state, so the host does not need to keep its own copy.

After `ERR` for an unknown mode or command the board also prints the help block (see below). After `ERR` for an invalid brightness there is no help.

Typical errors:

| Request | Reply | Reason |
|---------|-------|--------|
| `PURPLE` | `ERR PURPLE` + help | No such mode |
| `7` | `ERR 7` + help | Number out of range |
| `BRIGHT 300` | `ERR BRIGHT300` | Value above 255 |
| `BRIGHT` | `ERR BRIGHT` | Missing value |

### Device start-up

After a reset the board prints:

```
READY
Режимы:
  1 / RAINBOW
  2 / DOT
  3 / AZURE
  4 / GREEN
  5 / ORANGE
  6 / OFF
  BRIGHT <0-255>, STATUS
OK RAINBOW 80
```

The last line is the start-up state: `RAINBOW` mode, brightness `BRIGHTNESS` from the firmware (80). The state is not kept across reboots.

Opening the port resets an Arduino Nano (and often an ESP32) via the DTR line. So after opening the port the host must wait for the board to boot: `led_driver` waits up to 3 s for an `OK` line and sends `STATUS` if there was none.

### Delivery reliability

On an Arduino Nano, writing to the strip (`FastLED.show()`) disables interrupts while data is being sent. UART bytes arriving at that moment are lost. The protocol handles this on both sides.

**The device** does not update the strip while receiving and for 30 ms after the last received byte (`QUIET_MS`).

**The host** sends every command like this:

1. Flushes the input buffer.
2. Sends an empty line `\n`. It puts the board into "quiet" mode and also pushes any garbage out of its buffer.
3. Waits 5 ms and sends the command followed by `\n`.
4. Waits up to 0.5 s for an `OK` or `ERR` line, skipping other lines.
5. If the reply is not `OK`, repeats steps 1–4, up to 3 attempts in total.

All commands are idempotent, so retries are safe: at worst the effect restarts once more.

### Example session

```
→ 3
← OK AZURE 80
→ BRIGHT 150
← OK AZURE 150
→ dot
← OK DOT 150
→ STATUS
← OK DOT 150
→ PURPLE
← ERR PURPLE
← Режимы:
← ...
```

## Motion format

Each motion is a separate file `motions/<name>.csv`: time in seconds, joint positions in radians, metadata in `#` lines. The file name is the motion name. The format is described in detail in the [`cute_tapochek_motion` README](cute_tapochek_motion/README_EN.md#motion-file-format).

## Authors and license

Alice Zenina and Alexander Grachev, RTU MIREA. MIT license.
