#pragma once

#include <WiFi.h>
#include <WiFiClient.h>

void init_wifi();
void check_wifi();
void init_tcp_server();
void check_new_clients();
bool receive_line(String &line);
void respond(const String &msg);
void respond_battery(float volts);
