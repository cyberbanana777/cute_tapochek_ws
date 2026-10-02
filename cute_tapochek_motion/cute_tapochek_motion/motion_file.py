# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT
# Details in the LICENSE file in the root of the package.

"""
Motion file format: CSV with a commented metadata header.

Example:
    # cute_tapochek motion v1
    # source_topic: /leader/joint_states
    # recorded_at: 2026-10-02T18:40:00
    time,shoulder_pan_joint,shoulder_lift_joint,...
    0.000000,0.012000,-1.745000,...
    0.010000,0.013000,-1.744000,...

- Lines starting with '#' are metadata ("key: value") or comments.
- The first non-comment line is the column header; the first column is 'time'.
- time is in seconds from the start of the recording, positions in radians.
"""

import csv
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List

MAGIC = 'cute_tapochek_motion'
FORMAT_VERSION = 1


class MotionFileError(Exception):
    """Raised when a motion file cannot be parsed."""


@dataclass
class Motion:
    joint_names: List[str]
    times: List[float]
    positions: List[List[float]]  # positions[i][j]: joint j at sample i
    meta: Dict[str, str] = field(default_factory=dict)
    dropped_samples: int = 0       # non-increasing timestamps skipped on load

    def __len__(self) -> int:
        return len(self.times)

    @property
    def duration(self) -> float:
        return self.times[-1] - self.times[0] if self.times else 0.0

    def column(self, joint: str) -> List[float]:
        idx = self.joint_names.index(joint)
        return [row[idx] for row in self.positions]


class MotionWriter:
    """
    Stream samples to a motion file.

    Flushes periodically, so an interrupted recording still leaves
    a valid file on disk.
    """

    def __init__(self, path: str, joint_names: List[str],
                 meta: Dict[str, str] = None, flush_every: int = 50):
        self.path = path
        self._n_joints = len(joint_names)
        self._flush_every = max(1, flush_every)
        self._count = 0
        self._f = open(path, 'w', newline='')
        self._f.write(f'# {MAGIC} v{FORMAT_VERSION}\n')
        for key, value in (meta or {}).items():
            value = ' '.join(str(value).split())  # keep metadata on one line
            self._f.write(f'# {key}: {value}\n')
        self._csv = csv.writer(self._f)
        self._csv.writerow(['time', *joint_names])

    @property
    def count(self) -> int:
        return self._count

    def write(self, t: float, positions: List[float]) -> None:
        if len(positions) != self._n_joints:
            raise ValueError(
                f'expected {self._n_joints} positions, got {len(positions)}')
        self._csv.writerow([f'{t:.6f}', *(f'{p:.6f}' for p in positions)])
        self._count += 1
        if self._count % self._flush_every == 0:
            self._f.flush()

    def close(self) -> None:
        if not self._f.closed:
            self._f.flush()
            self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def load_motion(path: str) -> Motion:
    """Load and validate a motion file."""
    meta: Dict[str, str] = {}
    data_lines: List[str] = []
    with open(path, newline='') as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if s.startswith('#'):
                body = s[1:].strip()
                if ':' in body:
                    key, value = body.split(':', 1)
                    meta[key.strip()] = value.strip()
                continue
            data_lines.append(s)

    if not data_lines:
        raise MotionFileError(f'{path}: no header and no data')

    reader = csv.reader(data_lines)
    header = [h.strip() for h in next(reader)]
    if len(header) < 2 or header[0] != 'time':
        raise MotionFileError(
            f'{path}: header must be "time,<joint>,...", got {header}')
    joints = header[1:]
    if len(set(joints)) != len(joints):
        raise MotionFileError(f'{path}: duplicate joint names in header')

    times: List[float] = []
    positions: List[List[float]] = []
    dropped = 0
    prev_t = None
    for row_idx, row in enumerate(reader, start=1):
        if len(row) != len(header):
            raise MotionFileError(
                f'{path}: data row {row_idx} has {len(row)} columns, '
                f'expected {len(header)}')
        try:
            values = [float(x) for x in row]
        except ValueError as e:
            raise MotionFileError(f'{path}: data row {row_idx}: {e}') from e
        if not all(math.isfinite(v) for v in values):
            raise MotionFileError(f'{path}: data row {row_idx}: NaN/inf')
        t = values[0]
        if prev_t is not None and t <= prev_t:
            dropped += 1
            continue
        times.append(t)
        positions.append(values[1:])
        prev_t = t

    if not times:
        raise MotionFileError(f'{path}: no samples')

    return Motion(joints, times, positions, meta, dropped)


def save_motion(path: str, motion: Motion) -> None:
    """
    Write a whole Motion to `path` atomically.

    The file is written next to the target and then renamed, so a crash
    never leaves a half-written motion in the library.
    """
    tmp = f'{path}.tmp'
    try:
        with MotionWriter(tmp, motion.joint_names, motion.meta) as w:
            for t, row in zip(motion.times, motion.positions):
                w.write(t, row)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
