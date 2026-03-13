import subprocess
import time
from collections import deque
import logging

# Suppress Scapy IPv6 warnings on boot
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import sniff, RadioTap, Dot11, conf

# --- Configuration ---
# REPLACE THIS with the exact Name or Index from `show_interfaces()`
WIFI_INTERFACE = "Intel(R) Wi-Fi 6 AX200 160MHz"  
TARGET_MAC = "aa:bb:cc:dd:ee:ff"
HUB_ID = "1-1"
PORT_NUM = "13"

TURN_ON_THRESH = -60
TURN_OFF_THRESH = -75
HISTORY_SIZE = 5

rssi_history = deque(maxlen=HISTORY_SIZE)
current_usb_state = "unknown"

def control_usb_power(action):
    global current_usb_state
    if current_usb_state == action:
        return
        
    print(f"[{time.strftime('%H:%M:%S')}] Trigger: Turning {action.upper()} USB power...")
    try:
        # Note: uhubctl on Windows requires it to be compiled with MinGW/libusb
        # Ensure uhubctl.exe is in your system PATH or provide the full path here.
        subprocess.run(
            ["uhubctl.exe", "-a", action, "-h", HUB_ID, "-p", PORT_NUM],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        current_usb_state = action
        print(f"Success: USB power is now {action.upper()}.")
    except FileNotFoundError:
        print("Error: uhubctl.exe not found. Is it in your PATH?")
    except subprocess.CalledProcessError as e:
        print(f"Failed to control USB: {e}")

def process_wifi_frame(packet):
    # In Windows Monitor Mode via Npcap, packets should still have RadioTap
    if packet.haslayer(RadioTap) and packet.haslayer(Dot11):
        if packet.addr2 and packet.addr2.lower() == TARGET_MAC.lower():
            try:
                rssi = packet[RadioTap].dBm_AntSignal
                if rssi is None:
                    return
                
                rssi_history.append(rssi)
                avg_rssi = sum(rssi_history) / len(rssi_history)
                
                print(f"Intercepted {TARGET_MAC} | Current: {rssi} dBm | Avg: {avg_rssi:.1f} dBm")
                
                if avg_rssi >= TURN_ON_THRESH:
                    control_usb_power("on")
                elif avg_rssi <= TURN_OFF_THRESH:
                    control_usb_power("off")
                    
            except AttributeError:
                pass

if __name__ == "__main__":
    print(f"Listening on {WIFI_INTERFACE} for MAC: {TARGET_MAC}")
    
    # store=0 prevents memory leaks during infinite sniffing
    sniff(
        iface=WIFI_INTERFACE, 
        prn=process_wifi_frame, 
        store=0
    )
