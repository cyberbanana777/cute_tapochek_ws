#!/usr/bin/env python3

# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

"""
motion_server: a long-running node that owns the motion library.

Interfaces (names are relative to the node namespace):
  action  play_motion        cute_tapochek_interfaces/action/PlayMotion
  srv     stop_motion        std_srvs/Trigger
  srv     list_motions       cute_tapochek_interfaces/srv/ListMotions
  srv     start_recording    cute_tapochek_interfaces/srv/StartRecording
  srv     stop_recording     std_srvs/Trigger
  srv     discard_recording  std_srvs/Trigger
  srv     save_motion        cute_tapochek_interfaces/srv/SaveMotion
  srv     delete_motion      cute_tapochek_interfaces/srv/DeleteMotion
  srv     set_teleop         std_srvs/SetBool
  topic   motion_server/status  cute_tapochek_interfaces/msg/MotionServerStatus

Playback: the motion is sent to joint_trajectory_controller as ONE trajectory,
so timing is kept by the controller's real-time loop. A new play_motion goal
preempts the current one. The gripper column is streamed to
gripper_controller, synchronised to the trajectory start time.

The arm bringup is NOT started here: launch it separately.
"""

import threading
import time
from datetime import datetime

import rclpy
from control_msgs.action import FollowJointTrajectory, GripperCommand
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool, Trigger
from trajectory_msgs.msg import JointTrajectoryPoint

from cute_tapochek_interfaces.action import PlayMotion
from cute_tapochek_interfaces.msg import MotionServerStatus as Status
from cute_tapochek_interfaces.srv import (
    DeleteMotion, ListMotions, SaveMotion, StartRecording)

from .library import LibraryError, MotionLibrary, RecordingBuffer, check_name
from .playback import build_playback_points, interpolate, motion_time_at

try:
    from rclpy.executors import ExternalShutdownException
except ImportError:  # very old rclpy
    class ExternalShutdownException(Exception):
        pass

ARM_JOINTS = [
    'shoulder_pan_joint',
    'shoulder_lift_joint',
    'elbow_flex_joint',
    'wrist_flex_joint',
    'wrist_roll_joint',
]
ALL_JOINTS = ARM_JOINTS + ['gripper_jaw_joint']


def _wait(future, timeout: float) -> bool:
    """Block the calling thread until an rclpy future is done."""
    if future.done():
        return True
    event = threading.Event()
    future.add_done_callback(lambda _: event.set())
    return event.wait(timeout) or future.done()


class MotionServer(Node):

    def __init__(self):
        super().__init__('motion_server')

        dp = self.declare_parameter
        dp('motions_dir', '')
        dp('leader_topic', '/leader/joint_states')
        dp('follower_state_topic', '/follower/joint_states')
        dp('arm_action', '/follower/joint_trajectory_controller/follow_joint_trajectory')
        dp('gripper_action', '/follower/gripper_controller/gripper_cmd')
        dp('arm_joints', ARM_JOINTS)
        dp('record_joints', ALL_JOINTS)
        dp('gripper_joint', 'gripper_jaw_joint')
        dp('play_gripper', True)
        dp('default_approach_time', 2.0)
        dp('max_speed', 2.0)
        dp('start_delay', 0.2)
        dp('motion_threshold', 0.02)
        dp('default_max_recording', 120.0)
        dp('gripper_rate', 20.0)
        dp('gripper_threshold', 0.005)
        dp('gripper_max_effort', 10.0)
        dp('teleop_services', ['/arm_relay/set_enabled', '/gripper_relay/set_enabled'])
        dp('pause_teleop_on_play', True)

        p = lambda n: self.get_parameter(n).value  # noqa: E731
        motions_dir = p('motions_dir')
        if not motions_dir:
            raise ValueError(
                'parameter motions_dir is empty: pass motions_dir:=<repo>/motions '
                'or build with --symlink-install (see README)')
        self.library = MotionLibrary(motions_dir)

        self.arm_joints = list(p('arm_joints'))
        self.record_joints = list(p('record_joints'))
        self.gripper_joint = p('gripper_joint')
        self.play_gripper = bool(p('play_gripper'))
        self.default_approach = float(p('default_approach_time'))
        self.max_speed = float(p('max_speed'))
        self.start_delay = float(p('start_delay'))
        self.motion_threshold = float(p('motion_threshold'))
        self.default_max_recording = float(p('default_max_recording'))
        self.gripper_period = 1.0 / max(1.0, float(p('gripper_rate')))
        self.gripper_threshold = float(p('gripper_threshold'))
        self.gripper_max_effort = float(p('gripper_max_effort'))
        self.pause_teleop_on_play = bool(p('pause_teleop_on_play'))
        self.leader_topic = p('leader_topic')

        cb = ReentrantCallbackGroup()
        self._lock = threading.Lock()
        self._active_goal = None
        self._playing = ''
        self._progress = 0.0
        self._recording = None   # RecordingBuffer while recording
        self._draft = None       # last finished, unsaved recording
        self._follower = None    # {joint: position}
        self._teleop = Status.TELEOP_UNKNOWN

        self.arm_client = ActionClient(
            self, FollowJointTrajectory, p('arm_action'), callback_group=cb)
        self.gripper_client = ActionClient(
            self, GripperCommand, p('gripper_action'), callback_group=cb)
        self.teleop_clients = [
            self.create_client(SetBool, name, callback_group=cb)
            for name in p('teleop_services')]

        self.create_subscription(
            JointState, self.leader_topic, self._on_leader, 100, callback_group=cb)
        self.create_subscription(
            JointState, p('follower_state_topic'), self._on_follower, 10,
            callback_group=cb)

        self._action = ActionServer(
            self, PlayMotion, 'play_motion',
            execute_callback=self._execute,
            goal_callback=self._on_goal,
            handle_accepted_callback=self._on_accepted,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
            callback_group=cb)

        srv = self.create_service
        srv(Trigger, 'stop_motion', self._srv_stop_motion, callback_group=cb)
        srv(ListMotions, 'list_motions', self._srv_list, callback_group=cb)
        srv(StartRecording, 'start_recording', self._srv_start_rec, callback_group=cb)
        srv(Trigger, 'stop_recording', self._srv_stop_rec, callback_group=cb)
        srv(Trigger, 'discard_recording', self._srv_discard, callback_group=cb)
        srv(SaveMotion, 'save_motion', self._srv_save, callback_group=cb)
        srv(DeleteMotion, 'delete_motion', self._srv_delete, callback_group=cb)
        srv(SetBool, 'set_teleop', self._srv_set_teleop, callback_group=cb)

        self._status_pub = self.create_publisher(Status, '~/status', 10)
        self.create_timer(0.2, self._publish_status, callback_group=cb)

        names = self.library.names()
        self.get_logger().info(
            f'Motion library: {self.library.directory} ({len(names)} motions)')

    # ================================================================ state
    def _on_follower(self, msg: JointState):
        self._follower = dict(zip(msg.name, msg.position))

    def _on_leader(self, msg: JointState):
        with self._lock:
            buf = self._recording
            if buf is None:
                return
            stamp = Time.from_msg(msg.header.stamp)
            if stamp.nanoseconds == 0:
                stamp = self.get_clock().now()
            if not buf.feed(stamp.nanoseconds * 1e-9, msg.name, msg.position):
                self.get_logger().warn(
                    f'{self.leader_topic} lacks some of {buf.joints}',
                    throttle_duration_sec=5.0)
            if buf.full:
                self._finish_recording_locked()
                self.get_logger().warn('Recording stopped: max duration reached')

    def _publish_status(self):
        msg = Status()
        with self._lock:
            if self._playing:
                msg.state = Status.STATE_PLAYING
            elif self._recording is not None:
                msg.state = (Status.STATE_RECORDING if self._recording.started
                             else Status.STATE_WAITING)
            else:
                msg.state = Status.STATE_IDLE
            msg.playing = self._playing
            msg.progress = self._progress
            msg.recording_time = self._recording.duration if self._recording else 0.0
            msg.has_draft = self._draft is not None
            msg.draft_duration = self._draft.duration if self._draft else 0.0
            msg.teleop = self._teleop
        self._status_pub.publish(msg)

    # =============================================================== teleop
    def _set_teleop(self, enabled: bool) -> (bool, str):
        ready = [c for c in self.teleop_clients if c.service_is_ready()]
        if not ready:
            self._teleop = Status.TELEOP_UNAVAILABLE
            return False, 'teleoperation is not running'
        ok = True
        for client in ready:
            fut = client.call_async(SetBool.Request(data=enabled))
            if not _wait(fut, 1.0) or fut.result() is None or not fut.result().success:
                ok = False
        if ok:
            self._teleop = Status.TELEOP_ENABLED if enabled else Status.TELEOP_PAUSED
            return True, 'teleop ' + ('enabled' if enabled else 'paused')
        return False, 'some teleop relays did not answer'

    def _srv_set_teleop(self, req, res):
        res.success, res.message = self._set_teleop(req.data)
        return res

    # ============================================================= playback
    def _on_goal(self, goal):
        if goal.play_draft:
            if self._draft is None:
                self.get_logger().warn('play_motion rejected: no draft')
                return GoalResponse.REJECT
            return GoalResponse.ACCEPT
        try:
            if not self.library.exists(goal.name):
                self.get_logger().warn(f'play_motion rejected: unknown "{goal.name}"')
                return GoalResponse.REJECT
        except LibraryError as e:
            self.get_logger().warn(f'play_motion rejected: {e}')
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def _on_accepted(self, goal_handle):
        with self._lock:
            old = self._active_goal
            if old is not None and old.is_active:
                self.get_logger().info('New goal preempts the current motion')
                old.abort()
            self._active_goal = goal_handle
        goal_handle.execute()

    def _srv_stop_motion(self, req, res):
        with self._lock:
            gh = self._active_goal
            if gh is not None and gh.is_active:
                gh.abort()
                res.success, res.message = True, 'stopped'
            else:
                res.success, res.message = False, 'nothing is playing'
        return res

    def _end(self, goal_handle, ok: bool, message: str):
        if goal_handle.is_active:
            if ok:
                goal_handle.succeed()
            elif goal_handle.is_cancel_requested:
                goal_handle.canceled()
            else:
                goal_handle.abort()
        with self._lock:
            if self._active_goal is goal_handle:
                self._playing = ''
                self._progress = 0.0
        (self.get_logger().info if ok else self.get_logger().warn)(message)
        return PlayMotion.Result(success=ok, message=message)

    def _execute(self, goal_handle):
        req = goal_handle.request

        # ---- what to play
        try:
            if req.play_draft:
                motion, name = self._draft, '(draft)'
                if motion is None:
                    raise LibraryError('no draft to play')
            else:
                name = check_name(req.name)
                motion = self.library.load(name)
        except LibraryError as e:
            return self._end(goal_handle, False, str(e))
        missing = [j for j in self.arm_joints if j not in motion.joint_names]
        if missing:
            return self._end(goal_handle, False, f'{name}: no joints {missing}')

        speed = req.speed if req.speed > 0.0 else 1.0
        if speed > self.max_speed:
            return self._end(goal_handle, False,
                             f'speed {speed} > max_speed {self.max_speed}')
        approach = req.approach_time if req.approach_time > 0.0 else self.default_approach
        approach = max(0.5, approach)

        if self.pause_teleop_on_play:
            self._set_teleop(False)

        # ---- build and send the trajectory
        start = None
        if self._follower is not None:
            try:
                start = [self._follower[j] for j in self.arm_joints]
            except KeyError:
                start = None
        points = build_playback_points(
            motion, self.arm_joints, approach, speed, start_positions=start)
        total = points[-1][0]

        jtc_goal = FollowJointTrajectory.Goal()
        traj = jtc_goal.trajectory
        traj.joint_names = self.arm_joints
        start_time = self.get_clock().now() + Duration(seconds=self.start_delay)
        traj.header.stamp = start_time.to_msg()
        for t, pos in points:
            pt = JointTrajectoryPoint()
            pt.positions = [float(x) for x in pos]
            pt.time_from_start = Duration(seconds=t).to_msg()
            traj.points.append(pt)

        if not self.arm_client.wait_for_server(timeout_sec=2.0):
            return self._end(goal_handle, False, 'arm trajectory controller is not available')
        send = self.arm_client.send_goal_async(jtc_goal)
        if not _wait(send, 5.0) or send.result() is None or not send.result().accepted:
            return self._end(goal_handle, False, 'trajectory rejected by the controller')
        jtc = send.result()
        jtc_result = jtc.get_result_async()

        with self._lock:
            if self._active_goal is goal_handle:
                self._playing = name
                self._progress = 0.0
        self.get_logger().info(f'Playing {name}: {total:.2f} s, speed x{speed:g}')

        gripper = None
        if (self.play_gripper and self.gripper_joint in motion.joint_names
                and self.gripper_client.server_is_ready()):
            gripper = motion.column(self.gripper_joint)
        last_gripper = None

        # ---- supervise
        while not jtc_result.done():
            if not goal_handle.is_active:          # preempted or stop_motion
                jtc.cancel_goal_async()
                return self._end(goal_handle, False, f'{name}: interrupted')
            if goal_handle.is_cancel_requested:
                _wait(jtc.cancel_goal_async(), 2.0)
                return self._end(goal_handle, False, f'{name}: cancelled')

            elapsed = max(0.0, (self.get_clock().now() - start_time).nanoseconds * 1e-9)
            progress = min(1.0, elapsed / total) if total > 0 else 1.0
            with self._lock:
                if self._active_goal is goal_handle:
                    self._progress = progress
            fb = PlayMotion.Feedback(progress=progress, elapsed=elapsed, total=total)
            try:
                goal_handle.publish_feedback(fb)
            except Exception:  # goal finished concurrently
                pass

            if gripper is not None:
                t = motion_time_at(elapsed, motion, approach, speed)
                value = interpolate(motion.times, gripper, t)
                if last_gripper is None or abs(value - last_gripper) >= self.gripper_threshold:
                    self._send_gripper(value)
                    last_gripper = value

            time.sleep(self.gripper_period)

        if not goal_handle.is_active:
            return self._end(goal_handle, False, f'{name}: interrupted')

        wrapped = jtc_result.result()
        res = wrapped.result if wrapped is not None else None
        if res is None or res.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            text = f'{res.error_code} {res.error_string}' if res else 'no result'
            return self._end(goal_handle, False, f'{name}: controller error {text}')
        if gripper is not None:
            self._send_gripper(gripper[-1])
        return self._end(goal_handle, True, f'{name}: done')

    def _send_gripper(self, value: float):
        goal = GripperCommand.Goal()
        goal.command.position = float(value)
        goal.command.max_effort = self.gripper_max_effort
        self.gripper_client.send_goal_async(goal)

    # ============================================================ recording
    def _srv_start_rec(self, req, res):
        with self._lock:
            if self._recording is not None:
                res.success, res.message = False, 'already recording'
                return res
            max_dur = req.max_duration if req.max_duration > 0.0 else self.default_max_recording
            self._recording = RecordingBuffer(
                self.record_joints, req.start_on_motion, self.motion_threshold, max_dur,
                meta={'source_topic': self.leader_topic,
                      'recorded_at': datetime.now().isoformat(timespec='seconds')})
        res.success = True
        res.message = ('waiting for the leader to move' if req.start_on_motion
                       else 'recording')
        self.get_logger().info(f'Recording: {res.message}')
        return res

    def _finish_recording_locked(self) -> (bool, str):
        buf, self._recording = self._recording, None
        motion = buf.to_motion() if buf else None
        if motion is None:
            return False, 'nothing recorded (did the leader move?)'
        self._draft = motion
        return True, f'draft: {motion.duration:.2f} s, {len(motion)} samples'

    def _srv_stop_rec(self, req, res):
        with self._lock:
            if self._recording is None:
                res.success, res.message = False, 'not recording'
                return res
            res.success, res.message = self._finish_recording_locked()
        self.get_logger().info(f'Recording stopped: {res.message}')
        return res

    def _srv_discard(self, req, res):
        with self._lock:
            if self._recording is not None:
                self._recording = None
                res.message = 'recording discarded'
            elif self._draft is not None:
                self._draft = None
                res.message = 'draft discarded'
            else:
                res.success, res.message = False, 'nothing to discard'
                return res
        res.success = True
        return res

    # ============================================================== library
    def _srv_list(self, req, res):
        for name, duration, description in self.library.list():
            res.names.append(name)
            res.durations.append(duration)
            res.descriptions.append(description)
        return res

    def _srv_save(self, req, res):
        with self._lock:
            draft = self._draft
        if draft is None:
            res.success, res.message = False, 'no draft: record something first'
            return res
        try:
            name = check_name(req.name)
            path = self.library.save(name, draft, req.description, req.overwrite)
        except (LibraryError, OSError) as e:
            res.success, res.message = False, str(e)
            return res
        with self._lock:
            if self._draft is draft:
                self._draft = None
        res.success, res.message = True, f'saved {path}'
        self.get_logger().info(res.message)
        return res

    def _srv_delete(self, req, res):
        try:
            self.library.delete(req.name)
        except (LibraryError, OSError) as e:
            res.success, res.message = False, str(e)
            return res
        res.success, res.message = True, f'deleted {req.name}'
        self.get_logger().info(res.message)
        return res


def main(args=None):
    rclpy.init(args=args)
    try:
        node = MotionServer()
    except (ValueError, LibraryError, OSError) as e:
        print(f'[motion_server] {e}')
        rclpy.shutdown()
        return
    executor = MultiThreadedExecutor(num_threads=6)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
