#!/bin/bash
# Installation script for Rium GM Dosimeter dependencies
# For Raspberry Pi / Linux systems
# ASNR (formerly IRSN) Project

echo "======================================================================"
echo "  Rium GM Dosimeter - Dependency Installation"
echo "  ASNR (formerly IRSN) Project"
echo "======================================================================"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "⚠️  This script is designed for Linux systems (Raspberry Pi)"
    echo "   For Windows, use: pip install -r requirements.txt"
    exit 1
fi

# Check Python version
echo "→ Checking Python installation..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    echo "   Install it with: sudo apt install python3 python3-pip"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python $PYTHON_VERSION found"
echo ""

# Check pip
echo "→ Checking pip installation..."
if ! command -v pip3 &> /dev/null; then
    echo "⚠️  pip3 is not installed. Installing..."
    sudo apt update
    sudo apt install -y python3-pip
fi

PIP_VERSION=$(pip3 --version 2>&1 | awk '{print $2}')
echo "✅ pip $PIP_VERSION found"
echo ""

# Install Python dependencies
echo "→ Installing Python packages..."
echo "----------------------------------------------------------------------"
pip3 install -r requirements.txt

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Python packages installed successfully!"
else
    echo ""
    echo "❌ Failed to install packages"
    echo "   Try with: sudo pip3 install -r requirements.txt"
    exit 1
fi

echo ""
echo "----------------------------------------------------------------------"
echo "  CHECKING SERIAL PORT PERMISSIONS"
echo "----------------------------------------------------------------------"

# Check dialout group membership
USERNAME=$(whoami)
if groups $USERNAME | grep -q "\bdialout\b"; then
    echo "✅ User '$USERNAME' is in dialout group (serial port access OK)"
else
    echo "⚠️  User '$USERNAME' is NOT in dialout group"
    echo ""
    echo "   This is required to access USB serial devices."
    echo ""
    read -p "   Add user to dialout group? (y/n) [y]: " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
        sudo usermod -a -G dialout $USERNAME
        if [ $? -eq 0 ]; then
            echo ""
            echo "✅ User '$USERNAME' added to dialout group!"
            echo ""
            echo "⚠️  IMPORTANT: You must LOG OUT and LOG BACK IN"
            echo "   for this change to take effect."
            echo ""
        else
            echo "❌ Failed to add user to group"
            exit 1
        fi
    else
        echo "   Skipped. You can add manually with:"
        echo "   sudo usermod -a -G dialout $USERNAME"
    fi
fi

echo ""
echo "======================================================================"
echo "  Installation Complete!"
echo "======================================================================"
echo ""
echo "Next steps:"
echo "  1. If prompted, LOG OUT and LOG BACK IN"
echo "  2. Run the launcher: python3 launcher.py"
echo "  3. Configure your station (option 1)"
echo "  4. Start monitoring!"
echo ""
echo "For systemd service setup:"
echo "  sudo cp rium-dosimeter.service /etc/systemd/system/"
echo "  sudo systemctl enable rium-dosimeter.service"
echo "  sudo systemctl start rium-dosimeter.service"
echo ""
