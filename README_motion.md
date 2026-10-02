# cute_tapochek: движения

Подсистема записи и проигрывания движений для робота на базе SO-ARM101.

| Пакет | Что внутри |
|---|---|
| `cute_tapochek_interfaces` | action `PlayMotion`, сервисы библиотеки и записи, сообщение статуса |
| `cute_tapochek_motion` | нода `motion_server`: библиотека, запись с leader, проигрывание на follower |
| `cute_tapochek_gui` | rqt-плагин «Motion Studio» |
| `motions/` | сами движения, по CSV-файлу на движение (коммитятся в git) |

Bringup рук сюда не входит: `motion_server` ожидает, что follower (и leader для записи) уже подняты.

## Зависимости

- Репозиторий `soarm101` с патчем `soarm101_teleop_pause.patch`: он добавляет `arm_relay` и `gripper_relay` сервис паузы `~/set_enabled`. Без него проигрывание работает, но предпросмотр во время телеуправления будет бороться с relay.
- В `real_controllers.yaml` у JTC должно стоять `open_loop_control: true`.

## Сборка

```bash
cd ~/cute_ws
colcon build --symlink-install --packages-up-to cute_tapochek_gui cute_tapochek_motion
source install/setup.bash
```

С `--symlink-install` launch-файл находит папку `motions/` в репозитории сам. Без него укажи её явно: `motions_dir:=...` в launch или переменная окружения `CUTE_TAPOCHEK_MOTIONS_DIR`.

После первой сборки rqt нужно один раз пересканировать плагины: `rqt --force-discover`.

## Как записать движение

```bash
# терминал 1: руки и телеуправление (твой launch из soarm101)
ros2 launch soarm101_teleoperate teleoperate.launch.py
# терминал 2
ros2 launch cute_tapochek_motion motion_server.launch.py
# терминал 3
ros2 run cute_tapochek_gui motion_studio      # или rqt → Plugins → Cute Tapochek → Motion Studio
```

1. **● Записать**. С галочкой «ждать начала движения» запись стартует, когда сдвинешь leader.
2. **■ Остановить**. Запись становится черновиком.
3. **▶ Посмотреть** проигрывает черновик на follower. Телеуправление при этом само встаёт на паузу.
4. Понравилось — введи имя и описание и нажми **Сохранить**. Нет — **✕ Выбросить** или просто запиши заново.
5. Чтобы снова управлять с leader, нажми **Включить** в блоке «Телеуправление». Follower плавно за 2 с догонит leader и дальше пойдёт за ним.

## Как проигрывать из своего кода

Action `/play_motion` (`cute_tapochek_interfaces/action/PlayMotion`):

```bash
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: wave_hello}" --feedback
ros2 action send_goal /play_motion cute_tapochek_interfaces/action/PlayMotion "{name: sigh, speed: 0.7}"
```

- Неизвестное имя — цель отклоняется сразу.
- Новая цель **прерывает** текущую. Прерванная завершается с `success: false`, `message: "...: interrupted"`.
- Отмена цели или сервис `/stop_motion` останавливают руку на месте.
- Feedback: `progress` (0..1), `elapsed`, `total`.

Остальное API:

```bash
ros2 service call /list_motions cute_tapochek_interfaces/srv/ListMotions
ros2 service call /start_recording cute_tapochek_interfaces/srv/StartRecording "{start_on_motion: true}"
ros2 service call /stop_recording std_srvs/srv/Trigger
ros2 service call /save_motion cute_tapochek_interfaces/srv/SaveMotion "{name: wave_hello, description: 'машет рукой'}"
ros2 service call /delete_motion cute_tapochek_interfaces/srv/DeleteMotion "{name: wave_hello}"
ros2 service call /set_teleop std_srvs/srv/SetBool "{data: true}"
ros2 topic echo /motion_server/status
```

## Формат движений

`motions/<имя>.csv`: время в секундах, позиции в радианах, метаданные в строках `#`:

```
# cute_tapochek_motion v1
# source_topic: /leader/joint_states
# recorded_at: 2026-10-02T18:40:00
# name: wave_hello
# description: машет рукой
# saved_at: 2026-10-02T18:41:12
time,shoulder_pan_joint,...,gripper_jaw_joint
0.000000,0.012000,...
```

Имя файла — это имя движения: латиница, цифры, `_` и `-`. Описание хранится в самом файле, отдельного индекса нет, поэтому переименовать или удалить движение можно и просто в файловом менеджере.

## Параметры

Все параметры `motion_server` с комментариями лежат в `cute_tapochek_motion/config/motion_server.yaml`: топики, имена контроллеров, время подъезда к первой позе, предельная скорость, лимит длительности записи, сервисы паузы телеуправления.
