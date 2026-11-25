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
import hashlib
from pathlib import Path

# Try urllib first (stdlib), fall back to requests if available
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


# ── Configuration ───────────────────────────────────────────────

CONFIG_DIR = "/usr/local/share/duckyscripts"
CONFIG_FILE = os.path.join(CONFIG_DIR, "loader.conf")
LOCAL_FALLBACKS = [
    "/usr/local/share/duckyscripts/default.duckyscript",
    "/home/pi/DuckyScripts/default.duckyscript",
]

# ── Config file format ──────────────────────────────────────────
# Each line is KEY=VALUE:
#   SCRIPT_URL=https://raw.githubusercontent.com/user/repo/main/payload.duckyscript
#   CHECK_INTERVAL=300    (seconds between checks, for interactive mode)
#   MAX_RETRIES=3         (how many times to retry download on failure)
#   FALLBACK_LOCAL=1      (if 1, try local files when remote fails)

def load_config():
    """Load configuration from file or environment variables."""
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


# ── Download logic ──────────────────────────────────────────────

def download_script(url, max_retries=3):
    """Download a .duckyscript from a remote URL with retry logic.

    Returns the script content as a string, or None on failure.
    """
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
                time.sleep(min(attempt * 2, 10))  # Exponential backoff, max 10s

    return None


def download_and_save(url, output_path):
    """Download a script and save it to disk. Returns True on success."""
    content = download_script(url)
    if content is None:
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    # Verify the saved file has valid DuckyScript content
    lines = [l.strip() for l in content.splitlines() if l.strip()]
    if not lines or all(l.startswith('#') or l.startswith('//') for l in lines):
        print("  [WARN] Downloaded file is empty or all comments")
        return False

    return True


# ── Script execution (same as run_duckyscript.py but inline) ─────

def parse_script(filepath):
    """Parse a DuckyScript file into commands."""
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
    """Send a key code using evdev/uinput."""
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
    """Execute parsed DuckyScript commands."""
    evdev_available = send_key(0)  # Test if evdev works
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


# ── Main logic ──────────────────────────────────────────────────

def main():
    """Main entry point for the remote DuckyScript loader."""
    # Parse command-line arguments
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
            # Treat as URL if it looks like one, otherwise skip
            if args[i].startswith('http://') or args[i].startswith('https://'):
                url = args[i]
            i += 1

    # Load config (overrides CLI defaults)
    config = load_config()
    script_url = url or config['script_url']
    max_retries = config['max_retries']
    fallback_local = config['fallback_local']

    print("=" * 50)
    print("  Raspberry Pi Remote DuckyScript Loader")
    print("=" * 50)
    print()

    # Step 1: Try to download from remote URL
    if script_url:
        print(f"Fetching script from:")
        print(f"  {script_url}")
        print()

        success = False
        for attempt in range(1, max_retries + 1):
            content = download_script(script_url, max_retries=1)
            if content is not None:
                # Save to local cache
                cached_path = os.path.join(CONFIG_DIR, "remote_payload.duckyscript")
                with open(cached_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                print(f"  [OK] Downloaded successfully ({len(content)} bytes)")
                print(f"  [OK] Saved to {cached_path}")
                print()

                # Run the downloaded script
                commands = parse_script(cached_path)
                run_commands(commands)
                success = True
                break
            else:
                if attempt < max_retries:
                    wait = min(attempt * 3, 15)
                    print(f"  [WARN] Retry in {wait}s...")
                    time.sleep(wait)

        # Step 2: Fallback to local scripts if download failed
        if not success and fallback_local:
            print("  [INFO] Remote fetch failed or unavailable")
            print("  [INFO] Falling back to local scripts...")
            print()

    # Step 3: Run local fallback script(s)
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
    # Handle signals gracefully (for systemd auto-run)
    running = [True]
    def handle_signal(sig, frame):
        running[0] = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if running[0]:
        main()
