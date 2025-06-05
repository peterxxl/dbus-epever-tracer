#!/bin/bash

# ===============================
# Epever Tracer Venus OS Updater
# ===============================
# This script updates the Epever Tracer driver and its dependencies on Venus OS.
# It will download the latest driver and Victron Python library, install them,
# and set up permissions and symlinks. Use at your own risk!

read -p "Update Epever Tracer on Venus OS at your own risk? [Y to proceed]" -n 1 -r
echo    # move to a new line
if [[ $REPLY =~ ^[Yy]$ ]]
then
    echo "\n[1/6] Switching to /data directory..."
    cd /data

    echo "[2/6] Downloading latest dbus-epever-tracer driver..."
    wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
    echo "Unzipping driver..."
    unzip -q master.zip
    rm master.zip

    echo "[3/6] Downloading latest Victron velib_python library..."
    wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
    echo "Unzipping library..."
    unzip -q master.zip
    rm master.zip

    echo "[4/6] Installing libraries and organizing folders..."
    mkdir -p dbus-epever-tracer/ext/velib_python
    cp -R dbus-epever-tracer-master/* dbus-epever-tracer
    cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

    echo "Cleaning up temporary files..."
    rm -r velib_python-master
    rm -r dbus-epever-tracer-master

    echo "[5/6] Setting execute permissions on driver and service scripts..."
    chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
    chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
    chmod +x /data/dbus-epever-tracer/service/run
    chmod +x /data/dbus-epever-tracer/service/log/run

    echo "[6/6] Creating/Updating symlinks for Victron Energy integration..."
    ln -sf /data/dbus-epever-tracer/driver /opt/victronenergy/dbus-epever-tracer
    ln -sf /data/dbus-epever-tracer/service /opt/victronenergy/service-templates/dbus-epever-tracer

    echo "\nUpdate complete! To finish, please reboot your Venus OS device."
else
    echo "\nUpdate cancelled by user. No changes were made."
fi
