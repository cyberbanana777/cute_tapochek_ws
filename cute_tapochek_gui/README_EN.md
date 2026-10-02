# cute_tapochek_gui

[Русская версия](README.md)

**Motion Studio** rqt plugin for the cute_tapochek motion subsystem. It lets you record a motion from the leader arm, preview it on the follower, save it to the library and play saved motions.

The GUI stores nothing itself: every button calls a service or action of the `motion_server` node from [`cute_tapochek_motion`](../cute_tapochek_motion/README_EN.md). So everything done in the GUI can also be done from a terminal.

## Launch

First bring up the arms and `motion_server`:

```bash
ros2 launch soarm101_teleoperate teleoperate.launch.py
ros2 launch cute_tapochek_motion motion_server.launch.py
```

Then open Motion Studio in one of two ways:

```bash
# as a standalone window
ros2 run cute_tapochek_gui motion_studio

# inside rqt: Plugins → Cute Tapochek → Motion Studio
rqt
```

After the first build rqt must rescan its plugins once, otherwise Motion Studio does not appear in the menu:

```bash
rqt --force-discover
```

## Interface

The interface labels are in Russian; English translations are given in parentheses.

**Connection line.** Shows whether `motion_server` is reachable. The server is considered down if no status has arrived for more than 1.5 s; buttons that need the server are then disabled.

**Библиотека движений (Motion library).** A table with the name, duration and description of each motion.

- **Скорость × (Speed ×)** — playback speed multiplier, 0.1–2.0.
- **▶ Играть (Play)** — play the selected motion. Double-clicking a row does the same.
- **■ Стоп (Stop)** — stop playback, the arm stops where it is.
- **Удалить (Delete)** — delete the selected motion after confirmation.
- **Обновить (Refresh)** — reload the library.

**Запись с leader (Recording from the leader).** Shows the recording state: waiting for movement, recording (with a timer), playing, unsaved draft.

- **ждать начала движения (wait for movement)** — if checked, recording starts when the leader moves.
- **● Записать (Record)** — start recording. If there is an unsaved draft, the GUI asks for confirmation: the new recording replaces it.
- **■ Остановить (Stop)** — finish recording, it becomes the draft.
- **▶ Посмотреть (Preview)** — play the draft on the follower.
- **✕ Выбросить (Discard)** — discard the recording or the draft.
- **Имя (Name)**, **Описание (Description)**, **Сохранить (Save)** — save the draft to the library. The name is validated in the GUI: latin letters, digits, `_` and `-`, up to 64 characters. If a motion with that name exists, the GUI offers to overwrite it.

**Телеуправление (Teleoperation).** Shows the state of leader → follower relaying. The **Включить (Enable)** and **Пауза (Pause)** buttons enable and pause it. During playback the server pauses teleoperation by itself. To get it back, press **Включить**: the follower smoothly catches up with the leader and then follows it.

**Progress and log.** A playback progress bar and a log of server replies.

## Typical recording workflow

1. Check "ждать начала движения" and press **● Записать**.
2. Perform the motion with the leader arm and press **■ Остановить**.
3. Press **▶ Посмотреть**: the follower plays the draft, teleoperation is paused.
4. If you like it, enter a name and description and press **Сохранить**. If not, press **✕ Выбросить** or record again.
5. Press **Включить** in the "Телеуправление" block to control the follower from the leader again.

## Saved settings

rqt remembers the speed multiplier and the "ждать начала движения" checkbox between runs.

## Useful checks

```bash
# Does rqt see the plugin
rqt --list-plugins | grep -i motion

# Is the server reachable
ros2 topic hz /motion_server/status
ros2 service list | grep -E "motion|recording|teleop"
```

## Dependencies

- ROS 2:
  - `rclpy`
  - `rqt_gui`, `rqt_gui_py`
  - `python_qt_binding`
  - `cute_tapochek_interfaces`
  - `std_srvs`
- A running `motion_server` node from `cute_tapochek_motion`.

## Version

**0.1.0** — first version: library, recording, preview, saving and playback of motions, teleoperation control.
