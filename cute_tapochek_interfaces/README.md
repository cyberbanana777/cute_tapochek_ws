# cute_tapochek_interfaces

[English version](README_EN.md)

Интерфейсы подсистемы движений робота cute_tapochek: action проигрывания, сервисы библиотеки и записи, сообщение статуса. Сервер этих интерфейсов — нода `motion_server` из [`cute_tapochek_motion`](../cute_tapochek_motion/README.md), клиент с GUI — [`cute_tapochek_gui`](../cute_tapochek_gui/README.md).

## Состав

| Интерфейс | Тип | Где используется |
|-----------|-----|------------------|
| `PlayMotion` | action | `/play_motion` — проиграть движение |
| `ListMotions` | srv | `/list_motions` — список движений |
| `StartRecording` | srv | `/start_recording` — начать запись с leader |
| `SaveMotion` | srv | `/save_motion` — сохранить черновик в библиотеку |
| `DeleteMotion` | srv | `/delete_motion` — удалить движение |
| `MotionServerStatus` | msg | `/motion_server/status` — состояние сервера |

Остальные сервисы `motion_server` (`/stop_motion`, `/stop_recording`, `/discard_recording`, `/set_teleop`) используют стандартные `std_srvs/Trigger` и `std_srvs/SetBool`.

## action `PlayMotion`

Проиграть движение из библиотеки или последнюю несохранённую запись (черновик). Новая цель прерывает текущую.

**Цель**

| Поле | Тип | Описание |
|------|-----|----------|
| `name` | string | Имя движения в библиотеке |
| `play_draft` | bool | `true` — проиграть черновик, `name` игнорируется |
| `speed` | float64 | Множитель скорости. `0` — то же, что `1.0` |
| `approach_time` | float64 | Время подъезда к первой позе движения, с. `0` — значение сервера по умолчанию |

**Результат**

| Поле | Тип | Описание |
|------|-----|----------|
| `success` | bool | Движение проиграно до конца |
| `message` | string | Пояснение: `<имя>: done`, `<имя>: interrupted`, `<имя>: cancelled`, текст ошибки |

**Обратная связь**

| Поле | Тип | Описание |
|------|-----|----------|
| `progress` | float64 | Доля выполнения, 0..1 |
| `elapsed` | float64 | Время с начала траектории, с |
| `total` | float64 | Полная длительность: подъезд + движение, с |

## srv `ListMotions`

Запрос пустой.

| Поле ответа | Тип | Описание |
|-------------|-----|----------|
| `names` | string[] | Имена движений, по алфавиту |
| `durations` | float64[] | Длительности, с |
| `descriptions` | string[] | Описания |

Массивы параллельны: `i`-й элемент каждого относится к одному движению.

## srv `StartRecording`

| Поле запроса | Тип | Описание |
|--------------|-----|----------|
| `start_on_motion` | bool | Начать запись, только когда leader сдвинется |
| `max_duration` | float64 | Предельная длительность записи, с. `0` — значение сервера по умолчанию |

Ответ: `success` (bool), `message` (string).

## srv `SaveMotion`

Сохранить последнюю запись (черновик) в библиотеку.

| Поле запроса | Тип | Описание |
|--------------|-----|----------|
| `name` | string | Имя: латиница, цифры, `_` и `-`, до 64 символов, начинается с буквы или цифры |
| `description` | string | Описание движения |
| `overwrite` | bool | Перезаписать, если движение с таким именем уже есть |

Ответ: `success` (bool), `message` (string).

## srv `DeleteMotion`

| Поле запроса | Тип | Описание |
|--------------|-----|----------|
| `name` | string | Имя движения |

Ответ: `success` (bool), `message` (string).

## msg `MotionServerStatus`

| Поле | Тип | Описание |
|------|-----|----------|
| `state` | string | Состояние сервера, одна из констант `STATE_*` |
| `playing` | string | Имя проигрываемого движения (`(draft)` для черновика), пусто, если ничего не играет |
| `progress` | float64 | Доля выполнения при проигрывании, 0..1 |
| `recording_time` | float64 | Длительность текущей записи, с |
| `has_draft` | bool | Есть ли несохранённая запись |
| `draft_duration` | float64 | Длительность черновика, с |
| `teleop` | string | Последнее известное состояние телеуправления, одна из констант `TELEOP_*` |

**Константы состояния сервера**

| Константа | Значение | Смысл |
|-----------|----------|-------|
| `STATE_IDLE` | `idle` | Ничего не происходит |
| `STATE_WAITING` | `waiting_for_motion` | Запись запущена, сервер ждёт, когда leader начнёт двигаться |
| `STATE_RECORDING` | `recording` | Идёт запись |
| `STATE_PLAYING` | `playing` | Идёт проигрывание |

**Константы телеуправления**

| Константа | Значение | Смысл |
|-----------|----------|-------|
| `TELEOP_UNKNOWN` | `unknown` | Сервер ещё не обращался к телеуправлению |
| `TELEOP_ENABLED` | `enabled` | Ретрансляция leader → follower включена |
| `TELEOP_PAUSED` | `paused` | Ретрансляция на паузе |
| `TELEOP_UNAVAILABLE` | `unavailable` | Сервисы паузы телеуправления не найдены |

## Полезные проверки

```bash
ros2 interface show cute_tapochek_interfaces/action/PlayMotion
ros2 interface show cute_tapochek_interfaces/msg/MotionServerStatus
ros2 interface package cute_tapochek_interfaces
```

## Зависимости

- `ament_cmake`
- `rosidl_default_generators`, `rosidl_default_runtime`
- `action_msgs`

## Версия

**0.1.0** — первая версия: `PlayMotion`, сервисы библиотеки и записи, `MotionServerStatus`.
