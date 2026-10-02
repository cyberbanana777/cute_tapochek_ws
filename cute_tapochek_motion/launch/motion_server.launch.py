# Copyright (c) 2026 Alice Zenina and Alexander Grachev RTU MIREA (Russia)
# SPDX-License-Identifier: MIT

"""
Start motion_server only. The arm (follower/leader bringup, teleop) is launched elsewhere.

motions_dir default:
  1. launch argument motions_dir:=...
  2. environment variable CUTE_TAPOCHEK_MOTIONS_DIR
  3. <repo>/motions, if the workspace was built with --symlink-install
     (then this file resolves back into the source tree)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _repo_motions_dir() -> str:
    real = os.path.realpath(__file__)            # .../<repo>/cute_tapochek_motion/launch/x.py
    pkg_dir = os.path.dirname(os.path.dirname(real))
    if os.path.isfile(os.path.join(pkg_dir, 'setup.py')):   # source tree, not install/
        return os.path.join(os.path.dirname(pkg_dir), 'motions')
    return ''


def generate_launch_description():
    default_dir = os.environ.get('CUTE_TAPOCHEK_MOTIONS_DIR', '') or _repo_motions_dir()
    params = os.path.join(
        get_package_share_directory('cute_tapochek_motion'), 'config', 'motion_server.yaml')

    return LaunchDescription([
        DeclareLaunchArgument(
            'motions_dir', default_value=default_dir,
            description='Directory with motion CSV files (inside the repo)'),
        Node(
            package='cute_tapochek_motion',
            executable='motion_server',
            name='motion_server',
            output='screen',
            parameters=[params, {'motions_dir': LaunchConfiguration('motions_dir')}],
        ),
    ])
