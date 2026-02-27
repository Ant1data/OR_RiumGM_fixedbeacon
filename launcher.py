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
    
    while True:
        print_banner()
        print("What would you like to do?\n")
        print("  1. 🔧 Configure station (first-time setup or reconfigure)")
        print("  2. 🔍 Test connection (check if dosimeter is detected)")
        print("  3. 📊 Start monitoring (local only, no data upload)")
        print("  4. 🌐 Start monitoring + upload (TEST mode)")
        print("  5. 🚀 Start monitoring + upload (PRODUCTION mode)")
        print("  6. 📋 List available serial ports")
        print("  7. ❌ Exit")
        print()
        
        try:
            choice = input("Enter your choice (1-7): ").strip()
            
            if choice == '1':
                # Configuration wizard
                run_configuration_wizard()
                input("\nPress Enter to continue...")
                
            elif choice == '2':
                # Test connection
                run_command(
                    [sys.executable, main_script, '--list'],
                    "Scanning for serial ports and testing connection..."
                )
                input("\nPress Enter to continue...")
                
            elif choice == '3':
                # Monitor without upload
                print("\n→ Starting monitoring (local only, no data upload)")
                print("-" * 70)
                print("Press Ctrl+C to stop\n")
                run_command([sys.executable, main_script], "")
                input("\nPress Enter to continue...")
                
            elif choice == '4':
                # Monitor with upload (test)
                print("\n→ Starting monitoring with OpenRadiation upload (TEST mode)")
                print("-" * 70)
                print("Data will be marked as 'test' in the database")
                print("Press Ctrl+C to stop\n")
                run_command([sys.executable, main_script, '--send-data'], "")
                input("\nPress Enter to continue...")
                
            elif choice == '5':
                # Monitor with upload (production)
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
                
            elif choice == '6':
                # List ports
                run_command(
                    [sys.executable, main_script, '--list'],
                    "Listing available serial ports..."
                )
                input("\nPress Enter to continue...")
                
            elif choice == '7':
                # Exit
                print("\nGoodbye!")
                sys.exit(0)
                
            else:
                print("\n❌ Invalid choice. Please enter 1-7.")
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
