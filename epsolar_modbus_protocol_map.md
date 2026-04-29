# EPEVER LS-B / Tracer Series — Modbus Register Map

**Protocol version**: v2.5 — Beijing Epsolar Technology Co., Ltd.  
**Serial settings**: 115 200 bps, 8N1, no handshaking, default slave address 1.  
**Register addresses**: hexadecimal throughout.

---

## Range annotation key

Ranges shown in the Setting Parameters section use the following source labels:

| Label | Meaning |
|-------|---------|
| **spec** | Explicitly stated in the EPEVER protocol document |
| **observed** | Read from a Tracer 3210A on a 24 V system; may differ for 12 V or other models |
| **inferred** | Derived from the register's physical meaning — not stated in the spec |
| *(none)* | Unknown — the spec gives no range and no observed data is available |

Voltage thresholds have no explicit range in the EPEVER protocol document. Allowed values depend on the system voltage (12 V or 24 V) and the relationship between thresholds (e.g. float < boost < charging limit < HVD). The observed column shows the factory defaults on a 24 V Flooded bank.

---

## Tracer 3210A Compatibility Notes

Verified by raw Modbus dump against a **Tracer 3210A** at 115 200 bps over USB RS-485.

### Read block limits

| Block | Protocol count | **Tracer 3210A max** | Notes |
|-------|---------------|----------------------|-------|
| Rated data (FC04, 0x3000) | 15 | **0 — unsupported** | Every attempt returns exception 02 |
| Real-time data (FC04, 0x3100) | 24 | **18** (0x3100–0x3111) | Count > 18 returns exception 02 |
| Statistical data (FC04, 0x3300) | 32 | **20** (0x3300–0x3313) | Count > 20 returns exception 02 |
| Status (FC04, 0x3200) | 3 | **3** | Works correctly |
| Charging parameters (FC03, 0x9000) | 15 | **15** | Works correctly |
| All other FC03 blocks | — | As documented | |

### Registers confirmed unsupported on Tracer 3210A

| Address | Name | Reason |
|---------|------|--------|
| 0x3000–0x300E | Entire rated data block | Exception 02 on any FC04 read starting at 0x3000 |
| 0x3112 | Power component temperature | Beyond the 18-register real-time limit |
| 0x3314–0x3315 | CO₂ reduction | Beyond the 20-register statistics limit |
| 0x331B–0x331C | Net battery current | Same |
| 0x331D | Battery temperature (stats) | Same |
| 0x331E | Ambient temperature | Same |

### Registers requiring individual reads on Tracer 3210A

| Address | Name | Notes |
|---------|------|-------|
| 0x311A | Battery SOC | Must be read alone — including it in a block causes exception 02 |
| 0x311B | Remote battery temperature | Same |
| 0x311D | System rated voltage | Same |

Reading 0x311A–0x311D as a block fails for any unsupported address in the range, which corrupts the serial buffer and breaks subsequent reads.

### Load register addresses

The v2.5 protocol spec places load voltage at **0x310C**, load current at **0x310D**, and load power at **0x310E–310F**. This matches observed Tracer 3210A behaviour. Registers 0x3108–0x310B are skipped by the v2.5 spec and should be treated as undocumented.

### Serial timing

The 45-byte statistics response (0x3300 × 20) is sent in two bursts with a mid-frame pause while the controller reads from internal flash. A serial timeout of at least **500 ms** is required; 200 ms causes ~15 % truncation failures.

---

## Read-Only Input Registers

Function code **FC04** for all sections below.

### Rated Data — 0x3000 (⛔ unsupported on Tracer 3210A)

| Address | Name | Unit | Scale | Notes |
|---------|------|------|-------|-------|
| 0x3000 | Rated PV input voltage | V | ÷100 | |
| 0x3001 | Rated PV input current | A | ÷100 | |
| 0x3002 | Rated PV input power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x3003 | Rated PV input power (high word) | W | ÷100 | |
| 0x3004 | Rated battery voltage | V | ÷100 | |
| 0x3005 | Rated charging current | A | ÷100 | |
| 0x3006 | Rated charging power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x3007 | Rated charging power (high word) | W | ÷100 | |
| 0x3008 | Charging mode | — | — | 0x0001 = PWM |
| 0x300D | Rated load voltage | V | ÷100 | |
| 0x300E | Rated load current | A | ÷100 | |
| 0x300F | Rated load power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x3010 | Rated load power (high word) | W | ÷100 | |

### Real-Time Data — 0x3100

| Address | Name | Unit | Scale | Notes |
|---------|------|------|-------|-------|
| 0x3100 | PV array voltage | V | ÷100 | |
| 0x3101 | PV array current | A | ÷100 | |
| 0x3102 | PV array power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x3103 | PV array power (high word) | W | ÷100 | |
| 0x3104 | Battery voltage | V | ÷100 | |
| 0x3105 | Battery charging current | A | ÷100 | |
| 0x3106 | Battery charging power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x3107 | Battery charging power (high word) | W | ÷100 | |
| 0x3108–0x310B | (not documented in v2.5 spec) | — | — | Skipped in protocol; possibly unused or internal |
| 0x310C | Load voltage | V | ÷100 | Per v2.5 spec; confirmed on Tracer 3210A |
| 0x310D | Load current | A | ÷100 | Per v2.5 spec; confirmed matches measured output |
| 0x310E | Load power (low word) | W | ÷100 | 32-bit: low \| (high << 16) |
| 0x310F | Load power (high word) | W | ÷100 | |
| 0x3110 | Battery temperature | °C | ÷100 | Signed 16-bit |
| 0x3111 | Controller internal temperature | °C | ÷100 | Signed 16-bit |
| 0x3112 | Power component temperature | °C | ÷100 | ⛔ beyond Tracer 3210A block limit |
| 0x311A | Battery SOC | % | ÷1 | Read individually only |
| 0x311B | Remote battery temperature | °C | ÷100 | Signed 16-bit; read individually only |
| 0x311D | System rated voltage | V | ÷100 | Read individually only |

### Real-Time Status — 0x3200

| Address | Name | Bit field description |
|---------|------|-----------------------|
| 0x3200 | Battery status | **D3–D0**: 0=Normal, 1=Overvoltage, 2=Undervoltage, 3=Low-voltage disconnect (v2.5: "Over discharge"), 4=Fault<br>**D7–D4**: 0=Normal, 1=Over-temperature, 2=Low-temperature<br>**D8**: Battery resistance — 1=Abnormal<br>**D15**: Rated voltage mismatch — 1=Incorrect |
| 0x3201 | Charging equipment status | **D15–D14**: Input voltage — 0=Normal, 1=No power, 2=High voltage, 3=Error<br>**D13**: Charging MOSFET short<br>**D12**: Charging/anti-reverse MOSFET short<br>**D11**: Anti-reverse MOSFET short<br>**D10**: Input overcurrent<br>**D9**: Load overcurrent<br>**D8**: Load short<br>**D7**: Load MOSFET short<br>**D4**: PV input short<br>**D3–D2**: Charging phase — 0=Off, 1=Float, 2=Boost, 3=Equalization<br>**D1**: 1=Fault<br>**D0**: 1=Running |
| 0x3202 | Load on/off state (v2.5: "Discharging equipment status") | **D0**: 1=On (Running), 0=Off (Standby)<br>**D1**: 1=Fault<br>**D4**: Output over voltage<br>**D5**: Boost over voltage<br>**D6**: Short circuit (high-voltage side)<br>**D7**: Input over voltage<br>**D8**: Output voltage abnormal<br>**D9**: Unable to stop discharging<br>**D10**: Unable to discharge<br>**D11**: Short circuit<br>**D12–D13**: Output power — 0=Light, 1=Moderate, 2=Rated, 3=Overload<br>**D14–D15**: Input voltage — 0=Normal, 1=Low, 2=High, 3=No access |

### Statistical Data — 0x3300

| Address | Name | Unit | Scale | Notes |
|---------|------|------|-------|-------|
| 0x3300 | Maximum PV voltage today | V | ÷100 | Reset at midnight by controller |
| 0x3301 | Minimum PV voltage today | V | ÷100 | Reset at midnight |
| 0x3302 | Maximum battery voltage today | V | ÷100 | Reset at midnight |
| 0x3303 | Minimum battery voltage today | V | ÷100 | Reset at midnight |
| 0x3304 | Consumed energy today (low) | kWh | ÷100 | 32-bit pair; reset at midnight |
| 0x3305 | Consumed energy today (high) | kWh | ÷100 | |
| 0x3306 | Consumed energy this month (low) | kWh | ÷100 | 32-bit pair; reset 1st of month |
| 0x3307 | Consumed energy this month (high) | kWh | ÷100 | |
| 0x3308 | Consumed energy this year (low) | kWh | ÷100 | 32-bit pair; reset Jan 1 |
| 0x3309 | Consumed energy this year (high) | kWh | ÷100 | |
| 0x330A | Total consumed energy (low) | kWh | ÷100 | 32-bit pair; lifetime |
| 0x330B | Total consumed energy (high) | kWh | ÷100 | |
| 0x330C | Generated energy today (low) | kWh | ÷100 | 32-bit pair; reset at midnight |
| 0x330D | Generated energy today (high) | kWh | ÷100 | |
| 0x330E | Generated energy this month (low) | kWh | ÷100 | 32-bit pair; reset 1st of month |
| 0x330F | Generated energy this month (high) | kWh | ÷100 | |
| 0x3310 | Generated energy this year (low) | kWh | ÷100 | 32-bit pair; reset Jan 1 |
| 0x3311 | Generated energy this year (high) | kWh | ÷100 | |
| 0x3312 | Total generated energy (low) | kWh | ÷100 | 32-bit pair; lifetime |
| 0x3313 | Total generated energy (high) | kWh | ÷100 | |
| 0x3314 | CO₂ reduction (low) | t | ÷100 | ⛔ beyond Tracer 3210A block limit |
| 0x3315 | CO₂ reduction (high) | t | ÷100 | 1 kWh = 0.997 kg CO₂ |
| 0x331A | Battery voltage | V | ÷100 | ⛔ beyond Tracer 3210A block limit |
| 0x331B | Battery current (low word) | A | ÷100 | ⛔ beyond Tracer 3210A block limit; 32-bit signed |
| 0x331C | Battery current (high word) | A | ÷100 | |
| 0x331D | Battery temperature | °C | ÷100 | ⛔ beyond Tracer 3210A block limit |
| 0x331E | Ambient temperature | °C | ÷100 | ⛔ beyond Tracer 3210A block limit |

---

## Read-Write Holding Registers

Function code **FC03** to read, **FC06** (single) or **FC10** (multiple) to write.

### Battery bank

| Address | Name | Unit | Scale | Options / Range | Source |
|---------|------|------|-------|-----------------|--------|
| 0x9000 | Battery type | — | — | 0=User-defined, 1=Sealed, 2=GEL, 3=Flooded | **spec** |
| 0x9001 | Battery capacity | Ah | ÷1 | 1–9999 Ah | inferred |
| 0x9067 | Battery rated voltage | — | — | 0=Auto-detect, 1=12 V, 2=24 V, 3=36 V, 4=48 V, 5=60 V, 6=110 V, 7=120 V, 8=220 V, 9=240 V | **spec** |
| 0x9070 | Battery management mode | — | — | 0=Voltage compensation, 1=SOC | **spec** |

### Charging voltage thresholds (all voltages signed, ÷100 → V)

The thresholds must satisfy: discharging limit < LVD < LVW < LVW-reconnect < LVR < boost-reconnect < float < boost < equalize < charging limit < OVR < HVD

| Address | Name | Observed 24 V | Source |
|---------|------|--------------|--------|
| 0x9003 | High voltage disconnect | 32.00 V | observed |
| 0x9004 | Charging limit voltage | 30.00 V | observed |
| 0x9005 | Overvoltage reconnect | 30.00 V | observed |
| 0x9006 | Equalization voltage | 29.20 V | observed |
| 0x9007 | Boost / absorption voltage | 28.80 V | observed |
| 0x9008 | Float voltage | 27.60 V | observed |
| 0x9009 | Boost reconnect voltage | 26.40 V | observed |
| 0x900A | Low voltage reconnect | 25.20 V | observed |
| 0x900B | Undervoltage warning reconnect | 24.40 V | observed |
| 0x900C | Undervoltage warning | 24.00 V | observed |
| 0x900D | Low voltage disconnect | 22.20 V | observed |
| 0x900E | Discharging limit voltage | 21.20 V | observed |

No explicit min/max range is stated in the EPEVER protocol document for any voltage register. The controller enforces the ordering constraint between thresholds; writing a value that violates it may be silently rejected or clamped.

### Temperature settings (signed 16-bit registers, ÷100 → °C)

Registers 0x9017–0x901C are **signed 16-bit** integers. Reading them as unsigned produces wrong values for sub-zero setpoints (e.g. raw 0xF060 = 61536 unsigned = −4000 signed = −40.00 °C).

| Address | Name | Observed | Range | Source |
|---------|------|----------|-------|--------|
| 0x9017 | Battery temp warning high | 65.00 °C | inferred 0–100 °C | |
| 0x9018 | Battery temp warning low | −40.00 °C | inferred −50–50 °C | signed 16-bit |
| 0x9019 | Controller temp limit high | 85.00 °C | inferred 0–100 °C | |
| 0x901A | Controller temp recovery | 75.00 °C | inferred 0–100 °C | |
| 0x901B | Power component temp limit | — | inferred 0–100 °C | |
| 0x901C | Power component temp recovery | — | inferred 0–100 °C | |
| 0x9002 | Temperature compensation | 3 mV/°C/2V | **0–9** (spec) | |

### Timing

| Address | Name | Unit | Observed | Range | Source |
|---------|------|------|----------|-------|--------|
| 0x906C | Boost duration | min | 120 | typically 60–120 | **spec** |
| 0x906B | Equalization duration | min | 120 | typically 60–120 | **spec** |
| 0x9016 | Equalization cycle | days | 30 | 0=disabled | inferred |

### Sun detection

PV voltage thresholds for day/night transitions. No range is stated in the spec; observed values on a 24 V system suggest these can exceed 10 V.

| Address | Name | Unit | Scale | Observed | Source |
|---------|------|------|-------|----------|--------|
| 0x901E | Night threshold voltage (NTTV) | V | ÷100 | 10.00 V | observed |
| 0x901F | Night detection delay | min | ÷1 | 10 min | observed |
| 0x9020 | Day threshold voltage (DTTV) | V | ÷100 | 12.00 V | observed |
| 0x9021 | Day detection delay | min | ÷1 | 10 min | observed |

### Load control

| Address | Name | Unit | Options / Notes |
|---------|------|------|-----------------|
| 0x903D | Load control mode | — | 0=Manual, 1=Light ON/OFF, 2=Light ON + Timer, 3=Time Control |
| 0x906A | Default load state (manual mode) | — | 0=Off, 1=On |
| 0x9069 | Load timing control selection | — | 0=One timer, 1=Two timers |
| 0x903E | Load timer 1 duration | — | D15–D8: Hours, D7–D0: Minutes |
| 0x903F | Load timer 2 duration | — | D15–D8: Hours, D7–D0: Minutes |
| 0x9042 | Load timing 1 on (seconds) | s | |
| 0x9043 | Load timing 1 on (minutes) | min | |
| 0x9044 | Load timing 1 on (hours) | h | |
| 0x9045 | Load timing 1 off (seconds) | s | |
| 0x9046 | Load timing 1 off (minutes) | min | |
| 0x9047 | Load timing 1 off (hours) | h | |
| 0x9048 | Load timing 2 on (seconds) | s | |
| 0x9049 | Load timing 2 on (minutes) | min | |
| 0x904A | Load timing 2 on (hours) | h | |
| 0x904B | Load timing 2 off (seconds) | s | |
| 0x904C | Load timing 2 off (minutes) | min | |
| 0x904D | Load timing 2 off (hours) | h | |
| 0x9065 | Night duration | — | Total night duration |

### Other settings

| Address | Name | Unit | Scale | Options / Range | Source |
|---------|------|------|-------|-----------------|--------|
| 0x901D | Line impedance | mΩ | ÷100 | Resistance of wires | |
| 0x906D | Discharging percentage | % | ÷100 | typically 20–80 % | **spec** |
| 0x906E | Charging percentage | % | ÷100 | typically 20–100 % | **spec** |
| 0x9063 | Backlight time | s | ÷1 | Seconds until LCD backlight turns off | **spec** |

### Real-time clock

Write all three registers simultaneously (FC10) to update the clock atomically.

| Address | Name | Encoding |
|---------|------|----------|
| 0x9013 | Seconds / Minutes | D7–D0: Seconds, D15–D8: Minutes |
| 0x9014 | Hours / Day | D7–D0: Hours, D15–D8: Day |
| 0x9015 | Month / Year | D7–D0: Month, D15–D8: Year (2-digit, e.g. 26 for 2026) |

---

## Coils (Read-Write, FC01 read / FC05 write)

| Address | Name | Values |
|---------|------|--------|
| 0x0000 | Charging device on/off | 1=On, 0=Off |
| 0x0001 | Output control mode | 1=Manual, 0=Automatic — **not supported on Tracer 3210A** (returns exception 02) |
| 0x0002 | Manual load control | 1=On, 0=Off (only effective in manual mode) |
| 0x0003 | Default load control | 1=On, 0=Off (only effective in default mode) |
| 0x0005 | Load test mode | 1=Enable, 0=Normal |
| 0x0006 | Force load on/off | 1=On, 0=Off (temporary test) |
| 0x0013 | Restore system defaults | 1=Execute, 0=No |
| 0x0014 | Clear generated energy statistics | 1=Clear (root privileges required) |

## Discrete Inputs (Read-Only, FC02)

| Address | Name | Values |
|---------|------|--------|
| 0x2000 | Controller over-temperature | 1=Above protection threshold, 0=Normal |
| 0x200C | Day/Night status | 1=Night, 0=Day |

---

## RJ-45 Port Pin Definitions

| Pin | Description |
|-----|-------------|
| 1, 2 | Not connected |
| 3, 4 | RS-485 A |
| 5, 6 | RS-485 B |
| 7, 8 | Ground (connect to battery negative for noise reduction) |
