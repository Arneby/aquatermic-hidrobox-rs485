#!/usr/bin/env python3
"""
Aquatermic RS485 Timing-based Frame Detector
Hittar riktiga frame-gränser via tystnad på bussen (inter-frame gap),
inte via sync-byte. Visar paket grupperade per enhet och diff mot föregående.

Kör: ./venv/bin/python aquatermic_timing.py
Avbryt: Ctrl+C
"""

import serial
import time
import datetime
import os
import sys
import collections

PORT       = "/dev/tty.usbserial-BG01X9HJ"
BAUD       = 38400
LOG_DIR    = "logs"

# Vid 38400 bps är en byte ~260µs.
# Inter-frame gap: ≥3.5 tecken = ~910µs. Vi använder 3ms för säkerhets skull.
GAP_S      = 0.003   # 3 ms tystnad = ny frame
MIN_FRAME  = 4       # ignorera skräppaket kortare än detta

# ANSI
RED   = "\033[91m"
YEL   = "\033[93m"
GRN   = "\033[92m"
CYN   = "\033[96m"
DIM   = "\033[2m"
BOLD  = "\033[1m"
RST   = "\033[0m"


def now_str():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def hex_str(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def diff_str(curr: bytes, prev: bytes | None) -> str:
    if prev is None or len(prev) != len(curr):
        return hex_str(curr)
    parts = []
    for a, b in zip(curr, prev):
        if a != b:
            parts.append(f"{RED}{BOLD}{a:02X}{RST}")
        else:
            parts.append(f"{DIM}{a:02X}{RST}")
    return " ".join(parts)


def signature(data: bytes, n: int = 3) -> str:
    """Kort signaturnyckel för att gruppera frames per 'avsändare'."""
    return hex_str(data[:n])


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"timing_{ts}.log")

    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Aquatermic RS485 Timing-based Monitor{RST}")
    print(f"  Port: {PORT}  @  {BAUD} bps  |  gap-tröskel: {GAP_S*1000:.0f} ms")
    print(f"  Logg: {log_path}")
    print(f"  {YEL}Ctrl+C för att avsluta{RST}")
    print(f"{BOLD}{'═'*72}{RST}\n")

    logfile = open(log_path, "w", encoding="utf-8")
    logfile.write(f"Aquatermic Timing Monitor - {ts}\n")
    logfile.write(f"Port: {PORT} @ {BAUD} bps, gap={GAP_S*1000:.0f}ms\n\n")

    try:
        ser = serial.Serial(
            port=PORT, baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.001   # 1ms poll
        )
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"{RED}FEL: {e}{RST}")
        sys.exit(1)

    # Håll en dict: signatur → senaste frame (för diff per "avsändare")
    last_by_sig: dict[str, bytes] = {}
    # Räknare per signatur
    count_by_sig: dict[str, int] = collections.defaultdict(int)
    # Längdstatistik
    length_counter: collections.Counter = collections.Counter()

    # Sätt stdin i non-blocking för Enter-markörer
    import termios, tty, select
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())

    mark_nr    = 0
    frame_nr   = 0
    buf        = bytearray()
    last_byte  = time.monotonic()

    print(f"  {DIM}#     tid          len  hex (röd=ändrat vs föregående med samma prefix){RST}")
    print(f"  {YEL}Tryck Enter för att sätta en markör (MARK) i loggen{RST}\n")

    try:
        while True:
            # Kolla om användaren tryckt Enter
            if select.select([sys.stdin], [], [], 0)[0]:
                sys.stdin.read(1)
                mark_nr += 1
                ts_mark = now_str()
                mark_line = f"  {YEL}{BOLD}─── MARK {mark_nr} @ {ts_mark} ───{RST}"
                print(mark_line)
                logfile.write(f"\n--- MARK {mark_nr} @ {ts_mark} ---\n\n")
                logfile.flush()

            chunk = ser.read(128)
            now   = time.monotonic()

            # Gap detekterat?
            gap = now - last_byte
            if gap >= GAP_S and buf:
                # Spola ut buffern som en frame
                frame = bytes(buf)
                buf.clear()

                if len(frame) >= MIN_FRAME:
                    frame_nr += 1
                    sig = signature(frame)
                    prev = last_by_sig.get(sig)
                    last_by_sig[sig] = frame
                    count_by_sig[sig] += 1
                    length_counter[len(frame)] += 1

                    ts_str = now_str()
                    line   = diff_str(frame, prev)
                    changed = sum(1 for a, b in zip(frame, prev or frame)
                                  if a != b) if prev else 0
                    diff_mark = (f"  {YEL}▶ {changed} byte(s) ändrades{RST}"
                                 if changed else
                                 f"  {DIM}={RST}" if prev else
                                 f"  {GRN}(ny sig){RST}")

                    print(f"  {CYN}#{frame_nr:<4}{RST} {DIM}{ts_str}{RST} "
                          f"[{len(frame):2d}B]  {line}{diff_mark}")
                    sys.stdout.flush()

                    logfile.write(f"#{frame_nr:<4} {ts_str} [{len(frame):2d}B] "
                                  f"{hex_str(frame)}"
                                  f"  {'CHG:'+str(changed) if prev and changed else 'same' if prev else 'new'}\n")
                    logfile.flush()

            if chunk:
                last_byte = now
                buf.extend(chunk)

    except KeyboardInterrupt:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        # Spola kvarvarande buffer
        if len(buf) >= MIN_FRAME:
            frame_nr += 1
            sig  = signature(buf)
            prev = last_by_sig.get(sig)
            line = diff_str(bytes(buf), prev)
            print(f"  {CYN}#{frame_nr:<4}{RST} {DIM}{now_str()}{RST} "
                  f"[{len(buf):2d}B]  {line}  {DIM}(sista){RST}")

        print(f"\n\n{BOLD}{'─'*72}{RST}")
        print(f"  Totalt {frame_nr} frames\n")

        print(f"  {BOLD}Frame-längder som observerats:{RST}")
        for length, cnt in sorted(length_counter.items()):
            bar = "█" * min(cnt, 40)
            print(f"    {length:3d} bytes: {cnt:4d}×  {bar}")

        print(f"\n  {BOLD}Unika frame-prefix (första 3 bytes) = troliga avsändare:{RST}")
        for sig, cnt in sorted(count_by_sig.items(), key=lambda x: -x[1]):
            print(f"    [{sig}]  {cnt}× frames")

        print(f"\n  Logg: {log_path}")
        print(f"{BOLD}{'─'*72}{RST}\n")

        logfile.write(f"\n--- Avbruten ---\nTotalt: {frame_nr} frames\n")
        logfile.write("\nFrame-längder:\n")
        for length, cnt in sorted(length_counter.items()):
            logfile.write(f"  {length:3d} bytes: {cnt}x\n")
        logfile.write("\nPrefix-statistik:\n")
        for sig, cnt in sorted(count_by_sig.items(), key=lambda x: -x[1]):
            logfile.write(f"  [{sig}]: {cnt}x\n")

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
