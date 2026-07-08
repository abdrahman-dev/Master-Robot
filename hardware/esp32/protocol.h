#pragma once

#include <Arduino.h>
#include <ESP32Servo.h>

void init_hardware();
void dispatch_command(const String &cmd);
void check_timed_stop();
void update_happy_animation();
void report_battery();

// Motor helpers (used by main loop timed stop)
void motors_stop();
