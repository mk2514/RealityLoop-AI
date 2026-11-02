#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "secrets.h"

namespace {
constexpr int kIrPin = 27;
constexpr uint32_t kSampleIntervalMs = 5000;
constexpr size_t kMaxBatchReadings = 20;
constexpr size_t kMaxQueueBytes = 512 * 1024;
constexpr char kQueuePath[] = "/readings.jsonl";
constexpr char kQueueTempPath[] = "/readings.tmp";
constexpr char kQueueBackupPath[] = "/readings.bak";

volatile uint32_t ir_count = 0;
uint32_t last_sample_ms = 0;
bool storage_ready = false;
Preferences preferences;

void IRAM_ATTR on_ir_pulse() {
  ++ir_count;
}

bool utc_timestamp(char *output, size_t output_size) {
  struct tm utc_time;
  if (!getLocalTime(&utc_time, 50)) {
    return false;
  }
  return strftime(output, output_size, "%Y-%m-%dT%H:%M:%SZ", &utc_time) > 0;
}

void enqueue_count(uint32_t count, const char *event_time) {
  const uint64_t sequence = preferences.getULong64("sequence", 0) + 1;
  preferences.putULong64("sequence", sequence);

  DynamicJsonDocument reading(512);
  reading["sensor_id"] = SENSOR_ID;
  reading["value"] = count;
  reading["unit"] = "count";
  reading["event_time_utc"] = event_time;
  reading["sequence"] = sequence;
  char event_id[48];
  snprintf(event_id, sizeof(event_id), "esp32-ir-%llu", sequence);
  reading["source_event_id"] = event_id;

  String encoded;
  serializeJson(reading, encoded);
  File queue_file = LittleFS.open(kQueuePath, FILE_APPEND);
  if (!queue_file) {
    Serial.println("Could not append to the durable sensor queue.");
    return;
  }
  if (queue_file.size() + encoded.length() + 1 > kMaxQueueBytes) {
    queue_file.close();
    Serial.println("Durable sensor queue is full; sample was not stored.");
    return;
  }
  queue_file.println(encoded);
  queue_file.close();
}

void remove_published(size_t count) {
  File input = LittleFS.open(kQueuePath, FILE_READ);
  File output = LittleFS.open(kQueueTempPath, FILE_WRITE);
  if (!input || !output) {
    if (input) input.close();
    if (output) output.close();
    Serial.println("Could not rewrite the durable sensor queue.");
    return;
  }
  size_t skipped = 0;
  while (input.available()) {
    String line = input.readStringUntil('\n');
    if (line.isEmpty()) continue;
    if (skipped++ >= count) output.println(line);
  }
  input.close();
  output.close();
  LittleFS.remove(kQueueBackupPath);
  if (!LittleFS.rename(kQueuePath, kQueueBackupPath)) {
    LittleFS.remove(kQueueTempPath);
    Serial.println("Could not preserve the old durable queue during rewrite.");
    return;
  }
  if (LittleFS.rename(kQueueTempPath, kQueuePath)) {
    LittleFS.remove(kQueueBackupPath);
  } else {
    LittleFS.rename(kQueueBackupPath, kQueuePath);
    Serial.println("Queue rewrite failed; preserved the previous durable queue.");
  }
}

void publish_queued() {
  File queue_file = LittleFS.open(kQueuePath, FILE_READ);
  if (!queue_file || queue_file.size() == 0) {
    if (queue_file) queue_file.close();
    return;
  }

  DynamicJsonDocument envelope(16384);
  JsonArray readings = envelope["readings"].to<JsonArray>();
  while (queue_file.available() && readings.size() < kMaxBatchReadings) {
    String line = queue_file.readStringUntil('\n');
    if (line.isEmpty()) continue;
    DynamicJsonDocument reading(512);
    if (deserializeJson(reading, line) != DeserializationError::Ok) {
      queue_file.close();
      Serial.println("A queued row is malformed; queue retained for inspection.");
      return;
    }
    readings.add(reading.as<JsonObject>());
  }
  queue_file.close();
  if (readings.isEmpty()) return;

  WiFiClientSecure client;
  client.setCACert(ROOT_CA);
  HTTPClient http;
  if (!http.begin(client, REALITYLOOP_API_URL)) {
    Serial.println("Could not open the HTTPS telemetry endpoint.");
    return;
  }
  http.addHeader("Authorization", String("Bearer ") + DEVICE_CREDENTIAL);
  http.addHeader("Content-Type", "application/json");
  String body;
  serializeJson(envelope, body);
  const int status = http.POST(body);
  bool all_resolved = false;
  if (status >= 200 && status < 300) {
    DynamicJsonDocument response(8192);
    if (deserializeJson(response, http.getString()) == DeserializationError::Ok) {
      const JsonObject counts = response["counts"];
      const size_t accepted = counts["accepted"] | 0;
      const size_t duplicates = counts["duplicates"] | 0;
      const size_t rejected = counts["rejected"] | 0;
      all_resolved = rejected == 0 && accepted + duplicates == readings.size();
    }
  }
  http.end();
  if (all_resolved) {
    remove_published(readings.size());
  } else {
    Serial.printf("Telemetry response %d; queued readings retained.\n", status);
  }
}

void connect_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  if (!LittleFS.begin(false)) {
    Serial.println("LittleFS initialization failed.");
    return;
  }
  storage_ready = true;
  preferences.begin("rl-edge", false);
  pinMode(kIrPin, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(kIrPin), on_ir_pulse, FALLING);
  connect_wifi();
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
}

void loop() {
  if (!storage_ready) return;
  if (WiFi.status() != WL_CONNECTED) {
    connect_wifi();
  }
  if (millis() - last_sample_ms >= kSampleIntervalMs) {
    last_sample_ms = millis();
    char timestamp[32];
    if (!utc_timestamp(timestamp, sizeof(timestamp))) {
      Serial.println("No synchronized UTC clock; sample was not queued.");
      publish_queued();
      delay(100);
      return;
    }
    uint32_t measured_count;
    noInterrupts();
    measured_count = ir_count;
    ir_count = 0;
    interrupts();
    enqueue_count(measured_count, timestamp);
  }
  publish_queued();
  delay(100);
}
