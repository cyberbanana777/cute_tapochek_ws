# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

"""Run Motion Studio as a standalone window: ros2 run cute_tapochek_gui motion_studio."""

import sys

from rqt_gui.main import Main


def main():
    sys.exit(Main().main(sys.argv, standalone='cute_tapochek_gui.motion_studio.MotionStudio'))


if __name__ == '__main__':
    main()
