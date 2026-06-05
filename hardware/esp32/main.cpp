#include <Arduino.h>

// TB6612FNG pin assignments
const uint8_t PWMA = 25;
const uint8_t AIN1 = 26;
const uint8_t AIN2 = 27;
const uint8_t PWMB = 14;
const uint8_t BIN1 = 12;
const uint8_t BIN2 = 13;
const uint8_t STBY = 33;

// PWM configuration
const int PWM_FREQ = 1000;
const int PWM_RES = 8;
const uint8_t PWM_CH_A = 0;
const uint8_t PWM_CH_B = 1;

// Motor states
int _speed = 180;
unsigned long _move_until = 0;

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

void respond(const String &msg) {
  Serial2.println(msg);
  Serial.println(msg);
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

  ledcSetup(PWM_CH_A, PWM_FREQ, PWM_RES);
  ledcAttachPin(PWMA, PWM_CH_A);
  ledcSetup(PWM_CH_B, PWM_FREQ, PWM_RES);
  ledcAttachPin(PWMB, PWM_CH_B);

  digitalWrite(STBY, HIGH);

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

  if (Serial2.available()) {
    String line = Serial2.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      handle_command(line);
    }
  }
}
