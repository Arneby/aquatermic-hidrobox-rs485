#!/usr/bin/env python3
"""
Aquatermic RS485 Frame Watcher
Söker aktivt efter prefixet 60 06 F8 i byteströmmen och extraherar
24-byte frames. Ignorerar allt brus däremellan.

Kör: ./venv/bin/python aquatermic_watch.py
Enter i terminalen = sätt MARK i loggen
Ctrl+C = avsluta
"""

import serial
import time
import datetime
import os
import sys
import collections
import termios
import tty
import select

PORT       = "/dev/tty.usbserial-BG01X9HJ"
BAUD       = 38400
FRAME_SIZE = 24
PREFIX     = bytes([0x60, 0x06, 0xF8])   # känd frame-start
LOG_DIR    = "logs"

# Bytes som varierar av sig själva (räknare, klocka) – ignoreras vid utskrift
NOISE_BYTES = {11, 13, 23}  # byte[11]=sekvensräknare, byte[13]=klock-blink, byte[23]=enhets-ID/typ

RED   = "\033[91m"
YEL   = "\033[93m"
GRN   = "\033[92m"
CYN   = "\033[96m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RST   = "\033[0m"


def now_str():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def diff_str(curr: bytes, prev: bytes | None) -> str:
    if prev is None:
        return " ".join(f"{b:02X}" for b in curr)
    parts = []
    changed = 0
    for i, (a, b) in enumerate(zip(curr, prev)):
        if a != b:
            parts.append(f"{RED}{BOLD}{a:02X}{RST}")
            changed += 1
        else:
            parts.append(f"{DIM}{a:02X}{RST}")
    return " ".join(parts), changed


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"watch_{ts}.log")

    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Aquatermic Frame Watcher{RST}  (prefix: {' '.join(f'{b:02X}' for b in PREFIX)})")
    print(f"  Port: {PORT}  @  {BAUD} bps")
    print(f"  Logg: {log_path}")
    print(f"  {YEL}Enter = MARK  |  Ctrl+C = avsluta{RST}")
    print(f"{BOLD}{'═'*72}{RST}\n")
    print(f"  {DIM}#      tid            bytes (röd=ändrat vs föregående frame){RST}")
    print(f"  {DIM}       [00]=60 [01]=06 [02]=F8 alltid{RST}\n")

    logfile = open(log_path, "w", encoding="utf-8")
    logfile.write(f"Aquatermic Frame Watcher - {ts}\n")
    logfile.write(f"Prefix: {' '.join(f'{b:02X}' for b in PREFIX)}  Frame: {FRAME_SIZE}B\n\n")

    # Non-blocking stdin för MARK
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    try:
        ser = serial.Serial(
            port=PORT, baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.01
        )
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"{RED}FEL: {e}{RST}")
        sys.exit(1)

    buf        = bytearray()
    prev_frame = None
    frame_nr   = 0
    mark_nr    = 0

    # Statistik
    byte_changes = [0] * FRAME_SIZE
    frame_values  = [collections.Counter() for _ in range(FRAME_SIZE)]

    try:
        while True:
            # MARK via Enter
            if select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.read(1)
                mark_nr += 1
                ts_m = now_str()
                print(f"\n  {YEL}{BOLD}─── MARK {mark_nr} @ {ts_m} ───{RST}\n")
                logfile.write(f"\n--- MARK {mark_nr} @ {ts_m} ---\n\n")
                logfile.flush()

            chunk = ser.read(256)
            if chunk:
                buf.extend(chunk)

            # Extrahera alla frames med känt prefix
            while True:
                idx = buf.find(PREFIX)
                if idx == -1:
                    # Behåll de sista 2 bytes (kan vara start på prefix)
                    buf = buf[-2:] if len(buf) >= 2 else buf
                    break
                if idx + FRAME_SIZE > len(buf):
                    # Prefix hittad men frame inte komplett än
                    buf = buf[idx:]
                    break

                frame = bytes(buf[idx:idx + FRAME_SIZE])
                buf = buf[idx + FRAME_SIZE:]

                frame_nr += 1
                ts_f = now_str()

                # Uppdatera statistik
                for i, b in enumerate(frame):
                    frame_values[i][b] += 1
                    if prev_frame and frame[i] != prev_frame[i]:
                        byte_changes[i] += 1

                # Formatera output – visa bara om något ändrats
                if prev_frame is None:
                    hex_part = " ".join(f"{b:02X}" for b in frame)
                    changed = 0
                    print(f"  {CYN}#{frame_nr:<5}{RST} {DIM}{ts_f}{RST}  {hex_part}  {GRN}(första){RST}")
                    sys.stdout.flush()
                else:
                    hex_part, changed = diff_str(frame, prev_frame)
                    signal_positions = [i for i in range(FRAME_SIZE)
                                        if prev_frame[i] != frame[i] and i not in NOISE_BYTES]
                    if signal_positions:
                        diff_info = f"  {YEL}▶ byte[{', '.join(str(i) for i in signal_positions)}]{RST}"
                        print(f"  {CYN}#{frame_nr:<5}{RST} {DIM}{ts_f}{RST}  {hex_part}{diff_info}")
                        sys.stdout.flush()
                    # Identiska frames och enbart-brus skrivs inte ut

                logfile.write(f"#{frame_nr:<5} {ts_f}  "
                              f"{' '.join(f'{b:02X}' for b in frame)}  "
                              f"{'CHG:'+','.join(str(i) for i in range(FRAME_SIZE) if prev_frame and prev_frame[i]!=frame[i]) if prev_frame and changed else 'first' if not prev_frame else 'same'}\n")
                logfile.flush()

                prev_frame = frame

    except KeyboardInterrupt:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        total = max(frame_nr - 1, 1)

        print(f"\n\n{BOLD}{'─'*72}{RST}")
        print(f"  Totalt {frame_nr} frames\n")

        print(f"  {BOLD}Byte-förändringsfrekvens (hur ofta varierar varje position):{RST}")
        for i in range(FRAME_SIZE):
            pct = byte_changes[i] / total * 100
            top = frame_values[i].most_common(3)
            top_str = "  ".join(f"0x{v:02X}({c}×)" for v, c in top)
            color = RED if pct > 10 else YEL if pct > 1 else DIM
            bar = "█" * int(pct / 2)
            print(f"  [{i:2d}]  {color}{pct:5.1f}%{RST}  {bar:<25}  {DIM}{top_str}{RST}")

        print(f"\n  Logg: {log_path}")
        print(f"{BOLD}{'─'*72}{RST}\n")

        logfile.write(f"\n--- Avbruten: {frame_nr} frames ---\n")
        logfile.write("Byte-förändringsfrekvens:\n")
        for i in range(FRAME_SIZE):
            pct = byte_changes[i] / total * 100
            top = frame_values[i].most_common(5)
            logfile.write(f"  [{i:2d}] {pct:.1f}%  "
                          f"{' '.join(f'0x{v:02X}({c})' for v, c in top)}\n")

    finally:
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except Exception:
            pass
        logfile.close()
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
