#!/bin/bash

DRIVER_DIR=/data/dbus-epever-tracer
GITHUB_DRIVER=https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip
GITHUB_VELIB=https://github.com/victronenergy/velib_python/archive/master.zip
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SCRIPT_NAME=$(basename "$0")

# ─── Colours ──────────────────────────────────────────────────────────────────

BD=$'\033[1m'
DM=$'\033[2m'
RS=$'\033[0m'
CY=$'\033[96m'   # bright cyan  — headers, step labels
GR=$'\033[92m'   # bright green — success, done
YL=$'\033[93m'   # bright yellow — warnings, prompts, info
RD=$'\033[91m'   # bright red   — errors
WH=$'\033[97m'   # bright white — banner text, values

is_installed() {
    [ -f "$DRIVER_DIR/driver/dbus-epever-tracer.py" ]
}

echo ""
echo "${BD}${CY}=================================================${RS}"
echo "${BD}${WH}  Epever Tracer — Venus OS Driver Setup${RS}"
echo "${DM}${WH}  Tested with Victron Energy USB RS485 cable${RS}"
echo "${BD}${CY}=================================================${RS}"
echo ""

# ─── Menu ─────────────────────────────────────────────────────────────────────

if is_installed; then
    CURRENT_VERSION=$(grep -m1 "^firmwareversion" "$DRIVER_DIR/driver/dbus-epever-tracer.py" \
        | sed "s/.*=[ ]*['\"]//;s/['\"].*//")
    echo "  Status: ${GR}${BD}installed${RS} ${DM}(${CURRENT_VERSION:-unknown})${RS}"
    echo ""
    echo "  ${WH}1)${RS} Update to latest version"
    echo "  ${WH}2)${RS} Remove from system"
    echo "  ${WH}3)${RS} Cancel"
    echo ""
    read -p "${YL}  Choose [1/2/3]: ${RS}" -n 1 -r CHOICE
    echo ""
    case "$CHOICE" in
        1) ACTION=update ;;
        2) ACTION=remove ;;
        *) echo "${YL}  Cancelled.${RS}"; exit 0 ;;
    esac
else
    echo "  Status: ${YL}not installed${RS}"
    echo ""
    read -p "${YL}  Install at your own risk. Proceed? [y/N] ${RS}" -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "${YL}  Cancelled. No changes were made.${RS}"
        exit 0
    fi
    ACTION=install
fi

# ─── Remove ───────────────────────────────────────────────────────────────────

do_remove() {
    echo "${YL}  The following changes will be made:${RS}"
    echo "${DM}    - Driver service(s) stopped and removed from supervision"
    echo "    - Symlinks removed from /opt/victronenergy/"
    echo "    - epever entry removed from /etc/venus/serial-starter.conf"
    echo "    - Udev rule removed from /etc/udev/rules.d/serial-starter.rules"
    echo "    - Boot hook entries removed from /data/rcS.local and /data/rc.local"
    echo "    - serial-starter restarted to reassign the serial port${RS}"
    echo ""
    read -p "${YL}  Continue? [y/N] ${RS}" -r REPLY
    echo ""
    if [[ ! $REPLY =~ ^[Yy] ]]; then
        echo "${YL}  Cancelled. Nothing was changed.${RS}"
        exit 0
    fi

    echo ""
    echo "  ${BD}${CY}[1/5]${RS} Stopping driver service(s)..."
    for SVC in $(ls /service/ 2>/dev/null | grep dbus-epever-tracer); do
        svc -d "/service/$SVC" 2>/dev/null || true
        sleep 1
        TTY="${SVC#dbus-epever-tracer.}"
        rm -f "/var/lock/serial-starter/$TTY"
        rm -f "/service/$SVC"
        rm -rf "/var/volatile/services/$SVC"
    done
    echo "        ${GR}Done.${RS}"

    echo ""
    echo "  ${BD}${CY}[2/5]${RS} Removing symlinks from /opt/victronenergy/..."
    rm -f /opt/victronenergy/dbus-epever-tracer
    rm -f /opt/victronenergy/service-templates/dbus-epever-tracer
    echo "        ${GR}Done.${RS}"

    echo ""
    echo "  ${BD}${CY}[3/5]${RS} Removing serial-starter entry..."
    sed -i '/service[[:space:]]*epever[[:space:]]*dbus-epever-tracer/d' \
        /etc/venus/serial-starter.conf
    echo "        ${GR}Done.${RS}"

    echo ""
    echo "  ${BD}${CY}[4/5]${RS} Removing udev rule and boot hooks..."
    sed -i '/# Epever Tracer/d' /etc/udev/rules.d/serial-starter.rules
    sed -i '/VE_SERVICE.*="epever"/d' /etc/udev/rules.d/serial-starter.rules
    udevadm control --reload-rules 2>/dev/null || true
    if [ -f /data/rcS.local ]; then
        sed -i '/dbus-epever-tracer\/setup-post-os-update.sh/d' /data/rcS.local
    fi
    if [ -f /data/rc.local ]; then
        sed -i '/dbus-epever-tracer\/setup-post-os-update.sh/d' /data/rc.local
        sed -i '/udevadm trigger --action=add --subsystem-match=tty/d' /data/rc.local
    fi
    echo "        ${GR}Done.${RS}"

    echo ""
    echo "  ${BD}${CY}[5/5]${RS} Restarting serial-starter..."
    svc -t /service/serial-starter 2>/dev/null || true
    echo "        ${GR}Done.${RS}"

    echo ""
    read -p "${YL}  Also delete driver files in $DRIVER_DIR? [y/N] ${RS}" -r REPLY
    echo ""
    if [[ $REPLY =~ ^[Yy] ]]; then
        rm -rf "$DRIVER_DIR"
        echo "        ${GR}Files deleted.${RS}"
    else
        echo "        ${DM}Files kept at $DRIVER_DIR${RS}"
        echo "        ${DM}(run this script again to reinstall)${RS}"
    fi

    echo ""
    echo "${BD}${GR}=================================================${RS}"
    echo "${BD}${GR}  Driver removed successfully.${RS}"
    echo "${BD}${GR}=================================================${RS}"
    echo ""
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

download_and_extract() {
    local url=$1
    local label=$2
    rm -f master.zip
    if ! wget -q --show-progress "$url" -O master.zip; then
        echo "        ${RD}${BD}ERROR:${RS}${RD} download failed ($label).${RS}"
        rm -f master.zip
        exit 1
    fi
    if ! unzip -q master.zip; then
        echo "        ${RD}${BD}ERROR:${RS}${RD} failed to extract archive ($label).${RS}"
        rm -f master.zip
        exit 1
    fi
    rm master.zip
}

# ─── Custom name ──────────────────────────────────────────────────────────────

save_custom_name() {
    echo ""
    read -p "${YL}  Give this device a custom name? [y/N] ${RS}" -r REPLY
    echo ""
    local CUSTOM_NAME=""
    if [[ $REPLY =~ ^[Yy] ]]; then
        read -p "${WH}    Enter name (default: PV Charger): ${RS}" -r CUSTOM_NAME
        CUSTOM_NAME="$(echo "$CUSTOM_NAME" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    fi
    [ -z "$CUSTOM_NAME" ] && CUSTOM_NAME="PV Charger"

    echo ""
    read -p "${YL}  Give the battery temperature sensor a custom name? [y/N] ${RS}" -r REPLY
    echo ""
    local BATT_TEMP_NAME=""
    if [[ $REPLY =~ ^[Yy] ]]; then
        read -p "${WH}    Enter name (default: Battery Temperature): ${RS}" -r BATT_TEMP_NAME
        BATT_TEMP_NAME="$(echo "$BATT_TEMP_NAME" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    fi
    [ -z "$BATT_TEMP_NAME" ] && BATT_TEMP_NAME="Battery Temperature"

    CUSTOM_NAME_CHARGER="$CUSTOM_NAME" \
    CUSTOM_NAME_TEMP="$CUSTOM_NAME Temperature" \
    CUSTOM_NAME_SWITCH="$CUSTOM_NAME Load Output" \
    CUSTOM_NAME_BATT_TEMP="$BATT_TEMP_NAME" \
    python3 - <<'PYEOF'
import json, os
state_file = '/data/dbus-epever-tracer/state.json'
try:
    with open(state_file) as f:
        s = json.load(f)
except Exception:
    s = {}
s['customname_charger']      = os.environ['CUSTOM_NAME_CHARGER']
s['customname_temp']         = os.environ['CUSTOM_NAME_TEMP']
s['customname_switch']       = os.environ['CUSTOM_NAME_SWITCH']
s['customname_output']       = ''
s['customname_battery_temp'] = os.environ['CUSTOM_NAME_BATT_TEMP']
with open(state_file, 'w') as f:
    json.dump(s, f)
PYEOF
    echo "        ${GR}Device name set to: ${BD}$CUSTOM_NAME${RS}"
    echo "        ${GR}Battery temp name set to: ${BD}$BATT_TEMP_NAME${RS}"
}

save_serial_number() {
    echo ""
    read -p "${YL}  Set a serial number for this device? [y/N] ${RS}" -r REPLY
    echo ""
    local SERIAL=""
    if [[ $REPLY =~ ^[Yy] ]]; then
        read -p "${WH}    Enter serial number: ${RS}" -r SERIAL
        SERIAL="$(echo "$SERIAL" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    fi
    SERIAL_NUMBER="$SERIAL" \
    python3 - <<'PYEOF'
import json, os
state_file = '/data/dbus-epever-tracer/state.json'
try:
    with open(state_file) as f:
        s = json.load(f)
except Exception:
    s = {}
s['serialnumber'] = os.environ['SERIAL_NUMBER']
with open(state_file, 'w') as f:
    json.dump(s, f)
PYEOF
    if [ -n "$SERIAL" ]; then
        echo "        ${GR}Serial number set to: ${BD}$SERIAL${RS}"
    else
        echo "        ${DM}Serial number left empty.${RS}"
    fi
}

save_device_instance() {
    echo ""
    echo "  ${DM}The VRM instance number identifies this device in the Victron portal."
    echo "  Default is 278. Change only if another device on this system"
    echo "  already uses that number.${RS}"
    echo ""
    read -p "${YL}  Set a custom VRM instance? [y/N] ${RS}" -r REPLY
    echo ""
    local INSTANCE=""
    if [[ $REPLY =~ ^[Yy] ]]; then
        read -p "${WH}    Enter VRM instance number (default: 278): ${RS}" -r INSTANCE
        INSTANCE="$(echo "$INSTANCE" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
        if ! [[ "$INSTANCE" =~ ^[0-9]+$ ]]; then
            echo "        ${YL}Invalid number — using default 278.${RS}"
            INSTANCE="278"
        fi
    fi
    [ -z "$INSTANCE" ] && INSTANCE="278"
    DEVICE_INSTANCE="$INSTANCE" \
    python3 - <<'PYEOF'
import json, os
state_file = '/data/dbus-epever-tracer/state.json'
try:
    with open(state_file) as f:
        s = json.load(f)
except Exception:
    s = {}
s['deviceinstance'] = int(os.environ['DEVICE_INSTANCE'])
with open(state_file, 'w') as f:
    json.dump(s, f)
PYEOF
    echo "        ${GR}VRM instance set to: ${BD}$INSTANCE${RS}"
}

# ─── Install / Update ─────────────────────────────────────────────────────────

do_install_update() {
    cd /data

    if [ "$ACTION" = install ]; then
        echo ""
        echo "  ${BD}${CY}[1/5]${RS} Downloading driver..."
        download_and_extract "$GITHUB_DRIVER" "driver"
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[2/5]${RS} Downloading Victron velib_python library..."
        download_and_extract "$GITHUB_VELIB" "velib_python"
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[3/5]${RS} Installing files..."
        mkdir -p dbus-epever-tracer/ext/velib_python
        cp -R dbus-epever-tracer-master/* dbus-epever-tracer
        cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
        if [ "$SCRIPT_DIR" != "/data/dbus-epever-tracer" ] && [ -f "$SCRIPT_DIR/$SCRIPT_NAME" ]; then
            cp "dbus-epever-tracer-master/$SCRIPT_NAME" "$SCRIPT_DIR/$SCRIPT_NAME" \
                && chmod +x "$SCRIPT_DIR/$SCRIPT_NAME"
        fi
        rm -r velib_python-master dbus-epever-tracer-master
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[4/5]${RS} Setting permissions..."
        chmod +x /data/dbus-epever-tracer/setup-epever-driver.sh
        chmod +x /data/dbus-epever-tracer/setup-post-os-update.sh
        chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
        chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
        chmod +x /data/dbus-epever-tracer/service/run
        chmod +x /data/dbus-epever-tracer/service/log/run
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[5/5]${RS} Applying OS configuration (symlinks, serial-starter, udev, boot hooks)..."
        bash /data/dbus-epever-tracer/setup-post-os-update.sh
        echo "        ${GR}Done.${RS}"

        save_custom_name
        save_serial_number
        save_device_instance

        echo ""
        echo "  ${BD}${CY}[+]${RS} Starting driver..."
        svc -t /service/serial-starter
        sleep 3
        SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -n 1)
        if [ -n "$SVC" ]; then
            echo "        ${GR}Driver started: ${BD}$SVC${RS}"
        else
            echo "        ${YL}RS485 adapter not detected yet — plug it in and the driver will start automatically.${RS}"
        fi

    else  # update

        OLD_VERSION=$(grep -m1 "^firmwareversion" "$DRIVER_DIR/driver/dbus-epever-tracer.py" \
            | sed "s/.*=[ ]*['\"]//;s/['\"].*//")

        SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -n 1)

        echo ""
        echo "  ${BD}${CY}[1/5]${RS} Downloading driver..."
        download_and_extract "$GITHUB_DRIVER" "driver"
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[2/5]${RS} Downloading Victron velib_python library..."
        download_and_extract "$GITHUB_VELIB" "velib_python"
        echo "        ${GR}Done.${RS}"

        NEW_VERSION=$(grep -m1 "^firmwareversion" "dbus-epever-tracer-master/driver/dbus-epever-tracer.py" \
            | sed "s/.*=[ ]*['\"]//;s/['\"].*//")

        echo ""
        echo "  ${BD}${CY}[3/5]${RS} Installing files..."
        mkdir -p dbus-epever-tracer/ext/velib_python
        cp -R dbus-epever-tracer-master/* dbus-epever-tracer
        cp -R velib_python-master/* dbus-epever-tracer/ext/velib_python
        if [ "$SCRIPT_DIR" != "/data/dbus-epever-tracer" ] && [ -f "$SCRIPT_DIR/$SCRIPT_NAME" ]; then
            cp "dbus-epever-tracer-master/$SCRIPT_NAME" "$SCRIPT_DIR/$SCRIPT_NAME" \
                && chmod +x "$SCRIPT_DIR/$SCRIPT_NAME"
        fi
        rm -r velib_python-master dbus-epever-tracer-master
        chmod +x /data/dbus-epever-tracer/setup-epever-driver.sh
        chmod +x /data/dbus-epever-tracer/setup-post-os-update.sh
        chmod +x /data/dbus-epever-tracer/driver/start-dbus-epever-tracer.sh
        chmod +x /data/dbus-epever-tracer/driver/dbus-epever-tracer.py
        chmod +x /data/dbus-epever-tracer/service/run
        chmod +x /data/dbus-epever-tracer/service/log/run
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[4/5]${RS} Applying OS configuration (symlinks, serial-starter, udev, boot hooks)..."
        bash /data/dbus-epever-tracer/setup-post-os-update.sh
        echo "        ${GR}Done.${RS}"

        echo ""
        echo "  ${BD}${CY}[5/5]${RS} Restarting driver..."
        if [ -n "$SVC" ]; then
            svc -d "/service/$SVC" 2>/dev/null || true
            sleep 1
        fi
        svc -t /service/serial-starter
        sleep 4
        SVC=$(ls /service/ 2>/dev/null | grep dbus-epever-tracer | head -n 1)
        if [ -n "$SVC" ]; then
            echo "        ${GR}Driver restarted: ${BD}$SVC${RS}"
        else
            echo "        ${YL}RS485 adapter not detected — plug it in and the driver will start automatically.${RS}"
        fi

    fi

    echo ""
    echo "${BD}${GR}=================================================${RS}"
    if [ "$ACTION" = update ]; then
        echo "${BD}${GR}  Update complete.${RS}"
        echo ""
        echo "  ${DM}Previous version :${RS} ${WH}${OLD_VERSION:-unknown}${RS}"
        echo "  ${DM}Installed version:${RS} ${WH}${BD}${NEW_VERSION:-unknown}${RS}"
    else
        echo "${BD}${GR}  Installation complete.${RS}"
    fi
    echo "${BD}${GR}=================================================${RS}"
    echo ""
    read -p "${YL}  Reboot the system now? [y/N] ${RS}" -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "${YL}  Rebooting...${RS}"
        reboot
    else
        echo "${DM}  Reboot skipped.${RS}"
    fi
    echo ""
}

# ─── Dispatch ─────────────────────────────────────────────────────────────────

case "$ACTION" in
    remove)         do_remove ;;
    install|update) do_install_update ;;
esac
