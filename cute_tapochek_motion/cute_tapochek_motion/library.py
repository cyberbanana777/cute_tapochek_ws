# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

"""
Motion library and recording buffer. No ROS imports: unit-testable.

Library layout: one CSV file per motion, the file name is the motion name.

    motions/
        wave.csv
        sigh.csv

Description and creation time live in the CSV header, so there is no
separate index file that could get out of sync with the files.
"""

import os
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from .motion_file import Motion, MotionFileError, load_motion, save_motion

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


class LibraryError(Exception):
    """User-facing library error (bad name, missing motion...)."""


def check_name(name: str) -> str:
    name = (name or '').strip()
    if not NAME_RE.match(name):
        raise LibraryError(
            f'bad motion name "{name}": use latin letters, digits, "_" and "-", '
            'up to 64 chars, starting with a letter or digit')
    return name


class MotionLibrary:
    """A directory of motion files. Thread-safe, caches parsed files by mtime."""

    def __init__(self, directory: str):
        self.directory = os.path.abspath(os.path.expanduser(directory))
        os.makedirs(self.directory, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: Dict[str, Tuple[float, Motion]] = {}

    def path_of(self, name: str) -> str:
        return os.path.join(self.directory, f'{check_name(name)}.csv')

    def exists(self, name: str) -> bool:
        return os.path.isfile(self.path_of(name))

    def names(self) -> List[str]:
        out = []
        for fn in os.listdir(self.directory):
            stem, ext = os.path.splitext(fn)
            if ext == '.csv' and NAME_RE.match(stem):
                out.append(stem)
        return sorted(out)

    def load(self, name: str) -> Motion:
        path = self.path_of(name)
        if not os.path.isfile(path):
            raise LibraryError(f'motion "{name}" not found in {self.directory}')
        mtime = os.path.getmtime(path)
        with self._lock:
            cached = self._cache.get(name)
            if cached and cached[0] == mtime:
                return cached[1]
        try:
            motion = load_motion(path)
        except MotionFileError as e:
            raise LibraryError(str(e)) from e
        with self._lock:
            self._cache[name] = (mtime, motion)
        return motion

    def list(self) -> List[Tuple[str, float, str]]:
        """Return (name, duration, description); broken files are skipped."""
        out = []
        for name in self.names():
            try:
                m = self.load(name)
            except LibraryError:
                continue
            out.append((name, m.duration, m.meta.get('description', '')))
        return out

    def save(self, name: str, motion: Motion, description: str = '',
             overwrite: bool = False) -> str:
        path = self.path_of(name)
        if os.path.exists(path) and not overwrite:
            raise LibraryError(f'motion "{name}" already exists')
        meta = dict(motion.meta)
        meta['name'] = name
        meta['description'] = description
        meta['saved_at'] = datetime.now().isoformat(timespec='seconds')
        to_save = Motion(motion.joint_names, motion.times, motion.positions, meta)
        save_motion(path, to_save)
        with self._lock:
            self._cache.pop(name, None)
        return path

    def delete(self, name: str) -> None:
        path = self.path_of(name)
        if not os.path.isfile(path):
            raise LibraryError(f'motion "{name}" not found')
        os.remove(path)
        with self._lock:
            self._cache.pop(name, None)


class RecordingBuffer:
    """
    Collect JointState samples into a Motion.

    With start_on_motion the recording begins only when any joint moves more
    than `threshold` from the pose at the start; the last idle sample becomes
    t = 0, so the very beginning of the movement is kept.
    """

    def __init__(self, joints: Sequence[str], start_on_motion: bool = True,
                 threshold: float = 0.02, max_duration: float = 0.0,
                 meta: Optional[Dict[str, str]] = None):
        self.joints = list(joints)
        self.start_on_motion = start_on_motion
        self.threshold = threshold
        self.max_duration = max_duration
        self.meta = dict(meta or {})
        self.times: List[float] = []
        self.positions: List[List[float]] = []
        self.started = False
        self.full = False  # max_duration reached
        self._t0 = None
        self._ref = None
        self._prev = None

    @property
    def duration(self) -> float:
        return self.times[-1] if self.times else 0.0

    def feed(self, stamp: float, names: Sequence[str],
             values: Sequence[float]) -> bool:
        """Add a sample. Return False if the joints are missing in it."""
        if self.full:
            return True
        by_name = dict(zip(names, values))
        try:
            pos = [float(by_name[j]) for j in self.joints]
        except KeyError:
            return False

        if not self.started:
            if self.start_on_motion:
                if self._ref is None:
                    self._ref = pos
                    self._prev = (stamp, pos)
                    return True
                if max(abs(a - b) for a, b in zip(pos, self._ref)) < self.threshold:
                    self._prev = (stamp, pos)
                    return True
                self._begin(*self._prev)
            else:
                self._begin(stamp, pos)
                return True

        t = stamp - self._t0
        if t <= self.times[-1]:
            return True  # duplicate / out-of-order stamp
        self.times.append(t)
        self.positions.append(pos)
        if self.max_duration > 0.0 and t >= self.max_duration:
            self.full = True
        return True

    def _begin(self, stamp: float, pos: List[float]):
        self.started = True
        self._t0 = stamp
        self.times.append(0.0)
        self.positions.append(pos)

    def to_motion(self) -> Optional[Motion]:
        if len(self.times) < 2:
            return None
        return Motion(list(self.joints), list(self.times),
                      [list(p) for p in self.positions], dict(self.meta))
