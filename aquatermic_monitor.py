#!/usr/bin/env python3
"""
Aquatermic RS485 Real-time Monitor
Visar frames löpande med tidsstämpel och markerar ändrade bytes.
Kör: ./venv/bin/python aquatermic_monitor.py
Avbryt: Ctrl+C
"""

import serial
import time
import datetime
import os
import sys

PORT = "/dev/tty.usbserial-BG01X9HJ"
BAUD = 38400
FRAME_SIZE = 24
FRAME_SYNC = 0x60
LOG_DIR = "logs"

# ANSI-färger
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# Inter-frame timeout: ~5× bytetime @ 38400 = ~1.3ms, vi använder 10ms
INTER_FRAME_MS = 0.010


def now_str() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def format_frame_diff(frame: bytes, prev: bytes | None) -> str:
    """Formaterar en frame med färgmarkering av ändrade bytes."""
    parts = []
    changed_positions = []

    for i, b in enumerate(frame):
        if prev is None or i >= len(prev):
            parts.append(f"{b:02X}")
        elif b != prev[i]:
            parts.append(f"{RED}{BOLD}{b:02X}{RESET}")
            changed_positions.append(i)
        else:
            parts.append(f"{DIM}{b:02X}{RESET}")

    hex_str = " ".join(parts)

    if changed_positions:
        diff_info = f"  {YELLOW}▶ byte[{', '.join(str(p) for p in changed_positions)}] ändrades{RESET}"
    elif prev is None:
        diff_info = f"  {GREEN}(första frame){RESET}"
    else:
        diff_info = f"  {DIM}(oförändrad){RESET}"

    return hex_str + diff_info


def format_frame_diff_log(frame: bytes, prev: bytes | None) -> str:
    """Logg-version utan ANSI-koder."""
    hex_str = " ".join(f"{b:02X}" for b in frame)
    if prev is None:
        diff_info = "(första frame)"
    else:
        changed = [i for i, (a, b) in enumerate(zip(frame, prev)) if a != b]
        if changed:
            diff_info = f"ÄNDRAT byte[{', '.join(str(p) for p in changed)}]"
        else:
            diff_info = "(oförändrad)"
    return f"{hex_str}  {diff_info}"


def extract_frames_from_buffer(buf: bytearray) -> tuple[list[bytes], bytearray]:
    """
    Extraherar kompletta 24-byte frames som börjar med FRAME_SYNC.
    Returnerar (frames, kvarvarande_buffer).
    """
    frames = []
    i = 0
    while i < len(buf):
        # Hitta sync-byte
        if buf[i] != FRAME_SYNC:
            i += 1
            continue
        # Kontrollera att vi har tillräckligt med bytes
        if i + FRAME_SIZE > len(buf):
            break
        frame = bytes(buf[i:i + FRAME_SIZE])
        frames.append(frame)
        i += FRAME_SIZE

    # Kvarvarande data = allt från senaste ofullständiga frame
    remainder = buf[i:]
    return frames, remainder


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"monitor_{timestamp}.log")

    print(f"\n{BOLD}{'═'*72}{RESET}")
    print(f"  {CYAN}{BOLD}Aquatermic RS485 Real-time Monitor{RESET}")
    print(f"  Port: {PORT}  @  {BAUD} bps  8N1")
    print(f"  Frame-storlek: {FRAME_SIZE} bytes  |  Sync: 0x{FRAME_SYNC:02X}")
    print(f"  Logg: {log_path}")
    print(f"  {YELLOW}Tryck Ctrl+C för att avsluta{RESET}")
    print(f"{BOLD}{'═'*72}{RESET}")
    print(f"\n  {DIM}#frame  tid          frame-data (röd=ändrad, grå=oförändrad){RESET}\n")

    logfile = open(log_path, "w", encoding="utf-8")
    logfile.write(f"Aquatermic RS485 Monitor - {timestamp}\n")
    logfile.write(f"Port: {PORT} @ {BAUD} bps 8N1\n")
    logfile.write(f"Format: #nr  tid  hex-data  diff-info\n\n")

    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05   # 50ms läs-timeout för responsivitet
        )
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"{RED}FEL: Kan inte öppna {PORT}: {e}{RESET}")
        sys.exit(1)

    buf = bytearray()
    prev_frame: bytes | None = None
    frame_count = 0
    total_bytes = 0
    last_rx_time = time.monotonic()

    # Statistik för byte-variationer
    byte_change_count = [0] * FRAME_SIZE

    try:
        while True:
            chunk = ser.read(256)
            now = time.monotonic()

            if chunk:
                # Om det gått mer än INTER_FRAME_MS sedan senaste byte →
                # sannolik frame-gräns, rensa buffern om den är skräpig
                if now - last_rx_time > INTER_FRAME_MS and len(buf) > 0:
                    # Synka om nödvändigt – kasta bytes tills vi hittar sync
                    sync_pos = buf.find(FRAME_SYNC)
                    if sync_pos > 0:
                        buf = buf[sync_pos:]
                last_rx_time = now
                buf.extend(chunk)
                total_bytes += len(chunk)

            # Extrahera alla kompletta frames
            frames, buf = extract_frames_from_buffer(buf)

            for frame in frames:
                frame_count += 1
                ts = now_str()

                # Räkna byte-förändringar för statistik
                if prev_frame and len(prev_frame) == FRAME_SIZE:
                    for i in range(FRAME_SIZE):
                        if frame[i] != prev_frame[i]:
                            byte_change_count[i] += 1

                # Terminal-output
                diff_line = format_frame_diff(frame, prev_frame)
                print(f"  {CYAN}#{frame_count:<5}{RESET} {DIM}{ts}{RESET}  {diff_line}")
                sys.stdout.flush()

                # Logg utan ANSI
                log_line = format_frame_diff_log(frame, prev_frame)
                logfile.write(f"#{frame_count:<5} {ts}  {log_line}\n")
                logfile.flush()

                prev_frame = frame

    except KeyboardInterrupt:
        print(f"\n\n{BOLD}{'─'*72}{RESET}")
        print(f"  Avbruten. Totalt: {frame_count} frames, {total_bytes} bytes\n")

        if frame_count > 1:
            print(f"  {BOLD}Byte-förändringsfrekvens per position:{RESET}")
            for i in range(FRAME_SIZE):
                pct = byte_change_count[i] / max(frame_count - 1, 1) * 100
                bar = "█" * int(pct / 2)
                marker = f"{RED}{BOLD}" if pct > 5 else DIM
                print(f"  [{i:2d}]  {marker}{pct:5.1f}%  {bar}{RESET}")

        print(f"\n  Logg sparad: {log_path}")
        print(f"{BOLD}{'─'*72}{RESET}\n")

        logfile.write(f"\n--- Avbruten ---\n")
        logfile.write(f"Totalt: {frame_count} frames, {total_bytes} bytes\n")
        logfile.write(f"\nByte-förändringsfrekvens:\n")
        for i in range(FRAME_SIZE):
            pct = byte_change_count[i] / max(frame_count - 1, 1) * 100
            logfile.write(f"  [{i:2d}]  {pct:.1f}%\n")

    finally:
        logfile.close()
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
