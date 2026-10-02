# cute_tapochek_motion

[Русская версия](README.md)

Motion subsystem of the cute_tapochek robot. The `motion_server` node keeps the motion library, records new motions from the leader arm and plays them back on the follower.

Arm bringup is not included: `motion_server` expects the follower (and, for recording, the leader) to be already running from the `soarm101` repository.

## Features

- Motion library as CSV files in the repository's `motions/` folder: the files can be inspected, edited and committed to git.
- Recording from the leader arm, optionally starting automatically when the arm begins to move.
- Previewing a recording on the follower before saving.
- Playback as a single trajectory through `joint_trajectory_controller`: timing is kept by the controller's real-time loop, not by Python.
- Smooth approach to the first pose of a motion and speed scaling.
- Gripper control synchronised with the trajectory.
- Preemption: a new goal interrupts the current one.
- Automatic teleoperation pause during playback.

## Node `motion_server`

A long-running node. All its services and the action live in the root namespace; the status is published on `/motion_server/status`.

### Parameters

All parameters with comments are in `config/motion_server.yaml`. `motions_dir` is set by the launch file.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `motions_dir` | string | `''` | Motion library folder. Required: the node does not start if it is empty |
| `leader_topic` | string | `/leader/joint_states` | Source of recordings |
| `follower_state_topic` | string | `/follower/joint_states` | Current follower pose: starting point of the approach |
| `arm_action` | string | `/follower/joint_trajectory_controller/follow_joint_trajectory` | Arm trajectory controller action |
| `gripper_action` | string | `/follower/gripper_controller/gripper_cmd` | Gripper controller action |
| `arm_joints` | string[] | 5 arm joints | Joints played as a trajectory |
| `record_joints` | string[] | 5 arm joints + `gripper_jaw_joint` | Joints written to the file |
| `gripper_joint` | string | `gripper_jaw_joint` | Gripper joint |
| `play_gripper` | bool | `true` | Whether to play the gripper |
| `default_approach_time` | double | `2.0` | Default approach time to the first pose, s. Minimum 0.5 s |
| `max_speed` | double | `2.0` | Maximum allowed speed multiplier |
| `start_delay` | double | `0.2` | Trajectory start delay after the goal is sent, s |
| `motion_threshold` | double | `0.02` | Displacement of any joint after which the leader is considered moving, rad |
| `default_max_recording` | double | `120.0` | Default length limit of one recording, s |
| `gripper_rate` | double | `20.0` | Rate of gripper goals during playback, Hz |
| `gripper_threshold` | double | `0.005` | Minimum gripper position change for a new goal, rad |
| `gripper_max_effort` | double | `10.0` | `max_effort` of gripper goals |
| `teleop_services` | string[] | `[/arm_relay/set_enabled, /gripper_relay/set_enabled]` | Teleoperation pause services |
| `pause_teleop_on_play` | bool | `true` | Whether to pause teleoperation before playback |

Default arm joints: `shoulder_pan_joint`, `shoulder_lift_joint`, `elbow_flex_joint`, `wrist_flex_joint`, `wrist_roll_joint`.

### Actions

| Action | Type | Description |
|--------|------|-------------|
| `/play_motion` | `cute_tapochek_interfaces/action/PlayMotion` | Play a motion from the library or the draft |

### Services

| Service | Type | Description |
|---------|------|-------------|
| `/stop_motion` | `std_srvs/Trigger` | Stop playback, the arm stops where it is |
| `/list_motions` | `cute_tapochek_interfaces/srv/ListMotions` | List motions with durations and descriptions |
| `/start_recording` | `cute_tapochek_interfaces/srv/StartRecording` | Start recording from the leader |
| `/stop_recording` | `std_srvs/Trigger` | Finish recording, it becomes the draft |
| `/discard_recording` | `std_srvs/Trigger` | Discard the current recording, or the draft if there is none |
| `/save_motion` | `cute_tapochek_interfaces/srv/SaveMotion` | Save the draft to the library |
| `/delete_motion` | `cute_tapochek_interfaces/srv/DeleteMotion` | Delete a motion from the library |
| `/set_teleop` | `std_srvs/SetBool` | Enable (`true`) or pause (`false`) teleoperation |

### Topics

| Topic | Direction | Type | Description |
|-------|-----------|------|-------------|
| `/leader/joint_states` | subscription | `sensor_msgs/JointState` | Recording source |
| `/follower/joint_states` | subscription | `sensor_msgs/JointState` | Current follower pose |
| `/motion_server/status` | publication, 5 Hz | `cute_tapochek_interfaces/msg/MotionServerStatus` | Server state |

## Launch

```bash
ros2 launch cute_tapochek_motion motion_server.launch.py
ros2 launch cute_tapochek_motion motion_server.launch.py motions_dir:=$HOME/cute_ws/src/motions
```

The launch file starts only `motion_server`. The library folder is chosen in this order:

1. The `motions_dir:=...` argument.
2. The `CUTE_TAPOCHEK_MOTIONS_DIR` environment variable.
3. The `motions/` folder in the repository source tree. This works only if the workspace was built with `--symlink-install`: the launch file then finds the sources through the symlink.

If none of these works, the node exits with a message about an empty `motions_dir`. A missing folder is created.

## Recording a motion

1. `/start_recording`. With `start_on_motion: true` the server waits until any leader joint moves by more than `motion_threshold`. The last still sample becomes `t = 0`, so the beginning of the movement is not lost.
2. `/stop_recording`. The recording becomes the draft. If the leader never moved or there are fewer than two samples, no draft is created.
3. Preview: `/play_motion` with `play_draft: true`.
4. `/save_motion` with a name and description. The draft is cleared after saving.

Recording stops by itself when `max_duration` (or `default_max_recording`) is reached. The draft is kept in memory only and is lost if the server restarts.

## Playback

- An unknown name is rejected right away, before the goal is accepted.
- Before starting, if `pause_teleop_on_play: true`, the server pauses teleoperation. The pause is lifted only explicitly: with the `/set_teleop` service or the button in Motion Studio.
- The trajectory has two segments: a smooth approach from the current follower pose to the first recorded pose over `approach_time` (smoothstep profile, 50 points per second), and the recording itself with its time divided by `speed`. If the follower pose is unknown, the approach is a single point and the controller interpolates.
- The whole trajectory is sent to `joint_trajectory_controller` as one goal.
- The gripper is played separately: `gripper_controller` accepts one goal at a time, so the server sends it the recorded position `gripper_rate` times per second, in sync with the trajectory. A new goal is sent only if the position changed by more than `gripper_threshold`.
- A new `/play_motion` goal preempts the current one. The preempted goal finishes with `success: false` and the message `<name>: interrupted`.
- Cancelling the goal or calling `/stop_motion` stops the arm where it is.
- Feedback is published at `gripper_rate`: `progress` (0..1), `elapsed`, `total`.

## Motion file format

Each motion is a separate file `motions/<name>.csv`. The file name is the motion name: latin letters, digits, `_` and `-`, up to 64 characters, starting with a letter or digit.

```
# cute_tapochek_motion v1
# source_topic: /leader/joint_states
# recorded_at: 2026-10-02T20:55:58
# name: ahe
# description: Эххх
# saved_at: 2026-10-02T20:56:30
time,shoulder_pan_joint,shoulder_lift_joint,elbow_flex_joint,wrist_flex_joint,wrist_roll_joint,gripper_jaw_joint
0.000000,0.012000,-1.745000,...
0.010000,0.013000,-1.744000,...
```

- Lines starting with `#` are metadata (`key: value`) or comments.
- The first line without `#` is the header. The first column is `time`, then the joints.
- Time is in seconds from the start of the recording, positions are in radians.
- Samples with non-increasing time are skipped on load. Files with missing values, NaN or a wrong column count are treated as broken: they are not listed and cannot be played.
- Saving is atomic: the file is written to a temporary `<name>.csv.tmp` and then renamed, so a crash never leaves a half-written file in the library.

There is no separate index: the description lives in the file itself. So motions can be renamed, copied and deleted right in a file manager. The server re-reads a file when its modification time changes.

## Useful checks

```bash
# Server state
ros2 topic echo /motion_server/status

# Library
ros2 service call /list_motions cute_tapochek_interfaces/srv/ListMotions

# Recording
ros2 service call /start_recording cute_tapochek_interfaces/srv/StartRecording "{start_on_motion: true}"
ros2 service call /stop_recording std_srvs/srv/Trigger
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{play_draft: true}" --feedback
ros2 service call /save_motion cute_tapochek_interfaces/srv/SaveMotion "{name: wave_hello, description: 'waves a hand'}"
ros2 service call /discard_recording std_srvs/srv/Trigger

# Playback
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: wave_hello}" --feedback
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: wave_hello, speed: 0.5, approach_time: 3.0}"
ros2 service call /stop_motion std_srvs/srv/Trigger

# Deletion
ros2 service call /delete_motion cute_tapochek_interfaces/srv/DeleteMotion "{name: wave_hello}"

# Teleoperation
ros2 service call /set_teleop std_srvs/srv/SetBool "{data: true}"
ros2 service call /set_teleop std_srvs/srv/SetBool "{data: false}"
```

## Tests

The `library`, `motion_file` and `playback` modules do not import ROS and are covered by unit tests: file format, rejection of broken files and bad names, atomic saving, the recording buffer and start-on-motion, interpolation and trajectory building.

```bash
colcon test --packages-select cute_tapochek_motion
colcon test-result --verbose
# or without colcon, from the package directory:
python3 -m pytest test
```

## Dependencies

- ROS 2:
  - `rclpy`
  - `cute_tapochek_interfaces`
  - `sensor_msgs`
  - `trajectory_msgs`
  - `control_msgs`
  - `std_srvs`
  - `launch`, `launch_ros`, `ament_index_python`
- The `soarm101` repository:
  - running follower controllers: `joint_trajectory_controller` and `gripper_controller`;
  - `open_loop_control: true` for `joint_trajectory_controller` in `real_controllers.yaml`;
  - the `soarm101_teleop_pause.patch` patch (`~/set_enabled` service on `arm_relay` and `gripper_relay`). Without it playback works, but during teleoperation the relays will fight the server for the arm.

## Version

**0.1.0** — first version: motion library, recording from the leader, draft preview, playback with preemption, teleoperation pause.
