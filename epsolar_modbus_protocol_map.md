# LS-B Series MPPT Charge Controller Protocol
## Modbus Register Address List
**Version**: 1.1  
**Company**: Beijing Epsolar Technology Co., Ltd.

### Notes
1. The controller’s default ID is 1 and can be modified using PC software (Solar Station Monitor) or the MT50 remote meter.
2. Serial communication parameters: 115,200 bps baud rate, 8 data bits, 1 stop bit, no parity, no handshaking.
3. Register addresses are in hexadecimal format.
4. For 32-bit data (e.g., power), the L and H registers represent the low and high 16-bit values, respectively. For example, a charging input rated power of 3000 W (multiplied by 100) results in register 0x3002 holding 0x93F0 and register 0x3003 holding 0x0004.

## Rated Data (Read-Only) Input Registers

| Variable Name | Address | Description | Unit | Scale |
|---------------|---------|-------------|------|-------|
| Rated PV input voltage | 3000 | PV array rated voltage | V | 100 |
| Rated PV input current | 3001 | PV array rated current | A | 100 |
| Rated PV input power (low) | 3002 | PV array rated power (low 16 bits) | W | 100 |
| Rated PV input power (high) | 3003 | PV array rated power (high 16 bits) | W | 100 |
| Rated battery voltage | 3004 | Battery voltage | V | 100 |
| Rated charging current | 3005 | Rated charging current to battery | A | 100 |
| Rated charging power | 3006 | Rated charging power to battery | W | 100 |
| Reserved | 3007 |  | W | 100 |
| Charging mode | 3008 | 0001H: PWM |  |  |
| Rated load current | 300E | Rated load output current | A | 100 |

## Real-Time Data (Read-Only) Input Registers

| Variable Name | Address | Description | Unit | Scale |
|---------------|---------|-------------|------|-------|
| PV input voltage | 3100 | PV array voltage | V | 100 |
| PV input current | 3101 | PV array current | A | 100 |
| PV input power (low) | 3102 | PV array power (low 16 bits) | W | 100 |
| PV input power (high) | 3103 | PV array power (high 16 bits) | W | 100 |
| Battery voltage | 3104 | Battery voltage | V | 100 |
| Battery charging current | 3105 | Battery charging current | A | 100 |
| Battery charging power (low) | 3106 | Battery charging power (low 16 bits) | W | 100 |
| Battery charging power (high) | 3107 | Battery charging power (high 16 bits) | W | 100 |
| Load voltage | 310C | Load voltage | V | 100 |
| Load current | 310D | Load current | A | 100 |
| Load power (low) | 310E | Load power (low 16 bits) | W | 100 |
| Load power (high) | 310F | Load power (high 16 bits) | W | 100 |
| Battery temperature | 3110 | Battery temperature | °C | 100 |
| Controller internal temperature | 3111 | Internal case temperature | °C | 100 |
| Power component temperature | 3112 | Heat sink temperature of power components | °C | 100 |
| Battery SOC | 311A | Battery state of charge (remaining capacity percentage) | % | 100 |
| Remote battery temperature | 311B | Battery temperature from remote sensor | °C | 100 |
| System rated voltage | 311D | Current system rated voltage (1200 = 12 V, 2400 = 24 V) | V | 100 |

## Real-Time Status (Read-Only) Input Registers

| Variable Name | Address | Description |
|---------------|---------|-------------|
| Battery status | 3200 | **D3-D0**: 00H: Normal, 01H: Overvoltage, 02H: Undervoltage, 03H: Low Voltage Disconnect, 04H: Fault <br> **D7-D4**: 00H: Normal, 01H: Over Temperature (above warning threshold), 02H: Low Temperature (below warning threshold) <br> **D8**: Battery internal resistance: 1 = Abnormal, 0 = Normal <br> **D15**: Rated voltage identification: 1 = Incorrect, 0 = Correct |
| Charging equipment status | 3201 | **D15-D14**: Input voltage status: 00 = Normal, 01 = No power, 02H = High voltage, 03H = Voltage error <br> **D13**: Charging MOSFET short <br> **D12**: Charging or anti-reverse MOSFET short <br> **D11**: Anti-reverse MOSFET short <br> **D10**: Input overcurrent <br> **D9**: Load overcurrent <br> **D8**: Load short <br> **D7**: Load MOSFET short <br> **D4**: PV input short <br> **D3-D2**: Charging status: 00 = No charging, 01 = Float, 02 = Boost, 03 = Equalization <br> **D1**: 0 = Normal, 1 = Fault <br> **D0**: 1 = Running, 0 = Standby |

## Statistical Parameters (Read-Only) Input Registers

| Variable Name | Address | Description | Unit | Scale |
|---------------|---------|-------------|------|-------|
| Maximum PV voltage today | 3300 | Refreshed daily at 00:00 | V | 100 |
| Minimum PV voltage today | 3301 | Refreshed daily at 00:00 | V | 100 |
| Maximum battery voltage today | 3302 | Refreshed daily at 00:00 | V | 100 |
| Minimum battery voltage today | 3303 | Refreshed daily at 00:00 | V | 100 |
| Consumed energy today (low) | 3304 | Cleared daily at 00:00 | kWh | 100 |
| Consumed energy today (high) | 3305 | Cleared daily at 00:00 | kWh | 100 |
| Consumed energy this month (low) | 3306 | Cleared on the first day of the month | kWh | 100 |
| Consumed energy this month (high) | 3307 | Cleared on the first day of the month | kWh | 100 |
| Consumed energy this year (low) | 3308 | Cleared on January 1 | kWh | 100 |
| Consumed energy this year (high) | 3309 | Cleared on January 1 | kWh | 100 |
| Total consumed energy (low) | 330A |  | kWh | 100 |
| Total consumed energy (high) | 330B |  | kWh | 100 |
| Generated energy today (low) | 330C | Cleared daily at 00:00 | kWh | 100 |
| Generated energy today (high) | 330D | Cleared daily at 00:00 | kWh | 100 |
| Generated energy this month (low) | 330E | Cleared on the first day of the month | kWh | 100 |
| Generated energy this month (high) | 330F | Cleared on the first day of the month | kWh | 100 |
| Generated energy this year (low) | 3310 | Cleared on January 1 | kWh | 100 |
| Generated energy this year (high) | 3311 | Cleared on January 1 | kWh | 100 |
| Total generated energy (low) | 3312 |  | kWh | 100 |
| Total generated energy (high) | 3313 |  | kWh | 100 |
| CO2 reduction (low) | 3314 | 1 kWh saved = 0.997 kg CO2 or 0.272 kg carbon reduction | Ton | 100 |
| CO2 reduction (high) | 3315 |  | Ton | 100 |
| Net battery current (low) | 331B | Charging current minus discharging current (positive = charging, negative = discharging) | A | 100 |
| Net battery current (high) | 331C |  | A | 100 |
| Battery temperature | 331D | Battery temperature | °C | 100 |
| Ambient temperature | 331E | Ambient temperature | °C | 100 |

## Setting Parameters (Read-Write) Holding Registers

| Variable Name | Address | Description | Unit | Scale |
|---------------|---------|-------------|------|-------|
| Battery type | 9000 | 0000H: User-defined, 0001H: Sealed, 0002H: GEL, 0003H: Flooded |  |  |
| Battery capacity | 9001 | Rated battery capacity | Ah |  |
| Temperature compensation coefficient | 9002 | Range: 0–9 | mV/°C/2V | 100 |
| High voltage disconnect | 9003 |  | V | 100 |
| Charging limit voltage | 9004 |  | V | 100 |
| Overvoltage reconnect | 9005 |  | V | 100 |
| Equalization voltage | 9006 |  | V | 100 |
| Boost voltage | 9007 |  | V | 100 |
| Float voltage | 9008 |  | V | 100 |
| Boost reconnect voltage | 9009 |  | V | 100 |
| Low voltage reconnect | 900A |  | V | 100 |
| Undervoltage recovery | 900B |  | V | 100 |
| Undervoltage warning | 900C |  | V | 100 |
| Low voltage disconnect | 900D |  | V | 100 |
| Discharging limit voltage | 900E |  | V | 100 |
| Real-time clock (seconds/minutes) | 9013 | D7–D0: Seconds, D15–D8: Minutes (write Year, Month, Day, Minutes, Seconds simultaneously) |  |  |
| Real-time clock (hours/day) | 9014 | D7–D0: Hours, D15–D8: Day |  |  |
| Real-time clock (month/year) | 9015 | D7–D0: Month, D15–D8: Year |  |  |
| Equalization charging cycle | 9016 | Interval for auto-equalization charging | Days |  |
| Battery temperature warning upper limit | 9017 |  | °C | 100 |
| Battery temperature warning lower limit | 9018 |  | °C | 100 |
| Controller internal temperature upper limit | 9019 |  | °C | 100 |
| Controller internal temperature recovery | 901A | System resumes when temperature drops below this value | °C | 100 |
| Power component temperature upper limit | 901B | Charging/discharging stops if power component temperature exceeds this value | °C | 100 |
| Power component temperature recovery | 901C | System resumes when power component temperature drops below this value | °C | 100 |
| Line impedance | 901D | Resistance of connected wires | mΩ | 100 |
| Nighttime threshold voltage (NTTV) | 901E | PV voltage below this value indicates sundown | V | 100 |
| Night detection delay | 901F | Duration PV voltage must remain below NTTV to detect nighttime | Minutes |  |
| Daytime threshold voltage (DTTV) | 9020 | PV voltage above this value indicates sunrise | V | 100 |
| Day detection delay | 9021 | Duration PV voltage must remain above DTTV to detect daytime | Minutes |  |
| Load control mode | 903D | 0000H: Manual, 0001H: Light ON/OFF, 0002H: Light ON + Timer, 0003H: Time Control |  |  |
| Load timer 1 duration | 903E | Load output timer 1 duration (D15–D8: Hours, D7–D0: Minutes) |  |  |
| Load timer 2 duration | 903F | Load output timer 2 duration (D15–D8: Hours, D7–D0: Minutes) |  |  |
| Load timing 1 (on) | 9042 | Load on/off timing (seconds) | Seconds |  |
|  | 9043 | Load on/off timing (minutes) | Minutes |  |
|  | 9044 | Load on/off timing (hours) | Hours |  |
| Load timing 1 (off) | 9045 | Load on/off timing (seconds) | Seconds |  |
|  | 9046 | Load on/off timing (minutes) | Minutes |  |
|  | 9047 | Load on/off timing (hours) | Hours |  |
| Load timing 2 (on) | 9048 | Load on/off timing (seconds) | Seconds |  |
|  | 9049 | Default night duration (D15–D8: Hours, D7–D0: Minutes) | Minutes |  |
|  | 904A | Default night duration (hours) | Hours |  |
| Load timing 2 (off) | 904B | Load on/off timing (seconds) | Seconds |  |
|  | 904C | Load on/off timing (minutes) | Minutes |  |
|  | 904D | Load on/off timing (hours) | Hours |  |
| Night duration | 9065 | Total night duration |  |  |
| Battery rated voltage code | 9067 | 0: Auto-recognize, 1: 12 V, 2: 24 V |  |  |
| Load timing control selection | 9069 | Load timing period: 0 = One timer, 1 = Two timers |  |  |
| Default load state (manual mode) | 906A | 0: Off, 1: On |  |  |
| Equalization duration | 906B | Typically 60–120 minutes | Minutes |  |
| Boost duration | 906C | Typically 60–120 minutes | Minutes |  |
| Discharging percentage | 906D | Battery capacity percentage when discharging stops (typically 20%–80%) | % | 100 |
| Charging percentage | 906E | Depth of charge (typically 20%–100%) | % | 100 |
| Battery management mode | 9070 | 0: Voltage compensation, 1: SOC |  |  |

## Coils (Read-Write)

| Variable Name | Address | Description |
|---------------|---------|-------------|
| Manual load control | 2 | In manual mode: 1 = On, 0 = Off |
| Load test mode | 5 | 1 = Enable, 0 = Disable (normal) |
| Force load on/off | 6 | 1 = On, 0 = Off (for temporary load testing) |

## Discrete Inputs (Read-Only)

| Variable Name | Address | Description |
|---------------|---------|-------------|
| Controller over-temperature | 2000 | 1 = Temperature exceeds protection threshold, 0 = Normal |
| Day/night status | 200C | 1 = Night, 0 = Day |

## RJ-45 Port Pin Definitions

| Pin | Description |
|-----|-------------|
| 1, 2 | Not connected |
| 3, 4 | RS-485 A |
| 5, 6 | RS-485 B |
| 7, 8 | Ground |

### Notes
1. To enhance communication quality, ground pins 7 and 8 (connected to the battery’s negative terminal) may be used if needed. Ensure proper handling of common ground issues among connected devices.
2. For safety, do not use pins 1 and 2.