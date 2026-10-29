#include <WiFi.h>
#include <PubSubClient.h>
#include "DHT.h"
#include <time.h>

// ================== PIN ==================
#define DHTPIN 4
#define DHTTYPE DHT11
#define LDRPIN 34

#define LED1_PIN 21
#define LED2_PIN 19   
#define LED3_PIN 18
#define LED4_PIN 22 

// ================== WIFI ==================
const char* WIFI_SSID = "NHA TRO T4.5";
const char* WIFI_PASSWORD = "0969002292";

// ================== MQTT ==================
const char* MQTT_HOST = "192.168.1.229";
const uint16_t MQTT_PORT = 2000;
const char* MQTT_USER = "iotuser";
const char* MQTT_PASSWORD = "iot123";

// ================== SENSOR TOPICS ==================
const char* TOPIC_SENSOR = "iot/sensor/data";
const char* TOPIC_VALUES_TEMP = "iot/sensor/values/temperature";
const char* TOPIC_VALUES_HUM = "iot/sensor/values/humidity";
const char* TOPIC_VALUES_LIGHT = "iot/sensor/values/light";
const char* TOPIC_VALUES_CO2 = "iot/sensor/values/co2";
const char* TOPIC_VALUES_SUB = "iot/sensor/values/#";

// ================== LED TOPICS ==================
const char* TOPIC_LED1 = "iot/led/1";
const char* TOPIC_LED2 = "iot/led/2";
const char* TOPIC_LED3 = "iot/led/3";
const char* TOPIC_LED4 = "iot/led/4";
const char* TOPIC_LED_ALL = "iot/led/all";
const char* TOPIC_LED_SUB = "iot/led/#";

// ================== DEVICE ==================
const char* DEVICE_ID = "esp32-01";

// ================== INTERVAL ==================
const unsigned long SENSOR_INTERVAL = 2000;
const unsigned long WIFI_RETRY = 10000;
const unsigned long MQTT_RETRY = 3000;

// ================== OBJECT ==================
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHT dht(DHTPIN, DHTTYPE);

// ================== LED STATE ==================
bool led1State = false;
bool led2State = false;
bool led3State = false;
bool led4State = false;

// ================== TIMER ==================
unsigned long lastSensor = 0;
unsigned long lastWifi = 0;
unsigned long lastMqtt = 0;

// =================================================
// LDR
// =================================================
int readLight() {
  long total = 0;

  for (int i = 0; i < 10; i++) {
    total += analogRead(LDRPIN);
    delay(10);
  }

  int raw = total / 10;

  // Đảo chiều: sáng -> số cao, tối -> số thấp.
  // Nếu cảm biến của bạn cho chiều ngược lại, đổi thành: return raw;
  return 4095 - raw;
}

// =================================================
// TIME
// =================================================
String getTimeString() {
  time_t now = time(nullptr);

  if (now < 1700000000) {
    return "syncing";
  }

  struct tm timeInfo;
  localtime_r(&now, &timeInfo);

  char buffer[25];
  strftime(buffer, sizeof(buffer), "%d/%m/%Y %H:%M:%S", &timeInfo);

  return String(buffer);
}

// =================================================
// LED CONTROL
// =================================================
void setLed(int id, bool state) {
  switch (id) {
    case 1:
      led1State = state;
      digitalWrite(LED1_PIN, state ? HIGH : LOW);
      break;

    case 2:
      led2State = state;
      digitalWrite(LED2_PIN, state ? HIGH : LOW);
      break;

    case 3:
      led3State = state;
      digitalWrite(LED3_PIN, state ? HIGH : LOW);
      break;

    case 4:
      led4State = state;
      digitalWrite(LED4_PIN, state ? HIGH : LOW);
      break;
  }
}

// =================================================
// GET LED STATE
// =================================================
bool getLedState(int ledId) {
  switch (ledId) {
    case 1: return led1State;
    case 2: return led2State;
    case 3: return led3State;
    case 4: return led4State;
    default: return false;
  }
}

// =================================================
// PUBLISH LED STATUS
// =================================================
void publishLedStatus(int ledId) {
  bool state = getLedState(ledId);

  String topic = "iot/led/" + String(ledId) + "/status";

  String payload = "{";
  payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"led_id\":" + String(ledId) + ",";
  payload += "\"state\":\"";
  payload += state ? "ON" : "OFF";
  payload += "\",";
  payload += "\"executed_at\":\"" + getTimeString() + "\"";
  payload += "}";

  mqttClient.publish(topic.c_str(), payload.c_str(), true);

  Serial.println();
  Serial.println("LED STATUS:");
  Serial.print("Topic: ");
  Serial.println(topic);
  Serial.print("Data: ");
  Serial.println(payload);
}

// =================================================
// PUBLISH ALL LED STATUS
// =================================================
void publishAllLedStatus() {
  publishLedStatus(1);
  publishLedStatus(2);
  publishLedStatus(3);
  publishLedStatus(4);
}

// =================================================
// HANDLE ONE LED COMMAND
// =================================================
void handleLedCommand(int ledId, const String& command) {
  if (command == "ON") {
    setLed(ledId, true);
    publishLedStatus(ledId);
  } else if (command == "OFF") {
    setLed(ledId, false);
    publishLedStatus(ledId);
  }
}

// =================================================
// MQTT CALLBACK
// =================================================
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String message;

  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }

  message.trim();

  String upperMessage = message;
  upperMessage.toUpperCase();

  String topicString = String(topic);

  Serial.println();
  Serial.println("============================");
  Serial.println("MQTT MESSAGE");
  Serial.print("Time: ");
  Serial.println(getTimeString());
  Serial.print("Topic: ");
  Serial.println(topic);
  Serial.print("Message: ");
  Serial.println(message);

  // Manual sensor values
  if (topicString == TOPIC_VALUES_TEMP) {
    mqttClient.publish(TOPIC_VALUES_TEMP, message.c_str(), true);
    Serial.print("Temperature value -> ");
    Serial.println(message);
    return;
  }

  if (topicString == TOPIC_VALUES_HUM) {
    mqttClient.publish(TOPIC_VALUES_HUM, message.c_str(), true);
    Serial.print("Humidity value -> ");
    Serial.println(message);
    return;
  }

  if (topicString == TOPIC_VALUES_LIGHT) {
    mqttClient.publish(TOPIC_VALUES_LIGHT, message.c_str(), true);
    Serial.print("Light value -> ");
    Serial.println(message);
    return;
  }

  // Individual LED commands
  if (topicString == TOPIC_LED1) {
    handleLedCommand(1, upperMessage);
    return;
  }

  if (topicString == TOPIC_LED2) {
    handleLedCommand(2, upperMessage);
    return;
  }

  if (topicString == TOPIC_LED3) {
    handleLedCommand(3, upperMessage);
    return;
  }

  if (topicString == TOPIC_LED4) {
    handleLedCommand(4, upperMessage);
    return;
  }

  // All LEDs
  if (topicString == TOPIC_LED_ALL) {
    if (upperMessage == "ON") {
      setLed(1, true);
      setLed(2, true);
      setLed(3, true);
      setLed(4, true);
      publishAllLedStatus();
      Serial.println("ALL LED -> ON");
    } else if (upperMessage == "OFF") {
      setLed(1, false);
      setLed(2, false);
      setLed(3, false);
      setLed(4, false);
      publishAllLedStatus();
      Serial.println("ALL LED -> OFF");
    }
    return;
  }
}

// =================================================
// WIFI
// =================================================
void startWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  lastWifi = millis();

  Serial.print("Connecting WiFi");
}

// =================================================
// MAINTAIN WIFI
// =================================================
void maintainWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (millis() - lastWifi < WIFI_RETRY) {
    return;
  }

  lastWifi = millis();

  Serial.println();
  Serial.println("WiFi reconnect...");

  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// =================================================
// MQTT CONNECT
// =================================================
void connectMQTT() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  if (mqttClient.connected()) {
    return;
  }

  if (millis() - lastMqtt < MQTT_RETRY) {
    return;
  }

  lastMqtt = millis();

  String clientId = "ESP32-" + String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.print("Connecting MQTT...");

  if (mqttClient.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD)) {
    Serial.println("connected");

    mqttClient.subscribe(TOPIC_LED_SUB);
    mqttClient.subscribe(TOPIC_VALUES_SUB);

    Serial.print("Subscribe LED: ");
    Serial.println(TOPIC_LED_SUB);
    Serial.print("Subscribe sensor values: ");
    Serial.println(TOPIC_VALUES_SUB);

    // Publish initial states for all four LEDs
    publishAllLedStatus();
  } else {
    Serial.print("failed, state=");
    Serial.println(mqttClient.state());
  }
}

// =================================================
// SENSOR DATA
// =================================================
void publishSensorData() {
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  int light = readLight();
  int co2 = random(0, 102);   // 0..101

  if (isnan(temperature) || isnan(humidity)) {
    Serial.println("DHT11 READ FAILED!");
    return;
  }

  String tempValue = String(temperature, 1);
  String humValue = String(humidity, 1);
  String lightValue = String(light);
  String co2Value = String(co2);
  String timeValue = getTimeString();

  // Publish individual sensor values
  mqttClient.publish(TOPIC_VALUES_TEMP, tempValue.c_str(), true);
  mqttClient.publish(TOPIC_VALUES_HUM, humValue.c_str(), true);
  mqttClient.publish(TOPIC_VALUES_LIGHT, lightValue.c_str(), true);
  mqttClient.publish(TOPIC_VALUES_CO2, co2Value.c_str(), true);

  // Publish combined data with timestamp
  String dataPayload = "{";
  dataPayload += "\"temperature\":" + tempValue + ",";
  dataPayload += "\"humidity\":" + humValue + ",";
  dataPayload += "\"light\":" + lightValue + ",";
  dataPayload += "\"co2\":" + co2Value + ",";       
  dataPayload += "\"recorded_at\":\"" + timeValue + "\"";
  dataPayload += "}";

  mqttClient.publish(TOPIC_SENSOR, dataPayload.c_str(), true);

  // Serial output
  Serial.println();
  Serial.println("================================");
  Serial.println("SENSOR DATA PUBLISHED");
  Serial.println("================================");

  Serial.print(TOPIC_VALUES_TEMP);
  Serial.print(" -> ");
  Serial.println(tempValue);

  Serial.print(TOPIC_VALUES_HUM);
  Serial.print(" -> ");
  Serial.println(humValue);

  Serial.print(TOPIC_VALUES_LIGHT);
  Serial.print(" -> ");
  Serial.println(lightValue);

  Serial.println();
  Serial.print(TOPIC_SENSOR);
  Serial.print(" -> ");
  Serial.println(dataPayload);

  Serial.print("Time: ");
  Serial.println(timeValue);
  Serial.println("================================");
}

// =================================================
// SERIAL TEST
// =================================================
void handleSerial() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();
  command.toUpperCase();

  // Individual LEDs
  if (command == "ON1") {
    setLed(1, true);
    publishLedStatus(1);
  } else if (command == "OFF1") {
    setLed(1, false);
    publishLedStatus(1);
  } else if (command == "ON2") {
    setLed(2, true);
    publishLedStatus(2);
  } else if (command == "OFF2") {
    setLed(2, false);
    publishLedStatus(2);
  } else if (command == "ON3") {
    setLed(3, true);
    publishLedStatus(3);
  } else if (command == "OFF3") {
    setLed(3, false);
    publishLedStatus(3);
  } else if (command == "ON4") {
    setLed(4, true);
    publishLedStatus(4);
  } else if (command == "OFF4") {
    setLed(4, false);
    publishLedStatus(4);
  } else if (command == "ALLON") {
    setLed(1, true);
    setLed(2, true);
    setLed(3, true);
    setLed(4, true);
    publishAllLedStatus();
  } else if (command == "ALLOFF") {
    setLed(1, false);
    setLed(2, false);
    setLed(3, false);
    setLed(4, false);
    publishAllLedStatus();
  } else {
    Serial.println();
    Serial.println("Commands:");
    Serial.println("ON1 / OFF1");
    Serial.println("ON2 / OFF2");
    Serial.println("ON3 / OFF3");
    Serial.println("ON4 / OFF4");
    Serial.println("ALLON / ALLOFF");
  }
}

// =================================================
// SETUP
// =================================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  // LED pins
  pinMode(LED1_PIN, OUTPUT);
  pinMode(LED2_PIN, OUTPUT);
  pinMode(LED3_PIN, OUTPUT);
  pinMode(LED4_PIN, OUTPUT);

  // Turn off all LEDs at startup
  setLed(1, false);
  setLed(2, false);
  setLed(3, false);
  setLed(4, false);

  // LDR
  pinMode(LDRPIN, INPUT);

  // DHT11
  dht.begin();
  delay(2000);

  // WiFi
  startWiFi();

  // Vietnam time: UTC+7
  configTime(7 * 3600, 0, "pool.ntp.org", "time.nist.gov");

  // MQTT
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);

  Serial.println();
  Serial.println("============================");
  Serial.println("ESP32 SMART CLASSROOM");
  Serial.println("============================");

  Serial.println("Sensor values:");
  Serial.println("iot/sensor/values/temperature");
  Serial.println("iot/sensor/values/humidity");
  Serial.println("iot/sensor/values/light");

  Serial.println();
  Serial.println("Sensor data:");
  Serial.println("iot/sensor/data");

  Serial.println();
  Serial.println("LED control:");
  Serial.println("iot/led/1");
  Serial.println("iot/led/2");
  Serial.println("iot/led/3");
  Serial.println("iot/led/4");
  Serial.println("iot/led/all");

  Serial.println();
  Serial.println("LED status:");
  Serial.println("iot/led/1/status");
  Serial.println("iot/led/2/status");
  Serial.println("iot/led/3/status");
  Serial.println("iot/led/4/status");

  Serial.println();
  Serial.println("Serial commands:");
  Serial.println("ON1 / OFF1");
  Serial.println("ON2 / OFF2");
  Serial.println("ON3 / OFF3");
  Serial.println("ON4 / OFF4");
  Serial.println("ALLON / ALLOFF");
}

// =================================================
// LOOP
// =================================================
void loop() {
  maintainWiFi();
  connectMQTT();

  if (mqttClient.connected()) {
    mqttClient.loop();
  }

  handleSerial();

  if (mqttClient.connected() &&
      millis() - lastSensor >= SENSOR_INTERVAL) {
    lastSensor = millis();
    publishSensorData();
  }

  delay(10);
}
