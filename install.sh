#!/bin/bash

echo ""
echo "================================================="
echo "  Epever Tracer — Venus OS Installer"
echo "  Tested with Victron Energy USB RS485 cable"
echo "================================================="
echo ""

read -p "Install at your own risk. Proceed? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled. No changes were made."
    exit 0
fi

echo ""
echo "[1/6] Installing Python dependencies..."
opkg update
opkg install python3-pip
pip3 install -U minimalmodbus
echo "      Done."

echo ""
echo "[2/6] Downloading driver..."
cd /data
wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[3/6] Downloading Victron velib_python library..."
wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[4/6] Installing files..."
mkdir -p dbus-epever-tracer/ext/velib_python
cp -R dbus-epever-tracer-master/* dbus-epever-tracer
cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
rm -r velib_python-master dbus-epever-tracer-master
echo "      Done."

echo ""
echo "[5/6] Setting permissions..."
chmod +x /data/dbus-epever-tracer/setup.sh
chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
chmod +x /data/dbus-epever-tracer/service/run
chmod +x /data/dbus-epever-tracer/service/log/run
echo "      Done."

echo ""
echo "[6/6] Applying OS configuration (symlinks, serial-starter, udev, boot hook)..."
bash /data/dbus-epever-tracer/setup.sh
echo "      Done."

echo ""
echo "================================================="
echo "  Installation complete. Please reboot to finish."
echo "================================================="
echo ""
