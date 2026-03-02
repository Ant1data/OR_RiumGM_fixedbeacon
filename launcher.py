#!/usr/bin/env python3
"""
All-in-one launcher for Rium GM Dosimeter Reader.
Provides a user-friendly menu for all operations including first-time setup.

ASNR (formerly IRSN) Project
"""

import configparser
import os
import sys
import subprocess
import platform
import importlib.util


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
        'requests': 'requests'
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
        # Determine pip command
        pip_cmd = 'pip3' if is_linux() else 'pip'
        
        # Try to install
        cmd = [sys.executable, '-m', 'pip', 'install'] + packages
        
        print(f"Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=False)
        
        if result.returncode == 0:
            print("\n✅ Dependencies installed successfully!")
            return True
        else:
            print("\n❌ Installation failed.")
            print("\nTry manually with:")
            if is_linux():
                print(f"  pip3 install {' '.join(packages)}")
                print("Or with sudo if needed:")
                print(f"  sudo pip3 install {' '.join(packages)}")
            else:
                print(f"  pip install {' '.join(packages)}")
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
        # Check if service file exists
        if not os.path.exists(service_file_src):
            print(f"\n❌ Service file not found: {service_file_src}")
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


def print_banner():
    print("\n" + "="*70)
    print("  RIUM GM DOSIMETER - Quick Launcher")
    print("  ASNR (formerly IRSN) Project")
    print("="*70)
    print()


def get_input(prompt, default=None, required=False):
    """Get user input with optional default value."""
    if default:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "
    
    while True:
        value = input(full_prompt).strip()
        
        if not value and default:
            return default
        
        if not value and required:
            print("  ⚠️  This field is required. Please enter a value.")
            continue
        
        return value


def get_float(prompt, required=False):
    """Get a float input from user."""
    while True:
        value = input(f"{prompt}: ").strip()
        
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
    
    # Check if config already exists
    if os.path.exists(config_file):
        print(f"⚠️  Configuration file already exists: {config_file}")
        overwrite = input("Do you want to overwrite it? (yes/no) [no]: ").strip().lower()
        if overwrite not in ['yes', 'y']:
            print("Configuration cancelled. Existing file preserved.")
            return False
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
    
    api_key = get_input("Enter your OpenRadiation API key", required=True)
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
    
    latitude = get_float("Latitude (e.g., 48.8566)", required=True)
    longitude = get_float("Longitude (e.g., 2.3522)", required=True)
    print()
    
    # User ID
    print("3️⃣  User Identification (Optional)")
    print("-" * 70)
    print("Associate measurements with your OpenRadiation user account.")
    print()
    
    user_id = get_input("Enter your OpenRadiation user ID (press Enter to skip)")
    print()
    
    # Tags
    print("4️⃣  Station Tags (Optional)")
    print("-" * 70)
    print("Add descriptive tags to help identify and filter your station's data.")
    print("Note: All tags will automatically be prefixed with 'fixed_beacon_'")
    print()
    print("Examples (enter WITHOUT the prefix):")
    print("  • station_name=HomeStation  → becomes: fixed_beacon_station_name=HomeStation")
    print("  • location=Paris  → becomes: fixed_beacon_location=Paris")
    print("  • device=RiumGM_001  → becomes: fixed_beacon_device=RiumGM_001")
    print("  • altitude=100m  → becomes: fixed_beacon_altitude=100m")
    print()
    print("Enter tags (comma-separated, press Enter to skip):")
    
    tags = get_input("Tags")
    
    # Add fixed_beacon_ prefix if user provided tags
    if tags:
        tag_list = [t.strip() for t in tags.split(',') if t.strip()]
        prefixed_tags = []
        for tag in tag_list:
            if not tag.startswith('fixed_beacon_'):
                tag = f'fixed_beacon_{tag}'
            prefixed_tags.append(tag)
        tags = ', '.join(prefixed_tags)
        print(f"\n  → Tags with prefix: {tags}")
    
    print()
    
    # Summary
    print("="*70)
    print("Configuration Summary:")
    print("="*70)
    print(f"API Key: {'*' * 8}{api_key[-4:] if len(api_key) > 4 else api_key}")
    print(f"Location: {latitude}, {longitude}")
    print(f"User ID: {user_id if user_id else 'Not set'}")
    print(f"Tags: {tags if tags else 'None'}")
    print("="*70)
    print()
    
    confirm = input("Save this configuration? (yes/no) [yes]: ").strip().lower()
    if confirm in ['', 'yes', 'y']:
        # Create config
        config = configparser.ConfigParser()
        config['DEFAULT'] = {
            'api_key': api_key,
            'latitude': str(latitude),
            'longitude': str(longitude),
            'user_id': user_id if user_id else '',
            'tags': tags if tags else ''
        }
        
        # Write config file
        with open(config_file, 'w') as f:
            f.write("# OpenRadiation API Configuration\n")
            f.write("# Generated by configuration wizard\n")
            f.write("# ASNR (formerly IRSN) Project\n")
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


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(script_dir, 'read_dosimeter.py')
    
    # Check dependencies on first run
    deps_ok = check_dependencies()
    if not deps_ok:
        print("\n⚠️  Please install dependencies before continuing.")
        input("Press Enter to exit...")
        sys.exit(1)
    
    while True:
        print_banner()
        print("What would you like to do?\n")
        print("  1. 🔧 Configure station (first-time setup or reconfigure)")
        print("  2. 📊 Start monitoring (local only, no data upload)")
        print("  3. 🌐 Start monitoring + upload (TEST mode)")
        print("  4. 🚀 Start monitoring + upload (PRODUCTION mode)")
        print("  5. 📋 List available serial ports")
        
        # Show systemd option only on Linux
        if is_linux():
            print("  6. ⚙️  Setup auto-start service (systemd)")
            print("  7. ❌ Exit")
            max_choice = 7
        else:
            print("  6. ❌ Exit")
            max_choice = 6
        
        print()
        
        try:
            choice = input(f"Enter your choice (1-{max_choice}): ").strip()
            
            if choice == '1':
                # Configuration wizard
                run_configuration_wizard()
                input("\nPress Enter to continue...")
                
            elif choice == '2':
                # Monitor without upload - Test the dosimeter
                print("\n→ Starting monitoring (local only, no data upload)")
                print("-" * 70)
                print("This will test if your dosimeter is working correctly.")
                print("Press Ctrl+C to stop when you're satisfied it's working.\n")
                
                run_command([sys.executable, main_script], "")
                input("\nPress Enter to continue...")
                
            elif choice == '3':
                # Monitor with upload (test) - Full test with OpenRadiation
                print("\n→ Starting monitoring with OpenRadiation upload (TEST mode)")
                print("-" * 70)
                print("Data will be marked as 'test' in the database")
                print("Press Ctrl+C to stop when you're satisfied it's working.\n")
                
                success = run_command([sys.executable, main_script, '--send-data'], "")
                
                # After successful TEST, propose to setup systemd service (Linux only)
                if success and is_linux():
                    print("\n" + "="*70)
                    print("✅ Test completed successfully!")
                    print("="*70)
                    print("\nYour dosimeter is working and sending data to OpenRadiation.")
                    print("You can now set it up to run automatically (survives power cuts).")
                    print()
                    setup_service = input("Do you want to setup automatic start (systemd service)? (yes/no) [yes]: ").strip().lower()
                    if setup_service in ['', 'yes', 'y']:
                        setup_systemd_service()
                
                input("\nPress Enter to continue...")
                
            elif choice == '4':
                # Monitor with upload (production) (ex-choice 5)
                print("\n⚠️  PRODUCTION MODE")
                print("="*70)
                print("This will send REAL data to OpenRadiation.")
                print("Make sure:")
                print("  • Configuration is correct")
                print("  • GPS coordinates are accurate")
                print("  • You have tested in TEST mode first")
                print("="*70)
                confirm = input("\nAre you sure? (yes/no): ").strip().lower()
                
                if confirm in ['yes', 'y']:
                    print("\n→ Starting monitoring with OpenRadiation upload (PRODUCTION)")
                    print("-" * 70)
                    print("Press Ctrl+C to stop\n")
                    run_command([sys.executable, main_script, '--send-data', '--production'], "")
                else:
                    print("Operation cancelled.")
                input("\nPress Enter to continue...")
                
            elif choice == '5':
                # List ports
                run_command(
                    [sys.executable, main_script, '--list'],
                    "Listing available serial ports..."
                )
                input("\nPress Enter to continue...")
                
            elif choice == '6':
                # Setup systemd service (Linux) or Exit (Windows)
                if is_linux():
                    setup_systemd_service()
                    input("\nPress Enter to continue...")
                else:
                    # Exit on Windows
                    print("\nGoodbye!")
                    sys.exit(0)
                
            elif choice == '7' and is_linux():
                # Exit on Linux
                print("\nGoodbye!")
                sys.exit(0)
                
            else:
                print(f"\n❌ Invalid choice. Please enter 1-{max_choice}.")
                input("Press Enter to continue...")
                
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
