# dbus-epever-tracer

**A Venus OS driver for EPEVER Tracer MPPT Solar Charge Controllers**

---

> **Tested Hardware & Software**
>
> - **Victron Cerbo-S GX** running **Venus OS v3.55**
> - **EPEVER Tracer 3210A MPPT Solar Charge Controller**
> - **Victron Energy USB RS485 cable (FT232R chipset)** — recommended and tested
> - Should also work on other Venus OS devices (GX, Raspberry Pi, etc.) and compatible EPEVER Tracer models

---

## Overview

This open-source driver integrates EPEVER Tracer MPPT solar charge controllers with Victron Venus OS, making real-time and historical solar data available on Venus-based devices, VRM, and the Victron ecosystem. It communicates over Modbus RTU (RS485) and exposes all key charger, battery, and PV metrics via dbus.

**Features:**
- Real-time monitoring of PV, battery, and load parameters
- Historical yield and statistics tracking
- Compatible with Victron VRM and remote monitoring
- Easy installation and update scripts
- Customizable product/device name for VRM display

---

## Hardware Requirements

- **Victron Venus OS device:** Cerbo GX, Cerbo-S GX, Raspberry Pi, etc.
- **EPEVER Tracer MPPT** (tested on 3210A, other models may work)
- **RS485 to USB adapter** (tested with Victron Energy USB RS485 cable (FT232R chipset))

---

## Software Requirements

- **Venus OS v3.55** (other versions may work, but this is tested)
- Root access to your Venus OS device
- Internet connection for installation

---

## Installation

1. **Enable root access** on your Venus OS device.
2. **SSH into your device** as root.
3. Download the installer:
   ```sh
   wget https://github.com/peterxxl/dbus-epever-tracer/raw/master/install.sh
   chmod +x install.sh
   ./install.sh
   ```
4. Answer `Y` when prompted to install the driver and dependencies.
5. **Reboot** the Venus OS device after installation.
6. **Connect your RS485 adapter** to the Venus OS device (USB port).

---

## Update

To update to the latest version, run:
```sh
wget https://github.com/peterxxl/dbus-epever-tracer/raw/master/update.sh
chmod +x update.sh
./update.sh
```

---

## Hardware Connection Notes

- **Recommended and tested:** Victron Energy USB RS485 cable (FT232R chipset). This is the officially supported and tested adapter for this driver.
- Ensure the driver service is started with the correct serial device (e.g., `/dev/ttyUSB0`).
- If using a different adapter, update the start script or service configuration as needed.

---

## Troubleshooting

- **No Data on VRM:**
  - Check that the driver is running (`ps aux | grep dbus-epever-tracer`)
  - Verify the correct serial port is specified
  - Inspect logs for errors (`/var/log/daemon.log` or `journalctl`)
- **Driver Fails to Start:**
  - Ensure dependencies are installed (see install script output)
  - Confirm the RS485 adapter is detected (`ls /dev/ttyUSB*`)
- **Customizing Device Name:**
  - Edit `productname`, `customname`, etc. in `driver/dbus-epever-tracer.py` before installation or update

---

## Disclaimer

> **This project is provided as-is, with no warranty. Use at your own risk. Incorrect wiring or configuration can damage your hardware.**

---

## Credits & License

- Based on original work by [kassl-2007](https://github.com/kassl-2007/dbus-epever-tracer) and improved by the community.
- MIT License. See LICENSE for details.

---

**Enjoy reliable EPEVER solar data on your Victron-powered system!**

For this see:

https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus#howto-add-a-driver-to-serial-starter
