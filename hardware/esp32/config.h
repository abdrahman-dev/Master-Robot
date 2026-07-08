#pragma once

// ── WiFi ──
const char *WIFI_SSID = "3mar";
const char *WIFI_PASSWORD = "";
const uint16_t TCP_PORT = 3333;

// ── Motor A (Right) ──
const uint8_t ENA = 25;
const uint8_t IN1 = 26;
const uint8_t IN2 = 27;

// ── Motor B (Left) ──
const uint8_t ENB = 14;
const uint8_t IN3 = 12;
const uint8_t IN4 = 13;

// ── Servos ──
const uint8_t SERVO_HEAD_PIN = 18;
const uint8_t SERVO_ARM_R_PIN = 19;
const uint8_t SERVO_ARM_L_PIN = 21;

// ── Battery ──
const uint8_t BATTERY_PIN = 34;
const float VREF = 3.3;
const float ADC_MAX = 4095.0;
const float DIV_RATIO = 3.0;

// ── PWM ──
const int PWM_FREQ = 1000;
const int PWM_RES = 8;

// ── Defaults ──
const int DEFAULT_SPEED = 180;

// ── Timing (ms) ──
const unsigned long WIFI_TIMEOUT_MS = 20000;
const unsigned long WIFI_RETRY_MS = 5000;
const unsigned long BATTERY_INTERVAL_MS = 2000;
