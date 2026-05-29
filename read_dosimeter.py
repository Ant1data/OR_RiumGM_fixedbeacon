#!/usr/bin/env python3
"""
Simple serial reader for a Rium GM dosimeter (generic USB serial logger).

Contributors:
E. Martinet-Gerphagnon, PhD Student, ASNR x Institut Curie
A. Dreux, Data engineer in dosimetry, ASNR

Features:
- Scans likely serial device paths and/or accepts a `--port` override
- Tries a baud rate (configurable) and logs raw/line data
- Attempts simple numeric extraction from incoming text and writes CSV with timestamp
- Optionally prints hex dump for binary data

Usage examples:
  python3 read_dosimeter.py --port /dev/ttyUSB0
  python3 read_dosimeter.py --baud 9600 --hex

If the device protocol is known, replace the simple parsing section with a proper parser.
"""

import argparse
import atexit
import configparser
import csv
import errno
import glob
import getpass
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet


DEFAULT_SAVE_RATE = 900  # [s] - Default peiod for aggregating and sending measurements (15 minutes)
MAX_QUEUE_SIZE = 1400  # Maximum number of failed measurements to keep in queue
MAX_QUEUE_AGE_DAYS = 14  # Maximum age of queued measurements in days
MAX_LOCAL_DOSES = 10000  # Maximum number of dose measurements to keep in local CSV (~10 000 measurements @ 15min = ~3 years)
MIN_DURATION_FOR_API = 600  # [s] Minimum duration (10 min) required before sending a measurement to the API


def get_pid_file() -> str:
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.join(script_dir, 'read_dosimeter.pid')


def read_pid_file() -> Optional[int]:
    pid_file = get_pid_file()
    if not os.path.exists(pid_file):
        return None
    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            pid_text = f.read().strip()
            return int(pid_text)
    except Exception:
        return None


def is_process_running(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def write_pid_file() -> bool:
    pid_file = get_pid_file()
    try:
        with open(pid_file, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))
        try:
            os.chmod(pid_file, 0o600)
        except Exception:
            pass
        return True
    except Exception:
        return False


def remove_pid_file() -> None:
    pid_file = get_pid_file()
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass


# Global reference for signal handlers
_global_serial_port = None
_global_csv_file = None
_cleanup_done = False


def _signal_handler(signum, frame) -> None:
    """Handle signals (SIGINT, SIGTERM) by cleanly closing resources."""
    global _global_serial_port, _global_csv_file, _cleanup_done
    
    if _cleanup_done:
        return  # Prevent duplicate cleanup
    
    _cleanup_done = True
    print('\n\nShutting down gracefully...')
    
    # Close serial port with aggressive file descriptor cleanup
    if _global_serial_port:
        try:
            # Try to flush any pending data
            try:
                _global_serial_port.flush()
            except Exception:
                pass
            
            # Close the serial port
            _global_serial_port.close()
            print('  ✓ Serial port closed')
            
            # Explicitly close the underlying file descriptor
            try:
                fd = _global_serial_port.fd
                if fd and fd >= 0:
                    os.close(fd)
            except Exception:
                pass
                
        except Exception as e:
            print(f'  ✗ Error closing serial port: {e}')
    
    # Close CSV file
    if _global_csv_file:
        try:
            _global_csv_file.flush()
            _global_csv_file.close()
            print('  ✓ CSV file closed')
        except Exception as e:
            print(f'  ✗ Error closing CSV file: {e}')
    
    remove_pid_file()
    print('='*60)
    
    # Force exit to ensure complete process termination
    os._exit(0)


def setup_pidfile_cleanup() -> None:
    """Register PID file cleanup and signal handlers."""
    atexit.register(remove_pid_file)
    if os.name == 'posix':
        for sig_name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
            try:
                signal.signal(getattr(signal, sig_name), _signal_handler)
            except Exception:
                pass


def check_existing_pid_file() -> Optional[int]:
    pid = read_pid_file()
    if pid and is_process_running(pid):
        return pid
    if pid:
        remove_pid_file()
    return None

# Check and install dependencies automatically
def check_dependencies():
    """Check if required dependencies are installed and offer to install them."""
    missing = []
    
    try:
        import serial
    except ImportError:
        missing.append('pyserial')
    
    try:
        import requests
    except ImportError:
        missing.append('requests')
    
    try:
        import cryptography
    except ImportError:
        missing.append('cryptography')
    
    if missing:
        print("="*60)
        print("Missing required dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("="*60)
        print("\nOn Raspberry Pi OS you can install system packages (preferred):")
        print("  sudo apt update && sudo apt install -y python3-serial python3-requests")
        print("\nOr install with pip:")
        print(f"  pip3 install {' '.join(missing)}")
        print("\nOr install all requirements via pip:")
        print("  pip3 install -r requirements.txt")
        print("="*60)
        
        # Try auto-install if user agrees (only in interactive mode)
        if sys.stdin.isatty():
            try:
                response = input("\nAttempt automatic installation? (yes/no) [yes]: ").strip().lower()
                if response in ['', 'yes', 'y']:
                    import subprocess
                    print("\nInstalling dependencies...")
                    result = subprocess.run(
                        [sys.executable, '-m', 'pip', 'install'] + missing,
                        capture_output=True,
                        text=True
                    )
                    if result.returncode == 0:
                        print("Dependencies installed successfully!")
                        print("Please run the script again.")
                        sys.exit(0)
                    else:
                        print(f"Installation failed: {result.stderr}")
                        sys.exit(1)
            except KeyboardInterrupt:
                print("\nInstallation cancelled.")
                sys.exit(1)
        
        sys.exit(1)

check_dependencies()

import serial
import requests


def find_candidate_ports():
    """Return a list of likely serial ports (all major OS)."""
    ports = []
    if os.name == 'posix':
        import platform
        if platform.system() == 'Darwin':  # macOS
            ports.extend(sorted(glob.glob('/dev/tty.usbserial*')))
            ports.extend(sorted(glob.glob('/dev/tty.usbmodem*')))
            ports.extend(sorted(glob.glob('/dev/cu.usbserial*')))
            ports.extend(sorted(glob.glob('/dev/cu.usbmodem*')))
        else:  # Linux / Raspberry Pi
            ports.extend(sorted(glob.glob('/dev/ttyUSB*')))
            ports.extend(sorted(glob.glob('/dev/ttyACM*')))
            ports.extend(sorted(glob.glob('/dev/serial/by-id/*')))
    # Windows (and fallback for any OS via pyserial enumeration)
    try:
        import serial.tools.list_ports
        detected = [p.device for p in serial.tools.list_ports.comports()]
        for p in detected:
            if p not in ports:
                ports.append(p)
    except Exception:
        pass
    return ports


def validate_dosimeter_connection(port, baud, timeout=20):
    """
    Test if a Rium GM dosimeter is connected on the given port.
    Returns True if valid frames detected, False otherwise.
    """
    print(f"Testing connection on {port}...", end=' ', flush=True)
    try:
        ser = serial.Serial(port=port, baudrate=baud, timeout=2)
        buffer = bytearray()
        start_time = time.time()
        
        # Read for a few seconds looking for valid frames
        while (time.time() - start_time) < timeout:
            if ser.in_waiting > 0:
                b = ser.read(1)
                if not b:
                    continue
                buffer.append(b[0])
                
                # Keep buffer reasonable
                if len(buffer) > 100:
                    del buffer[0:len(buffer) - 100]
                
                # Look for C1 00 header
                if len(buffer) >= 12:
                    for i in range(len(buffer) - 11):
                        if buffer[i] == 0xC1 and buffer[i+1] == 0x00:
                            # Found potential frame
                            frame = bytes(buffer[i:i+12])
                            parsed = parse_rium_frame(frame)
                            if parsed:
                                ser.close()
                                print("Rium GM detected!")
                                return True
        
        ser.close()
        print("No valid Rium frames detected")
        return False
        
    except serial.SerialException as e:
        print(f"Error: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False


def load_config(config_path='config.ini'):
    """Load configuration from INI file."""
    config = configparser.ConfigParser()
    
    # Find config file in script directory if relative path
    if not os.path.isabs(config_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, config_path)
    
    if not os.path.exists(config_path):
        print("="*60)
        print("Configuration file not found!")
        print("="*60)
        print(f"Expected location: {config_path}")
        print("\nCreating a template config.ini file...")
        
        config['DEFAULT'] = {
            'api_key': '',
            'username': '',
            'latitude': '',
            'longitude': '',
            'user_id': '',
            'tags': ''
        }
        
        with open(config_path, 'w') as f:
            f.write("# OpenRadiation API Configuration\n")
            f.write("# ASNR Project\n\n")
            f.write("[DEFAULT]\n")
            f.write("# Get your API key from: https://www.openradiation.org/\n")
            f.write("api_key = \n\n")
            f.write("# OpenRadiation account credentials\n")
            f.write("# Use either user_id or username plus password in encrypted storage (not stored here).\n")
            f.write("username = \n")
            f.write("# password = (not stored in config.ini; use --set-password command or setup wizard)\n\n")
            f.write("# Fixed station GPS coordinates (decimal degrees)\n")
            f.write("# Example: 48.8566 for Paris\n")
            f.write("latitude = \n")
            f.write("longitude = \n\n")
            f.write("# Optional: User ID\n")
            f.write("user_id = \n\n")
            f.write("# Optional: Tags (comma-separated)\n")
            f.write("# Example: station=Home, device=RiumGM_001\n")
            f.write("tags = \n")
        
        print(f"Template created: {config_path}")
        print("="*60)
        print("\nConfiguration needed! You have 2 options:")
        print("  1. Run the setup wizard:")
        print("     python3 setup_config.py")
        print("\n  2. Edit config.ini manually:")
        print(f"     nano {config_path}")
        print("="*60)
        
        # Offer to run setup wizard
        if sys.stdin.isatty():
            try:
                response = input("\nRun setup wizard now? (yes/no) [yes]: ").strip().lower()
                if response in ['', 'yes', 'y']:
                    setup_script = os.path.join(os.path.dirname(config_path), 'setup_config.py')
                    if os.path.exists(setup_script):
                        import subprocess
                        subprocess.run([sys.executable, setup_script])
                        print("\nConfiguration complete! Please run the script again.")
                        sys.exit(0)
                    else:
                        print(f"Setup wizard not found at: {setup_script}")
            except KeyboardInterrupt:
                print("\nConfiguration postponed.")
        
        return None
    
    config.read(config_path)
    return config['DEFAULT']


def get_stored_password(username: str) -> Optional[str]:
    """Retrieve a stored password from encrypted file."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        key_file = os.path.join(script_dir, '.dosimeter_key')
        password_file = os.path.join(script_dir, f'.dosimeter_{username}')

        if not os.path.exists(key_file) or not os.path.exists(password_file):
            return None

        # Load encryption key
        with open(key_file, 'rb') as f:
            key = f.read()

        fernet = Fernet(key)

        # Load and decrypt password
        with open(password_file, 'rb') as f:
            encrypted_password = f.read()

        decrypted_password = fernet.decrypt(encrypted_password).decode()
        return decrypted_password

    except Exception:
        return None


def set_stored_password(username: str, password: str) -> bool:
    """Store a password securely in encrypted file."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        key_file = os.path.join(script_dir, '.dosimeter_key')
        password_file = os.path.join(script_dir, f'.dosimeter_{username}')

        # Generate or load encryption key
        if not os.path.exists(key_file):
            key = Fernet.generate_key()
            with open(key_file, 'wb') as f:
                f.write(key)
            # Set restrictive permissions on key file
            os.chmod(key_file, 0o600)
        else:
            with open(key_file, 'rb') as f:
                key = f.read()

        fernet = Fernet(key)
        encrypted_password = fernet.encrypt(password.encode())

        # Store encrypted password
        with open(password_file, 'wb') as f:
            f.write(encrypted_password)

        # Set restrictive permissions on password file
        os.chmod(password_file, 0o600)
        return True

    except Exception:
        return False


def open_serial(port, baud, timeout=None):
    # Use blocking reads by default (timeout=None) so we can read single bytes
    # with minimal latency. This gives high time-sensitivity for detecting hits.
    return serial.Serial(port=port, baudrate=baud, timeout=timeout)


def hexdump(b: bytes) -> str:
    return ' '.join(f'{x:02x}' for x in b)


def convert_cps_to_usvh(cps, factor, formula=None):
    """Convert CPM (counts per second) to µSv/h using either a factor or formula."""
    if formula:
        # Accept '^' as power for convenience, convert to Python '**'
        safe_formula = formula.replace('^', '**')
        safe_locals = {'cps': cps, 'abs': abs, 'max': max, 'min': min, 'pow': pow}
        try:
            value = eval(safe_formula, {'__builtins__': {}}, safe_locals)
            return float(value)
        except Exception as e:
            print(f"Warning: invalid cps-to-usvh formula '{formula}': {e}")
            print(f"Falling back to simple factor conversion: cps * {factor}")
            return cps * factor
    return cps * factor


def get_queue_file():
    """Get the path to the queue file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'pending_measurements.json')


def load_queue():
    """Load pending measurements from queue file."""
    queue_file = get_queue_file()
    if not os.path.exists(queue_file):
        return []
    
    try:
        with open(queue_file, 'r') as f:
            queue = json.load(f)
        
        # Filter out measurements older than MAX_QUEUE_AGE_DAYS
        now = time.time()
        max_age_seconds = MAX_QUEUE_AGE_DAYS * 24 * 60 * 60
        
        filtered_queue = []
        for item in queue:
            queued_time = item.get('queued_at', 0)
            if now - queued_time < max_age_seconds:
                filtered_queue.append(item)
        
        # Keep only the most recent MAX_QUEUE_SIZE items
        if len(filtered_queue) > MAX_QUEUE_SIZE:
            filtered_queue = filtered_queue[-MAX_QUEUE_SIZE:]
        
        # Save filtered queue back if we removed items
        if len(filtered_queue) < len(queue):
            save_queue(filtered_queue)
        
        return filtered_queue
    except Exception as e:
        print(f"Warning: Could not load queue file: {e}")
        return []


def save_queue(queue):
    """Save pending measurements to queue file."""
    queue_file = get_queue_file()
    try:
        with open(queue_file, 'w') as f:
            json.dump(queue, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save queue file: {e}")


def get_local_doses_file():
    """Get the path to the local doses CSV file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'local_dose_rates.csv')


def save_local_dose(timestamp, value, duration, device_id='', temp=0):
    """Save dose measurement to local CSV (rolling last MAX_LOCAL_DOSES measurements, ~3 years @ 15min)."""
    local_file = get_local_doses_file()
    
    try:
        # Append-only: much faster than read-all / write-all for 10 000 rows
        file_exists = os.path.exists(local_file)
        with open(local_file, 'a', newline='') as f:
            fieldnames = ['timestamp', 'iso_time', 'dose_rate_usvh', 'duration_s', 'device_id', 'temperature_c']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'timestamp': timestamp,
                'iso_time': datetime.fromtimestamp(float(timestamp), tz=timezone.utc).isoformat(),
                'dose_rate_usvh': f"{value:.4f}",
                'duration_s': f"{duration:.1f}",
                'device_id': device_id,
                'temperature_c': f"{temp:.1f}"
            })
        
        # Trim to MAX_LOCAL_DOSES only when file is large (every 100 writes)
        try:
            with open(local_file, 'r', newline='') as f:
                rows = list(csv.DictReader(f))
            if len(rows) > MAX_LOCAL_DOSES:
                rows = rows[-MAX_LOCAL_DOSES:]
                with open(local_file, 'w', newline='') as f:
                    fieldnames = ['timestamp', 'iso_time', 'dose_rate_usvh', 'duration_s', 'device_id', 'temperature_c']
                    w = csv.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(rows)
        except Exception:
            pass  # trim failure is non-critical
        
        return True
    except Exception as e:
        print(f"Warning: Could not save local dose measurement: {e}")
        return False


def add_to_queue(api_key, data, production=False):
    """Add a failed measurement to the queue."""
    queue = load_queue()
    
    queue_item = {
        'api_key': api_key,
        'data': data,
        'production': production,
        'queued_at': time.time()
    }
    
    queue.append(queue_item)
    
    # Keep only the most recent MAX_QUEUE_SIZE items
    if len(queue) > MAX_QUEUE_SIZE:
        queue = queue[-MAX_QUEUE_SIZE:]
    
    save_queue(queue)
    print(f"  Added to queue ({len(queue)} pending measurements)")


def process_queue():
    """Try to send all queued measurements."""
    queue = load_queue()
    if not queue:
        return
    
    print(f"\nProcessing queue: {len(queue)} pending measurements...")
    
    successful = []
    failed = []
    
    for idx, item in enumerate(queue):
        print(f"  Attempt {idx + 1}/{len(queue)}...", end=' ')
        
        # Try to send without retries (we're already in retry mode)
        if post_measurement(
            item['api_key'],
            item['data'],
            item['production'],
            max_retries=1  # Single attempt for queued items
        ):
            successful.append(item)
            print("OK")
        else:
            failed.append(item)
            print("FAILED")
            # Don't spam if multiple failures
            if len(failed) >= 3:
                print(f"  (Stopping after 3 consecutive failures)")
                # Keep the rest in queue
                failed.extend(queue[idx + 1:])
                break
    
    # Update queue with only the failed ones
    save_queue(failed)
    
    if successful:
        print(f"Successfully sent {len(successful)} queued measurements")
    if failed:
        print(f"  ({len(failed)} measurements still in queue)")


def parse_rium_frame(frame: bytes) -> dict:
    """
    Parse a single Rium frame (12 bytes).
    Format: C1 00 | AA AA AA AA | BB BB | CC CC | DD DD
    - C1 00: Header
    - A (4 bytes): Device ID (32 bits)
    - B (2 bytes): Count (16 bits)
    - C (2 bytes): Delay in deciseconds (16 bits)
    - D (2 bytes): Temperature in deciseconds (16 bits) 
    
    Returns dict with parsed data or None if invalid frame.
    """
    if len(frame) != 12:
        return None
    
    # Check header
    if frame[0] != 0xC1 or frame[1] != 0x00:
        return None
    
    # Extract fields
    device_id = frame[2:6].hex()  # 4 bytes -> 8 hex chars
    count = int.from_bytes(frame[6:8], byteorder='big')
    delay_decisec = int.from_bytes(frame[8:10], byteorder='big')
    temp_decisec = int.from_bytes(frame[10:12], byteorder='big')
    
    return {
        'device': device_id,
        'count': count,
        'delay': delay_decisec / 10.0,  # Convert to seconds
        'temp': temp_decisec / 10.0      # Convert to °C
    }


def post_measurement(api_key, data, production, max_retries=3):
    """
    Post measurement data to OpenRadiation API with retry logic.
    Returns True if successful, False otherwise.
    """
    print("\nPosting measurement to OpenRadiation API...")
    print("production:", production )
    print

    url = "https://submit.openradiation.net/measurements"
    payload = {
        "apiKey": api_key,
        "data": data 
    }
    if not production:
        print("Sending in TEST mode (reportContext=test)")
        payload["data"]["reportContext"] = "test"
    else:
        print("Sending in PRODUCTION mode (reportContext=routine)")
        payload["data"]["reportContext"] = "routine"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    # Show sent data for debugging
    print("Prepared measurement data for API:")
    # print json but not password
    print(json.dumps({**payload, "data": {**payload["data"], "userPwd": "****" if "userPwd" in payload["data"] else None}}, indent=2))
    print(f"API endpoint: {url}")
    
    # Retry loop with exponential backoff
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                print("Measurement posted successfully.")
                return True
            else:
                print(f"Failed to post measurement: {response.status_code}")
                print(f"  Response: {response.text}")
                
                # If it's a client error (4xx), don't retry
                if 400 <= response.status_code < 500:
                    print("  Client error, not retrying.")
                    return False
                    
                # Server error (5xx), retry
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"  Retrying in {wait_time}s... (attempt {attempt + 2}/{max_retries})")
                    time.sleep(wait_time)
                    
        except requests.exceptions.Timeout:
            print(f"Error: Request timeout after 30s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"  Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        except requests.exceptions.ConnectionError as e:
            print(f"Error: No internet connection (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                print(f"  Will retry in {wait_time}s...")
                print(f"  (Measurements continue to be logged locally)")
                time.sleep(wait_time)
                
        except Exception as e:
            print(f"Error posting measurement: {e} (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"  Retrying in {wait_time}s...")
                time.sleep(wait_time)
    
    # All retries failed
    print("Failed to post measurement after all retries.")
    print("  Data has been saved locally in CSV file.")
    
    # Add to queue for later retry (only if max_retries > 1, to avoid queuing during queue processing)
    if max_retries > 1:
        add_to_queue(api_key, data, production)
        print("  Will retry automatically when connection is restored.")
    
    return False



def main():
    parser = argparse.ArgumentParser(
        description='Read Rium GM dosimeter via USB serial and log data.',
        epilog='Configuration: API credentials and location are read from config.ini file.'
    )
    parser.add_argument('--port', '-p', help='Serial port (e.g. /dev/ttyUSB0 or COM3). If omitted, tries to auto-detect.')
    parser.add_argument('--baud', '-b', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('--csv', default='dosimeter_log.csv', help='CSV file to append logs to')
    parser.add_argument('--dat-dir', default='rium_data/wd', help='Directory for .dat files (default: rium_data/wd)')
    parser.add_argument('--json-dir', default='rium_data/upload', help='Directory for .json files (default: rium_data/upload)')
    parser.add_argument('--config', default='config.ini', help='Path to configuration file (default: config.ini)')
    parser.add_argument('--hex', action='store_true', help='Print hex dump of incoming bytes instead of trying to parse text')
    parser.add_argument('--raw', action='store_true', help='Write raw bytes (base64) into CSV raw_data column')
    parser.add_argument('--list', action='store_true', help='List candidate ports and exit')
    parser.add_argument('--send-data', action='store_true', help='Enable sending data to OpenRadiation API (default: disabled)')
    
    # Optional overrides for config file values (useful for testing)
    parser.add_argument('--api-key', help='Override API key from config.ini')
    parser.add_argument('--latitude', type=float, help='Override latitude from config.ini')
    parser.add_argument('--longitude', type=float, help='Override longitude from config.ini')
    parser.add_argument('--user-id', help='Override user ID from config.ini')

    # Sensitivity of Rium GM : Sensitivity 2.6 cps/µSv/h according to https://www.riummanufacturing.com/products/gm-tubes/ and user reports. This means 1 CPS corresponds to approximately 0.385 µSv/h, so the conversion factor is 1/2.6.
    parser.add_argument('--cps-to-usvh', type=float, default=1/2.6, help='Conversion factor from CPS to µSv/h (default: 1/2.6)')
    parser.add_argument('--cps-to-usvh-func', default=None, help='Conversion formula of cps to µSv/h, e.g. "(0.00000003751 * (cps * 60 - 4)**2 + 0.00965 * (cps * 60 - 4)) * 0.85"')
    parser.add_argument('--production', action='store_true', help='Set reportContext to routine (real data) instead of test. Use with caution!')
    parser.add_argument('--tag', action='append', default=[], help='Add tags to measurements (can be used multiple times, e.g. --tag location=Paris --tag device=GM1)')
    parser.add_argument('--set-password', help='Set password for a user ID in encrypted storage (e.g. --set-password myuser)')
    parser.add_argument('--clear-password', help='Clear stored password for a user ID from encrypted storage (e.g. --clear-password myuser)')
    parser.add_argument('--save-rate', type=float, help='Save/send interval in minutes (minimum 15)')
    parser.add_argument('--test-duration', type=int, help='Run for given seconds then stop (useful for quick TEST runs)')
    
    args = parser.parse_args()
    print("Production : ", args.production)
    print("send_data : ", args.send_data)
    # Handle password management commands first (before other processing)

    if args.set_password:
        if not sys.stdin.isatty():
            print("Error: --set-password requires interactive terminal")
            sys.exit(1)
        password = getpass.getpass(f"Enter password for user '{args.set_password}': ")
        if set_stored_password(args.set_password, password):
            print(f"Password stored securely for user '{args.set_password}'")
        else:
            print("Failed to store password")
        sys.exit(0)
    
    if args.clear_password:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        password_file = os.path.join(script_dir, f'.dosimeter_{args.clear_password}')
        key_file = os.path.join(script_dir, '.dosimeter_key')
        
        try:
            # Remove password file if it exists
            if os.path.exists(password_file):
                os.remove(password_file)
                print(f"Password cleared for user '{args.clear_password}'")
            else:
                print(f"No stored password found for user '{args.clear_password}'")
            
            # Optionally remove key file if no other passwords exist
            # Check if any other .dosimeter_* files exist
            import glob
            password_files = glob.glob(os.path.join(script_dir, '.dosimeter_*'))
            # Remove key file from the list
            if key_file in password_files:
                password_files.remove(key_file)
            
            if not password_files and os.path.exists(key_file):
                os.remove(key_file)
                print("Encryption key file also removed (no passwords remaining)")
                
        except Exception as e:
            print(f"Error clearing password: {e}")
        sys.exit(0)
    
    # Welcome banner
    print("\n" + "="*60)
    print("  RIUM GM DOSIMETER READER")
    print("  ASNR Project")
    print("="*60)
    print()

    # Load configuration from file
    config = load_config(args.config)
    if config is None and args.send_data:
        print("Error: Cannot send data without valid configuration.")
        sys.exit(1)

    # Determine SAVE_RATE (seconds) from CLI or config (config stored in minutes)
    SAVE_RATE = DEFAULT_SAVE_RATE
    stop_time = None
    if args.test_duration:
        try:
            SAVE_RATE = int(args.test_duration)
            stop_time = time.time() + args.test_duration
        except Exception:
            stop_time = None

    # Production/default: try CLI --save-rate (minutes) then config 'save_rate' (minutes)
    if args.save_rate:
        try:
            minutes = float(args.save_rate)
            if minutes < 15:
                print("Warning: save-rate minimum is 15 minutes; using 15 minutes.")
                minutes = 15
            SAVE_RATE = int(minutes * 60)
        except Exception:
            pass
    elif config and config.get('save_rate'):
        try:
            minutes = float(config.get('save_rate'))
            if minutes < 15:
                print("Warning: configured save_rate is less than 15 minutes; using 15 minutes.")
                minutes = 15.0
            SAVE_RATE = int(minutes * 60)
        except Exception:
            pass

    # Merge config file values with command line arguments (CLI takes precedence)
    api_key = args.api_key if args.api_key else (config.get('api_key') if config else None)
    
    # Validate and convert latitude/longitude to float
    latitude = None
    longitude = None
    
    if args.latitude is not None:
        latitude = float(args.latitude)
    elif config and config.get('latitude'):
        try:
            latitude = float(config.get('latitude'))
        except (ValueError, TypeError):
            print(f"Error: Invalid latitude value in config: '{config.get('latitude')}' (must be a number)")
            latitude = None
    
    if args.longitude is not None:
        longitude = float(args.longitude)
    elif config and config.get('longitude'):
        try:
            longitude = float(config.get('longitude'))
        except (ValueError, TypeError):
            print(f"Error: Invalid longitude value in config: '{config.get('longitude')}' (must be a number)")
            longitude = None
    
    # Validate API key is a non-empty string
    if api_key and not isinstance(api_key, str):
        api_key = str(api_key)
    if api_key:
        api_key = api_key.strip()
        if not api_key:
            api_key = None
    
    user_id = args.user_id if args.user_id else (config.get('user_id') if config else None)
    username = config.get('username') if config else None

    # Always use OpenRadiation username as userId, unless explicit user_id override given
    if not user_id and username:
        user_id = username

    user_pwd = config.get('password') if config else None

    credential_key = user_id or username

    # If plain-text password is found in config, save it to encrypted storage and use it
    if user_pwd and credential_key:
        if set_stored_password(credential_key, user_pwd):
            print(f"Password migrated to encrypted storage for '{credential_key}'.")
        user_pwd = user_pwd  # still use current value for this session

    # If we are going to send data and no password present, try encrypted storage/prompt
    if args.send_data and credential_key and not user_pwd:
        user_pwd = get_stored_password(credential_key)
        if not user_pwd and sys.stdin.isatty():
            # Prompt for password once, store it securely for future runs
            user_pwd = getpass.getpass(f"Password for user '{credential_key}': ")
            if user_pwd:
                if not set_stored_password(credential_key, user_pwd):
                    print("Warning: could not store password in encrypted storage")
        elif not user_pwd:
            print("Warning: no password stored for user; API upload may fail")
    
    # Parse tags from config file (comma-separated) and merge with CLI tags
    config_tags = []
    if config and config.get('tags'):
        config_tags = [tag.strip() for tag in config.get('tags').split(',') if tag.strip()]
    
    # Combine tags from config and CLI
    all_tags = [tag.strip() for tag in (config_tags + args.tag) if tag.strip()]

    # Display configuration status
    print("="*60)
    print("RIUM GM DOSIMETER READER - Configuration")
    print("="*60)
    if config:
        print(f"Configuration file: {args.config}")
        print(f"  API Key: {'*' * 8 + api_key[-4:] if api_key and len(api_key) > 4 else 'NOT SET'}")
        print(f"  Username: {username if username else 'NOT SET'}")
        print(f"  Password: {'*' * len(user_pwd) if user_pwd else 'NOT SET'}")
        print(f"  Location: {latitude}, {longitude}" if latitude and longitude else "  Location: NOT SET")
        print(f"  User ID: {user_id if user_id else 'NOT SET'}")
        print(f"  Tags: {', '.join(all_tags) if all_tags else 'NONE'}")
        print(f"  Save rate: {SAVE_RATE // 60} minutes")
    print(f"Data submission: {'ENABLED (production)' if args.send_data and args.production else 'ENABLED (test mode)' if args.send_data else 'DISABLED'}")
    
    
    # Show queue status
    if args.send_data:
        queue = load_queue()
        if queue:
            print(f"Queued measurements: {len(queue)} pending (will retry when connection is restored)")
    
    print("="*60 + "\n")

    # Validate send-data requirements
    if args.send_data:
        missing = []
        if not api_key:
            missing.append("API key")
        if latitude is None or longitude is None:
            missing.append("Location (latitude/longitude)")
        
        if missing:
            print(f"Error: The following are required when --send-data is enabled:")
            for item in missing:
                print(f"  - {item}")
            print(f"\nPlease edit {args.config} or use command line arguments.")
            sys.exit(1)

    candidates = find_candidate_ports()
    print('='*60)
    print('Available serial ports:')
    print('='*60)
    if candidates:
        for p in candidates:
            print(f'  {p}')
    else:
        print('  No serial ports detected!')
        print('  Please check:')
        print('    - Dosimeter is connected via USB')
        print('    - USB cable is functional')
        print('    - Device drivers are installed')
    print('='*60)

    port = args.port
    if not port:
        # If no candidate ports found, don't exit immediately. Offer interactive retry
        # or wait briefly in non-interactive contexts. This prevents the launcher
        # from returning immediately when the device is not yet connected.
        if not candidates:
            print('='*60)
            print('No serial ports detected.')
            print('Please check the dosimeter connection and drivers.')
            print('='*60)

            if sys.stdin.isatty():
                try:
                    user_input = input("Press Enter to retry, enter a port (e.g. COM3 or /dev/ttyUSB0), or 'q' to quit: ").strip()
                    if user_input.lower() == 'q':
                        sys.exit(1)
                    elif user_input:
                        port = user_input
                    else:
                        # Retry once immediately
                        candidates = find_candidate_ports()
                except KeyboardInterrupt:
                    print('\nCancelled.')
                    sys.exit(1)
            else:
                # Non-interactive (service) mode: retry 3 times with a delay between attempts
                USB_MAX_RETRIES = 3
                USB_RETRY_DELAY = 15  # seconds between attempts
                usb_found = False
                for usb_attempt in range(1, USB_MAX_RETRIES + 1):
                    print(f'USB scan attempt {usb_attempt}/{USB_MAX_RETRIES}...')
                    candidates = find_candidate_ports()
                    if candidates:
                        usb_found = True
                        break
                    if usb_attempt < USB_MAX_RETRIES:
                        print(f'No USB serial port found. Retrying in {USB_RETRY_DELAY}s...')
                        time.sleep(USB_RETRY_DELAY)
                if not usb_found:
                    print('No serial ports detected after 3 attempts.')
                    print('Service will stop cleanly and restart at next system boot.')
                    sys.exit(0)  # Exit code 0 = clean stop; systemd (Restart=on-failure) won't restart immediately

        # Auto-detect: try to validate each candidate
        if not port:
            print("Auto-detecting Rium GM dosimeter...")
            print("="*60)
            port = None
            for candidate in candidates:
                if validate_dosimeter_connection(candidate, args.baud):
                    port = candidate
                    break

            if not port:
                print("="*60)
                print("Could not auto-detect Rium GM dosimeter")
                print("="*60)
                print("Detected serial ports:")
                for i, p in enumerate(candidates, 1):
                    print(f"  {i}. {p}")
                print("\nThe device may be:")
                print("  • Not sending data yet (needs to detect radiation)")
                print("  • Using a different baud rate")
                print("  • Not a Rium GM dosimeter")
                print("\nYou can:")
                print("  1. Choose a port from the list above")
                print("  2. Specify port manually: --port /dev/ttyUSB0")
                print("  3. Wait for the dosimeter to start sending data")
                print("  4. Check the dosimeter is powered on")
                print("="*60)

                # Offer to choose from available ports
                if sys.stdin.isatty():
                    try:
                        while True:
                            choice = input(f"\nChoose a port (1-{len(candidates)}) or 'q' to quit [1]: ").strip().lower()
                            if choice in ['', '1']:
                                port = candidates[0]
                                print(f"Using {port} (not validated)")
                                break
                            elif choice == 'q':
                                sys.exit(1)
                            elif choice.isdigit() and 1 <= int(choice) <= len(candidates):
                                port = candidates[int(choice) - 1]
                                print(f"Using {port} (not validated)")
                                break
                            else:
                                print(f"Invalid choice. Please enter 1-{len(candidates)} or 'q'.")
                    except KeyboardInterrupt:
                        print("\nCancelled.")
                        sys.exit(1)
                else:
                    # Non-interactive: use first port
                    port = candidates[0]
                    print(f"Non-interactive mode: using first port {port}")
    else:
        print(f'Using specified port: {port}')

    setup_pidfile_cleanup()
    if not write_pid_file():
        print('Warning: could not write PID file; duplicate-instance protection is disabled.')

    print(f'\nOpening {port} at {args.baud} baud...')
    
    # Connection retry logic
    max_retries = 3
    retry_delay = 2
    ser = None
    
    busy_kill_attempted = False
    for attempt in range(max_retries):
        try:
            ser = open_serial(port, args.baud)
            print(f'Connected successfully!')
            break
        except serial.SerialException as e:
            error_text = str(e)
            if not busy_kill_attempted and os.name == 'posix' and re.search(r'(device or resource busy|permission denied|access is denied|could not open port|readiness to read but returned no data)', error_text, re.I):
                pids = find_port_users(port)
                if pids and prompt_kill_port_owners(port, pids):
                    busy_kill_attempted = True
                    continue
            if attempt < max_retries - 1:
                print(f'Connection failed (attempt {attempt + 1}/{max_retries}): {e}')
                print(f'   Retrying in {retry_delay} seconds...')
                time.sleep(retry_delay)
            else:
                print(f'Failed to open serial port after {max_retries} attempts: {e}')
                print('\nTroubleshooting:')
                print('  • Check the device is connected')
                print('  • Verify you have permissions (Linux: dialout group)')
                print('  • Try a different USB port')
                print('  • Check if another program is using the port')
                sys.exit(2)
        except Exception as e:
            print(f'Unexpected error opening port: {e}')
            sys.exit(2)
    
    if ser is None:
        print('Could not establish connection')
        sys.exit(2)

    # Ensure CSV header exists (add detailed columns)
    global _global_serial_port, _global_csv_file
    _global_serial_port = ser
    
    csv_exists = os.path.exists(args.csv)
    csvfile = open(args.csv, 'a', newline='')
    _global_csv_file = csvfile
    # writer = csv.writer(csvfile)
    # if not csv_exists:
    #     writer.writerow(['timestamp', 'iso', 'raw_hex', 'device_id', 'count', 'delay_s', 'temp_c', 'hit'])
    #     csvfile.flush()

    # Create directories for .dat and .json files if they don't exist
    # os.makedirs(args.dat_dir, exist_ok=True)
    # os.makedirs(args.json_dir, exist_ok=True)

    print('Reading (byte-level). press Ctrl-C to stop.')
    try:
        # We'll read single bytes in blocking mode and maintain buffers
        buffer = bytearray()
        period_hit_times = []  # hits in current period
        period_events = []  # detailed events in current period
        time_last_save = time.time()  # Initialize to now
        device_info_shown = False  # Track if device info has been shown

        while True:
            try:
                # Blocking read for one byte — minimal latency to detect C1 events
                # Use timeout to allow periodic check of test duration
                ser.timeout = 0.1  # 100ms timeout
                b = ser.read(1)
                if not b:
                    if stop_time and time.time() >= stop_time:
                        print(f"\nTest duration ({args.test_duration}s) complete — stopping.")
                        break
                    continue

                ts = time.time()
                iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() 
                
                # Append to buffer
                buffer.append(b[0])

                # Keep rolling buffer bounded to avoid unbounded memory growth
                # Only keep what's needed for frame detection (12 bytes)
                if len(buffer) > 512:
                    del buffer[0:len(buffer) - 512]

                # Immediate frame detection: check last 12-byte window
                frame = False
                if len(buffer) >= 12:
                    # Look for C1 00 header in the last bytes
                    # Check multiple possible positions in case of misalignment
                    for i in range(max(0, len(buffer) - 24), len(buffer) - 11):
                        if buffer[i] == 0xC1 and buffer[i+1] == 0x00:
                            frame = bytes(buffer[i:i+12])
                            # Verify it's a valid frame
                            if parse_rium_frame(frame):
                                frame = True
                                # Adjust buffer to point to this frame
                                del buffer[0:i]
                                break         

                # If a frame was detected, log it immediately with the 12-byte frame
                if frame:
                    frame = bytes(buffer[-12:])
                    raw_hex = hexdump(frame)
                    
                    # Parse the frame to extract detailed info
                    parsed = parse_rium_frame(frame)
                    
                    if parsed:
                        if not device_info_shown:
                            print(f'Device: {parsed["device"]}')
                            device_info_shown = True
                        print(f'- {iso}  Count: {parsed["count"]}, Temp: {parsed["temp"]:.1f}C')
                        
                        # # Write to CSV with parsed data
                        # writer.writerow([
                        #     ts, iso, raw_hex, 
                        #     parsed['device'], parsed['count'], 
                        #     parsed['delay'], parsed['temp'], 1
                        # ])

                        csvfile.flush()
                        
                        # Store for aggregation
                        period_hit_times.append(ts)
                        period_events.append({
                            'time': iso,
                            'count': parsed['count'],
                            'temp': parsed['temp'],
                            'delay': parsed['delay'],
                            'device': parsed['device']
                        })
                        
                        # Calculate hit rate for current period
                        if len(period_hit_times) > 1:
                            elapsed_seconds = ts - period_hit_times[0]
                            elapsed_hours = elapsed_seconds / 3600  # hours
                            elapsed_h = int(elapsed_seconds // 3600)
                            elapsed_m = int((elapsed_seconds % 3600) // 60)
                            elapsed_str = f"{elapsed_h}h:{elapsed_m:02d}m"
                            # number of hits is the number of count in every period event that is greater than 0
                            number_of_hits = sum(e['count'] for e in period_events)
                            hit_rate = number_of_hits / elapsed_hours if elapsed_hours > 0 else 0
                            print(f'Elapsed time (hh:mm): {elapsed_str} | Total number of hits : {number_of_hits} | Hit rate: {hit_rate:.2f} hits/hour | usv/h : {convert_cps_to_usvh(hit_rate / 3600, args.cps_to_usvh, args.cps_to_usvh_func):.4f}')
                            
                    else:
                        # Frame detected but parsing failed
                        print(f'{iso}  Invalid frame detected  hex={raw_hex}')
                    
                    # Flush buffer 
                    del buffer[0:12]

                # Periodic save to .dat and .json files
                if ts - time_last_save > SAVE_RATE:
                    print(f"\n{'='*60}")
                    print(f"Period summary [{datetime.fromtimestamp(time_last_save, tz=timezone.utc).strftime('%H:%M:%S')} - {datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%H:%M:%S')}]")
                    
                    # Calculate dose rate
                    hits_number = sum(e['count'] for e in period_events)
                    if hits_number > 0:
                        start_time = period_hit_times[0]
                        end_time = period_hit_times[-1]
                        duration = end_time - start_time if end_time > start_time else SAVE_RATE
                        cps = hits_number / duration
                        value = convert_cps_to_usvh(cps, args.cps_to_usvh, args.cps_to_usvh_func)
                        print(f'  Hits: {hits_number} in {duration:.1f}s')
                        print(f'  CPS: {cps:.3f} -> Dose rate: {value:.4f} uSv/h')
                        
                        # Get device info from last event
                        device_id = period_events[-1]['device'] if period_events else 'unknown'
                        avg_temp = sum(e['temp'] for e in period_events) / len(period_events) if period_events else 0
                        print(f'  Device: {device_id}, Avg temp: {avg_temp:.1f}°C')
                        
                        # Save to local CSV (rolling MAX_LOCAL_DOSES measurements)
                        save_local_dose(start_time, value, duration, device_id, avg_temp)
                        print(f'  Saved to local dose history')

                        # Send to OpenRadiation API if enabled
                        # Guard: duration must be at least MIN_DURATION_FOR_API (10 min)
                        if args.send_data and duration < MIN_DURATION_FOR_API:
                            print(f'  ⚠ Skipping API send: measurement duration {duration:.0f}s < {MIN_DURATION_FOR_API}s (10 min minimum)')
                        elif args.send_data:
                            report_uuid = str(uuid.uuid4())
                            data = {
                                "reportUuid": report_uuid,
                                "latitude": float(latitude),
                                "longitude": float(longitude),
                                "value": float(round(value, 4)),
                                "startTime": datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
                                "endTime": datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat(),
                                "hitsNumber": hits_number,
                                "description": f"Rium GM fixed beacon measurement",
                                "calibrationFunction": f"{args.cps_to_usvh_func}"
                            }
                            
                            # Add userId (prefer user_id over username)
                            if user_id:
                                data["userId"] = user_id
                            elif username:
                                data["userId"] = username
                            # Add password if provided
                            if user_pwd:
                                data["userPwd"] = user_pwd
                            # Add tags if provided
                            if all_tags:
                                data["tags"] = all_tags
                            
                            # Try to send current measurement
                            success = post_measurement(api_key, data, args.production)
                            
                            # If successful and there are queued measurements, process them
                            if success:
                                queue = load_queue()
                                if queue:
                                    print(f"\nConnection restored! Processing {len(queue)} queued measurements...")
                                    process_queue()
                    else:
                        print("  No hits detected in this period.")
                    
                    print(f"{'='*60}\n")
                    
                    # Reset for next period
                    period_hit_times = []
                    period_events = []
                    time_last_save = ts

            except KeyboardInterrupt:
                print('\nInterrupted by user')
                break
            except serial.SerialException as e:
                # Dosimeter unplugged or serial error — attempt reconnection
                print(f'\n⚠ Serial error: {e}')
                print('Dosimeter disconnected. Waiting for reconnection...')
                ser = None
                _global_serial_port = None
                reconnected = False
                for _attempt in range(60):  # try for up to 10 minutes (60 × 10s)
                    time.sleep(10)
                    try:
                        candidates = find_candidate_ports()
                        if candidates:
                            _port = port  # keep last known port
                            if _port not in candidates:
                                _port = candidates[0]
                            ser = open_serial(_port, args.baud)
                            _global_serial_port = ser
                            buffer = bytearray()  # reset frame buffer
                            print(f'✅ Reconnected on {_port}')
                            reconnected = True
                            break
                    except Exception:
                        pass
                    print(f'  Still waiting... ({(_attempt + 1) * 10}s elapsed)')
                if not reconnected:
                    print('❌ Could not reconnect after 10 minutes. Stopping.')
                    break
            except Exception as e:
                print('Read loop error:', e)
                continue
            
            if stop_time and time.time() >= stop_time:
                print(f"\nTest duration ({args.test_duration}s) complete — stopping.")
                break
    finally:
        print("\n" + "="*60)
        print("  SHUTDOWN SEQUENCE")
        print("="*60)
        
        # Close serial port with aggressive file descriptor cleanup
        try:
            if 'ser' in locals() and ser:
                try:
                    ser.flush()
                except Exception:
                    pass
                try:
                    ser.close()
                except Exception:
                    pass
                # Explicitly close the underlying file descriptor
                try:
                    fd = ser.fd
                    if fd and fd >= 0:
                        os.close(fd)
                except Exception:
                    pass
                print("  ✓ Serial port closed and flushed")
        except Exception as e:
            print(f"  ✗ Error closing serial port: {e}")
        
        # Close CSV file
        try:
            if 'csvfile' in locals() and csvfile:
                csvfile.flush()
                csvfile.close()
                print("  ✓ CSV file closed and flushed")
        except Exception as e:
            print(f"  ✗ Error closing CSV file: {e}")
        
        # Remove PID file
        try:
            remove_pid_file()
            print("  ✓ PID file cleaned up")
        except Exception as e:
            print(f"  ✗ Error removing PID file: {e}")
        
        print("="*60)
        print("  SHUTDOWN COMPLETE")
        print("="*60 + "\n")
        
        # Immediately terminate - no lingering processes

        
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted by user')
        try:
            remove_pid_file()
        except Exception:
            pass
        sys.exit(0)