#!/bin/bash

# ===============================
# Epever Tracer Venus OS Installer
# ===============================
# Tested with Victron Energy USB RS485 cable (FT232R chipset)
# This script installs the Epever Tracer driver and its dependencies on Venus OS.
# It will install required Python packages, download the driver and libraries,
# and organize everything for you. Use at your own risk!

read -p "Install Epever Tracer on Venus OS at your own risk? [Y to proceed]" -n 1 -r
echo    # Move to a new line for readability
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "[1/6] Installing Python3 pip and minimalmodbus library..."
    # Update opkg package list
    opkg update
    # Install Python3 pip
    opkg install python3-pip
    # Install or upgrade minimalmodbus Python library
    pip3 install -U minimalmodbus

    echo "[2/6] Downloading latest dbus-epever-tracer driver..."
    cd /data
    wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
    echo "Unzipping driver..."
    unzip -q master.zip
    rm master.zip

    echo "[3/6] Downloading latest Victron velib_python library..."
    wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
    echo "Unzipping library..."
    unzip -q master.zip
    rm master.zip

    echo "[4/6] Organizing driver and library folders..."
    # Create directory for velib_python library and copy files
    mkdir -p dbus-epever-tracer/ext/velib_python
    cp -R dbus-epever-tracer-master/* dbus-epever-tracer
    cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

    echo "[5/6] Cleaning up temporary files..."
    rm -r velib_python-master
    rm -r dbus-epever-tracer-master

    echo "[6/6] Finalizing installation..."
    # Make driver and service scripts executable
    chmod +x /data/dbus-epever-tracer/setup.sh
    chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
    chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
    chmod +x /data/dbus-epever-tracer/service/run
    chmod +x /data/dbus-epever-tracer/service/log/run

    # Run setup.sh to create symlinks, serial-starter entry, and udev rule
    bash /data/dbus-epever-tracer/setup.sh

    # Register setup.sh in /data/rc.local so it runs automatically after every
    # Venus OS update, recreating the symlinks and config that the update wiped.
    if ! grep -q "dbus-epever-tracer/setup.sh" /data/rc.local 2>/dev/null; then
        echo "bash /data/dbus-epever-tracer/setup.sh" >> /data/rc.local
        chmod +x /data/rc.local
        echo "Registered setup.sh in /data/rc.local for post-update auto-recovery."
    fi

    echo "[6/6] Installation complete!"

    # Final step: Prompt user to reboot
    echo "To finish, reboot the Venus OS device"
else
    echo "Installation cancelled by user. No changes were made."
fi
