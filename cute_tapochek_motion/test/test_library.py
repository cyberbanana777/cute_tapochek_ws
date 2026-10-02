# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

import os

import pytest

from cute_tapochek_motion.library import (
    LibraryError, MotionLibrary, RecordingBuffer, check_name)

J = ['a', 'b']


def _rec(start_on_motion=True, **kw):
    buf = RecordingBuffer(J, start_on_motion=start_on_motion, threshold=0.1, **kw)
    return buf


def test_names():
    assert check_name(' wave_1 ') == 'wave_1'
    for bad in ['', '_x', 'a b', 'привет', 'a/b', 'x' * 65, '../etc']:
        with pytest.raises(LibraryError):
            check_name(bad)


def test_recording_waits_for_motion():
    buf = _rec()
    buf.feed(10.0, J, [0, 0])
    buf.feed(10.1, J, [0.05, 0])      # below threshold
    assert not buf.started
    buf.feed(10.2, J, [0.2, 0])       # moved
    buf.feed(10.3, J, [0.3, 0])
    m = buf.to_motion()
    assert m.times == pytest.approx([0.0, 0.1, 0.2])   # last idle sample is t=0
    assert m.positions[0] == pytest.approx([0.05, 0])


def test_recording_immediate_and_limits():
    buf = _rec(start_on_motion=False, max_duration=0.25)
    assert buf.feed(0.0, ['a'], [1]) is False           # missing joint
    for i in range(10):
        buf.feed(i * 0.1, J, [i, i])
    buf.feed(0.05, J, [9, 9])                           # out of order: ignored
    assert buf.full
    assert buf.to_motion().times == pytest.approx([0, 0.1, 0.2, 0.3])
    assert _rec().to_motion() is None


def test_library_roundtrip(tmp_path):
    lib = MotionLibrary(str(tmp_path / 'motions'))
    buf = _rec(start_on_motion=False)
    for i in range(3):
        buf.feed(i * 0.5, J, [i, -i])
    m = buf.to_motion()
    path = lib.save('wave', m, 'say\nhello')
    assert os.path.basename(path) == 'wave.csv'
    with pytest.raises(LibraryError):
        lib.save('wave', m)                              # no overwrite
    lib.save('wave', m, 'hi again', overwrite=True)
    assert lib.list() == [('wave', pytest.approx(1.0), 'hi again')]
    assert lib.load('wave').positions[2] == pytest.approx([2, -2])
    (tmp_path / 'motions' / 'broken.csv').write_text('garbage')
    (tmp_path / 'motions' / 'notes.txt').write_text('x')
    assert [n for n, _, _ in lib.list()] == ['wave']     # broken file skipped
    lib.delete('wave')
    assert not lib.exists('wave')
    with pytest.raises(LibraryError):
        lib.load('wave')
    assert not any(f.endswith('.tmp') for f in os.listdir(tmp_path / 'motions'))
