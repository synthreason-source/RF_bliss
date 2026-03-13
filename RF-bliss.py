#include <WiFi.h>
#include <esp_wifi.h>

// --- Configuration ---
const uint8_t TARGET_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};

// GPIO pin to control the Relay / MOSFET for USB Power
const int RELAY_PIN = 1; 

// --- Trigger Logic ---
const int TURN_ON_THRESH = -60;       // Trigger if signal gets stronger than this
const int RSSI_CHANGE_TRIGGER = 10;   // Trigger if signal suddenly changes by 10 dBm

// --- Timer Configuration ---
const unsigned long USB_ON_DURATION = 5000; // 5000 milliseconds (5 seconds)

// 'volatile' is crucial on the single-core C3 to share variables between the WiFi task and loop()
volatile unsigned long usb_turn_on_time = 0;
volatile bool usb_timer_active = false;
volatile int current_channel = 1;

// Rolling Average Configuration
const int HISTORY_SIZE = 5;
int rssi_history[HISTORY_SIZE];
int history_index = 0;
bool history_filled = false;

// State management
unsigned long last_channel_hop = 0;
float last_stable_rssi = -100.0;

// Calculate the average RSSI
float get_average_rssi() {
  int sum = 0;
  int count = history_filled ? HISTORY_SIZE : history_index;
  if (count == 0) return -100.0; 
  for (int i = 0; i < count; i++) { sum += rssi_history[i]; }
  return (float)sum / count;
}

// Triggers the 5-second pulse
void trigger_usb_pulse(const char* reason) {
  if (!usb_timer_active) {
    Serial.printf("Trigger [%s]: Turning USB Power ON for 5 seconds (Pin 1 HIGH)\n", reason);
    digitalWrite(RELAY_PIN, HIGH);
  } else {
    Serial.printf("Trigger [%s]: Extending USB timer by 5 more seconds\n", reason);
  }
  
  // Start or reset the 5-second countdown
  usb_turn_on_time = millis();
  usb_timer_active = true;
}

// Promiscuous Mode Callback (Runs in the background WiFi Task)
void promiscuous_rx_cb(void *buf, wifi_promiscuous_pkt_type_t type) {
  wifi_promiscuous_pkt_t *pkt = (wifi_promiscuous_pkt_t *)buf;
  
  // Extract MAC address from payload offset 10
  uint8_t *mac_payload = pkt->payload;
  uint8_t transmitter_mac[6];
  for (int i = 0; i < 6; i++) {
    transmitter_mac[i] = mac_payload[10 + i];
  }

  // Check if it's our target device
  bool is_target = true;
  for (int i = 0; i < 6; i++) {
    if (transmitter_mac[i] != TARGET_MAC[i]) {
      is_target = false;
      break;
    }
  }

  if (is_target) {
    int rssi = pkt->rx_ctrl.rssi;
    
    rssi_history[history_index] = rssi;
    history_index++;
    if (history_index >= HISTORY_SIZE) {
      history_index = 0;
      history_filled = true;
    }
    
    float avg_rssi = get_average_rssi();
    float rssi_change = abs(avg_rssi - last_stable_rssi);
    
    // Evaluate Triggers
    if (history_filled && rssi_change >= RSSI_CHANGE_TRIGGER) {
      trigger_usb_pulse("Sudden dBm Change Detected");
      last_stable_rssi = avg_rssi;
    } 
    else if (avg_rssi >= TURN_ON_THRESH) {
      if (!usb_timer_active) {
        trigger_usb_pulse("Crossed ON Threshold");
      }
      last_stable_rssi = avg_rssi;
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // Start with USB power OFF

  // Set WiFi to Station mode but disconnect to free the 2.4GHz radio
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);

  Serial.println("Starting Promiscuous Mode on ESP32-C3 (Pin 1)...");
  
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&promiscuous_rx_cb);
  esp_wifi_set_channel(current_channel, WIFI_SECOND_CHAN_NONE);
  
  Serial.println("Tracking initialized.");
}

void loop() {
  // --- 1. Non-Blocking 5-Second Timer ---
  if (usb_timer_active && (millis() - usb_turn_on_time >= USB_ON_DURATION)) {
    Serial.println("Timer complete: Turning USB Power OFF (Pin 1 LOW)");
    digitalWrite(RELAY_PIN, LOW);
    usb_timer_active = false;
  }

  // --- 2. Channel Hopping Logic ---
  // The C3 only supports 2.4GHz Wi-Fi, so we loop strictly through channels 1-13
  if (millis() - last_channel_hop > 250) {
    int next_channel = current_channel + 1;
    if (next_channel > 13) {
      next_channel = 1;
    }
    current_channel = next_channel;
    esp_wifi_set_channel(current_channel, WIFI_SECOND_CHAN_NONE);
    last_channel_hop = millis();
  }
}
