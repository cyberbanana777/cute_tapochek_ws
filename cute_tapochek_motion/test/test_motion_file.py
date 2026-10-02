# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

import pytest

from cute_tapochek_motion.motion_file import (
    MotionFileError, MotionWriter, load_motion)
from cute_tapochek_motion.playback import (
    build_playback_points, interpolate, motion_time_at)

JOINTS = ['a', 'b', 'g']


def _write(path, rows, meta=None):
    with MotionWriter(str(path), JOINTS, meta) as w:
        for t, *pos in rows:
            w.write(t, pos)


def test_roundtrip(tmp_path):
    f = tmp_path / 'm.csv'
    _write(f, [(0.0, 1, 2, 3), (0.01, 1.1, 2.1, 3.1)], {'source_topic': '/x'})
    m = load_motion(str(f))
    assert m.joint_names == JOINTS
    assert m.times == [0.0, 0.01]
    assert m.positions[1] == pytest.approx([1.1, 2.1, 3.1])
    assert m.meta['source_topic'] == '/x'
    assert m.column('g') == pytest.approx([3, 3.1])


def test_non_increasing_times_dropped(tmp_path):
    f = tmp_path / 'm.csv'
    f.write_text('time,a\n0,0\n0.1,1\n0.1,2\n0.05,3\n0.2,4\n')
    m = load_motion(str(f))
    assert m.times == [0, 0.1, 0.2]
    assert m.dropped_samples == 2


@pytest.mark.parametrize('text', [
    '', '# only comments\n', 'a,b\n0,1\n', 'time,a\n0,1,2\n', 'time,a\n0,x\n',
    'time,a\n', 'time,a,a\n0,1,2\n',
])
def test_bad_files(tmp_path, text):
    f = tmp_path / 'm.csv'
    f.write_text(text)
    with pytest.raises(MotionFileError):
        load_motion(str(f))


def test_interpolate_clamps():
    assert interpolate([0, 1], [0, 10], -1) == 0
    assert interpolate([0, 1], [0, 10], 0.25) == pytest.approx(2.5)
    assert interpolate([0, 1], [0, 10], 5) == 10


def test_playback_points(tmp_path):
    f = tmp_path / 'm.csv'
    _write(f, [(0.0, 1, 2, 0), (1.0, 2, 3, 0), (2.0, 3, 4, 0)])
    m = load_motion(str(f))
    pts = build_playback_points(m, ['a', 'b'], approach_time=2.0, speed=2.0,
                                start_positions=[0, 0], approach_rate=10)
    times = [t for t, _ in pts]
    assert all(t2 > t1 for t1, t2 in zip(times, times[1:]))
    # approach ends exactly at the first recorded pose
    assert pts[19] == (pytest.approx(2.0), pytest.approx([1, 2]))
    # recording time-scaled by 1/speed
    assert pts[-1][0] == pytest.approx(2.0 + 2.0 / 2.0)
    assert pts[-1][1] == pytest.approx([3, 4])
    # without start pose: single approach point
    pts2 = build_playback_points(m, ['a'], approach_time=1.0)
    assert pts2[0] == (1.0, [1])
    assert motion_time_at(3.0, m, approach_time=2.0, speed=2.0) == pytest.approx(2.0)
