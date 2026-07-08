#include "network.h"
#include "config.h"

static WiFiServer server(TCP_PORT);
static WiFiClient client;

// ── WiFi ──
void init_wifi() {
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_TIMEOUT_MS) {
    delay(300);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("WiFi connected! IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("WiFi connection failed, will retry in loop()");
  }
}

void check_wifi() {
  if (WiFi.status() != WL_CONNECTED) {
    static unsigned long lastRetry = 0;
    if (millis() - lastRetry > WIFI_RETRY_MS) {
      lastRetry = millis();
      init_wifi();
    }
  }
}

// ── TCP server ──
void init_tcp_server() {
  server.begin();
  server.setNoDelay(true);
}

void check_new_clients() {
  if (server.hasClient()) {
    if (!client || !client.connected()) {
      if (client) client.stop();
      client = server.available();
      Serial.println("Client connected: " + client.remoteIP().toString());
    } else {
      WiFiClient newClient = server.available();
      newClient.stop();
    }
  }
}

// ── I/O ──
bool receive_line(String &line) {
  if (!client || !client.connected()) return false;
  if (!client.available()) return false;
  line = client.readStringUntil('\n');
  line.trim();
  return line.length() > 0;
}

void respond(const String &msg) {
  if (client && client.connected()) {
    client.println(msg);
  }
  Serial.println(msg);
}

void respond_battery(float volts) {
  if (client && client.connected()) {
    client.print("BAT:");
    client.println(volts, 2);
  }
}
