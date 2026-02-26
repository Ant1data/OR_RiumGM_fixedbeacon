#!/usr/bin/env python3
"""
Simple serial reader for a Rium GM dosimeter (generic USB serial logger).

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
import csv
import glob
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime


SAVE_RATE = 60 # [s]

try:
    import serial
except Exception:
    print("Missing dependency: pyserial. Install with 'pip3 install pyserial' or see README.")
    raise

try:
    import requests
except Exception:
    print("Missing dependency: requests. Install with 'pip3 install requests' or see README.")
    raise


def find_candidate_ports():
    """Return a list of likely serial ports (posix and fallback for Windows)."""
    ports = []
    if os.name == 'posix':
        ports.extend(sorted(glob.glob('/dev/ttyUSB*')))
        ports.extend(sorted(glob.glob('/dev/ttyACM*')))
        ports.extend(sorted(glob.glob('/dev/serial/by-id/*')))
    else:
        # Windows fallback
        ports.extend([f'COM{i}' for i in range(1, 21)])
    return ports


def open_serial(port, baud, timeout=None):
    # Use blocking reads by default (timeout=None) so we can read single bytes
    # with minimal latency. This gives high time-sensitivity for detecting hits.
    return serial.Serial(port=port, baudrate=baud, timeout=timeout)


def hexdump(b: bytes) -> str:
    return ' '.join(f'{x:02x}' for x in b)


def post_measurement(api_key, data, production=False):
    """Post measurement data to OpenRadiation API."""
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
    }
    
    # Show sent data for debugging
    print("Prepared measurement data for API:")
    print(json.dumps(payload, indent=2))
    print(f"API endpoint: {url}")
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 201:
            print("Measurement posted successfully.")
        else:
            print(f"Failed to post measurement: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Error posting measurement: {e}")



def main():
    parser = argparse.ArgumentParser(description='Read Rium GM dosimeter via USB serial and log data.')
    parser.add_argument('--port', '-p', help='Serial port (e.g. /dev/ttyUSB0). If omitted, tries to auto-detect.')
    parser.add_argument('--baud', '-b', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('--csv', default='dosimeter_log.csv', help='CSV file to append logs to')
    parser.add_argument('--hex', action='store_true', help='Print hex dump of incoming bytes instead of trying to parse text')
    parser.add_argument('--raw', action='store_true', help='Write raw bytes (base64) into CSV raw_data column')
    parser.add_argument('--list', action='store_true', help='List candidate ports and exit')
    parser.add_argument('--send-data', action='store_true', help='Enable sending data to OpenRadiation API (default: disabled for safety)')
    parser.add_argument('--api-key', default='bde8ebc61cb089b8cc997dd7a0d0a434', help='API key for OpenRadiation (default: test key)')
    parser.add_argument('--latitude', type=float, required='--send-data' in sys.argv, help='Latitude for measurements (required if sending data)')
    parser.add_argument('--longitude', type=float, required='--send-data' in sys.argv, help='Longitude for measurements (required if sending data)')
    # Sensitivity of Rium GM : Sensitivity 2.6 cps/µSv/h according to https://www.riummanufacturing.com/products/gm-tubes/ and user reports. This means 1 CPS corresponds to approximately 0.385 µSv/h, so the conversion factor is 1/2.6.
    parser.add_argument('--cps-to-usvh', type=float, default=1/2.6, help='Conversion factor from CPS to µSv/h (default: 1/2.6)')
    parser.add_argument('--production', action='store_true', help='Set reportContext to routine (real data) instead of test. Use with caution!')
    parser.add_argument('--tag', action='append', default=[], help='Add tags to measurements (can be used multiple times, e.g. --tag location=Paris --tag device=GM1)')
    parser.add_argument('--user-id', help='User ID to associate with measurements')
    
    args = parser.parse_args()

    candidates = find_candidate_ports()
    if args.list:
        print('Candidate ports:')
        for p in candidates:
            print('  ', p)
        return

    port = args.port
    if not port:
        if not candidates:
            print('No candidate serial ports found. Provide --port manually.')
            sys.exit(1)
        port = candidates[0]
        print(f'No --port given, using first candidate: {port}')

    print(f'Opening {port} at {args.baud} baud...')
    try:
        ser = open_serial(port, args.baud)
    except Exception as e:
        print('Failed to open serial port:', e)
        sys.exit(2)

    # Ensure CSV header exists (add `hit` column)
    csv_exists = os.path.exists(args.csv)
    csvfile = open(args.csv, 'a', newline='')
    writer = csv.writer(csvfile)
    if not csv_exists:
        writer.writerow(['timestamp', 'iso', 'raw_hex', 'hit'])
        csvfile.flush()

    if args.send_data and (args.latitude is None or args.longitude is None):
        print("Error: --latitude and --longitude are required when --send-data is enabled.")
        sys.exit(1)

    print('Reading (byte-level). press Ctrl-C to stop.')
    try:
        # We'll read single bytes in blocking mode and maintain two buffers:
        # - `buffer`: rolling buffer used to detect the Hit pattern across read boundaries
        buffer = bytearray()
        hit_times = []
        period_hit_times = []  # hits in current period
        time_last_save = time.time()  # Initialize to now
        while True:
            try:
                # Blocking read for one byte — minimal latency to detect C1 events
                b = ser.read(1)
                if not b:
                    # shouldn't happen with blocking read, but guard anyway
                    continue

                ts = time.time()
                
                iso = datetime.utcfromtimestamp(ts).isoformat() 
                
                # Append to buffers
                buffer.append(b[0])
                #line_buf.append(b[0])

                # Keep rolling buffer bounded to avoid unbounded memory growth
                if len(buffer) > 4096:
                    del buffer[0:len(buffer) - 4096]

                # Immediate Hit detection: check last 12-byte window
                hit = False
                if len(buffer) >= 12:
                    # Check if first bytes is C1
                    if buffer[-12] == 0xC1:
                        hit = True         

                # If a Hit was detected, log it immediately with the 12-byte frame
                if hit:
                    frame = bytes(buffer[-12:])
                    raw_hex = hexdump(frame)
                    print(f'{iso}  HIT detected  hex={raw_hex}')
                    writer.writerow([ts, iso, raw_hex, 1])
                    hit_times.append(ts) # Append to hit times for hit rates
                    period_hit_times.append(ts)
                    
                    #calculate hit rate per hour
                    if len(hit_times) > 1:
                        elapsed_hours = (ts - hit_times[0]) / 3600  # hours
                        hit_rate = len(hit_times) / elapsed_hours if elapsed_hours > 0 else 0
                        print(f'  Hit rate: {hit_rate:.2f} hits/hour')
                    # Flush buffer up 
                    del buffer[0:12]

                if ts - time_last_save  > SAVE_RATE:
                    print("Saving data...")
                    # Calculate dose rate
                    hits_number = len(period_hit_times)
                    if hits_number > 0:
                        start_time = period_hit_times[0]
                        end_time = period_hit_times[-1]
                        duration = end_time - start_time if end_time > start_time else SAVE_RATE
                        cps = hits_number / duration
                        value = cps * args.cps_to_usvh
                        print(f'  Period: {hits_number} hits in {duration:.1f}s, CPS: {cps:.2f}, Value: {value:.4f} µSv/h')
                        
                        if args.send_data:
                            report_uuid = str(uuid.uuid4())
                            data = {
                                "reportUuid": f"{report_uuid}",
                                "latitude": float(args.latitude),
                                "longitude": float(args.longitude),
                                "value": float(round(value, 4)),
                                "startTime": f"{datetime.utcfromtimestamp(start_time).isoformat()}",
                                #"endTime": f"{datetime.utcfromtimestamp(end_time).isoformat()}Z",
                                #"hitsNumber": int(hits_number),
                                #"apparatusSensorType": "geiger",
                                #"manualReporting": False
                            }
                            
                            # Add user ID if provided
                            if args.user_id:
                                data["userId"] = args.user_id
                                # Add tags if provided
                            if args.tag:
                                data["tags"] = args.tag
                            post_measurement(args.api_key, data, args.production)
                    else:
                        print("  No hits in period.")
                    
                    period_hit_times = []  # Reset for next period
                    time_last_save = ts


            except serial.SerialException as se:
                print('Serial error:', se)
                break
            except KeyboardInterrupt:
                print('\nInterrupted by user')
                break
            except Exception as e:
                print('Read loop error:', e)
                # continue reading; don't sleep long to preserve responsiveness
                continue
    finally:
        try:
            ser.close()
        except Exception:
            pass
        csvfile.close()


if __name__ == '__main__':
    main()
