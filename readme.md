# Rium GM Dosimeter Reader

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)]()

**ASNR (formerly IRSN) Project** - Modernization of Rium GM probes for creating fixed radioactivity measurement stations.

---

## 🚀 Quick Start (3 Steps!)

### Step 1: Download & Connect
1. Download/clone this repository
2. Plug your Rium GM dosimeter into a USB port

### Step 2: Launch
- **Windows**: Double-click `START_WINDOWS.bat`
- **Linux/Mac/Raspberry Pi**: Run `./start.sh`
- **Or**: `python3 launcher.py`

### Step 3: Follow the menu
The launcher will guide you through:
1. Configuration (first time only)
2. Connection test
3. Start monitoring

**That's it!** The system automatically:
- Installs dependencies (if needed)
- Detects your dosimeter
- Records radiation events
- Saves data locally (CSV)
- Uploads to OpenRadiation (optional)

---

## Description

This Python script reads data from a Rium GM dosimeter via USB serial and automatically sends it to the OpenRadiation API. Designed to run on Raspberry Pi or Arduino to create fixed measurement stations.

## Features

- ✅ Real-time reading of impacts detected by the Geiger-Müller tube
- ✅ Automatic dose rate calculation (µSv/h)
- ✅ Local CSV logging with timestamps
- ✅ **Automatic queue system for failed uploads** (new!)
- ✅ Automatic submission to OpenRadiation (optional)
- ✅ Persistent configuration via `config.ini` file
- ✅ Network resilience with automatic retry
- ✅ Compatible with Raspberry Pi / Arduino / Linux / Windows

## Installation

### Prerequisites

```bash
pip install pyserial requests
```

Or use the requirements file:
```bash
pip install -r requirements.txt
```

**Note**: The script will offer to auto-install dependencies if missing.

### Configuration

**Option 1: Quick Launcher (Recommended for beginners)**
```bash
python launcher.py
```
Select option 1 to run the configuration wizard.

**Option 2: Manual setup**

1. **Run the configuration wizard**:
```bash
python setup_config.py
```

2. **Or edit `config.ini` manually**:

```ini
[DEFAULT]
# OpenRadiation API key (obtain from https://www.openradiation.org/)
api_key = YOUR_API_KEY

# Fixed station GPS coordinates
latitude = 48.8566
longitude = 2.3522

# Optional: User ID
user_id = your_user_id

# Optional: Tags to identify the station
tags = station=Home, device=RiumGM_001
```

2. **Connect the Rium GM dosimeter** via USB

## Usage

### Quick Start (Easy Mode)

```bash
python launcher.py
```

This interactive menu guides you through:
- First-time configuration
- Connection testing
- Starting monitoring (with or without data upload)
- Switching between test and production modes

### Manual Mode

#### Test mode (without data submission)

```bash
python read_dosimeter.py
```

### Production mode (sending to OpenRadiation)

```bash
# Test mode (data marked as "test")
python read_dosimeter.py --send-data

# Production mode (real data)
python read_dosimeter.py --send-data --production
```

### Advanced options

```bash
# Specify serial port manually
python read_dosimeter.py --port COM3  # Windows
python read_dosimeter.py --port /dev/ttyUSB0  # Linux/Raspberry Pi

# List available serial ports
python read_dosimeter.py --list

# Use a different configuration file
python read_dosimeter.py --config /path/to/other_config.ini

# Override config.ini parameters
python read_dosimeter.py --send-data --latitude 45.0 --longitude 5.0 --api-key OTHER_KEY
```

## Raspberry Pi Deployment (Fixed Station)

### Prerequisites

Ensure your Raspberry Pi has:
- Internet connection (WiFi or Ethernet)
- Python 3.7+ (pre-installed on Raspberry Pi OS)
- Git (install if needed):

```bash
# Check if git is installed
git --version

# If not installed, install it:
sudo apt update
sudo apt install git -y
```

### Quick Method

```bash
# 1. Clone repository
git clone https://github.com/Ant1data/OR_RiumGM_fixedbeacon.git
cd OR_RiumGM_fixedbeacon

# 2. Install Python dependencies
pip3 install -r requirements.txt

# 3. Run launcher for initial setup
python3 launcher.py
# Select option 1 to configure, then option 4 to test

# 4. Once tested, set up auto-start
sudo cp rium-dosimeter.service /etc/systemd/system/
sudo nano /etc/systemd/system/rium-dosimeter.service  # Edit paths if needed
sudo systemctl daemon-reload
sudo systemctl enable rium-dosimeter.service
sudo systemctl start rium-dosimeter.service
```

### System Service Details

The included `rium-dosimeter.service` file provides:
- Automatic startup on boot
- Auto-restart on failure
- Logging via systemd journal

Check status and logs:
```bash
# Service status
sudo systemctl status rium-dosimeter.service

# View logs (live)
journalctl -u rium-dosimeter.service -f

# View recent logs
journalctl -u rium-dosimeter.service -n 100
```

### Manual Deployment Steps

If you prefer manual setup:

1. **Install Python dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

2. **Configure the station**
   ```bash
   python3 launcher.py  # Choose option 1
   ```

3. **Test the connection**
   ```bash
   python3 launcher.py  # Choose option 2
   ```

4. **Test monitoring (local only)**
   ```bash
   python3 read_dosimeter.py
   ```

5. **Test with data upload (test mode)**
   ```bash
   python3 read_dosimeter.py --send-data
   ```

6. **Enable for production**
   ```bash
   # Edit service file
   sudo nano /etc/systemd/system/rium-dosimeter.service
   
   # Enable and start
   sudo systemctl enable rium-dosimeter.service
   sudo systemctl start rium-dosimeter.service
   ```

```bash
journalctl -u rium-dosimeter.service -f
```

## Data Format

### Local CSV file

The `dosimeter_log.csv` file contains:
- `timestamp`: Unix timestamp
- `iso`: ISO 8601 date/time
- `raw_hex`: Raw data (hex)
- `device_id`: Device ID
- `count`: Counter
- `delay_s`: Delay in seconds
- `temp_c`: Temperature in °C
- `hit`: 1 if hit detected, 0 otherwise

### Data sent to OpenRadiation

Every 60 seconds (configurable via `SAVE_RATE`), the script sends:
- GPS coordinates
- Calculated dose rate (µSv/h)
- Number of hits
- Measurement period
- Tags and metadata

## Calibration

The default conversion factor is **1/2.6 CPS/µSv/h** (Rium GM tube sensitivity).

To adjust:

```bash
python read_dosimeter.py --cps-to-usvh 0.4  # Example custom factor
```

## Troubleshooting

### Serial port not detected

```bash
# List available ports
python read_dosimeter.py --list

# On Linux, check permissions
sudo usermod -a -G dialout $USER
# Then log out/log in
```

### Configuration error

The script will automatically create a `config.ini` template if missing.

### No data received

Verify that the dosimeter is powered on and configured to send via USB serial.

### Queued measurements

If you see "X pending measurements" at startup, it means previous uploads failed (e.g., due to network issues). The system will automatically retry when the connection is restored. See [QUEUE_SYSTEM.md](QUEUE_SYSTEM.md) for details.

## Advanced Features

### Automatic Queue System

Failed measurements are automatically queued and retried when connection is restored:
- **Maximum queue size**: 100 measurements
- **Auto-cleanup**: Measurements older than 7 days are removed
- **Zero manual intervention**: Fully automatic

See [QUEUE_SYSTEM.md](QUEUE_SYSTEM.md) for complete documentation.

### Network Resilience

The system handles network failures gracefully:
- **3 automatic retries** with exponential backoff
- **Local CSV backup** always preserved
- **Queue system** for extended outages
- **Continues monitoring** even without internet

See [ROBUSTNESS.md](ROBUSTNESS.md) for reliability details.

## Contributors

- E. Martinet-Gerphagnon, PhD Student, ASNR x Institut Marie Curie
- A. Dreux, Data Engineer in Dosimetry, ASNR

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

See [LICENSE](LICENSE) file

## Acknowledgments

- ASNR (formerly IRSN) for project support
- OpenRadiation network for API access
- Rium Manufacturing for dosimeter specifications

## Links

- [OpenRadiation](https://www.openradiation.org/)
- [ASNR](https://www.asnr.fr/)
- [Rium Manufacturing](https://www.riummanufacturing.com/)

