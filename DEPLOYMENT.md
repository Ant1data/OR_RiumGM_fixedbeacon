# Quick Deployment Guide

## Quick Start (Easiest Method)

### 1. Initial Setup

```bash
# Clone repository
git clone https://github.com/Ant1data/Xx_Custom_Rium_GM_xX.git
cd Xx_Custom_Rium_GM_xX

# Run the launcher (handles dependencies and configuration)
python3 launcher.py
```

The launcher provides an interactive menu that handles:
- ✅ Dependency installation
- ✅ Configuration wizard
- ✅ Connection testing
- ✅ Starting the monitoring

## For Fixed Station (Raspberry Pi)

### 1. System Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python dependencies
pip3 install -r requirements.txt

# Clone repository
git clone https://github.com/Ant1data/Xx_Custom_Rium_GM_xX.git
cd Xx_Custom_Rium_GM_xX
```

### 2. Configure

```bash
# Run configuration wizard
python3 setup_config.py

# Or manually edit config.ini
nano config.ini
```

### 3. Test

```bash
# Test serial connection
python3 read_dosimeter.py --list

# Test acquisition (no upload)
python3 read_dosimeter.py

# Test with data upload (test mode)
python3 read_dosimeter.py --send-data
```

### 4. Deploy as Service

```bash
# Copy service file
sudo cp rium-dosimeter.service /etc/systemd/system/

# Edit paths if needed
sudo nano /etc/systemd/system/rium-dosimeter.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable rium-dosimeter.service
sudo systemctl start rium-dosimeter.service

# Check status
sudo systemctl status rium-dosimeter.service
```

### 5. Monitor

```bash
# View logs
journalctl -u rium-dosimeter.service -f

# Check data file
tail -f dosimeter_log.csv
```

## For Development/Testing

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
python setup_config.py

# Run interactively
python read_dosimeter.py --send-data
```

## Troubleshooting

### Permission denied on serial port

```bash
sudo usermod -a -G dialout $USER
# Then logout/login
```

### Service won't start

```bash
# Check logs
journalctl -u rium-dosimeter.service -n 50

# Check configuration
python3 read_dosimeter.py --list
```

### Data not uploading

1. Check internet connection
2. Verify API key in config.ini
3. Test in interactive mode first
4. Check OpenRadiation API status

## Production Checklist

- [ ] Config.ini filled with valid credentials
- [ ] GPS coordinates accurate (6+ decimals)
- [ ] Serial port accessible
- [ ] Tested in `--send-data` mode
- [ ] Service starts on boot
- [ ] Logs monitored for 24h
- [ ] Data visible on OpenRadiation
