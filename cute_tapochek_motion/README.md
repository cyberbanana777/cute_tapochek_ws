# cute_tapochek_motion

[English version](README_EN.md)

Подсистема движений робота cute_tapochek. Нода `motion_server` хранит библиотеку движений, записывает новые движения с leader-руки и проигрывает их на follower.

Bringup рук сюда не входит: `motion_server` ожидает, что follower (а для записи и leader) уже подняты из репозитория `soarm101`.

## Возможности

- Библиотека движений в виде CSV-файлов в папке `motions/` репозитория: файлы можно смотреть, править и коммитить в git.
- Запись с leader-руки, в том числе с автоматическим стартом, когда рука начинает двигаться.
- Предпросмотр записи на follower до сохранения.
- Проигрывание одной траекторией через `joint_trajectory_controller`: тайминг выдерживает контроллер в своём цикле реального времени, а не Python.
- Плавный подъезд к первой позе движения и масштабирование скорости.
- Синхронное с траекторией управление схватом.
- Вытеснение: новая цель прерывает текущую.
- Автоматическая пауза телеуправления на время проигрывания.

## Узел `motion_server`

Постоянно работающая нода. Все её сервисы и action находятся в корневом пространстве имён, статус — в `/motion_server/status`.

### Параметры

Все параметры с комментариями лежат в `config/motion_server.yaml`. `motions_dir` задаётся launch-файлом.

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `motions_dir` | string | `''` | Папка с библиотекой движений. Обязательный: при пустом значении нода не стартует |
| `leader_topic` | string | `/leader/joint_states` | Откуда записывать движение |
| `follower_state_topic` | string | `/follower/joint_states` | Текущая поза follower: начальная точка подъезда |
| `arm_action` | string | `/follower/joint_trajectory_controller/follow_joint_trajectory` | Action контроллера траекторий руки |
| `gripper_action` | string | `/follower/gripper_controller/gripper_cmd` | Action контроллера схвата |
| `arm_joints` | string[] | 5 суставов руки | Суставы, которые проигрываются траекторией |
| `record_joints` | string[] | 5 суставов руки + `gripper_jaw_joint` | Суставы, которые записываются в файл |
| `gripper_joint` | string | `gripper_jaw_joint` | Сустав схвата |
| `play_gripper` | bool | `true` | Проигрывать ли схват |
| `default_approach_time` | double | `2.0` | Время подъезда к первой позе по умолчанию, с. Минимум 0,5 с |
| `max_speed` | double | `2.0` | Максимально допустимый множитель скорости |
| `start_delay` | double | `0.2` | Задержка старта траектории после отправки цели, с |
| `motion_threshold` | double | `0.02` | Сдвиг любого сустава, после которого считается, что leader начал двигаться, рад |
| `default_max_recording` | double | `120.0` | Предельная длительность одной записи по умолчанию, с |
| `gripper_rate` | double | `20.0` | Частота отправки целей схвату при проигрывании, Гц |
| `gripper_threshold` | double | `0.005` | Минимальное изменение позиции схвата для новой цели, рад |
| `gripper_max_effort` | double | `10.0` | `max_effort` в целях схвата |
| `teleop_services` | string[] | `[/arm_relay/set_enabled, /gripper_relay/set_enabled]` | Сервисы паузы телеуправления |
| `pause_teleop_on_play` | bool | `true` | Ставить ли телеуправление на паузу перед проигрыванием |

Суставы руки по умолчанию: `shoulder_pan_joint`, `shoulder_lift_joint`, `elbow_flex_joint`, `wrist_flex_joint`, `wrist_roll_joint`.

### Действия

| Action | Тип | Описание |
|--------|-----|----------|
| `/play_motion` | `cute_tapochek_interfaces/action/PlayMotion` | Проиграть движение из библиотеки или черновик |

### Сервисы

| Сервис | Тип | Описание |
|--------|-----|----------|
| `/stop_motion` | `std_srvs/Trigger` | Остановить проигрывание, рука останавливается на месте |
| `/list_motions` | `cute_tapochek_interfaces/srv/ListMotions` | Список движений с длительностями и описаниями |
| `/start_recording` | `cute_tapochek_interfaces/srv/StartRecording` | Начать запись с leader |
| `/stop_recording` | `std_srvs/Trigger` | Закончить запись, она становится черновиком |
| `/discard_recording` | `std_srvs/Trigger` | Выбросить текущую запись, а если её нет — черновик |
| `/save_motion` | `cute_tapochek_interfaces/srv/SaveMotion` | Сохранить черновик в библиотеку |
| `/delete_motion` | `cute_tapochek_interfaces/srv/DeleteMotion` | Удалить движение из библиотеки |
| `/set_teleop` | `std_srvs/SetBool` | Включить (`true`) или поставить на паузу (`false`) телеуправление |

### Топики

| Топик | Направление | Тип | Описание |
|-------|-------------|-----|----------|
| `/leader/joint_states` | подписка | `sensor_msgs/JointState` | Источник записи |
| `/follower/joint_states` | подписка | `sensor_msgs/JointState` | Текущая поза follower |
| `/motion_server/status` | публикация, 5 Гц | `cute_tapochek_interfaces/msg/MotionServerStatus` | Состояние сервера |

## Запуск

```bash
ros2 launch cute_tapochek_motion motion_server.launch.py
ros2 launch cute_tapochek_motion motion_server.launch.py motions_dir:=$HOME/cute_ws/src/motions
```

Launch-файл поднимает только `motion_server`. Папка библиотеки выбирается в таком порядке:

1. Аргумент `motions_dir:=...`.
2. Переменная окружения `CUTE_TAPOCHEK_MOTIONS_DIR`.
3. Папка `motions/` в исходниках репозитория. Работает, только если workspace собран с `--symlink-install`: тогда launch-файл находит исходники по символической ссылке.

Если ни один вариант не сработал, нода завершается с сообщением о пустом `motions_dir`. Если папки нет, она будет создана.

## Запись движения

1. `/start_recording`. С `start_on_motion: true` сервер ждёт, пока любой сустав leader сдвинется больше чем на `motion_threshold`. Последний неподвижный отсчёт становится моментом `t = 0`, поэтому начало движения не теряется.
2. `/stop_recording`. Запись становится черновиком. Если leader так и не сдвинулся или отсчётов меньше двух, черновик не создаётся.
3. Предпросмотр: `/play_motion` с `play_draft: true`.
4. `/save_motion` с именем и описанием. После сохранения черновик удаляется.

Запись останавливается сама, когда достигнута `max_duration` (или `default_max_recording`). Черновик хранится только в памяти: при перезапуске сервера он пропадает.

## Проигрывание

- Неизвестное имя отклоняется сразу, ещё до принятия цели.
- Перед стартом, если `pause_teleop_on_play: true`, сервер ставит телеуправление на паузу. Снимается пауза только явно: сервисом `/set_teleop` или кнопкой в Motion Studio.
- Траектория строится из двух участков: плавный подъезд от текущей позы follower к первой позе записи за `approach_time` (профиль smoothstep, 50 точек в секунду) и сама запись, время которой поделено на `speed`. Если поза follower неизвестна, подъезд задаётся одной точкой, и интерполирует контроллер.
- Вся траектория отправляется в `joint_trajectory_controller` одной целью.
- Схват проигрывается отдельно: `gripper_controller` принимает одну цель за раз, поэтому сервер отправляет ему позицию из записи `gripper_rate` раз в секунду, синхронно с траекторией. Новая цель уходит, только если позиция изменилась больше чем на `gripper_threshold`.
- Новая цель `/play_motion` прерывает текущую. Прерванная завершается с `success: false` и сообщением `<имя>: interrupted`.
- Отмена цели или `/stop_motion` останавливают руку на месте.
- Feedback публикуется с частотой `gripper_rate`: `progress` (0..1), `elapsed`, `total`.

## Формат файла движения

Каждое движение — отдельный файл `motions/<имя>.csv`. Имя файла и есть имя движения: латиница, цифры, `_` и `-`, до 64 символов, начинается с буквы или цифры.

```
# cute_tapochek_motion v1
# source_topic: /leader/joint_states
# recorded_at: 2026-10-02T20:55:58
# name: ahe
# description: Эххх
# saved_at: 2026-10-02T20:56:30
time,shoulder_pan_joint,shoulder_lift_joint,elbow_flex_joint,wrist_flex_joint,wrist_roll_joint,gripper_jaw_joint
0.000000,0.012000,-1.745000,...
0.010000,0.013000,-1.744000,...
```

- Строки, начинающиеся с `#`, — метаданные в виде `ключ: значение` или комментарии.
- Первая строка без `#` — заголовок. Первый столбец — `time`, дальше — суставы.
- Время в секундах от начала записи, позиции в радианах.
- Отсчёты с невозрастающим временем при загрузке пропускаются. Файлы с пропущенными значениями, NaN или неверным числом столбцов считаются битыми: они не показываются в списке и не проигрываются.
- Сохранение атомарное: файл пишется во временный `<имя>.csv.tmp` и затем переименовывается, поэтому сбой не оставит в библиотеке недописанный файл.

Отдельного индекса нет: описание хранится в самом файле. Поэтому движения можно переименовывать, копировать и удалять прямо в файловом менеджере. Сервер перечитывает файл, если изменилось время его модификации.

## Полезные проверки

```bash
# Состояние сервера
ros2 topic echo /motion_server/status

# Библиотека
ros2 service call /list_motions cute_tapochek_interfaces/srv/ListMotions

# Запись
ros2 service call /start_recording cute_tapochek_interfaces/srv/StartRecording "{start_on_motion: true}"
ros2 service call /stop_recording std_srvs/srv/Trigger
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{play_draft: true}" --feedback
ros2 service call /save_motion cute_tapochek_interfaces/srv/SaveMotion "{name: wave_hello, description: 'машет рукой'}"
ros2 service call /discard_recording std_srvs/srv/Trigger

# Проигрывание
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: wave_hello}" --feedback
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: wave_hello, speed: 0.5, approach_time: 3.0}"
ros2 service call /stop_motion std_srvs/srv/Trigger

# Удаление
ros2 service call /delete_motion cute_tapochek_interfaces/srv/DeleteMotion "{name: wave_hello}"

# Телеуправление
ros2 service call /set_teleop std_srvs/srv/SetBool "{data: true}"
ros2 service call /set_teleop std_srvs/srv/SetBool "{data: false}"
```

## Тесты

Модули `library`, `motion_file` и `playback` не импортируют ROS и покрыты unit-тестами: формат файла, отбраковка битых файлов и плохих имён, атомарное сохранение, буфер записи и старт по движению, интерполяция и построение траектории.

```bash
colcon test --packages-select cute_tapochek_motion
colcon test-result --verbose
# или без colcon, из каталога пакета:
python3 -m pytest test
```

## Зависимости

- ROS 2:
  - `rclpy`
  - `cute_tapochek_interfaces`
  - `sensor_msgs`
  - `trajectory_msgs`
  - `control_msgs`
  - `std_srvs`
  - `launch`, `launch_ros`, `ament_index_python`
- Репозиторий `soarm101`:
  - поднятые контроллеры follower: `joint_trajectory_controller` и `gripper_controller`;
  - `open_loop_control: true` у `joint_trajectory_controller` в `real_controllers.yaml`;
  - патч `soarm101_teleop_pause.patch` (сервис `~/set_enabled` у `arm_relay` и `gripper_relay`). Без него проигрывание работает, но во время телеуправления relay будет бороться с сервером за руку.

## Версия

**0.1.0** — первая версия: библиотека движений, запись с leader, предпросмотр черновика, проигрывание с вытеснением, пауза телеуправления.
