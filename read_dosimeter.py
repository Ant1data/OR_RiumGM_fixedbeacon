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
import configparser
import csv
import glob
import json
import os
import re
import signal
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


SAVE_RATE = 60  # [s] - Period for aggregating and sending measurements
MAX_QUEUE_SIZE = 100  # Maximum number of failed measurements to keep in queue
MAX_QUEUE_AGE_DAYS = 7  # Maximum age of queued measurements in days

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global shutdown_requested
    print(f"\n{'='*60}")
    print(f"  Shutdown signal received (signal {signum})")
    print(f"{'='*60}")
    shutdown_requested = True


def get_pid_file():
    """Get the path to the PID file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, 'dosimeter.pid')


def create_pid_file():
    """Create a PID file to prevent multiple instances."""
    pid_file = get_pid_file()
    
    # Check if already running
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r') as f:
                old_pid = int(f.read().strip())
            
            # Check if process is actually running
            try:
                os.kill(old_pid, 0)  # Signal 0 just checks if process exists
                print(f"⚠️  Another instance is already running (PID: {old_pid})")
                print(f"   To stop it, run: kill {old_pid}")
                return False
            except OSError:
                # Process doesn't exist, remove stale PID file
                print(f"→ Removing stale PID file (PID {old_pid} not running)")
                os.remove(pid_file)
        except (ValueError, IOError):
            # Corrupted PID file, remove it
            os.remove(pid_file)
    
    # Create new PID file
    try:
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except IOError as e:
        print(f"⚠️  Warning: Could not create PID file: {e}")
        return True  # Continue anyway


def remove_pid_file():
    """Remove the PID file on clean exit."""
    pid_file = get_pid_file()
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except IOError:
        pass

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
    
    if missing:
        print("="*60)
        print("⚠️  Missing required dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("="*60)
        print("\nYou can install them with:")
        print(f"  pip3 install {' '.join(missing)}")
        print("\nOr install all requirements:")
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
                        print("✅ Dependencies installed successfully!")
                        print("Please run the script again.")
                        sys.exit(0)
                    else:
                        print(f"❌ Installation failed: {result.stderr}")
                        sys.exit(1)
            except KeyboardInterrupt:
                print("\nInstallation cancelled.")
                sys.exit(1)
        
        sys.exit(1)

check_dependencies()

import serial
import requests


def find_candidate_ports():
    """Return a list of likely serial ports (posix and fallback for Windows)."""
    ports = []
    if os.name == 'posix':
        ports.extend(sorted(glob.glob('/dev/ttyUSB*')))
        ports.extend(sorted(glob.glob('/dev/ttyACM*')))
        ports.extend(sorted(glob.glob('/dev/serial/by-id/*')))
    else:
        # Windows: check which COM ports actually exist
        import serial.tools.list_ports
        available = [port.device for port in serial.tools.list_ports.comports()]
        ports.extend(sorted(available))
    return ports


def validate_dosimeter_connection(port, baud, timeout=5):
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
                                print("✅ Rium GM detected!")
                                return True
        
        ser.close()
        print("❌ No valid Rium frames detected")
        return False
        
    except serial.SerialException as e:
        print(f"❌ Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
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
        print("⚠️  Configuration file not found!")
        print("="*60)
        print(f"Expected location: {config_path}")
        print("\nCreating a template config.ini file...")
        
        config['DEFAULT'] = {
            'api_key': '',
            'latitude': '',
            'longitude': '',
            'user_id': '',
            'tags': ''
        }
        
        with open(config_path, 'w') as f:
            f.write("# OpenRadiation API Configuration\n")
            f.write("# ASNR (formerly IRSN) Project\n\n")
            f.write("[DEFAULT]\n")
            f.write("# Get your API key from: https://www.openradiation.org/\n")
            f.write("api_key = \n\n")
            f.write("# Fixed station GPS coordinates (decimal degrees)\n")
            f.write("# Example: 48.8566 for Paris\n")
            f.write("latitude = \n")
            f.write("longitude = \n\n")
            f.write("# Optional: User ID\n")
            f.write("user_id = \n\n")
            f.write("# Optional: Tags (comma-separated)\n")
            f.write("# Example: station=Home, device=RiumGM_001\n")
            f.write("tags = \n")
        
        print(f"✅ Template created: {config_path}")
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


def open_serial(port, baud, timeout=None):
    # Use blocking reads by default (timeout=None) so we can read single bytes
    # with minimal latency. This gives high time-sensitivity for detecting hits.
    return serial.Serial(port=port, baudrate=baud, timeout=timeout)


def hexdump(b: bytes) -> str:
    return ' '.join(f'{x:02x}' for x in b)


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
    print(f"  → Added to queue ({len(queue)} pending measurements)")


def process_queue():
    """Try to send all queued measurements."""
    queue = load_queue()
    if not queue:
        return
    
    print(f"\n→ Processing queue: {len(queue)} pending measurements...")
    
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
            print("✓")
        else:
            failed.append(item)
            print("✗")
            # Don't spam if multiple failures
            if len(failed) >= 3:
                print(f"  (Stopping after 3 consecutive failures)")
                # Keep the rest in queue
                failed.extend(queue[idx + 1:])
                break
    
    # Update queue with only the failed ones
    save_queue(failed)
    
    if successful:
        print(f"✓ Successfully sent {len(successful)} queued measurements")
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


def post_measurement(api_key, data, production=False, max_retries=3):
    """
    Post measurement data to OpenRadiation API with retry logic.
    Returns True if successful, False otherwise.
    """
    url = "https://submit.openradiation.net/measurements"
    payload = {
        "apiKey": api_key,
        "data": data 
    }
    if not production:
        payload["data"]["reportContext"] = "test"
    else:
        payload["data"]["reportContext"] = "routine"
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    # Show sent data for debugging
    print("Prepared measurement data for API:")
    print(json.dumps(payload, indent=2))
    print(f"API endpoint: {url}")
    
    # Retry loop with exponential backoff
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 201:
                print("✓ Measurement posted successfully.")
                return True
            else:
                print(f"✗ Failed to post measurement: {response.status_code}")
                print(f"  Response: {response.text}")
                
                # If it's a client error (4xx), don't retry
                if 400 <= response.status_code < 500:
                    print("  → Client error, not retrying.")
                    return False
                    
                # Server error (5xx), retry
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    print(f"  → Retrying in {wait_time}s... (attempt {attempt + 2}/{max_retries})")
                    time.sleep(wait_time)
                    
        except requests.exceptions.Timeout:
            print(f"✗ Error: Request timeout after 30s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"  → Retrying in {wait_time}s...")
                time.sleep(wait_time)
                
        except requests.exceptions.ConnectionError as e:
            print(f"✗ Error: No internet connection (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s
                print(f"  → Will retry in {wait_time}s...")
                print(f"  → (Measurements continue to be logged locally)")
                time.sleep(wait_time)
                
        except Exception as e:
            print(f"✗ Error posting measurement: {e} (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"  → Retrying in {wait_time}s...")
                time.sleep(wait_time)
    
    # All retries failed
    print("✗ Failed to post measurement after all retries.")
    print("  → Data has been saved locally in CSV file.")
    
    # Add to queue for later retry (only if max_retries > 1, to avoid queuing during queue processing)
    if max_retries > 1:
        add_to_queue(api_key, data, production)
        print("  → Will retry automatically when connection is restored.")
    
    return False



def main():
    global shutdown_requested
    
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
    parser.add_argument('--production', action='store_true', help='Set reportContext to routine (real data) instead of test. Use with caution!')
    parser.add_argument('--tag', action='append', default=[], help='Add tags to measurements (can be used multiple times, e.g. --tag location=Paris --tag device=GM1)')
    
    args = parser.parse_args()

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # systemctl stop
    
    # Create PID file to prevent multiple instances
    if not create_pid_file():
        sys.exit(1)

    # Welcome banner
    print("\n" + "="*60)
    print("  RIUM GM DOSIMETER READER")
    print("  ASNR (formerly IRSN) Project")
    print("="*60)
    print()

    # Load configuration from file
    config = load_config(args.config)
    if config is None and args.send_data:
        print("Error: Cannot send data without valid configuration.")
        sys.exit(1)

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
    
    # Parse tags from config file (comma-separated) and merge with CLI tags
    # Force "fixed_beacon_" prefix on all tags
    config_tags = []
    if config and config.get('tags'):
        config_tags = [tag.strip() for tag in config.get('tags').split(',') if tag.strip()]
    
    # Combine and ensure fixed_beacon_ prefix
    all_tags = []
    for tag in (config_tags + args.tag):
        tag = tag.strip()
        if tag:
            # Add fixed_beacon_ prefix if not already present
            if not tag.startswith('fixed_beacon_'):
                tag = f'fixed_beacon_{tag}'
            all_tags.append(tag)

    # Display configuration status
    print("="*60)
    print("RIUM GM DOSIMETER READER - Configuration")
    print("="*60)
    if config:
        print(f"Configuration file: {args.config}")
        print(f"  API Key: {'*' * 8 + api_key[-4:] if api_key and len(api_key) > 4 else 'NOT SET'}")
        print(f"  Location: {latitude}, {longitude}" if latitude and longitude else "  Location: NOT SET")
        print(f"  User ID: {user_id if user_id else 'NOT SET'}")
        print(f"  Tags: {', '.join(all_tags) if all_tags else 'NONE'}")
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
    if args.list:
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
        return

    port = args.port
    if not port:
        if not candidates:
            print('='*60)
            print('❌ ERROR: No serial ports detected!')
            print('='*60)
            print('Please check:')
            print('  1. Rium GM dosimeter is connected via USB')
            print('  2. USB cable is functional')
            print('  3. Device drivers are installed')
            print('\nOn Linux, you may need permissions:')
            print('  sudo usermod -a -G dialout $USER')
            print('  (then logout/login)')
            print('\nRun with --list to see available ports.')
            print('='*60)
            sys.exit(1)
        
        # Auto-detect: try to validate each candidate
        print("Auto-detecting Rium GM dosimeter...")
        print("="*60)
        port = None
        for candidate in candidates:
            if validate_dosimeter_connection(candidate, args.baud):
                port = candidate
                break
        
        if not port:
            print("="*60)
            print("⚠️  Could not auto-detect Rium GM dosimeter")
            print("="*60)
            print("Detected serial ports:")
            for p in candidates:
                print(f"  - {p}")
            print("\nThe device may be:")
            print("  • Not sending data yet (needs to detect radiation)")
            print("  • Using a different baud rate")
            print("  • Not a Rium GM dosimeter")
            print("\nYou can:")
            print("  1. Specify port manually: --port /dev/ttyUSB0")
            print("  2. Wait for the dosimeter to start sending data")
            print("  3. Check the dosimeter is powered on")
            print("="*60)
            
            # Offer to try first port anyway
            if sys.stdin.isatty():
                try:
                    response = input(f"\nTry using {candidates[0]} anyway? (yes/no) [yes]: ").strip().lower()
                    if response in ['', 'yes', 'y']:
                        port = candidates[0]
                        print(f"Using {port} (not validated)")
                    else:
                        sys.exit(1)
                except KeyboardInterrupt:
                    print("\nCancelled.")
                    sys.exit(1)
            else:
                # Non-interactive: use first port
                port = candidates[0]
                print(f"Non-interactive mode: using first port {port}")
    else:
        print(f'Using specified port: {port}')

    print(f'\nOpening {port} at {args.baud} baud...')
    
    # Connection retry logic
    max_retries = 3
    retry_delay = 2
    ser = None
    
    for attempt in range(max_retries):
        try:
            ser = open_serial(port, args.baud)
            print(f'✅ Connected successfully!')
            break
        except serial.SerialException as e:
            if attempt < max_retries - 1:
                print(f'⚠️  Connection failed (attempt {attempt + 1}/{max_retries}): {e}')
                print(f'   Retrying in {retry_delay} seconds...')
                time.sleep(retry_delay)
            else:
                print(f'❌ Failed to open serial port after {max_retries} attempts: {e}')
                print('\nTroubleshooting:')
                print('  • Check the device is connected')
                print('  • Verify you have permissions (Linux: dialout group)')
                print('  • Try a different USB port')
                print('  • Check if another program is using the port')
                sys.exit(2)
        except Exception as e:
            print(f'❌ Unexpected error opening port: {e}')
            sys.exit(2)
    
    if ser is None:
        print('❌ Could not establish connection')
        sys.exit(2)

    # Ensure CSV header exists (add detailed columns)
    csv_exists = os.path.exists(args.csv)
    csvfile = open(args.csv, 'a', newline='')
    writer = csv.writer(csvfile)
    if not csv_exists:
        writer.writerow(['timestamp', 'iso', 'raw_hex', 'device_id', 'count', 'delay_s', 'temp_c', 'hit'])
        csvfile.flush()

    # Create directories for .dat and .json files if they don't exist
    os.makedirs(args.dat_dir, exist_ok=True)
    os.makedirs(args.json_dir, exist_ok=True)

    print('Reading (byte-level). press Ctrl-C to stop.')
    try:
        # We'll read single bytes in blocking mode and maintain buffers
        buffer = bytearray()
        period_hit_times = []  # hits in current period
        period_events = []  # detailed events in current period
        time_last_save = time.time()  # Initialize to now
        
        while not shutdown_requested:
            try:
                # Blocking read for one byte — minimal latency to detect C1 events
                # Use timeout to allow checking shutdown_requested periodically
                ser.timeout = 0.1  # 100ms timeout
                b = ser.read(1)
                if not b:
                    # No data available, check shutdown flag and continue
                    continue

                ts = time.time()
                iso = datetime.utcfromtimestamp(ts).isoformat() 
                
                # Append to buffer
                buffer.append(b[0])

                # Keep rolling buffer bounded to avoid unbounded memory growth
                # Only keep what's needed for frame detection (12 bytes)
                if len(buffer) > 512:
                    del buffer[0:len(buffer) - 512]

                # Immediate Hit detection: check last 12-byte window
                hit = False
                if len(buffer) >= 12:
                    # Look for C1 00 header in the last bytes
                    # Check multiple possible positions in case of misalignment
                    for i in range(max(0, len(buffer) - 24), len(buffer) - 11):
                        if buffer[i] == 0xC1 and buffer[i+1] == 0x00:
                            frame = bytes(buffer[i:i+12])
                            # Verify it's a valid frame
                            if parse_rium_frame(frame):
                                hit = True
                                # Adjust buffer to point to this frame
                                del buffer[0:i]
                                break         

                # If a Hit was detected, log it immediately with the 12-byte frame
                if hit:
                    frame = bytes(buffer[-12:])
                    raw_hex = hexdump(frame)
                    
                    # Parse the frame to extract detailed info
                    parsed = parse_rium_frame(frame)
                    
                    if parsed:
                        print(f'{iso}  HIT detected  hex={raw_hex}')
                        print(f'  Device: {parsed["device"]}, Count: {parsed["count"]}, Delay: {parsed["delay"]:.1f}s, Temp: {parsed["temp"]:.1f}°C')
                        
                        # Write to CSV with parsed data
                        writer.writerow([
                            ts, iso, raw_hex, 
                            parsed['device'], parsed['count'], 
                            parsed['delay'], parsed['temp'], 1
                        ])
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
                            elapsed_hours = (ts - period_hit_times[0]) / 3600  # hours
                            hit_rate = len(period_hit_times) / elapsed_hours if elapsed_hours > 0 else 0
                            print(f'  Period hit rate: {hit_rate:.2f} hits/hour')
                    else:
                        # Frame detected but parsing failed
                        print(f'{iso}  Invalid frame detected  hex={raw_hex}')
                        writer.writerow([ts, iso, raw_hex, '', 0, 0, 0, 0])
                        csvfile.flush()
                    
                    # Flush buffer 
                    del buffer[0:12]

                # Periodic save to .dat and .json files
                if ts - time_last_save > SAVE_RATE:
                    print(f"\n{'='*60}")
                    print(f"Period summary [{datetime.utcfromtimestamp(time_last_save).strftime('%H:%M:%S')} - {datetime.utcfromtimestamp(ts).strftime('%H:%M:%S')}]")
                    
                    # Calculate dose rate
                    hits_number = len(period_hit_times)
                    if hits_number > 0:
                        start_time = period_hit_times[0]
                        end_time = period_hit_times[-1]
                        duration = end_time - start_time if end_time > start_time else SAVE_RATE
                        cps = hits_number / duration
                        value = cps * args.cps_to_usvh
                        print(f'  Hits: {hits_number} in {duration:.1f}s')
                        print(f'  CPS: {cps:.3f} → Dose rate: {value:.4f} µSv/h')
                        
                        # Get device info from last event
                        device_id = period_events[-1]['device'] if period_events else 'unknown'
                        avg_temp = sum(e['temp'] for e in period_events) / len(period_events) if period_events else 0
                        print(f'  Device: {device_id}, Avg temp: {avg_temp:.1f}°C')

                        # Send to OpenRadiation API if enabled
                        if args.send_data:
                            report_uuid = str(uuid.uuid4())
                            data = {
                                "reportUuid": report_uuid,
                                "latitude": float(latitude),
                                "longitude": float(longitude),
                                "value": float(round(value, 4)),
                                "startTime": datetime.utcfromtimestamp(start_time).isoformat(),
                                "hitsNumber": hits_number,
                                "hitsPeriod": int(duration)
                            }
                            
                            # Add user ID if provided
                            if user_id:
                                data["userId"] = user_id
                            # Add tags if provided
                            if all_tags:
                                data["tags"] = all_tags
                            
                            # Try to send current measurement
                            success = post_measurement(api_key, data, args.production)
                            
                            # If successful and there are queued measurements, process them
                            if success:
                                queue = load_queue()
                                if queue:
                                    print(f"\n→ Connection restored! Processing {len(queue)} queued measurements...")
                                    process_queue()
                    else:
                        print("  No hits detected in this period.")
                    
                    print(f"{'='*60}\n")
                    
                    # Reset for next period
                    period_hit_times = []
                    period_events = []
                    time_last_save = ts


            except serial.SerialException as se:
                print('Serial error:', se)
                break
            except KeyboardInterrupt:
                print('\nInterrupted by user')
                shutdown_requested = True
                break
            except Exception as e:
                print('Read loop error:', e)
                # continue reading; don't sleep long to preserve responsiveness
                continue
        
        # Graceful shutdown
        if shutdown_requested:
            print(f"\n{'='*60}")
            print("  SHUTTING DOWN GRACEFULLY")
            print(f"{'='*60}")
            
            # Save final period if there's data
            if period_hit_times:
                print("\n→ Saving final measurement period...")
                hits_number = len(period_hit_times)
                start_time = period_hit_times[0]
                end_time = period_hit_times[-1]
                duration = end_time - start_time if end_time > start_time else 1
                cps = hits_number / duration
                value = cps * args.cps_to_usvh
                
                print(f"  Final period: {hits_number} hits, {value:.4f} µSv/h")
                
                # Send if enabled
                if args.send_data:
                    report_uuid = str(uuid.uuid4())
                    data = {
                        "reportUuid": report_uuid,
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                        "value": float(round(value, 4)),
                        "startTime": datetime.utcfromtimestamp(start_time).isoformat(),
                        "hitsNumber": hits_number,
                        "hitsPeriod": int(duration)
                    }
                    if user_id:
                        data["userId"] = user_id
                    if all_tags:
                        data["tags"] = all_tags
                    
                    post_measurement(api_key, data, args.production)
            
            print("\n→ Closing serial port...")
            
    finally:
        try:
            ser.close()
            print("  ✓ Serial port closed")
        except Exception:
            pass
        
        try:
            csvfile.close()
            print("  ✓ CSV file closed")
        except Exception:
            pass
        
        # Remove PID file
        remove_pid_file()
        print("  ✓ PID file removed")
        
        print("\n" + "="*60)
        print("  SHUTDOWN COMPLETE")
        print("="*60 + "\n")


if __name__ == '__main__':
    main()
