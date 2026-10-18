"""Настоящий проигрыватель: клипы -> /play_motion, домой -> траектория, голос -> aplay, лента -> led_driver."""
import glob
import os
import random
import subprocess
import threading

from control_msgs.action import FollowJointTrajectory
from cute_tapochek_interfaces.action import PlayMotion
from builtin_interfaces.msg import Duration
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectoryPoint

from candy_dispenser.candy_sm import Bus, E

ARM_JOINTS = ["shoulder_pan_joint", "elbow_flex_joint", "wrist_flex_joint",
              "wrist_roll_joint", "shoulder_lift_joint"]    


class RosClipPlayer(Node):
    def __init__(self, bus: Bus) -> None:
        super().__init__("candy_clip_player")
        self.bus = bus
        self.declare_parameter("home_joints", [0.0092,0.9139,0.3285,-1.3905,-1.1394])          # 5 чисел, рад (обязательно задать)
        self.declare_parameter("home_speed", 1.2)             # рад/с, самый быстрый сустав
        self.declare_parameter("home_reserve", 0.5)           # с, запас по времени
        self.declare_parameter("clip_timeout", 60.0)          # с, дольше -> CLIP_FAILED
        self.declare_parameter("voice_dir", os.path.expanduser("~/Documents/lerobot/cute_ws/src/voice"))  # voice_dir/<группа>/*.wav
        self.declare_parameter("phrase_timeout", 15.0)

        self._lock = threading.Lock()
        self._gen = {"clip": 0, "home": 0, "phrase": 0}      # номер «поколения»: старые ответы игнорируем
        self._goal = {"clip": None, "home": None}
        self._voice: subprocess.Popen | None = None
        self._q: dict[str, float] = {}
"""Настоящий проигрыватель.

Клип = XML из clip_conf_dir (движение + голос + лента, всё стартует вместе).
Если XML-файла нет, играется одноимённое движение, как раньше.
Домой -> траектория в контроллер, фраза -> aplay/mpg123, лента -> led_driver.
"""
import glob
import os
import random
import subprocess
import threading
import xml.etree.ElementTree as ET

from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from cute_tapochek_interfaces.action import PlayMotion
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from trajectory_msgs.msg import JointTrajectoryPoint

from candy_dispenser.candy_sm import Bus, E

# порядок как в /follower/joint_states
ARM_JOINTS = ["shoulder_pan_joint", "elbow_flex_joint", "wrist_flex_joint",
              "wrist_roll_joint", "shoulder_lift_joint"]


class RosClipPlayer(Node):
    def __init__(self, bus: Bus) -> None:
        super().__init__("candy_clip_player")
        self.bus = bus
        self.declare_parameter("home_joints", [0.0092,0.9139,0.3285,-1.3905,-1.1394])          # 5 чисел, рад (обязательно задать)
        self.declare_parameter("home_speed", 1.2)             # рад/с, самый быстрый сустав
        self.declare_parameter("home_reserve", 0.5)           # с, запас по времени
        self.declare_parameter("clip_timeout", 80.0)          # с, дольше -> CLIP_FAILED
        self.declare_parameter("voice_dir", os.path.expanduser("~/Documents/lerobot/cute_ws/src/voice"))  # voice_dir/<группа>/*.wav
        self.declare_parameter("phrase_timeout", 15.0)
        self.declare_parameter("clip_conf_dir", "/home/moody/Documents/lerobot/cute_ws/src/clip_conf")
        
        self._lock = threading.Lock()
        self._gen = {"clip": 0, "home": 0, "phrase": 0}      # номер «поколения»: старые ответы игнорируем
        self._goal = {"clip": None, "home": None}
        self._voices: dict = {}                              # "clip" / "phrase" -> процесс плеера
        self._pending: set = set()                           # какие части клипа ещё идут
        self._clip_led = False                               # клип менял цвет ленты
        self._base_led = None                                # цвет, который просила машина
        self._q: dict = {}

        self.play_ac = ActionClient(self, PlayMotion, "/play_motion")
        self.arm_ac = ActionClient(
            self, FollowJointTrajectory, "/follower/joint_trajectory_controller/follow_joint_trajectory")
        self.create_subscription(JointState, "/follower/joint_states", self._on_js, 10)
        self.led_pub = self.create_publisher(String, "/led_driver/mode", 10)

    # ---------- общее ----------
    def _on_js(self, msg: JointState) -> None:
        self._q = dict(zip(msg.name, msg.position))

    def _new_gen(self, slot: str) -> int:
        with self._lock:
            self._gen[slot] += 1
            return self._gen[slot]

    def _alive(self, slot: str, g: int) -> bool:
        with self._lock:
            return self._gen[slot] == g

    def _cancel(self, slot: str) -> None:
        with self._lock:
            gh, self._goal[slot] = self._goal[slot], None
        if gh is not None:
            gh.cancel_goal_async()

    def _on_goal(self, slot: str, g: int, fut, done) -> None:
        """Ответ на отправку цели. done(ok) вызывается один раз, когда цель закончилась."""
        gh = fut.result()
        if not gh.accepted:
            if self._alive(slot, g):
                done(False)
            return
        if not self._alive(slot, g):          # пока ждали ответ, нас остановили
            gh.cancel_goal_async()
            return
        with self._lock:
            self._goal[slot] = gh
        gh.get_result_async().add_done_callback(lambda f: self._on_result(slot, g, f, done))

    def _on_result(self, slot: str, g: int, fut, done) -> None:
        if not self._alive(slot, g):
            return
        res = fut.result().result
        ok = getattr(res, "success", None)
        if ok is None:                        # FollowJointTrajectory: error_code == 0
            ok = res.error_code == 0
        done(bool(ok))

    # ---------- звук ----------
    def _pick_audio(self, group: str):
        folder = os.path.join(self.get_parameter("voice_dir").value, group)
        files = glob.glob(os.path.join(folder, "*.wav")) + glob.glob(os.path.join(folder, "*.mp3"))
        return random.choice(files) if files else None

    def _speak(self, kind: str, path: str, done) -> None:
        """Играет файл в отдельном потоке; done() вызывается всегда: и после конца, и после сбоя."""
        try:
            cmd = ["mpg123", "-q", path] if path.lower().endswith(".mp3") else ["aplay", "-q", path]
            p = subprocess.Popen(cmd)
            self._voices[kind] = p
            p.wait(timeout=self.get_parameter("phrase_timeout").value)
        except Exception as e:                # нет плеера, завис и т.п.
            self.get_logger().warn(f"[voice] сбой озвучки: {e}")
            self._kill_voice(kind)
        done()

    def _kill_voice(self, kind: str) -> None:
        p = self._voices.pop(kind, None)
        if p is not None and p.poll() is None:
            p.kill()

    # ---------- клип ----------
    def _read_clip(self, clip: str):
        """-> (движение, группа голоса, цвет ленты). Нет XML -> просто одноимённое движение."""
        path = os.path.join(self.get_parameter("clip_conf_dir").value, clip + ".xml")
        if not os.path.isfile(path):
            return clip, None, None
        root = ET.parse(path).getroot()
        if root.tag != "clip":
            raise ValueError(f"{path}: корневой тег должен быть <clip>")

        def attr(tag: str, name: str):
            el = root.find(tag)
            if el is None:
                return None
            value = el.get(name)
            if not value:
                raise ValueError(f"{path}: у <{tag}> нет атрибута {name}")
            return value

        return attr("motion", "name"), attr("voice", "group"), attr("led", "mode")

    def play(self, clip: str) -> None:
        g = self._new_gen("clip")
        try:
            motion, voice, led = self._read_clip(clip)
        except Exception as e:                # битый XML и т.п.
            self.get_logger().error(f"[clip] {clip}: {e}")
            self.bus.post(E.CLIP_FAILED)
            return
        parts = {p for p, v in (("motion", motion), ("voice", voice)) if v}
        if not parts:
            self.get_logger().error(f"[clip] {clip}: в клипе нет ни движения, ни голоса")
            self.bus.post(E.CLIP_FAILED)
            return
        self.get_logger().info(f"[clip] {clip}: motion={motion} voice={voice} led={led}")
        with self._lock:
            self._pending = set(parts)
            self._clip_led = bool(led)
        if led:
            self.led_pub.publish(String(data=led))

        if motion:
            if not self.play_ac.server_is_ready():
                self.get_logger().error("нет сервера /play_motion")
                self._end_clip(g, E.CLIP_FAILED)
                return
            fut = self.play_ac.send_goal_async(PlayMotion.Goal(name=motion, speed=1.0))
            fut.add_done_callback(
                lambda f: self._on_goal("clip", g, f, lambda ok: self._part_done(g, "motion", ok)))
        if voice:
            path = self._pick_audio(voice)
            if path is None:
                self.get_logger().warn(f"[clip] нет файлов для голоса «{voice}»")
                self._part_done(g, "voice", True)
            else:
                threading.Thread(
                    target=self._speak, daemon=True,
                    args=("clip", path, lambda: self._part_done(g, "voice", True))).start()
        threading.Timer(self.get_parameter("clip_timeout").value, self._clip_timeout, args=(g,)).start()

    def _part_done(self, g: int, part: str, ok: bool) -> None:
        if not self._alive("clip", g):
            return
        if not ok:
            self._end_clip(g, E.CLIP_FAILED)
            return
        with self._lock:
            self._pending.discard(part)
            empty = not self._pending
        if empty:
            self._end_clip(g, E.CLIP_DONE)

    def _end_clip(self, g: int, ev: E) -> None:
        """Закончить клип ровно один раз: убрать остатки, вернуть цвет ленты, послать событие."""
        with self._lock:
            if self._gen["clip"] != g:
                return
            self._gen["clip"] += 1
            gh, self._goal["clip"] = self._goal["clip"], None
            restore, self._clip_led = self._clip_led, False
            self._pending = set()
        self._kill_voice("clip")
        if gh is not None and ev is E.CLIP_FAILED:
            gh.cancel_goal_async()
        if restore and self._base_led:
            self.led_pub.publish(String(data=self._base_led))
        self.bus.post(ev)

    def _clip_timeout(self, g: int) -> None:
        if self._alive("clip", g):
            self.get_logger().error("клип завис")
            self._end_clip(g, E.CLIP_FAILED)

    # ---------- домой ----------
    def go_home(self) -> None:
        g = self._new_gen("home")
        home = list(self.get_parameter("home_joints").value)
        if len(home) != 5 or not self._q or not self.arm_ac.server_is_ready():
            self.get_logger().error("go_home: нужны home_joints (5 чисел), /follower/joint_states и контроллер")
            self.bus.post(E.HOME_FAILED)
            return
        cur = [self._q[j] for j in ARM_JOINTS]
        d = max(abs(a - b) for a, b in zip(cur, home))
        if d < 0.02:                          # уже дома
            self.bus.post(E.HOME_REACHED)
            return
        t = d / self.get_parameter("home_speed").value + self.get_parameter("home_reserve").value
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ARM_JOINTS
        sec = int(t)
        goal.trajectory.points = [JointTrajectoryPoint(
            positions=home, time_from_start=Duration(sec=sec, nanosec=int((t - sec) * 1e9)))]
        self.get_logger().info(f"[go home] {t:.1f} с")
        fut = self.arm_ac.send_goal_async(goal)
        fut.add_done_callback(lambda f: self._on_goal("home", g, f, lambda ok: self._home_done(g, ok)))

    def _home_done(self, g: int, ok: bool) -> None:
        if self._alive("home", g):
            self._new_gen("home")             # событие одно: повторов не будет
            self.bus.post(E.HOME_REACHED if ok else E.HOME_FAILED)

    # ---------- фраза машины (say) ----------
    def say(self, phrase_group: str) -> None:
        g = self._new_gen("phrase")
        path = self._pick_audio(phrase_group)
        if path is None:
            self.get_logger().warn(f"[say] нет файлов для «{phrase_group}», жду 2 с")
            threading.Timer(2.0, self._phrase_done, args=(g,)).start()
            return
        self.get_logger().info(f"[say] {path}")
        threading.Thread(target=self._speak, daemon=True,
                         args=("phrase", path, lambda: self._phrase_done(g))).start()

    def _phrase_done(self, g: int) -> None:
        if self._alive("phrase", g):
            self._new_gen("phrase")
            self.bus.post(E.PHRASE_DONE)

    # ---------- стоп и лента ----------
    def stop(self) -> None:
        self.get_logger().info("[stop]")
        for slot in ("clip", "phrase", "home"):
            self._new_gen(slot)               # после этого старые события не придут
        self._cancel("clip")
        self._cancel("home")
        self._kill_voice("clip")
        self._kill_voice("phrase")
        with self._lock:
            restore, self._clip_led = self._clip_led, False
            self._pending = set()
        if restore and self._base_led:
            self.led_pub.publish(String(data=self._base_led))

    def set_led(self, mode: str) -> None:
        self._base_led = mode
        self.led_pub.publish(String(data=mode))
        self.play_ac = ActionClient(self, PlayMotion, "/play_motion")
        self.arm_ac = ActionClient(
            self, FollowJointTrajectory, "/follower/joint_trajectory_controller/follow_joint_trajectory")
        self.create_subscription(JointState, "/follower/joint_states", self._on_js, 10)
        self.led_pub = self.create_publisher(String, "/led_driver/mode", 10)

    # ---------- общее ----------
    def _on_js(self, msg: JointState) -> None:
        self._q = dict(zip(msg.name, msg.position))

    def _new_gen(self, slot: str) -> int:
        with self._lock:
            self._gen[slot] += 1
            return self._gen[slot]

    def _alive(self, slot: str, g: int) -> bool:
        with self._lock:
            return self._gen[slot] == g

    def _cancel(self, slot: str) -> None:
        with self._lock:
            gh, self._goal[slot] = self._goal[slot], None
        if gh is not None:
            gh.cancel_goal_async()

    # ---------- клип ----------
    def play(self, clip: str) -> None:
        g = self._new_gen("clip")
        if not self.play_ac.server_is_ready():
            self.get_logger().error("нет сервера /play_motion")
            self.bus.post(E.CLIP_FAILED)
            return
        self.get_logger().info(f"[clip] {clip}")
        fut = self.play_ac.send_goal_async(PlayMotion.Goal(name=clip, speed=1.0))
        fut.add_done_callback(lambda f: self._on_goal("clip", g, f, E.CLIP_DONE, E.CLIP_FAILED))
        threading.Timer(self.get_parameter("clip_timeout").value, self._clip_timeout, args=(g,)).start()

    def _clip_timeout(self, g: int) -> None:
        if self._alive("clip", g):
            self.get_logger().error("клип завис")
            self._new_gen("clip")
            self._cancel("clip")
            self.bus.post(E.CLIP_FAILED)

    def _on_goal(self, slot, g, fut, ok_ev, fail_ev) -> None:
        gh = fut.result()
        if not gh.accepted:
            if self._alive(slot, g):
                self.bus.post(fail_ev)
            return
        if not self._alive(slot, g):          # пока ждали ответ, нас остановили
            gh.cancel_goal_async()
            return
        with self._lock:
            self._goal[slot] = gh
        gh.get_result_async().add_done_callback(
            lambda f: self._on_result(slot, g, f, ok_ev, fail_ev))

    def _on_result(self, slot, g, fut, ok_ev, fail_ev) -> None:
        if not self._alive(slot, g):
            return
        self._new_gen(slot)                   # событие одно: повторов не будет
        res = fut.result().result
        ok = getattr(res, "success", None)
        if ok is None:                        # FollowJointTrajectory: error_code == 0
            ok = res.error_code == 0
        self.bus.post(ok_ev if ok else fail_ev)

    # ---------- домой ----------
    def go_home(self) -> None:
        g = self._new_gen("home")
        home = list(self.get_parameter("home_joints").value)
        if len(home) != 5 or not self._q or not self.arm_ac.server_is_ready():
            self.get_logger().error("go_home: нужны home_joints (5 чисел), /follower/joint_states и контроллер")
            self.bus.post(E.HOME_FAILED)
            return
        cur = [self._q[j] for j in ARM_JOINTS]
        d = max(abs(a - b) for a, b in zip(cur, home))
        if d < 0.02:                          # уже дома
            self.bus.post(E.HOME_REACHED)
            return
        t = d / self.get_parameter("home_speed").value + self.get_parameter("home_reserve").value
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ARM_JOINTS
        sec = int(t)
        goal.trajectory.points = [JointTrajectoryPoint(
            positions=home, time_from_start=Duration(sec=sec, nanosec=int((t - sec) * 1e9)))]
        self.get_logger().info(f"[go home] {t:.1f} с")
        fut = self.arm_ac.send_goal_async(goal)
        fut.add_done_callback(lambda f: self._on_goal("home", g, f, E.HOME_REACHED, E.HOME_FAILED))

    # ---------- голос ----------
    def say(self, phrase_group: str) -> None:
        g = self._new_gen("phrase")
        folder = os.path.join(self.get_parameter("voice_dir").value, phrase_group)
        files = glob.glob(os.path.join(folder, "*.wav")) + glob.glob(os.path.join(folder, "*.mp3"))
        if not files:
            self.get_logger().warn(f"[say] нет файлов для «{phrase_group}», жду 2 с")
            threading.Timer(2.0, self._phrase_done, args=(g,)).start()
            return
        f = random.choice(files)
        self.get_logger().info(f"[say] {f}")
        threading.Thread(target=self._speak, args=(g, f), daemon=True).start()

    def _speak(self, g: int, path: str) -> None:
        try:
            cmd = ["mpg123", "-q", path] if path.lower().endswith(".mp3") else ["aplay", "-q", path]
            p = subprocess.Popen(cmd)
            self._voice = p
            p.wait(timeout=self.get_parameter("phrase_timeout").value)
        except Exception as e:                # нет aplay, завис и т.п. - всё равно шлём PHRASE_DONE
            self.get_logger().warn(f"[say] сбой озвучки: {e}")
            if self._voice:
                self._voice.kill()
        self._phrase_done(g)

    def _phrase_done(self, g: int) -> None:
        if self._alive("phrase", g):
            self._new_gen("phrase")
            self.bus.post(E.PHRASE_DONE)

    # ---------- стоп и лента ----------
    def stop(self) -> None:
        self.get_logger().info("[stop]")
        for slot in ("clip", "phrase", "home"):
            self._new_gen(slot)               # после этого старые события не придут
        self._cancel("clip")
        self._cancel("home")
        if self._voice and self._voice.poll() is None:
            self._voice.kill()

    def set_led(self, mode: str) -> None:
        self.led_pub.publish(String(data=mode))
