# Aquatermic Hidrobox RS485 Protocol Reverse Engineering

Reverse engineering of the RS485 communication protocol in an **Aquatermic Hidrobox 16 Multi-Hybrid** HVAC system, with the goal of integrating it with Home Assistant.

## Hardware

| Component | Details |
|-----------|---------|
| HVAC unit | Aquatermic Hidrobox 16 Multi-Hybrid |
| Master panel | XK57 (built into Hidrobox) |
| Zone panels | XK46 × 2 (wall-mounted, floors 1 & 2) |
| USB adapter | Waveshare Industrial USB to RS485 (FT232RL) |
| Port | `/dev/tty.usbserial-BG01X9HJ` |
| Wiring | A+ → D0, B- → D1, GND → cable shield |

## Confirmed Protocol Parameters

- **Baudrate:** 38400 bps
- **Format:** 8N1
- **Bus:** RS485 half-duplex
- **Frame size:** 24 bytes
- **Frame prefix:** `60 06 F8` (bytes 0–2, always constant)
- **Cycle:** ~430 ms (≈2.3 Hz), frames come in request/response pairs ~20 ms apart

## Frame Structure

```
Byte  Value       Status      Notes
────────────────────────────────────────────────────────
[0]   0x60        Fixed       Frame sync / prefix start
[1]   0x06        Fixed       Prefix
[2]   0xF8        Fixed       Prefix
[3]   0x60        Fixed       Header
[4]   0xFE        Fixed       Header
[5]   0x00        Fixed       Header
[6]   0x06        Fixed       Header
[7]   0x78        Fixed       Header
[8]   0x66        Fixed       Header
[9]   0x18        Fixed       Header
[10]  0x60        Fixed       Header
[11]  0x61/0x63   Noise       Sequence counter (2-bit)
[12]  0x43        ~Fixed      Rarely changes, unknown
[13]  0x70/0xF0   Noise       Clock colon blink (~1 Hz, bit 7 toggles)
[14]  varies      Status?     Possible setpoint encoding (0x33 = 51 = VVB setpoint?)
[15]  varies      Status      Mode/page indicator (0x00, 0x06, 0x18, 0x66, 0x86, 0x98)
[16]  varies      Display     LCD segment data
[17]  varies      Display     LCD segment data
[18]  varies      Display     LCD segment data
[19]  varies      Display     LCD segment data
[20]  varies      Display     LCD segment data
[21]  varies      Display     LCD segment data
[22]  varies      Display     LCD segment data (0x66 = digit "4" observed)
[23]  0x60/0x7E   Protocol    Device identifier (alternates between two devices)
```

## What the XK57 Display Shows

The XK57 has a monochrome segment LCD (white/blue on black) showing:

| Element | Notes |
|---------|-------|
| VVB on/off indicator | Hot water heater status |
| UFH on/off indicator | Underfloor heating status |
| Temperature (actual) | Tank temp (VVB) or loop temp (UFH) |
| Temperature (setpoint) | Shown briefly when pressing ▲/▼ or switching mode |
| Mode indicator | "Auto" for VVB, "Keep" for UFH |
| System clock | HH:MM |
| Water level | 5-segment bar (max 3 segments observed = ~60%) |

**Observed temperatures during testing:**
- VVB actual: 49°C, setpoint: 51°C
- UFH actual: 40°C, setpoint: 35°C

## Key Findings

### Frame detection
Initial attempts to find frames by gap timing (inter-frame silence) failed because 0x60 appears multiple times within frames, causing misalignment. Solution: search for the unique 3-byte prefix `60 06 F8` directly in the byte stream.

### Request/Response pairs
Frames arrive in pairs approximately 20 ms apart, then ~430 ms silence. Byte[23] alternates between 0x60 and 0x7E – likely a device identifier distinguishing the Hidrobox from the XK57.

### Byte[15] – mode/state indicator
Observed to change in response to button presses with values:
`0x00`, `0x06`, `0x18`, `0x66`, `0x86`, `0x98`

### Bytes[16–22] – LCD display data
These 7 bytes change every ~430 ms cycle and contain live LCD segment data. `0x66` (= digit "4" in standard 7-segment LSB encoding) confirmed at byte[22] correlating with the tens digit of UFH temperature (40°C).

### Still to decode
- Exact mapping of bytes[16–22] to display elements (temperature digits, clock, water level, mode text)
- Full meaning of byte[14] and byte[15] values
- Setpoint vs actual temperature encoding
- Write commands (sending data back to control the system)

## XK57 Button Layout

```
┌─────────────────┬──────────┬────────┬────────┐
│  ENTER/CANCEL   │  TIMER   │   ▲    │  MODE  │
├─────────────────┼──────────┼────────┼────────┤
│    FUNCTION     │ WAT/AC/FL│   ▼    │ ON/OFF │
└─────────────────┴──────────┴────────┴────────┘
```

- **WATER/AC/FLOOR** – cycles between subsystems (VVB/UFH; AC is locked/inactive)
- **ON/OFF** – toggles VVB or UFH on/off depending on active selection
- **▲ / ▼** – adjusts temperature setpoint (briefly shows setpoint, then reverts to actual)
- **MODE** – changes operating mode (Auto / Keep)
- **TIMER** – timer settings for VVB / UFH
- **FUNCTION** – unknown, possibly parameter selection

## Scripts

| Script | Purpose |
|--------|---------|
| `aquatermic_watch.py` | **Main tool.** Real-time frame monitor. Searches for `60 06 F8` prefix, shows only changed frames. Press Enter to insert MARK timestamp. |
| `aquatermic_guided.py` | Interactive guided button test (requires terminal with tty) |
| `aquatermic_timing.py` | Gap-based frame detector (superseded by watch.py) |
| `aquatermic_monitor.py` | Earlier monitor based on gap detection |
| `aquatermic_frames.py` | Batch frame analyzer |
| `aquatermic_analyze.py` | Baudrate pattern analyzer |
| `aquatermic_decode.py` | Manchester/NRZI/oversampling decoder tests |
| `aquatermic_shift7.py` | 7-bit shift decoder test |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install pyserial

# Run main monitor
python aquatermic_watch.py
```

## Next Steps

1. **Decode LCD bytes** – press ▲ while monitoring to capture setpoint display (51/35) vs actual (49/40) and map 7-segment values
2. **Map byte[15]** – systematic WATER/AC/FLOOR cycling to confirm mode encoding
3. **Identify clock bytes** – wait for minute rollover and find which bytes change
4. **Water level segments** – identify the 5 bits controlling the level indicator
5. **Write protocol** – determine if/how to send commands back to Hidrobox for HA control

## Goal

Home Assistant integration via a custom component or ESPHome bridge that can:
- Read VVB and UFH temperatures (actual + setpoint)
- Read on/off status for VVB and UFH
- Read current mode (Auto/Keep)
- Optionally: control setpoints and on/off state
