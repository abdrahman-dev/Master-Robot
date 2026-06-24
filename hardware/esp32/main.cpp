#include <Arduino.h>
#include <ESP32Servo.h>

// TB6612FNG pin assignments
const uint8_t PWMA = 25;
const uint8_t AIN1 = 26;
const uint8_t AIN2 = 27;
const uint8_t PWMB = 14;
const uint8_t BIN1 = 12;
const uint8_t BIN2 = 13;
const uint8_t STBY = 33;

// Servo pin assignments
const uint8_t SERVO_HEAD_PIN  = 18;
const uint8_t SERVO_ARM_R_PIN = 19;
const uint8_t SERVO_ARM_L_PIN = 21;

// Battery
const uint8_t BATTERY_PIN = 34;
const float   VREF        = 3.3;
const float   ADC_MAX     = 4095.0;
const float   DIV_RATIO   = 3.0;

// PWM configuration
const int PWM_FREQ = 1000;
const int PWM_RES = 8;
const uint8_t PWM_CH_A = 0;
const uint8_t PWM_CH_B = 1;

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

void respond(const String &msg) {
  Serial2.println(msg);
  Serial.println(msg);
}

void motor_a_forward() {
  digitalWrite(AIN1, HIGH);
  digitalWrite(AIN2, LOW);
}

void motor_a_backward() {
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, HIGH);
}

void motor_a_stop() {
  digitalWrite(AIN1, LOW);
  digitalWrite(AIN2, LOW);
}

void motor_b_forward() {
  digitalWrite(BIN1, HIGH);
  digitalWrite(BIN2, LOW);
}

void motor_b_backward() {
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, HIGH);
}

void motor_b_stop() {
  digitalWrite(BIN1, LOW);
  digitalWrite(BIN2, LOW);
}

void motors_stop() {
  motor_a_stop();
  motor_b_stop();
  ledcWrite(PWM_CH_A, 0);
  ledcWrite(PWM_CH_B, 0);
  _move_until = 0;
}

void motors_forward() {
  motor_a_forward();
  motor_b_forward();
  ledcWrite(PWM_CH_A, _speed);
  ledcWrite(PWM_CH_B, _speed);
}

void motors_backward() {
  motor_a_backward();
  motor_b_backward();
  ledcWrite(PWM_CH_A, _speed);
  ledcWrite(PWM_CH_B, _speed);
}

void motors_turn_left() {
  motor_a_backward();
  motor_b_forward();
  ledcWrite(PWM_CH_A, _speed);
  ledcWrite(PWM_CH_B, _speed);
}

void motors_turn_right() {
  motor_a_forward();
  motor_b_backward();
  ledcWrite(PWM_CH_A, _speed);
  ledcWrite(PWM_CH_B, _speed);
}

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
    if (ms > 0) {
      motors_forward();
      _move_until = millis() + ms;
      respond("OK:F" + String(ms));
    }
  } else if (cmd.startsWith("B")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) {
      motors_backward();
      _move_until = millis() + ms;
      respond("OK:B" + String(ms));
    }
  } else if (cmd.startsWith("L")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) {
      motors_turn_left();
      _move_until = millis() + ms;
      respond("OK:L" + String(ms));
    }
  } else if (cmd.startsWith("R")) {
    unsigned long ms = cmd.substring(1).toInt();
    if (ms > 0) {
      motors_turn_right();
      _move_until = millis() + ms;
      respond("OK:R" + String(ms));
    }
  } else if (cmd.startsWith("SPD:")) {
    int spd = cmd.substring(4).toInt();
    _speed = constrain(spd, 0, 255);
    respond("OK:SPD:" + String(_speed));
  } else if (cmd.startsWith("SPD")) {
    respond("ERR:unknown");
  } else if (cmd.startsWith("HEAD:")) {
    int angle = cmd.substring(5).toInt();
    angle = constrain(angle, 0, 180);
    headAngle = angle;
    servoHead.write(headAngle);
    respond("OK:HEAD:" + String(headAngle));
  } else if (cmd.startsWith("ARM_R:")) {
    int angle = cmd.substring(6).toInt();
    angle = constrain(angle, 0, 180);
    armRAngle = angle;
    servoArmR.write(armRAngle);
    respond("OK:ARM_R:" + String(armRAngle));
  } else if (cmd.startsWith("ARM_L:")) {
    int angle = cmd.substring(6).toInt();
    angle = constrain(angle, 0, 180);
    armLAngle = angle;
    servoArmL.write(armLAngle);
    respond("OK:ARM_L:" + String(armLAngle));
  } else if (cmd == "HAPPY") {
    if (!happyActive) {
      happyActive = true;
      happyStart = millis();
      happyPhase = 0;
    }
  } else if (cmd == "CENTER") {
    headAngle = 90;
    armRAngle = 90;
    armLAngle = 90;
    servoHead.write(90);
    servoArmR.write(90);
    servoArmL.write(90);
    respond("OK:CENTER");
  } else {
    respond("ERR:unknown");
  }
}

void setup() {
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, 16, 17);

  pinMode(AIN1, OUTPUT);
  pinMode(AIN2, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(BIN2, OUTPUT);
  pinMode(STBY, OUTPUT);
  pinMode(BATTERY_PIN, INPUT);

  ledcSetup(PWM_CH_A, PWM_FREQ, PWM_RES);
  ledcAttachPin(PWMA, PWM_CH_A);
  ledcSetup(PWM_CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(PWMB, PWM_CH_B);

  digitalWrite(STBY, HIGH);

  servoHead.attach(SERVO_HEAD_PIN, 500, 2400);
  servoArmR.attach(SERVO_ARM_R_PIN, 500, 2400);
  servoArmL.attach(SERVO_ARM_L_PIN, 500, 2400);
  servoHead.write(90);
  servoArmR.write(90);
  servoArmL.write(90);

  motors_stop();

  String msg = "ROPE Motor Controller Ready";
  Serial.println(msg);
  Serial2.println(msg);
}

void loop() {
  if (_move_until > 0 && millis() >= _move_until) {
    motors_stop();
    respond("STOPPED");
  }

  if (millis() - lastBatteryRead >= BATTERY_INTERVAL) {
    lastBatteryRead = millis();
    long sum = 0;
    for (int i = 0; i < 10; i++) {
      sum += analogRead(BATTERY_PIN);
      delayMicroseconds(500);
    }
    float adc = sum / 10.0;
    float vPin = (adc / ADC_MAX) * VREF;
    float vBatt = vPin * DIV_RATIO;
    Serial2.print("BAT:");
    Serial2.println(vBatt, 2);
  }

  if (happyActive) {
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

  if (Serial2.available()) {
    String line = Serial2.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      handle_command(line);
    }
  }
}
