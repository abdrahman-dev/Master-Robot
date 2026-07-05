#include <Arduino.h>
#include <ESP32Servo.h>

// ============================================================
// L298N pin assignments (ESP32 DevKit 30-pin)
// ============================================================
// Motor A (Right)
const uint8_t ENA  = 25;   // PWM speed control - Motor A
const uint8_t IN1  = 26;   // Direction
const uint8_t IN2  = 27;   // Direction

// Motor B (Left)
const uint8_t ENB  = 14;   // PWM speed control - Motor B
const uint8_t IN3  = 12;   // Direction
const uint8_t IN4  = 13;   // Direction

// Servo pin assignments
const uint8_t SERVO_HEAD_PIN  = 18;
const uint8_t SERVO_ARM_R_PIN = 19;
const uint8_t SERVO_ARM_L_PIN = 21;

// Battery
const uint8_t BATTERY_PIN = 34;
const float   VREF        = 3.3;
const float   ADC_MAX     = 4095.0;
const float   DIV_RATIO   = 3.0;

// PWM configuration (ESP32 Arduino Core v3.x API)
const int PWM_FREQ = 1000;
const int PWM_RES  = 8;    // 8-bit = 0..255

// Motor states
int _speed = 180;
unsigned long _move_until = 0;

// Servo objects
Servo servoHead;
Servo servoArmR;
Servo servoArmL;

int headAngle = 90;
int armRAngle = 90;
int armLAngle = 90;

// Battery
unsigned long lastBatteryRead = 0;
const unsigned long BATTERY_INTERVAL = 2000;

// HAPPY animation state machine
bool happyActive = false;
unsigned long happyStart = 0;
int happyPhase = 0;

// ============================================================
void respond(const String &msg) {
  Serial2.println(msg);
  Serial.println(msg);
}

// --- Motor A (Right) ---
void motor_a_forward()  { digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);  }
void motor_a_backward() { digitalWrite(IN1, LOW);  digitalWrite(IN2, HIGH); }
void motor_a_stop()     { digitalWrite(IN1, LOW);  digitalWrite(IN2, LOW);  }

// --- Motor B (Left) ---
void motor_b_forward()  { digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);  }
void motor_b_backward() { digitalWrite(IN3, LOW);  digitalWrite(IN4, HIGH); }
void motor_b_stop()     { digitalWrite(IN3, LOW);  digitalWrite(IN4, LOW);  }

// --- Combined ---
void motors_stop() {
  motor_a_stop();
  motor_b_stop();
  ledcWrite(ENA, 0);   // ✅ New API: pass pin directly
  ledcWrite(ENB, 0);
  _move_until = 0;
}

void motors_forward() {
  motor_a_forward();
  motor_b_forward();
  ledcWrite(ENA, _speed);
  ledcWrite(ENB, _speed);
}

void motors_backward() {
  motor_a_backward();
  motor_b_backward();
  ledcWrite(ENA, _speed);
  ledcWrite(ENB, _speed);
}

void motors_turn_left() {
  motor_a_backward();
  motor_b_forward();
  ledcWrite(ENA, _speed);
  ledcWrite(ENB, _speed);
}

void motors_turn_right() {
  motor_a_forward();
  motor_b_backward();
  ledcWrite(ENA, _speed);
  ledcWrite(ENB, _speed);
}

// ============================================================
void handle_command(const String &cmd) {
  if (cmd == "F") {
    motors_forward();
    respond("OK:F");
  } else if (cmd == "B") {
    motors_backward();
    respond("OK:B");
  } else if (cmd == "L") {
    motors_turn_left();
    respond("OK:L");
  } else if (cmd == "R") {
    motors_turn_right();
    respond("OK:R");
  } else if (cmd == "S") {
    motors_stop();
    respond("STOPPED");
  } else if (cmd.startsWith("F")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) { motors_forward();  _move_until = millis() + ms; respond("OK:F" + String(ms)); }
  } else if (cmd.startsWith("B")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) { motors_backward(); _move_until = millis() + ms; respond("OK:B" + String(ms)); }
  } else if (cmd.startsWith("L")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) { motors_turn_left();  _move_until = millis() + ms; respond("OK:L" + String(ms)); }
  } else if (cmd.startsWith("R")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) { motors_turn_right(); _move_until = millis() + ms; respond("OK:R" + String(ms)); }
  } else if (cmd.startsWith("SPD:")) {
    int spd = cmd.substring(4).toInt();
    _speed = constrain(spd, 0, 255);
    respond("OK:SPD:" + String(_speed));
  } else if (cmd.startsWith("HEAD:")) {
    int angle = constrain(cmd.substring(5).toInt(), 0, 180);
    headAngle = angle;
    servoHead.write(headAngle);
    respond("OK:HEAD:" + String(headAngle));
  } else if (cmd.startsWith("ARM_R:")) {
    int angle = constrain(cmd.substring(6).toInt(), 0, 180);
    armRAngle = angle;
    servoArmR.write(armRAngle);
    respond("OK:ARM_R:" + String(armRAngle));
  } else if (cmd.startsWith("ARM_L:")) {
    int angle = constrain(cmd.substring(6).toInt(), 0, 180);
    armLAngle = angle;
    servoArmL.write(armLAngle);
    respond("OK:ARM_L:" + String(armLAngle));
  } else if (cmd == "HAPPY") {
    if (!happyActive) { happyActive = true; happyStart = millis(); happyPhase = 0; }
  } else if (cmd == "CENTER") {
    headAngle = armRAngle = armLAngle = 90;
    servoHead.write(90); servoArmR.write(90); servoArmL.write(90);
    respond("OK:CENTER");
  } else {
    respond("ERR:unknown");
  }
}

// ============================================================
void setup() {
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, 16, 17);

  // Direction pins
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(BATTERY_PIN, INPUT);

  // ✅ ESP32 Core v3.x: ledcAttach(pin, freq, resolution)
  // No STBY pin needed — L298N is always enabled
  ledcAttach(ENA, PWM_FREQ, PWM_RES);
  ledcAttach(ENB, PWM_FREQ, PWM_RES);

  servoHead.attach(SERVO_HEAD_PIN, 500, 2400);
  servoArmR.attach(SERVO_ARM_R_PIN, 500, 2400);
  servoArmL.attach(SERVO_ARM_L_PIN, 500, 2400);
  servoHead.write(90); servoArmR.write(90); servoArmL.write(90);

  motors_stop();

  Serial.println("ROPE Motor Controller Ready");
  Serial2.println("ROPE Motor Controller Ready");
}

// ============================================================
void loop() {
  if (_move_until > 0 && millis() >= _move_until) {
    motors_stop();
    respond("STOPPED");
  }

  if (millis() - lastBatteryRead >= BATTERY_INTERVAL) {
    lastBatteryRead = millis();
    long sum = 0;
    for (int i = 0; i < 10; i++) { sum += analogRead(BATTERY_PIN); delayMicroseconds(500); }
    float vBatt = (sum / 10.0 / ADC_MAX) * VREF * DIV_RATIO;
    Serial2.print("BAT:"); Serial2.println(vBatt, 2);
  }

  if (happyActive) {
    if (happyPhase == 0 && millis() - happyStart >= 0)    { servoArmR.write(150); servoArmL.write(30);  happyPhase = 1; }
    if (happyPhase == 1 && millis() - happyStart >= 500)  { servoArmR.write(90);  servoArmL.write(90);  happyPhase = 2; }
    if (happyPhase == 2 && millis() - happyStart >= 1000) { happyActive = false; happyPhase = 0; respond("OK:HAPPY"); }
  }

  if (Serial2.available()) {
    String line = Serial2.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) handle_command(line);
  }
}
