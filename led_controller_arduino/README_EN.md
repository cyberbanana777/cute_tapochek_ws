# led_controller_arduino

[Русская версия](README.md)

Firmware for an Arduino Nano or ESP32 that drives a WS2812B addressable LED strip. The board receives text commands over serial and switches lighting modes and brightness. On the PC side it is controlled by the [`led_driver`](../led_driver/README_EN.md) ROS 2 driver.

This is not a ROS package: the directory has no `package.xml`, and colcon skips it. The sketch is `main/main.ino`.

The protocol is specified in the [top-level README](../README_EN.md#led-strip-control-protocol).

## Features

- Six modes: rainbow, running dot with a tail, two solid-colour modes lit one LED at a time, orange, and off.
- Mode selection by name or number, case-insensitive.
- Brightness control 0–255.
- Every command is answered with the board's full state.
- Works with or without a line ending.
- Non-blocking loop: effects run on `millis()` timers, no `delay()`.
- Protection against lost bytes on an Arduino Nano: the strip is not updated while a command is being received.

## Hardware

| Component | Value |
|-----------|-------|
| Strip | WS2812B, 5 V, GRB colour order |
| Board | Arduino Nano or ESP32 |
| Data pin | `6` (`LED_PIN`) |
| Number of LEDs | `30` (`NUM_LEDS`) |

### Wiring

| Strip | Connect to |
|-------|------------|
| `DIN` | Pin `LED_PIN` through a 300–500 Ω resistor placed close to the strip |
| `+5V` | +5 V of the power supply |
| `GND` | GND of the power supply **and** GND of the board: the ground must be common |

A 470–1000 µF capacitor between +5V and GND at the start of the strip is recommended: it absorbs the inrush current at power-on.

One LED at full white draws up to ~60 mA. The firmware limits the strip current to 500 mA (`setMaxPowerInVoltsAndMilliamps(5, 500)`): at high brightness FastLED dims the strip on its own. Raise the limit only if the power supply can deliver more current.

**ESP32:** the board uses 3.3 V logic while the strip expects 5 V. It usually works directly, but a level shifter (e.g. 74AHCT125) is more reliable. Change the data pin number, e.g. to `13`.

## Settings

All settings are constants at the top of `main/main.ino`.

| Constant | Default | Description |
|----------|---------|-------------|
| `LED_PIN` | `6` | Strip data pin |
| `NUM_LEDS` | `30` | Number of LEDs |
| `BRIGHTNESS` | `80` | Brightness after power-on, 0–255 |
| `BAUD` | `115200` | Serial baud rate. Must match the `baud` parameter of `led_driver` |
| `COLOR_AZURE` | `(0, 170, 220)` | Colour of the `AZURE` mode |
| `COLOR_GREEN` | `(0, 255, 0)` | Colour of the `GREEN` mode |
| `COLOR_ORANGE` | `(255, 80, 0)` | Colour of the `ORANGE` mode. A "true" `(255, 165, 0)` looks yellow on the strip |
| `COLOR_DOT` | `(0, 255, 0)` | Colour of the running dot |
| `RAINBOW_STEP_MS` | `20` | Rainbow step period, ms. Lower is faster |
| `DOT_STEP_MS` | `40` | Dot step period, ms. Lower is faster |
| `DOT_FADE` | `70` | Tail fade per step, 0–255. Lower gives a longer tail |
| `WIPE_STEP_MS` | `35` | Delay between lighting neighbouring LEDs, ms |
| `QUIET_MS` | `30` | For how many ms after a received byte the strip is not updated |
| `LINE_TIMEOUT_MS` | `50` | Silence in ms after which a command without a line ending is considered complete |

## Modes

| # | Name | Behaviour |
|---|------|-----------|
| 1 | `RAINBOW` | Running rainbow. Mode after power-on |
| 2 | `DOT` | A `COLOR_DOT` dot with a fading tail runs in a loop: after the last LED it returns to the first. If the strip is bent into a ring, the motion looks continuous |
| 3 | `AZURE` | LEDs light up one by one in `COLOR_AZURE`, then the strip stays lit |
| 4 | `GREEN` | Same, in `COLOR_GREEN` |
| 5 | `ORANGE` | The whole strip lights up in `COLOR_ORANGE` at once |
| 6 | `OFF` | The strip goes dark |

## Building and flashing

### Arduino IDE

1. Install the **FastLED** library: "Tools → Manage Libraries", search for `FastLED`.
2. Open `main/main.ino`.
3. Select the board and port. For Nano clones with the old bootloader: "Processor → ATmega328P (Old Bootloader)".
4. Click "Upload".

### arduino-cli

Run the commands from the `led_controller_arduino` directory.

```bash
arduino-cli lib install FastLED

# Arduino Nano
arduino-cli compile --fqbn arduino:avr:nano main
arduino-cli upload  --fqbn arduino:avr:nano -p /dev/ttyUSB0 main
# clone with the old bootloader: --fqbn arduino:avr:nano:cpu=atmega328old

# ESP32 (requires the esp32:esp32 core)
arduino-cli compile --fqbn esp32:esp32:esp32 main
arduino-cli upload  --fqbn esp32:esp32:esp32 -p /dev/ttyUSB0 main
```

Stop `led_driver` before flashing: the upload fails while the node holds the port.

## Testing without ROS

Open the Serial Monitor (115200 baud, any line ending) and send commands:

```
3              → OK AZURE 80
bright 150     → OK AZURE 150
dot            → OK DOT 150
status         → OK DOT 150
```

## How the firmware works

- `loop()` never blocks. On every pass it reads serial (`readSerial()`) and then runs one step of the current effect (`updateEffect()`). Each effect decides from `millis()` whether it is time for its next step.
- The strip is updated (`FastLED.show()`) only when the frame has changed (`needShow` flag). Static modes do not touch the strip at all once they are lit, which lowers the chance of losing serial bytes.
- On an Arduino Nano, `FastLED.show()` disables interrupts while writing, and UART bytes arriving at that moment are lost. Therefore the strip is not updated for `QUIET_MS` ms after any received byte. The host additionally "wakes up" the board with an empty line before each command.
- Switching modes (`setMode()`) blanks the strip, resets the effect state and replies `OK` immediately.
- Changing brightness (`setBrightness()`) sets the `needShow` flag. Without it, static modes would not be redrawn with the new brightness.

## Adding a mode

1. Add a value to `enum Mode` and a name to `MODE_NAMES` **at the same position**. The mode number is the array position plus one. Numbers are accepted as a single digit, so there can be at most nine modes.
2. Add a branch to the `switch` in `updateEffect()`. For a static mode, set the colour in `setMode()`, as `ORANGE` does.
3. Add the name to the `MODES` tuple in `led_driver/led_driver.py` at the same position and update the mode tables in the documentation.

## Dependencies

- [FastLED](https://github.com/FastLED/FastLED) library.
- Arduino AVR core (for the Nano) or the ESP32 core.

## Version

Compatible with `led_driver` 0.0.0: modes, brightness and the `STATUS` command.
