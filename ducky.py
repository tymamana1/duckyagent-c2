"""
DuckyScript Interpreter for Raspberry Pi USB Rubber Ducky

Reads .duckyscript files and types them using keyboard simulation.
Also works on the Pi when connected via USB Gadget mode.

DuckyScript commands supported:
  DELAY <ms>     - Wait milliseconds
  SLEEP <ms>     - Same as DELAY  
  STRING <text>  - Type text literally (no special keys)
  ENTER          - Press Enter/Return
  TAB            - Press Tab
  ESCAPE         - Press Escape
  BACKSPACE      - Press Backspace
  DELETE         - Press Delete key
  INSERT         - Press Insert key
  UP/DOWN/LEFT/RIGHT  - Arrow keys
  LEFT/SHIFT/CTRL/ALT/ALTGR  - Modifier keys
  GUI/WINDOWS    - Press Windows key (Win+R, etc.)
  F1-F12         - Function keys
  VOLUME_UP/DOWN/MUTE  - Volume controls

Usage: python ducky.py <script.duckyscript> [--delay <ms between chars>]
"""

import sys
import os
import time
import re

try:
    import pyautogui
    USE_PYAUTOGUI = True
except ImportError:
    USE_PYAUTOPI = False


def parse_duckyscript(filepath):
    """Parse a DuckyScript file and return list of (command, args) tuples."""
    commands = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, raw_line in enumerate(f.readlines(), 1):
            # Strip whitespace but preserve STRING content
            line = raw_line.rstrip()
            
            # Skip empty lines and comments
            if not line or line.startswith('//') or line.startswith('#'):
                continue
            
            parts = line.split(None, 1)
            cmd = parts[0].upper()
            args = parts[1] if len(parts) > 1 else ''
            
            commands.append((cmd, args))
    
    return commands


parse_script = parse_duckyscript


def send_key(key):
    """Send a single key press."""
    if USE_PYAUTOGUI:
        pyautogui.press(key)
    time.sleep(0.05)


def type_text(text, delay=10):
    """Type text character by character with small delays between each."""
    for char in text:
        pyautogui.write(char, interval=delay/1000)


def execute_command(cmd, args):
    """Execute a single DuckyScript command."""
    
    if cmd == 'DELAY' or cmd == 'SLEEP':
        try:
            ms = int(args.strip())
        except (ValueError, AttributeError):
            print(f"  [WARN] Invalid DELAY value: '{args}' — skipping")
            return
        ms = max(0, min(ms, 60000))
        time.sleep(ms / 1000.0)
        
    elif cmd == 'STRING':
        # Type the rest of the line as literal text
        type_text(args, delay=5)
        
    elif cmd == 'ENTER':
        send_key('enter')
        
    elif cmd == 'TAB':
        send_key('tab')
        
    elif cmd == 'ESCAPE' or cmd == 'ESCAP':
        send_key('esc')
        
    elif cmd.startswith('F') and len(cmd) == 2 and cmd[1].isdigit():
        fnum = int(cmd[1])
        if 1 <= fnum <= 9:
            send_key(f'f{fnum}')
        else:
            print(f"  [WARN] Unknown command: {cmd} '{args}'")
        
    elif cmd == 'BACKSPACE':
        send_key('backspace')
        
    elif cmd == 'DELETE':
        send_key('delete')
        
    elif cmd == 'INSERT':
        send_key('insert')
        
    elif cmd in ('UP ARROW', 'UP'):
        send_key('up')
        
    elif cmd in ('DOWN ARROW', 'DOWN'):
        send_key('down')
        
    elif cmd in ('LEFT ARROW', 'LEFT'):
        send_key('left')
        
    elif cmd in ('RIGHT ARROW', 'RIGHT'):
        send_key('right')
        
    elif cmd in ('GUI', 'WINDOWS'):
        # GUI alone presses the Windows key
        send_key('win')
        
    elif cmd in ('GUI', 'WINDOWS'):
        arg = args.strip().lower() if args else ''
        if arg == 'r':
            pyautogui.hotkey('win', 'r')
            time.sleep(0.5)
        elif arg == 'e':
            pyautogui.hotkey('win', 'e')
            time.sleep(0.5)
        else:
            send_key('win')
        
    elif cmd in ('CTRL', 'CONTROL'):
        arg = args.strip().lower() if args else ''
        if arg == 'c':
            pyautogui.hotkey('ctrl', 'c')
        elif arg == 'v':
            pyautogui.hotkey('ctrl', 'v')
        elif arg == 'a':
            pyautogui.hotkey('ctrl', 'a')
        elif arg == 'f':
            pyautogui.hotkey('ctrl', 'f')
        else:
            send_key('ctrl')
        
    elif cmd in ('CTRL SHIFT', 'CONTROL SHIFT'):
        arg = args.strip().lower() if args else ''
        if arg == 't':
            pyautogui.hotkey('ctrl', 'shift', 't')
        elif arg == 'esc' or arg == 'escape':
            pyautogui.hotkey('ctrl', 'shift', 'esc')
        else:
            pyautogui.hotkey('ctrl', 'shift', arg)
        
    elif cmd in ('ALT', 'ALTOPTION'):
        arg = args.strip().lower() if args else ''
        if arg == 'f4':
            pyautogui.hotkey('alt', 'f4')
        else:
            send_key('alt')
        
    elif cmd.startswith('F') and len(cmd) <= 3:
        try:
            fnum = int(cmd[1:])
            if 1 <= fnum <= 12:
                send_key(f'f{fnum}')
            else:
                print(f"  [WARN] Unknown command: {cmd} '{args}'")
        except ValueError:
            print(f"  [WARN] Unknown command: {cmd} '{args}'")
        
    elif cmd in ('VOLUME UP', 'VOLUMEUP'):
        for _ in range(3):
            send_key('volume_up')
            
    elif cmd in ('VOLUME DOWN', 'VOLUMEDOWN'):
        for _ in range(3):
            send_key('volume_down')
            
    elif cmd == 'VOLUME MUT':
        send_key('mute')
        
    else:
        # Unknown command - try to type it as text
        print(f"  [WARN] Unknown command: {cmd} '{args}'")


def run_script(filepath, verbose=True):
    """Run a DuckyScript file."""
    
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    
    commands = parse_duckyscript(filepath)
    
    if verbose:
        print(f"\n{'='*50}")
        print(f"Running: {os.path.basename(filepath)}")
        print(f"Commands: {len(commands)}")
        print(f"{'='*50}\n")
        
        # Show each command as it runs
        for i, (cmd, args) in enumerate(commands):
            display = f"{cmd}" + (f" {args}" if args else "")
            print(f"  [{i+1}/{len(commands)}] {display}")
    
    # Execute each command
    for cmd, args in commands:
        execute_command(cmd, args)
    
    if verbose:
        print(f"\n{'='*50}")
        print("Script complete!")
        print(f"{'='*50}\n")


def list_scripts(directory):
    """List all DuckyScript files in a directory."""
    scripts = []
    for f in os.listdir(directory):
        if f.endswith('.duckyscript') or f.endswith('.txt'):
            scripts.append(f)
    
    return sorted(scripts)


if __name__ == '__main__':
    script_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else '.', 'DuckyScripts')
    
    if len(sys.argv) < 2:
        print("Raspberry Pi USB Rubber Ducky - DuckyScript Interpreter")
        print("=" * 55)
        print()
        
        # List available scripts
        if os.path.exists(script_dir):
            scripts = list_scripts(script_dir)
            if scripts:
                print(f"Available scripts in {script_dir}:")
                for s in scripts:
                    print(f"  - {s}")
                print()
        
        print("Usage:")
        print("  python ducky.py <script.duckyscript>")
        print()
        print("Or run all scripts:")
        print("  python ducky.py --all")
        sys.exit(0)
    
    if sys.argv[1] == '--all':
        # Run all scripts in order
        scripts = list_scripts(script_dir)
        for s in scripts:
            filepath = os.path.join(script_dir, s)
            run_script(filepath)
            time.sleep(2)
    else:
        filepath = sys.argv[1]
        if not os.path.isabs(filepath):
            # Try relative to script dir first, then current dir
            alt_path = os.path.join(script_dir, filepath)
            if os.path.exists(alt_path):
                filepath = alt_path
        
        run_script(filepath)
