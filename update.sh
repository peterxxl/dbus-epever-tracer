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
    echo "[1/5] Switching to /data directory..."
    cd /data

    echo "[2/5] Downloading latest dbus-epever-tracer driver..."
    wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
    echo "Unzipping driver..."
    unzip -q master.zip
    rm master.zip

    echo "[3/5] Downloading latest Victron velib_python library..."
    wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
    echo "Unzipping library..."
    unzip -q master.zip
    rm master.zip

    echo "[4/5] Installing libraries and organizing folders..."
    mkdir -p dbus-epever-tracer/ext/velib_python
    cp -R dbus-epever-tracer-master/* dbus-epever-tracer
    cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python

    echo "Cleaning up temporary files..."
    rm -r velib_python-master
    rm -r dbus-epever-tracer-master

    echo "[5/5] Setting permissions and re-applying OS configuration..."
    chmod +x /data/dbus-epever-tracer/setup.sh
    chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
    chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
    chmod +x /data/dbus-epever-tracer/service/run
    chmod +x /data/dbus-epever-tracer/service/log/run

    # Re-run setup.sh to ensure symlinks, serial-starter entry, and udev rule
    # are in place (they may have been wiped by a recent OS update).
    bash /data/dbus-epever-tracer/setup.sh

    # Ensure /data/rc.local calls setup.sh on every boot so future OS updates
    # do not require manual intervention.
    if ! grep -q "dbus-epever-tracer/setup.sh" /data/rc.local 2>/dev/null; then
        echo "bash /data/dbus-epever-tracer/setup.sh" >> /data/rc.local
        chmod +x /data/rc.local
        echo "Registered setup.sh in /data/rc.local for post-update auto-recovery."
    fi

    echo "Update complete! To finish, please reboot your Venus OS device."
else
    echo "Update cancelled by user. No changes were made."
fi
