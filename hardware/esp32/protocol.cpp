#include "protocol.h"
#include "network.h"
#include "config.h"

// ── Motor state ──
static int _speed = DEFAULT_SPEED;
static unsigned long _move_until = 0;

// ── Servo objects ──
static Servo servoHead;
static Servo servoArmR;
static Servo servoArmL;

// ── HAPPY animation state ──
static bool happyActive = false;
static unsigned long happyStart = 0;
static int happyPhase = 0;

// ── Battery ──
static unsigned long lastBatteryRead = 0;

// ============================================================
// Motor helpers (private to this file)
// ============================================================
static void motor_a_forward() { digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW); }
static void motor_a_backward() { digitalWrite(IN1, LOW); digitalWrite(IN2, HIGH); }
static void motor_a_stop() { digitalWrite(IN1, LOW); digitalWrite(IN2, LOW); }

static void motor_b_forward() { digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW); }
static void motor_b_backward() { digitalWrite(IN3, LOW); digitalWrite(IN4, HIGH); }
static void motor_b_stop() { digitalWrite(IN3, LOW); digitalWrite(IN4, LOW); }

static void motors_forward() {
  motor_a_forward(); motor_b_forward();
  ledcWrite(ENA, _speed); ledcWrite(ENB, _speed);
}

static void motors_backward() {
  motor_a_backward(); motor_b_backward();
  ledcWrite(ENA, _speed); ledcWrite(ENB, _speed);
}

static void motors_turn_left() {
  motor_a_backward(); motor_b_forward();
  ledcWrite(ENA, _speed); ledcWrite(ENB, _speed);
}

static void motors_turn_right() {
  motor_a_forward(); motor_b_backward();
  ledcWrite(ENA, _speed); ledcWrite(ENB, _speed);
}

void motors_stop() {
  motor_a_stop(); motor_b_stop();
  ledcWrite(ENA, 0); ledcWrite(ENB, 0);
  _move_until = 0;
}

// ============================================================
// Command handler declarations
// ============================================================
static void handle_f(const String &args);
static void handle_b(const String &args);
static void handle_l(const String &args);
static void handle_r(const String &args);
static void handle_s(const String &args);
static void handle_spd(const String &args);
static void handle_head(const String &args);
static void handle_arm_r(const String &args);
static void handle_arm_l(const String &args);
static void handle_center(const String &args);
static void handle_happy_cmd(const String &args);

// ============================================================
// Command dispatch table
// ============================================================
struct CommandEntry {
  const char *prefix;
  bool exact; // true = cmd == prefix, false = cmd.startsWith(prefix)
  void (*handler)(const String &);
};

static const CommandEntry COMMANDS[] = {
  // Multi-char prefixes first to avoid ambiguity with single-letter
  {"SPD:",   false, handle_spd},
  {"HEAD:",  false, handle_head},
  {"ARM_R:", false, handle_arm_r},
  {"ARM_L:", false, handle_arm_l},
  {"CENTER", true,  handle_center},
  {"HAPPY",  true,  handle_happy_cmd},
  // Single-letter exact
  {"F", true, handle_f},
  {"B", true, handle_b},
  {"L", true, handle_l},
  {"R", true, handle_r},
  {"S", true, handle_s},
};

static const size_t NUM_COMMANDS = sizeof(COMMANDS) / sizeof(COMMANDS[0]);

void dispatch_command(const String &cmd) {
  // Phase 1: exact match + colon-prefix table
  for (size_t i = 0; i < NUM_COMMANDS; i++) {
    if (COMMANDS[i].exact) {
      if (cmd == COMMANDS[i].prefix) {
        COMMANDS[i].handler("");
        return;
      }
    } else {
      if (cmd.startsWith(COMMANDS[i].prefix)) {
        String args = cmd.substring(strlen(COMMANDS[i].prefix));
        COMMANDS[i].handler(args);
        return;
      }
    }
  }

  // Phase 2: timed movement F<ms>, B<ms>, L<ms>, R<ms>
  if (cmd.length() > 1) {
    char c = cmd.charAt(0);
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) {
      switch (c) {
        case 'F': motors_forward(); _move_until = millis() + ms; respond("OK:F" + String(ms)); return;
        case 'B': motors_backward(); _move_until = millis() + ms; respond("OK:B" + String(ms)); return;
        case 'L': motors_turn_left(); _move_until = millis() + ms; respond("OK:L" + String(ms)); return;
        case 'R': motors_turn_right(); _move_until = millis() + ms; respond("OK:R" + String(ms)); return;
      }
    }
  }

  // Phase 3: unknown
  respond("ERR:unknown");
}

// ============================================================
// Command handlers
// ============================================================
static void handle_f(const String &args) {
  (void)args;
  motors_forward();
  respond("OK:F");
}

static void handle_b(const String &args) {
  (void)args;
  motors_backward();
  respond("OK:B");
}

static void handle_l(const String &args) {
  (void)args;
  motors_turn_left();
  respond("OK:L");
}

static void handle_r(const String &args) {
  (void)args;
  motors_turn_right();
  respond("OK:R");
}

static void handle_s(const String &args) {
  (void)args;
  motors_stop();
  respond("STOPPED");
}

static void handle_spd(const String &args) {
  int spd = args.toInt();
  _speed = constrain(spd, 0, 255);
  respond("OK:SPD:" + String(_speed));
}

static void handle_head(const String &args) {
  int angle = constrain(args.toInt(), 0, 180);
  servoHead.write(angle);
  respond("OK:HEAD:" + String(angle));
}

static void handle_arm_r(const String &args) {
  int angle = constrain(args.toInt(), 0, 180);
  servoArmR.write(angle);
  respond("OK:ARM_R:" + String(angle));
}

static void handle_arm_l(const String &args) {
  int angle = constrain(args.toInt(), 0, 180);
  servoArmL.write(angle);
  respond("OK:ARM_L:" + String(angle));
}

static void handle_center(const String &args) {
  (void)args;
  servoHead.write(90);
  servoArmR.write(90);
  servoArmL.write(90);
  respond("OK:CENTER");
}

static void handle_happy_cmd(const String &args) {
  (void)args;
  if (!happyActive) {
    happyActive = true;
    happyStart = millis();
    happyPhase = 0;
  }
}

// ============================================================
// Hardware init
// ============================================================
void init_hardware() {
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(BATTERY_PIN, INPUT);

  ledcAttach(ENA, PWM_FREQ, PWM_RES);
  ledcAttach(ENB, PWM_FREQ, PWM_RES);

  servoHead.attach(SERVO_HEAD_PIN, 500, 2400);
  servoArmR.attach(SERVO_ARM_R_PIN, 500, 2400);
  servoArmL.attach(SERVO_ARM_L_PIN, 500, 2400);

  servoHead.write(90);
  servoArmR.write(90);
  servoArmL.write(90);

  motors_stop();
}

// ============================================================
// Loop helpers
// ============================================================
void check_timed_stop() {
  if (_move_until > 0 && millis() >= _move_until) {
    motors_stop();
    respond("STOPPED");
  }
}

void update_happy_animation() {
  if (!happyActive) return;

  if (happyPhase == 0 && millis() - happyStart >= 0) {
    servoArmR.write(150);
    servoArmL.write(30);
    happyPhase = 1;
  }
  if (happyPhase == 1 && millis() - happyStart >= 500) {
    servoArmR.write(90);
    servoArmL.write(90);
    happyPhase = 2;
  }
  if (happyPhase == 2 && millis() - happyStart >= 1000) {
    happyActive = false;
    happyPhase = 0;
    respond("OK:HAPPY");
  }
}

void report_battery() {
  if (millis() - lastBatteryRead < BATTERY_INTERVAL_MS) return;
  lastBatteryRead = millis();

  long sum = 0;
  for (int i = 0; i < 10; i++) {
    sum += analogRead(BATTERY_PIN);
    delayMicroseconds(500);
  }
  float vBatt = (sum / 10.0 / ADC_MAX) * VREF * DIV_RATIO;
  respond_battery(vBatt);
}
