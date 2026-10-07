# realsense_d435i_configs

Четыре пресета для `realsense2_camera` + один launch-файл. IMU везде выключен.

| mode                   | RGB            | Depth        | PointCloud | USB  |
|------------------------|----------------|--------------|------------|------|
| `rgb_usb3`             | 1920x1080 @ 30 | -            | -          | 3.x  |
| `rgb_usb2`             | 640x480 @ 30   | -            | -          | 2.0  |
| `rgb_depth`            | 1280x720 @ 30  | 848x480 @ 30 | -          | 3.x  |
| `rgb_depth_pointcloud` | 1280x720 @ 30  | 848x480 @ 30 | да (цветное) | 3.x |

## Запуск
    ros2 launch realsense_d435i_configs d435i.launch.py mode:=rgb_usb3
    ros2 launch realsense_d435i_configs d435i.launch.py mode:=rgb_usb2
    ros2 launch realsense_d435i_configs d435i.launch.py mode:=rgb_depth
    ros2 launch realsense_d435i_configs d435i.launch.py mode:=rgb_depth_pointcloud serial_no:=123456789
