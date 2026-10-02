// Селектор режимов адресной ленты по Serial.
//
// Режим выбирается номером или названием (регистр не важен):
//   1 / RAINBOW  — бегущая радуга
//   2 / DOT      — зелёная точка с хвостом бежит по кругу
//   3 / AZURE    — всё горит бирюзово-лазурным (светодиоды загораются по очереди)
//   4 / GREEN    — всё горит зелёным (светодиоды загораются по очереди)
//   5 / ORANGE   — всё горит оранжевым
//   6 / OFF      — всё гаснет
//
// Другие команды:
//   BRIGHT <0-255>  — яркость, например "BRIGHT 120"
//   STATUS          — узнать текущее состояние
//
// На любую успешную команду плата отвечает: OK <РЕЖИМ> <ЯРКОСТЬ>, например "OK GREEN 120"
// На ошибку: ERR <что пришло>
// Работает и с переводом строки, и без него (Serial Monitor: любой вариант).

#include <FastLED.h>

// ---------- Подключение ----------
#define LED_PIN      6          // для ESP32, например, 13
#define NUM_LEDS     30
#define BRIGHTNESS   80
#define BAUD         115200

// ---------- Цвета (подбирай на глаз под свою ленту) ----------
const CRGB COLOR_AZURE  = CRGB(0, 170, 220);   // бирюзово-лазурный
const CRGB COLOR_GREEN  = CRGB(0, 255, 0);
const CRGB COLOR_ORANGE = CRGB(255, 80, 0);    // (255,165,0) на ленте выглядит жёлтым
const CRGB COLOR_DOT    = CRGB(0, 255, 0);     // цвет бегущей точки

// ---------- Скорости ----------
#define RAINBOW_STEP_MS 20      // скорость радуги: меньше — быстрее
#define DOT_STEP_MS     40      // скорость точки: меньше — быстрее
#define DOT_FADE        70      // длина хвоста: меньше — длиннее (0..255)
#define WIPE_STEP_MS    35      // пауза между загоранием соседних светодиодов

// ---------- Служебное ----------
#define QUIET_MS        30      // не обновляем ленту сразу после приёма байта
#define LINE_TIMEOUT_MS 50      // команда без перевода строки считается законченной

CRGB leds[NUM_LEDS];

enum Mode : uint8_t { RAINBOW, DOT, AZURE, GREEN, ORANGE, OFF };
const char* const MODE_NAMES[] = { "RAINBOW", "DOT", "AZURE", "GREEN", "ORANGE", "OFF" };
const uint8_t MODES_COUNT = sizeof(MODE_NAMES) / sizeof(MODE_NAMES[0]);

Mode     mode       = RAINBOW;
uint8_t  brightness = BRIGHTNESS;
bool     needShow   = true;      // показываем ленту только когда что-то поменялось
uint32_t lastStep = 0;
uint8_t  hue      = 0;
uint16_t dotPos   = 0;
uint16_t wipePos  = 0;

// =====================================================
//                    Режимы
// =====================================================
// Ответ на успешную команду: "OK <РЕЖИМ> <ЯРКОСТЬ>"
void printState() {
  Serial.print(F("OK "));
  Serial.print(MODE_NAMES[mode]);
  Serial.print(' ');
  Serial.println(brightness);
}

void setBrightness(uint8_t b) {
  brightness = b;
  FastLED.setBrightness(brightness);
  needShow = true;          // статичные режимы иначе не перерисуются с новой яркостью
  printState();
}

void setMode(Mode m) {
  mode = m;
  fill_solid(leds, NUM_LEDS, CRGB::Black);   // каждый режим стартует с чистой ленты
  dotPos   = 0;
  wipePos  = 0;
  lastStep = 0;                              // первый шаг эффекта — сразу
  needShow = true;

  if (m == ORANGE) fill_solid(leds, NUM_LEDS, COLOR_ORANGE);   // загорается сразу целиком

  printState();
}

// Светодиоды загораются по одному, потом лента просто горит
void wipe(uint32_t now, const CRGB& c) {
  if (wipePos < NUM_LEDS && now - lastStep >= WIPE_STEP_MS) {
    lastStep = now;
    leds[wipePos++] = c;
    needShow = true;
  }
}

void updateEffect(uint32_t now) {
  switch (mode) {
    case RAINBOW:
      if (now - lastStep >= RAINBOW_STEP_MS) {
        lastStep = now;
        fill_rainbow(leds, NUM_LEDS, hue++, 7);
        needShow = true;
      }
      break;

    case DOT:
      if (now - lastStep >= DOT_STEP_MS) {
        lastStep = now;
        fadeToBlackBy(leds, NUM_LEDS, DOT_FADE);   // хвост гаснет
        leds[dotPos] = COLOR_DOT;
        dotPos = (dotPos + 1) % NUM_LEDS;          // дошла до конца — снова с начала
        needShow = true;
      }
      break;

    case AZURE: wipe(now, COLOR_AZURE); break;
    case GREEN: wipe(now, COLOR_GREEN); break;

    case ORANGE:
    case OFF:
      break;                                       // статичные, всё сделано в setMode
  }
}

// =====================================================
//                 Приём команд
// =====================================================
char     buf[16];
uint8_t  bufLen     = 0;
uint32_t lastByteMs = 0;

void printHelp() {
  Serial.println(F("Режимы:"));
  for (uint8_t i = 0; i < MODES_COUNT; i++) {
    Serial.print(F("  ")); Serial.print(i + 1);
    Serial.print(F(" / ")); Serial.println(MODE_NAMES[i]);
  }
  Serial.println(F("  BRIGHT <0-255>, STATUS"));
}

// Число 0..255 из строки; false, если не число или вне диапазона
bool parseByte(const char* s, uint8_t& out) {
  if (*s == '\0') return false;
  char* end;
  long v = strtol(s, &end, 10);
  if (*end != '\0' || v < 0 || v > 255) return false;
  out = (uint8_t)v;
  return true;
}

void processCommand() {
  if (bufLen == 0) return;
  buf[bufLen] = '\0';
  bufLen = 0;

  // Пробелы при приёме отбрасываются, поэтому "BRIGHT 120" приходит как "BRIGHT120"
  if (strncmp(buf, "BRIGHT", 6) == 0) {
    uint8_t b;
    if (parseByte(buf + 6, b)) setBrightness(b);
    else { Serial.print(F("ERR ")); Serial.println(buf); }
    return;
  }
  if (strcmp(buf, "STATUS") == 0) {
    printState();
    return;
  }

  int8_t m = -1;
  if (buf[0] >= '1' && buf[0] <= '9' && buf[1] == '\0') {   // номер режима
    m = buf[0] - '1';
    if (m >= MODES_COUNT) m = -1;
  } else {                                                   // название режима
    for (uint8_t i = 0; i < MODES_COUNT; i++)
      if (strcmp(buf, MODE_NAMES[i]) == 0) m = i;
  }

  if (m < 0) {
    Serial.print(F("ERR "));
    Serial.println(buf);
    printHelp();
    return;
  }
  setMode((Mode)m);
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    lastByteMs = millis();
    if (c == '\n' || c == '\r') {
      processCommand();
    } else if (c != ' ' && bufLen < sizeof(buf) - 1) {
      buf[bufLen++] = toupper(c);
    }
  }
  // Пришло без перевода строки — после паузы считаем команду законченной
  if (bufLen > 0 && millis() - lastByteMs > LINE_TIMEOUT_MS) processCommand();
}

// =====================================================
void setup() {
  Serial.begin(BAUD);
  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
  FastLED.setBrightness(BRIGHTNESS);
  FastLED.setMaxPowerInVoltsAndMilliamps(5, 500);   // ограничение тока
  FastLED.clear(true);

  Serial.println(F("READY"));
  printHelp();
  setMode(RAINBOW);
}

void loop() {
  readSerial();

  uint32_t now = millis();
  // Пока идёт приём, ленту не трогаем: на Nano show() глушит прерывания и Serial теряет байты
  if (now - lastByteMs < QUIET_MS) return;

  updateEffect(now);
  if (needShow) {
    FastLED.show();
    needShow = false;
  }
}
