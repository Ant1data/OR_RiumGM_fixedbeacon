#!/usr/bin/env python3
"""
All-in-one launcher for Rium GM Dosimeter Reader.
Provides a user-friendly menu for all operations including first-time setup.

ASNR Project
"""

import configparser
import glob
import os
import sys
import subprocess
import platform
import importlib.util
import time
import getpass

PASSWORD_FILE = '.dosimeter_credentials'  # kept for legacy reference, not actively used
DEFAULT_SAVE_RATE_MINUTES = 30
MINIMUM_SAVE_RATE_MINUTES = 15

def get_stored_password(username):
    """Retrieve a stored password from encrypted file."""
    try:
        from cryptography.fernet import Fernet
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


def set_stored_password(username, password):
    """Store a password securely in encrypted file."""
    try:
        from cryptography.fernet import Fernet
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


def is_linux():
    """Check if running on Linux/Raspberry Pi."""
    return platform.system() == 'Linux'




def check_module_installed(module_name):
    """Check if a Python module is installed."""
    spec = importlib.util.find_spec(module_name)
    return spec is not None


def check_dependencies():
    """Check and install missing dependencies."""
    print("\n" + "="*70)
    print("  CHECKING DEPENDENCIES")
    print("="*70)
    
    required_modules = {
        'serial': 'pyserial',  # import name : package name
        'requests': 'requests',
        'cryptography.fernet': 'cryptography'
    }
    
    missing = []
    
    for module_name, package_name in required_modules.items():
        if not check_module_installed(module_name):
            missing.append(package_name)
            print(f"  ❌ Missing: {package_name}")
        else:
            print(f"  ✅ Found: {package_name}")
    
    if missing:
        print("\n⚠️  Some dependencies are missing.")
        print("\nOptions:")
        print("  1. Auto-install (recommended)")
        print("  2. Manual installation")
        print("  3. Skip (continue anyway)")
        
        choice = input("\nYour choice (1-3) [1]: ").strip() or '1'
        
        if choice == '1':
            return install_dependencies(missing)
        elif choice == '2':
            print("\nTo install manually, run:")
            if is_linux():
                print("  # Install system packages on Raspberry Pi OS (preferred)")
                print("  sudo apt update && sudo apt install -y python3-pip python3-serial python3-requests python3-cryptography")
                print("Or, if you prefer pip:")
                print(f"  pip3 install {' '.join(missing)}")
                print("Or:")
                print(f"  pip3 install -r requirements.txt")
            else:
                print(f"  pip install {' '.join(missing)}")
                print("Or:")
                print(f"  pip install -r requirements.txt")
            return False
        else:
            print("\n⚠️  Warning: Continuing without dependencies may cause errors.")
            return True
    else:
        print("\n✅ All dependencies are installed!")
        
        # On Linux, check serial port permissions
        if is_linux():
            check_serial_permissions()
        
        return True


def install_dependencies(packages):
    """Install missing Python packages."""
    print("\n→ Installing dependencies...")
    print("-" * 70)
    
    try:
        # Determine apt command
        apt_cmd = 'sudo apt update && sudo apt install -y' if is_linux() else None
        
        # Try to install with apt on Linux first (preferred)
        if apt_cmd:
            print("\nTrying to install with apt (Linux/Raspberry Pi OS)...")
            apt_packages = []
            for pkg in packages:
                if pkg == 'pyserial':
                    apt_packages.append('python3-serial')
                elif pkg == 'requests':
                    apt_packages.append('python3-requests')
                elif pkg == 'cryptography':
                    apt_packages.append('python3-cryptography')
                else:
                    apt_packages.append(pkg)
            
            apt_cmd_full = f"{apt_cmd} {' '.join(apt_packages)}"
            print(f"Running: {apt_cmd_full}\n")
            result = subprocess.run(apt_cmd_full, shell=True, check=False)
            
            if result.returncode == 0:
                print("\n✅ Dependencies installed successfully with apt!")
                return True
            else:
                print("\n⚠️  Apt installation failed, trying pip...")

                cmd = [sys.executable, '-m', 'pip', 'install'] + packages
        
                print(f"Running: {' '.join(cmd)}\n")
                result = subprocess.run(cmd, check=False)
        
                if result.returncode == 0:
                    print("\n✅ Dependencies installed successfully!")
                    return True
                else:
                    print("\n❌ Installation failed.")
                    return False    
    except Exception as e:
        print(f"\n❌ Error during installation: {e}")
        return False


def check_serial_permissions():
    """Check if user has permissions for serial port access (Linux only)."""
    import grp
    import getpass
    
    print("\n" + "-"*70)
    print("  CHECKING SERIAL PORT PERMISSIONS (Linux)")
    print("-"*70)
    
    try:
        # Check if user is in dialout group
        username = getpass.getuser()
        user_groups = [g.gr_name for g in grp.getgrall() if username in g.gr_mem]
        
        # Also check primary group
        import pwd
        user_info = pwd.getpwnam(username)
        primary_gid = user_info.pw_gid
        primary_group = grp.getgrgid(primary_gid).gr_name
        user_groups.append(primary_group)
        
        if 'dialout' in user_groups:
            print(f"  ✅ User '{username}' has serial port access (dialout group)")
        else:
            print(f"  ⚠️  User '{username}' is NOT in 'dialout' group")
            print("\n  This is required to access USB serial devices.")
            print("\n  To fix this, run:")
            print(f"    sudo usermod -a -G dialout {username}")
            print("\n  Then LOG OUT and LOG BACK IN for changes to take effect.")
            print("\n  Note: This is a one-time setup for Raspberry Pi.")
            
            add_to_group = input("\n  Add user to dialout group now? (yes/no) [yes]: ").strip().lower()
            if add_to_group in ['', 'yes', 'y']:
                try:
                    subprocess.run(['sudo', 'usermod', '-a', '-G', 'dialout', username], check=True)
                    print(f"\n  ✅ User '{username}' added to dialout group!")
                    print("  ⚠️  You must LOG OUT and LOG BACK IN for this to take effect.")
                    input("\n  Press Enter after you have logged out/in...")
                except subprocess.CalledProcessError:
                    print("  ❌ Failed to add user to group. Try manually.")
                except Exception as e:
                    print(f"  ❌ Error: {e}")
    
    except ImportError:
        print("  ⚠️  Cannot check permissions (missing modules)")
    except Exception as e:
        print(f"  ⚠️  Error checking permissions: {e}")


def setup_systemd_service():
    """Setup systemd service for auto-start on boot (Linux only)."""
    if not is_linux():
        print("\n⚠️  Systemd service is only available on Linux/Raspberry Pi.")
        return False
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    service_file_src = os.path.join(script_dir, 'rium-dosimeter.service')
    service_file_dst = '/etc/systemd/system/rium-dosimeter.service'
    
    print("\n" + "="*70)
    print("  SETUP SYSTEMD SERVICE")
    print("="*70)
    print()
    print("This will configure the dosimeter to start automatically:")
    print("  • On boot (survives power cuts)")
    print("  • Auto-restart on crash")
    print("  • Runs in background")
    print()
    print("⚠️  IMPORTANT: Make sure you have:")
    print("  1. Configured the station (option 1)")
    print("  2. Tested monitoring successfully (option 2)")
    print("  3. Verified it works in TEST mode (option 3)")
    print()
    
    confirm = input("Do you want to setup the systemd service? (yes/no) [yes]: ").strip().lower()
    
    if confirm not in ['', 'yes', 'y']:
        print("Service setup cancelled.")
        return False
    
    try:
        # Check if service file exists — generate one if missing
        if not os.path.exists(service_file_src):
            print(f"\n\u26a0\ufe0f  Service file not found: {service_file_src}")
            print("\u2192 Generating a default service file...")
            service_content = f"""[Unit]
Description=Rium GM Dosimeter Reader
After=multi-user.target
Wants=multi-user.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/{getpass.getuser()}/OR_RiumGM_fixedbeacon
ExecStart=/usr/bin/python3 /home/{getpass.getuser()}/OR_RiumGM_fixedbeacon/read_dosimeter.py --send-data --production
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            with open(service_file_src, 'w') as f:
                f.write(service_content)
            print(f"\u2705 Service file generated: {service_file_src}")
            print("\u2139\ufe0f  Review and edit it if needed before proceeding.")
            review = input("\nContinue with this service file? (yes/no) [yes]: ").strip().lower()
            if review not in ['', 'yes', 'y']:
                print("Service setup cancelled. Edit the file and try again.")
                return False
        
        print("\n→ Installing service file...")
        # Copy service file
        result = subprocess.run(['sudo', 'cp', service_file_src, service_file_dst], check=True)
        print("✅ Service file copied")
        
        # Reload systemd
        print("\n→ Reloading systemd...")
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
        print("✅ Systemd reloaded")
        
        # Enable service
        print("\n→ Enabling service (auto-start on boot)...")
        subprocess.run(['sudo', 'systemctl', 'enable', 'rium-dosimeter.service'], check=True)
        print("✅ Service enabled")
        
        # Ask if user wants to start now
        start_now = input("\nStart the service now? (yes/no) [yes]: ").strip().lower()
        if start_now in ['', 'yes', 'y']:
            print("\n→ Starting service...")
            subprocess.run(['sudo', 'systemctl', 'start', 'rium-dosimeter.service'], check=True)
            print("✅ Service started")
            
            # Show status
            print("\n→ Service status:")
            subprocess.run(['sudo', 'systemctl', 'status', 'rium-dosimeter.service', '--no-pager'])
        
        print("\n" + "="*70)
        print("✅ Systemd service setup complete!")
        print("="*70)
        print()
        print("Useful commands:")
        print("  • Check status:  sudo systemctl status rium-dosimeter.service")
        print("  • View logs:     journalctl -u rium-dosimeter.service -f")
        print("  • Stop service:  sudo systemctl stop rium-dosimeter.service")
        print("  • Start service: sudo systemctl start rium-dosimeter.service")
        print("  • Disable:       sudo systemctl disable rium-dosimeter.service")
        print()
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error setting up service: {e}")
        print("\nYou can setup manually with:")
        print(f"  sudo cp {service_file_src} {service_file_dst}")
        print("  sudo systemctl daemon-reload")
        print("  sudo systemctl enable rium-dosimeter.service")
        print("  sudo systemctl start rium-dosimeter.service")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False


# ANSI colours (work on Linux/Raspberry Pi terminals)
_GREEN = '\033[32m'
_RED   = '\033[31m'
_RESET = '\033[0m'

SERVICE_NAME = 'rium-dosimeter.service'


def get_service_status():
    """Return (enabled, active) booleans for the systemd service (Linux only)."""
    if not is_linux():
        return None, None
    try:
        enabled_result = subprocess.run(
            ['systemctl', 'is-enabled', SERVICE_NAME],
            capture_output=True, text=True
        )
        active_result = subprocess.run(
            ['systemctl', 'is-active', SERVICE_NAME],
            capture_output=True, text=True
        )
        enabled = enabled_result.stdout.strip() == 'enabled'
        active  = active_result.stdout.strip()  == 'active'
        return enabled, active
    except Exception:
        return None, None


def print_banner():
    print("\n" + "="*70)
    print("  RIUM GM DOSIMETER - Quick Launcher")
    print("  ASNR Project")
    print("="*70)

    if is_linux():
        enabled, active = get_service_status()
        if enabled is None:
            svc_line = "  Service status : unknown"
        else:
            if enabled and active:
                svc_line = f"  Service : {_GREEN}enabled / active{_RESET}"
            elif enabled and not active:
                svc_line = f"  Service : {_RED}enabled / inactive{_RESET}"
            elif not enabled and active:
                svc_line = f"  Service : {_RED}disabled / active{_RESET}"
            else:
                svc_line = f"  Service : {_RED}disabled / inactive{_RESET}"
        print(svc_line)
        print("="*70)
    print()


def get_input(prompt, default=None, required=False):
    """Get user input with optional default value."""
    if default is not None:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "
    
    while True:
        value = input(full_prompt).strip()
        
        if not value and default is not None:
            return default
        
        if not value and required:
            print("  ⚠️  This field is required. Please enter a value.")
            continue
        
        return value


def get_float(prompt, default=None, required=False):
    """Get a float input from user."""
    if default is not None:
        full_prompt = f"{prompt} [{default}]"
    else:
        full_prompt = prompt
    
    while True:
        value = input(f"{full_prompt}: ").strip()
        
        if not value and default is not None:
            return default
        
        if not value and not required:
            return None
        
        try:
            return float(value)
        except ValueError:
            print("  ⚠️  Please enter a valid number.")


def run_configuration_wizard():
    """Interactive configuration wizard."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, 'config.ini')
    
    print("\n" + "="*70)
    print("  CONFIGURATION WIZARD")
    print("="*70)
    print()
    
    # Load existing config if it exists
    existing_config = {}
    if os.path.exists(config_file):
        config = configparser.ConfigParser()
        config.read(config_file)
        existing_config = {
            'api_key': config.get('DEFAULT', 'api_key', fallback=''),
            'username': config.get('DEFAULT', 'username', fallback=''),
            'password': config.get('DEFAULT', 'password', fallback=''),
            'latitude': config.get('DEFAULT', 'latitude', fallback=''),
            'longitude': config.get('DEFAULT', 'longitude', fallback=''),
            'tags': config.get('DEFAULT', 'tags', fallback=''),
            'save_rate': config.get('DEFAULT', 'save_rate', fallback='')
        }
        print(f"⚠️  Configuration file already exists: {config_file}")
        print("You can modify individual settings below.")
        print("Press Enter to keep current values.")
        print()
    
    print("This wizard will help you configure your fixed Rium GM dosimeter station.")
    print()
    
    # OpenRadiation API Key
    print("1️⃣  OpenRadiation API Configuration")
    print("-" * 70)
    print("To get your API key:")
    print("  • Visit: https://www.openradiation.org/")
    print("  • Create an account or log in")
    print("  • Go to your profile to find your API key")
    print()
    
    current_api_key = existing_config.get('api_key', '')
    if current_api_key:
        masked_key = '*' * 8 + current_api_key[-4:] if len(current_api_key) > 4 else current_api_key
        print(f"Current API Key: {masked_key}")
    
    api_key = get_input("Enter your OpenRadiation API key (press Enter to skip)", default=current_api_key, required=False)
    print()
    
    # Username
    print("1.1️⃣  OpenRadiation Username")
    print("-" * 70)
    print("Enter your OpenRadiation account username.")
    print()
    
    current_username = existing_config.get('username', '')
    if current_username:
        print(f"Current Username: {current_username}")
    
    username = get_input("Enter your OpenRadiation username (press Enter to skip)", default=current_username)
    print()

    user_id = username  # use username as userId always
    # Password
    print("1.2️⃣  OpenRadiation Password")
    print("-" * 70)
    print("Enter your OpenRadiation account password.")
    print()
    
    current_password = None  # noqa: F841 — kept for potential future use
    credential_key = None
    keyring_password = None  # initialise avant utilisation
    if existing_config.get('user_id'):
        credential_key = existing_config.get('user_id')
    elif existing_config.get('username'):
        credential_key = existing_config.get('username')

    if credential_key:
        keyring_password = get_stored_password(credential_key)
        if keyring_password:
            print(f"Current password is stored securely for {credential_key}.")
        else:
            print(f"No password found for {credential_key}.")

    password_input = getpass.getpass("Enter password (press Enter to keep existing value or skip): ").strip()
    if password_input:
        password = password_input
    else:
        password = keyring_password if credential_key else None
    print()

    # Save password securely to encrypted file (if provided)
    effective_user_key = user_id or username
    if password and effective_user_key:
        if set_stored_password(effective_user_key, password):
            print(f"Password stored securely in encrypted file under '{effective_user_key}'.")
        else:
            print("Warning: Unable to store password securely.")
    elif password and not effective_user_key:
        print("Warning: password entered but no userId/username provided, will not be saved.")

    # do not store password in config.ini
    print("(Password is NOT saved in config.ini, use encrypted file storage.)")
    print()
    
    # Location
    print("2️⃣  Station Location (GPS Coordinates)")
    print("-" * 70)
    print("Enter the fixed location of your dosimeter station.")
    print("You can find coordinates by:")
    print("  • Right-clicking on Google Maps and copying coordinates")
    print("  • Using a GPS device")
    print("  • Format: Decimal degrees (e.g., 48.8566 for latitude)")
    print()
    
    current_latitude = existing_config.get('latitude', '')
    if current_latitude:
        print(f"Current Latitude: {current_latitude}")
    
    try:
         latitude = get_float("Latitude (e.g., 48.8566) (press Enter to skip)", default=float(current_latitude) if current_latitude else None, required=False)
    except (ValueError, TypeError):
        latitude = get_float("Latitude (e.g., 48.8566) (press Enter to skip)", required=False)
    
    current_longitude = existing_config.get('longitude', '')
    if current_longitude:
        print(f"Current Longitude: {current_longitude}")
    
    try:
        longitude = get_float("Longitude (e.g., 2.3522) (press Enter to skip)", default=float(current_longitude) if current_longitude else None, required=False)
    except (ValueError, TypeError):
        longitude = get_float("Longitude (e.g., 2.3522) (press Enter to skip)", required=False)
    print()
    
    # Tags
    print("3️⃣  Station Tags (Optional)")
    print("-" * 70)
    print("Add descriptive tags to help identify and filter your station's data.")
    print("Note: The tag _fixed_beacon_ will be automatically added to identify this station as a fixed beacon.")

    current_tags = existing_config.get('tags', '')
    if current_tags:
        print(f"Current Tags: {current_tags}")
    
    tags_input = get_input("Tags (comma-separated, press Enter to skip)", default=current_tags)
    
    # always include _fixed_beacon_ tag
    tags_list = [tag.strip() for tag in tags_input.split(',') if tag.strip()] if tags_input else []
    if '_fixed_beacon_' not in tags_list:
        tags_list.append('_fixed_beacon_')

    tags = ','.join(tags_list)

    # Save rate (minutes)
    current_save_rate = existing_config.get('save_rate', '')
    if current_save_rate:
        print(f"Current save/send interval: {current_save_rate} minutes")
    else:
        print(f"Current save/send interval: Not set (default {DEFAULT_SAVE_RATE_MINUTES} minutes)")
        current_save_rate = str(DEFAULT_SAVE_RATE_MINUTES)
        
    while True:
        save_rate_input = get_input("Save/send interval in minutes (min 15) (press Enter to keep current)", default=current_save_rate)
        if save_rate_input in [None, '']:
            save_rate = current_save_rate
            break
        try:
            val = float(save_rate_input)
            if val < MINIMUM_SAVE_RATE_MINUTES:
                print(f"  ⚠️  Minimum save rate is {MINIMUM_SAVE_RATE_MINUTES} minutes; using {MINIMUM_SAVE_RATE_MINUTES}.")
                val = MINIMUM_SAVE_RATE_MINUTES
            save_rate = str(int(val))
            break
        except ValueError:
            print("  ⚠️  Please enter a valid number (minutes).")
    print()
    
    # Summary
    print("="*70)
    print("Configuration Summary:")
    print("="*70)
    masked_api = '*' * 8 + api_key[-4:] if api_key and len(api_key) > 4 else api_key if api_key else 'Not set'
    print(f"API Key: {masked_api}")
    print(f"Username/User ID: {user_id if user_id else 'Not set'}")
    print(f"Password: {'Stored in encrypted file' if password else 'Not set'}")
    location_str = f"{latitude}, {longitude}" if latitude and longitude else "Not set"
    print(f"Location: {location_str}")
    print(f"Tags: {tags if tags else 'None'}")
    print(f"Save/send interval: {save_rate + ' minutes' if save_rate else (current_save_rate + ' minutes' if current_save_rate else 'Not set (default 15 minutes)')}")
    print("="*70)
    print()
    
    confirm = input("Save this configuration? (yes/no) [yes]: ").strip().lower()
    if confirm in ['', 'yes', 'y']:
        # Create config
        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'api_key': api_key if api_key else '',
            'username': username if username else '',
            'latitude': str(latitude) if latitude else current_latitude,
            'longitude': str(longitude) if longitude else current_longitude,
            'tags': tags if tags else '',
            'save_rate': save_rate if save_rate else current_save_rate
        }
        
        # Write config file
        with open(config_file, 'w') as f:
            f.write("# OpenRadiation API Configuration\n")
            f.write("# Generated by configuration wizard\n")
            f.write("# ASNR Project\n")
            f.write("# Edit manually or run launcher again\n\n")
            config.write(f)
        
        print()
        print("✅ Configuration saved successfully!")
        print()
        return True
    else:
        print("Configuration cancelled.")
        return False


def run_command(cmd, description):
    """Run a command with description."""
    if description:
        print(f"\n→ {description}")
        print("-" * 70)
    try:
        result = subprocess.run(cmd, shell=False)
        return result.returncode == 0
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user.")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def find_candidate_ports():
    """Return a list of likely serial ports (posix and fallback for Windows)."""
    ports = []
    if os.name == 'posix':
        ports.extend(sorted(glob.glob('/dev/ttyUSB*')))
        ports.extend(sorted(glob.glob('/dev/ttyACM*')))
        ports.extend(sorted(glob.glob('/dev/serial/by-id/*')))
    else:
        try:
            import serial.tools.list_ports
            available = [port.device for port in serial.tools.list_ports.comports()]
            ports.extend(sorted(available))
        except ImportError:
            print("  \u26a0\ufe0f  pyserial not installed — cannot list COM ports on Windows.")
        except Exception as e:
            print(f"  \u26a0\ufe0f  Error listing ports: {e}")
    return ports

DEFAULT_CPS_TO_USVH_FUNC = "(0.00000003751 * (cps * 60 - 4)**2 + 0.00965 * (cps * 60 - 4)) * 0.85"


def check_openradiation_api(config_file):
    """
    Vérifie que les identifiants OpenRadiation sont valides en envoyant
    un payload minimal en mode test (reportContext=test).
    Retourne True si l'API répond 200, False sinon.
    """
    print("\n" + "-" * 70)
    print("Vérification des identifiants OpenRadiation (envoi test API)...")

    # Lire la configuration
    cfg = configparser.ConfigParser()
    if not os.path.exists(config_file):
        print("  ✗ Fichier config.ini introuvable. Configurez d'abord le système (option 1).")
        return False
    try:
        cfg.read(config_file)
    except Exception as e:
        print(f"  ✗ Erreur lecture config.ini : {e}")
        return False

    api_key = cfg.get('DEFAULT', 'api_key', fallback='').strip()
    username = cfg.get('DEFAULT', 'username', fallback='').strip()
    latitude = cfg.get('DEFAULT', 'latitude', fallback='0').strip()
    longitude = cfg.get('DEFAULT', 'longitude', fallback='0').strip()

    if not api_key:
        print("  ✗ api_key absent dans config.ini. Configurez d'abord le système (option 1).")
        return False
    if not username:
        print("  ✗ username absent dans config.ini. Configurez d'abord le système (option 1).")
        return False

    # Récupérer le mot de passe stocké
    user_pwd = get_stored_password(username)
    if not user_pwd:
        if sys.stdin.isatty():
            user_pwd = getpass.getpass(f"  Mot de passe pour '{username}' : ")
        if not user_pwd:
            print("  ✗ Aucun mot de passe disponible pour cet utilisateur.")
            return False

    # Construire un payload minimal en mode test
    try:
        import uuid
        from datetime import datetime, timezone
        import requests
    except ImportError as e:
        print(f"  ✗ Module manquant : {e}. Installez les dépendances (option 4).")
        return False

    now = datetime.now(tz=timezone.utc)
    payload = {
        "apiKey": api_key,
        "data": {
            "reportUuid": str(uuid.uuid4()),
            "latitude": float(latitude) if latitude else 0.0,
            "longitude": float(longitude) if longitude else 0.0,
            "value": 0.1,
            "startTime": now.isoformat(),
            "endTime": now.isoformat(),
            "hitsNumber": 10,
            "userId": username,
            "userPwd": user_pwd,
            "reportContext": "test",
            "description": "API credential check from launcher"
        }
    }

    url = "https://submit.openradiation.net/measurements"
    print(f"  → Envoi vers {url} (mode test, userId='{username}')...")
    try:
        response = requests.post(url, json=payload,
                                 headers={'Content-Type': 'application/json'},
                                 timeout=15)
        if response.status_code == 200:
            print("  ✓ Identifiants valides ! L'API a accepté l'envoi (HTTP 200).")
            return True
        elif response.status_code == 401:
            print(f"  ✗ Identifiants refusés (HTTP 401) : mot de passe ou api_key incorrect.")
            print(f"     Réponse : {response.text[:200]}")
            return False
        else:
            print(f"  ✗ Réponse inattendue de l'API (HTTP {response.status_code}).")
            print(f"     Réponse : {response.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("  ✗ Timeout : impossible de joindre l'API OpenRadiation (>15s).")
        return False
    except requests.exceptions.ConnectionError:
        print("  ✗ Pas de connexion internet ou l'API est inaccessible.")
        return False
    except Exception as e:
        print(f"  ✗ Erreur lors de l'envoi : {e}")
        return False
    finally:
        print("-" * 70)


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(script_dir, 'read_dosimeter.py')
    
    # Load configuration (to get save_rate) and check dependencies on first run
    config_file = os.path.join(script_dir, 'config.ini')
    cfg = configparser.ConfigParser()
    if os.path.exists(config_file):
        try:
            cfg.read(config_file)
        except Exception:
            cfg = None
    else:
        cfg = None

    # Determine configured save_rate in minutes (minimum 15)
    configured_save_rate_minutes = 15
    if cfg and cfg.has_option('DEFAULT', 'save_rate'):
        try:
            val = float(cfg.get('DEFAULT', 'save_rate'))
            if val < 15:
                configured_save_rate_minutes = 15
            else:
                configured_save_rate_minutes = int(val)
        except Exception:
            configured_save_rate_minutes = 15

    # Check dependencies on first run
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\n⚠️  Please install dependencies before continuing.")
        input("Press Enter to exit...")
        sys.exit(1)

    while True:
        print_banner()

        # Define action handlers
        def do_configure():
            run_configuration_wizard()
            input("\nPress Enter to continue...")

        def do_monitor_local():
            print("\n→ Starting monitoring (local only, no data upload)")
            print("-" * 70)
            print("This will test if your dosimeter is working correctly.")
            print("Press Ctrl+C to stop when you're satisfied it's working.\n")
            run_command([sys.executable, main_script, '--cps-to-usvh-func', DEFAULT_CPS_TO_USVH_FUNC], "")
            input("\nPress Enter to continue...")

        def do_monitor_test():
            print("\n→ Starting monitoring with OpenRadiation upload (TEST mode)")
            print("-" * 70)
            print("This will perform a 30s local test, then a 30s upload test.")
            print("Press Ctrl+C to stop at any time.\n")
            # Vérification rapide des identifiants API avant de lancer les tests
            api_ok = check_openradiation_api(config_file)
            if not api_ok:
                print("\n⚠️  La vérification des identifiants API a échoué.")
                print("   Le test d'envoi risque d'échouer. Vérifiez votre config (option 1).")
                proceed = input("\nContinuer quand même ? (oui/non) [non] : ").strip().lower()
                if proceed not in ['oui', 'o', 'yes', 'y']:
                    input("\nAppuyez sur Entrée pour continuer...")
                    return
            print()
            # Reload save_rate from config in case user just reconfigured
            _save_rate = 15
            if os.path.exists(config_file):
                try:
                    _cfg = configparser.ConfigParser()
                    _cfg.read(config_file)
                    if _cfg.has_option('DEFAULT', 'save_rate'):
                        val = float(_cfg.get('DEFAULT', 'save_rate'))
                        _save_rate = max(15, int(val))
                except Exception:
                    pass
            # 1) Run a short 30s local-only test (no upload)
            test_ok = run_command([
                sys.executable,
                main_script,
                '--test-duration', '30',
                '--cps-to-usvh-func',
                DEFAULT_CPS_TO_USVH_FUNC
            ], "Running 30s local test...")

            # 2) After the short test, start uploading in TEST mode using configured save_rate
            if test_ok:
                success = run_command([
                    sys.executable,
                    main_script,
                    '--test-duration', '30',
                    '--send-data',
                    '--cps-to-usvh-func',
                    DEFAULT_CPS_TO_USVH_FUNC,
                    '--save-rate', str(_save_rate),
                ], "Starting 30s upload test (TEST mode)...")

                if success and is_linux():
                    print("=" * 70)
                    print("\nYour dosimeter is working and sending data to OpenRadiation.")
                    print("You can now set it up to run automatically (survives power cuts).\n")
                    setup_service = input("Do you want to setup automatic start (systemd service)? (yes/no) [yes]: ").strip().lower()
                    if setup_service in ['', 'yes', 'y']:
                        setup_systemd_service()

            input("\nPress Enter to continue...")

        def do_monitor_production():
            print("\n⚠️  PRODUCTION MODE")
            print("=" * 70)
            print("This will send REAL data to OpenRadiation.")
            print("Make sure:")
            print("  • Configuration is correct")
            print("  • GPS coordinates are accurate")
            print("  • You have tested in TEST mode first")
            print("=" * 70)
            confirm = input("\nAre you sure? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                # Reload save_rate from config in case user just reconfigured
                _prod_save_rate = 15
                if os.path.exists(config_file):
                    try:
                        _cfg = configparser.ConfigParser()
                        _cfg.read(config_file)
                        if _cfg.has_option('DEFAULT', 'save_rate'):
                            val = float(_cfg.get('DEFAULT', 'save_rate'))
                            _prod_save_rate = max(15, int(val))
                    except Exception:
                        pass
                print("\n→ Starting monitoring with OpenRadiation upload (PRODUCTION)")
                print("-" * 70)
                print("Press Ctrl+C to stop\n")
                run_command([
                    sys.executable,
                    main_script,
                    '--send-data',
                    '--production',
                    '--cps-to-usvh-func',
                    DEFAULT_CPS_TO_USVH_FUNC,
                    '--save-rate', str(_prod_save_rate)
                ], "")
            else:
                print("Operation cancelled.")
            input("\nPress Enter to continue...")

        def do_list_ports():
            print("\n→ Listing available serial ports")
            print("-" * 70)
            ports = find_candidate_ports()
            print(f"Detected {len(ports)} serial port(s).")
            if ports:
                print("Available serial ports:")
                for port in ports:
                    print(f"  • {port}")
            input("\nPress Enter to continue...")

        def do_setup_service():
            setup_systemd_service()
            input("\nPress Enter to continue...")

        def do_exit():
            print("\nGoodbye!")
            sys.exit(0)

        # Build menu entries dynamically
        menu = []
        menu.append(("Configure station (first-time setup or reconfigure)", do_configure))
        menu.append(("Start monitoring (local only, no data upload)", do_monitor_local))
        menu.append(("Start monitoring + upload (TEST mode)", do_monitor_test))
        menu.append(("Start monitoring + upload (PRODUCTION mode)", do_monitor_production))
        menu.append(("List available serial ports", do_list_ports))

        if is_linux():
            menu.append(("Setup auto-start service (systemd)", do_setup_service))

            def do_service_status():
                """Affiche le statut complet du service systemd."""
                print("\n→ Statut du service systemd")
                print("-" * 70)
                subprocess.run(['sudo', 'systemctl', 'status', SERVICE_NAME, '--no-pager'])
                print()
                subprocess.run(['journalctl', '-u', SERVICE_NAME, '-n', '30', '--no-pager'])
                input("\nAppuyez sur Entrée pour continuer...")

            def do_stop_service():
                """Arrête le service systemd."""
                enabled, active = get_service_status()
                if not active:
                    print("\n⚠️  Le service n'est pas actif.")
                    input("\nAppuyez sur Entrée pour continuer...")
                    return
                confirm = input("\nArrêter le service rium-dosimeter ? (oui/non) [non] : ").strip().lower()
                if confirm in ['oui', 'o', 'yes', 'y']:
                    subprocess.run(['sudo', 'systemctl', 'stop', SERVICE_NAME], check=False)
                    print("✅ Service arrêté.")
                else:
                    print("Annulé.")
                input("\nAppuyez sur Entrée pour continuer...")

            def do_shutdown():
                """Éteint le Raspberry Pi / l'Arduino après confirmation."""
                confirm = input("\n⚠️  Éteindre la machine maintenant ? (oui/non) [non] : ").strip().lower()
                if confirm in ['oui', 'o', 'yes', 'y']:
                    print("→ Extinction en cours...")
                    subprocess.run(['sudo', 'shutdown', '-h', 'now'], check=False)
                else:
                    print("Annulé.")
                input("\nAppuyez sur Entrée pour continuer...")

            menu.append(("Voir statut du service", do_service_status))
            menu.append(("Arrêter le service", do_stop_service))
            menu.append(("Éteindre la machine (shutdown)", do_shutdown))

        menu.append(("Exit", do_exit))

        # Print menu
        print("\nWhat would you like to do?\n")
        for idx, (label, _) in enumerate(menu, start=1):
            print(f"  {idx}. {label}")

        print()

        try:
            choice = input(f"Enter your choice (1-{len(menu)}): ").strip()
            if not choice.isdigit():
                print(f"\n❌ Invalid choice. Please enter 1-{len(menu)}.")
                input("Press Enter to continue...")
                continue

            idx = int(choice)
            if idx < 1 or idx > len(menu):
                print(f"\n❌ Invalid choice. Please enter 1-{len(menu)}.")
                input("Press Enter to continue...")
                continue

            # Call the selected handler
            _, handler = menu[idx - 1]
            handler()

        except KeyboardInterrupt:
            print("\n\nExiting...")
            sys.exit(0)
        except Exception as e:
            print(f"\n❌ Error: {e}")
            input("Press Enter to continue...")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExiting...")
        sys.exit(0)
