/*
 * Self-checkout NFC scanner — ESP32-CAM (AI Thinker / Freenove) + PN532 V3 (I2C)
 *
 * Wiring:
 *   PN532 GND -> GND
 *   PN532 VCC -> 5V
 *   PN532 SDA -> GPIO 14
 *   PN532 SCL -> GPIO 15
 *   PN532 DIP switches: 1 = ON, 2 = OFF (I2C mode)
 *
 * Flow: read Mifare UID -> POST {"tag_id": "AA:BB:CC:DD"} to <API_BASE>/scan
 * with X-API-Key. 200 = product found (1 long flash), 404 = unknown tag
 * (3 short flashes), other errors = red LED blinks.
 *
 * Libraries: "Adafruit PN532" (Library Manager) + its dependency Adafruit BusIO.
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_PN532.h>

// ---------- CONFIG: edit these ----------
const char *WIFI_SSID     = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char *API_BASE      = "http://192.168.1.146:8123"; // computer running the API
const char *API_KEY       = "dev-secret-key";            // must match API .env
// ----------------------------------------

#define SDA_PIN 14
#define SCL_PIN 15
#define FLASH_LED_PIN 4  // ESP32-CAM white flash LED (bright!)
#define RED_LED_PIN 33   // ESP32-CAM small red LED, inverted (LOW = on)

#define SCAN_COOLDOWN_MS 2000  // ignore repeat reads of the same tag for this long
#define READ_TIMEOUT_MS 500    // how long each NFC poll waits

// IRQ/RESET are not wired; the library polls readiness over I2C.
Adafruit_PN532 nfc(-1, -1, &Wire);

String lastUid;
unsigned long lastScanAt = 0;

void flashBlink(int times, int onMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(FLASH_LED_PIN, HIGH);
    delay(onMs);
    digitalWrite(FLASH_LED_PIN, LOW);
    if (i < times - 1) delay(120);
  }
}

void redBlink(int times, int onMs) {
  for (int i = 0; i < times; i++) {
    digitalWrite(RED_LED_PIN, LOW);   // inverted
    delay(onMs);
    digitalWrite(RED_LED_PIN, HIGH);
    if (i < times - 1) delay(120);
  }
}

String uidToHex(const uint8_t *uid, uint8_t length) {
  String out;
  for (uint8_t i = 0; i < length; i++) {
    if (uid[i] < 0x10) out += "0";
    out += String(uid[i], HEX);
    if (i < length - 1) out += ":";
  }
  out.toUpperCase();
  return out;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to WiFi '%s'", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.printf("\nWiFi OK, IP: %s\n", WiFi.localIP().toString().c_str());
}

void sendScan(const String &tagId) {
  HTTPClient http;
  http.setTimeout(5000);
  http.begin(String(API_BASE) + "/scan");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  int code = http.POST("{\"tag_id\":\"" + tagId + "\"}");
  String body = http.getString();
  http.end();

  Serial.printf("POST /scan tag=%s -> %d\n", tagId.c_str(), code);
  Serial.println(body);

  if (code == 200) {
    flashBlink(1, 400);        // product found, pushed to kiosk UI
  } else if (code == 404) {
    flashBlink(3, 100);        // tag not registered — see serial for UID
    Serial.println(">> Unregistered tag. Register it with:");
    Serial.printf(">> curl -X POST %s/products -H 'Content-Type: application/json' \\\n", API_BASE);
    Serial.printf(">>   -d '{\"nfc_tag_id\":\"%s\",\"name\":\"NAME\",\"price\":\"0.00\",\"stock\":0}'\n", tagId.c_str());
  } else if (code == 401) {
    redBlink(2, 300);          // API key mismatch
    Serial.println(">> API key rejected — check API_KEY matches the API's .env");
  } else {
    redBlink(5, 100);          // network / server error (code < 0 = no connection)
    Serial.println(">> Request failed — is the API running with --host 0.0.0.0?");
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(FLASH_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, HIGH);  // off (inverted)

  connectWiFi();

  Wire.begin(SDA_PIN, SCL_PIN);
  nfc.begin();
  uint32_t version = nfc.getFirmwareVersion();
  if (!version) {
    Serial.println("PN532 not found — check wiring and DIP switches (1 ON, 2 OFF)");
    while (true) {
      redBlink(1, 150);
      delay(700);
    }
  }
  Serial.printf("PN532 found, firmware %d.%d\n", (version >> 16) & 0xFF, (version >> 8) & 0xFF);

  nfc.SAMConfig();  // configure to read ISO14443A tags
  Serial.println("Ready — scan a tag");
  flashBlink(2, 80);
}

void loop() {
  connectWiFi();  // reconnect if dropped

  uint8_t uid[7];
  uint8_t uidLength;
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength, READ_TIMEOUT_MS)) {
    String tagId = uidToHex(uid, uidLength);
    unsigned long now = millis();
    if (tagId != lastUid || now - lastScanAt > SCAN_COOLDOWN_MS) {
      lastUid = tagId;
      lastScanAt = now;
      sendScan(tagId);
    }
  }
}
