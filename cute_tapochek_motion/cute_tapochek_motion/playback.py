# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT
# Details in the LICENSE file in the root of the package.

"""Pure helpers for playback (no ROS imports, unit-testable)."""

import bisect
from typing import List, Optional, Sequence, Tuple

from .motion_file import Motion


def interpolate(times: Sequence[float], values: Sequence[float],
                t: float) -> float:
    """Linear interpolation, clamped to the first/last value."""
    if t <= times[0]:
        return values[0]
    if t >= times[-1]:
        return values[-1]
    i = bisect.bisect_right(times, t)
    t0, t1 = times[i - 1], times[i]
    a = (t - t0) / (t1 - t0)
    return values[i - 1] + a * (values[i] - values[i - 1])


def smoothstep(s: float) -> float:
    """Map 0..1 to 0..1 with zero slope at both ends."""
    s = min(1.0, max(0.0, s))
    return s * s * (3.0 - 2.0 * s)


def build_playback_points(
        motion: Motion,
        joints: Sequence[str],
        approach_time: float,
        speed: float = 1.0,
        start_positions: Optional[Sequence[float]] = None,
        approach_rate: float = 50.0,
) -> List[Tuple[float, List[float]]]:
    """
    Build (time_from_start, positions) points for a JointTrajectory.

    Segment 1 (0..approach_time): smooth move from start_positions to the
    first recorded pose. If start_positions is unknown, a single point at
    approach_time is used and the controller interpolates on its own.

    Segment 2: the recording itself, time-scaled by 1/speed.
    """
    if approach_time <= 0.0:
        raise ValueError('approach_time must be > 0')
    if speed <= 0.0:
        raise ValueError('speed must be > 0')
    idx = [motion.joint_names.index(j) for j in joints]
    first = [motion.positions[0][i] for i in idx]

    points: List[Tuple[float, List[float]]] = []
    if start_positions is not None and approach_rate > 0.0:
        if len(start_positions) != len(joints):
            raise ValueError('start_positions length != joints length')
        n = max(1, int(round(approach_time * approach_rate)))
        for k in range(1, n + 1):
            s = k / n
            a = smoothstep(s)
            points.append((
                approach_time * s,
                [sp + (fp - sp) * a for sp, fp in zip(start_positions, first)],
            ))
    else:
        points.append((approach_time, first))

    t0 = motion.times[0]
    for t, row in zip(motion.times[1:], motion.positions[1:]):
        points.append((approach_time + (t - t0) / speed,
                       [row[i] for i in idx]))
    return points


def motion_time_at(elapsed: float, motion: Motion, approach_time: float,
                   speed: float) -> float:
    """Map time since trajectory start to time inside the recording."""
    return motion.times[0] + (elapsed - approach_time) * speed
