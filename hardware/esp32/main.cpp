#include <Arduino.h>
#include "config.h"
#include "network.h"
#include "protocol.h"

void setup() {
  Serial.begin(115200);
  init_hardware();
  init_wifi();
  init_tcp_server();
  Serial.println("ROPE Motor Controller Ready (WiFi TCP mode)");
  Serial.print("Waiting for client on port ");
  Serial.println(TCP_PORT);
}

void loop() {
  check_wifi();
  check_new_clients();
  check_timed_stop();
  report_battery();
  update_happy_animation();

  String line;
  if (receive_line(line)) {
    dispatch_command(line);
  }
}
