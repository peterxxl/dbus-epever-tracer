#!/bin/bash

echo ""
echo "================================================="
echo "  Epever Tracer — Venus OS Updater"
echo "================================================="
echo ""

read -p "Update at your own risk. Proceed? [y/N] " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled. No changes were made."
    exit 0
fi

echo ""
cd /data

echo "[1/5] Downloading driver..."
wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[2/5] Downloading Victron velib_python library..."
wget -q --show-progress https://github.com/victronenergy/velib_python/archive/master.zip
unzip -q master.zip
rm master.zip
echo "      Done."

echo ""
echo "[3/5] Installing files..."
mkdir -p dbus-epever-tracer/ext/velib_python
cp -R dbus-epever-tracer-master/* dbus-epever-tracer
cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
rm -r velib_python-master dbus-epever-tracer-master
echo "      Done."

echo ""
echo "[4/5] Setting permissions..."
chmod +x /data/dbus-epever-tracer/setup.sh
chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
chmod +x /data/dbus-epever-tracer/service/run
chmod +x /data/dbus-epever-tracer/service/log/run
echo "      Done."

echo ""
echo "[5/5] Applying OS configuration (symlinks, serial-starter, udev)..."
bash /data/dbus-epever-tracer/setup.sh

if ! grep -q "dbus-epever-tracer/setup.sh" /data/rc.local 2>/dev/null; then
    echo "bash /data/dbus-epever-tracer/setup.sh" >> /data/rc.local
    chmod +x /data/rc.local
    echo "      Boot hook registered in /data/rc.local."
else
    echo "      Boot hook already registered."
fi
echo "      Done."

echo ""
echo "================================================="
echo "  Update complete. Please reboot to finish."
echo "================================================="
echo ""
