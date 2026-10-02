# cute_tapochek_interfaces

[Русская версия](README.md)

Interfaces of the cute_tapochek motion subsystem: playback action, library and recording services, status message. They are served by the `motion_server` node from [`cute_tapochek_motion`](../cute_tapochek_motion/README_EN.md); the GUI client is [`cute_tapochek_gui`](../cute_tapochek_gui/README_EN.md).

## Contents

| Interface | Kind | Used by |
|-----------|------|---------|
| `PlayMotion` | action | `/play_motion` — play a motion |
| `ListMotions` | srv | `/list_motions` — list motions |
| `StartRecording` | srv | `/start_recording` — start recording from the leader |
| `SaveMotion` | srv | `/save_motion` — save the draft to the library |
| `DeleteMotion` | srv | `/delete_motion` — delete a motion |
| `MotionServerStatus` | msg | `/motion_server/status` — server state |

The other `motion_server` services (`/stop_motion`, `/stop_recording`, `/discard_recording`, `/set_teleop`) use the standard `std_srvs/Trigger` and `std_srvs/SetBool`.

## action `PlayMotion`

Play a motion from the library or the last unsaved recording (draft). A new goal preempts the current one.

**Goal**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Motion name in the library |
| `play_draft` | bool | `true` — play the draft, `name` is ignored |
| `speed` | float64 | Speed multiplier. `0` means `1.0` |
| `approach_time` | float64 | Time to move to the first pose of the motion, s. `0` — server default |

**Result**

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | The motion was played to the end |
| `message` | string | Explanation: `<name>: done`, `<name>: interrupted`, `<name>: cancelled`, or an error text |

**Feedback**

| Field | Type | Description |
|-------|------|-------------|
| `progress` | float64 | Completed fraction, 0..1 |
| `elapsed` | float64 | Time since the trajectory start, s |
| `total` | float64 | Full duration: approach + motion, s |

## srv `ListMotions`

Empty request.

| Response field | Type | Description |
|----------------|------|-------------|
| `names` | string[] | Motion names, alphabetically |
| `durations` | float64[] | Durations, s |
| `descriptions` | string[] | Descriptions |

The arrays are parallel: the `i`-th element of each refers to the same motion.

## srv `StartRecording`

| Request field | Type | Description |
|---------------|------|-------------|
| `start_on_motion` | bool | Start recording only when the leader moves |
| `max_duration` | float64 | Recording length limit, s. `0` — server default |

Response: `success` (bool), `message` (string).

## srv `SaveMotion`

Save the last recording (draft) to the library.

| Request field | Type | Description |
|---------------|------|-------------|
| `name` | string | Name: latin letters, digits, `_` and `-`, up to 64 characters, starting with a letter or digit |
| `description` | string | Motion description |
| `overwrite` | bool | Overwrite if a motion with this name already exists |

Response: `success` (bool), `message` (string).

## srv `DeleteMotion`

| Request field | Type | Description |
|---------------|------|-------------|
| `name` | string | Motion name |

Response: `success` (bool), `message` (string).

## msg `MotionServerStatus`

| Field | Type | Description |
|-------|------|-------------|
| `state` | string | Server state, one of the `STATE_*` constants |
| `playing` | string | Name of the motion being played (`(draft)` for the draft), empty if nothing is playing |
| `progress` | float64 | Playback progress, 0..1 |
| `recording_time` | float64 | Length of the current recording, s |
| `has_draft` | bool | Whether there is an unsaved recording |
| `draft_duration` | float64 | Draft length, s |
| `teleop` | string | Last known teleoperation state, one of the `TELEOP_*` constants |

**Server state constants**

| Constant | Value | Meaning |
|----------|-------|---------|
| `STATE_IDLE` | `idle` | Nothing is happening |
| `STATE_WAITING` | `waiting_for_motion` | Recording started, waiting for the leader to move |
| `STATE_RECORDING` | `recording` | Recording in progress |
| `STATE_PLAYING` | `playing` | Playback in progress |

**Teleoperation constants**

| Constant | Value | Meaning |
|----------|-------|---------|
| `TELEOP_UNKNOWN` | `unknown` | The server has not contacted teleoperation yet |
| `TELEOP_ENABLED` | `enabled` | Leader → follower relaying is on |
| `TELEOP_PAUSED` | `paused` | Relaying is paused |
| `TELEOP_UNAVAILABLE` | `unavailable` | Teleoperation pause services were not found |

## Useful checks

```bash
ros2 interface show cute_tapochek_interfaces/action/PlayMotion
ros2 interface show cute_tapochek_interfaces/msg/MotionServerStatus
ros2 interface package cute_tapochek_interfaces
```

## Dependencies

- `ament_cmake`
- `rosidl_default_generators`, `rosidl_default_runtime`
- `action_msgs`

## Version

**0.1.0** — first version: `PlayMotion`, library and recording services, `MotionServerStatus`.
