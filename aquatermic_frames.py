#!/usr/bin/env python3
"""
Aquatermic RS485 Frame Analyzer - 38400 bps
Lyssnar länge och försöker identifiera frame-struktur.
"""

import serial
import time
import datetime
import os
import collections

PORT = "/dev/tty.usbserial-BG01X9HJ"
BAUD = 38400
LOG_DIR = "logs"
LISTEN_SECONDS = 30

def log(msg: str, logfile):
    print(msg)
    logfile.write(msg + "\n")
    logfile.flush()

def hex_row(data: bytes, offset: int = 0) -> str:
    hex_part = " ".join(f"{b:02X}" for b in data)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"  {offset:04X}  {hex_part:<48}  {ascii_part}"

def find_frames(data: bytes, frame_size: int = 24) -> list:
    frames = []
    i = 0
    while i < len(data) - frame_size:
        if data[i] == 0x60:
            frame = data[i:i+frame_size]
            frames.append((i, frame))
            i += frame_size
        else:
            i += 1
    return frames

def compare_frames(frames: list) -> dict:
    if len(frames) < 2:
        return {}
    frame_data = [f for _, f in frames]
    frame_len = len(frame_data[0])
    varying = {}
    stable = {}
    for pos in range(frame_len):
        values = set(f[pos] for f in frame_data if pos < len(f))
        if len(values) > 1:
            varying[pos] = sorted(values)
        else:
            stable[pos] = list(values)[0]
    return {"varying": varying, "stable": stable}

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"frames_{timestamp}.log")

    print(f"\n{'='*60}")
    print(f"  Aquatermic Frame Analyzer")
    print(f"  Port: {PORT} @ {BAUD} bps")
    print(f"  Lyssnar {LISTEN_SECONDS} sekunder...")
    print(f"{'='*60}\n")

    with open(log_path, "w") as logfile:
        log(f"Aquatermic Frame Analyzer - {timestamp}", logfile)
        log(f"Port: {PORT} @ {BAUD} bps\n", logfile)

        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        ser.reset_input_buffer()

        received = bytearray()
        start = time.time()
        last_print = start

        while time.time() - start < LISTEN_SECONDS:
            chunk = ser.read(256)
            if chunk:
                received.extend(chunk)
            if time.time() - last_print > 5:
                print(f"  ... {len(received)} bytes mottagna ({int(time.time()-start)}s)")
                last_print = time.time()

        ser.close()
        data = bytes(received)
        log(f"Totalt mottagna bytes: {len(data)}\n", logfile)

        log("BYTEFREKVENS (topp 10):", logfile)
        counter = collections.Counter(data)
        for byte_val, count in counter.most_common(10):
            bar = "█" * int(count / len(data) * 50)
            log(f"  0x{byte_val:02X}  {count:5d} ({count/len(data)*100:5.1f}%)  {bar}", logfile)

        log(f"\nFRAME-ANALYS (letar frames startande med 0x60):", logfile)

        for frame_size in [24, 25, 26, 16, 20, 32]:
            frames = find_frames(data, frame_size)
            if len(frames) > 5:
                log(f"\n  Frame-storlek {frame_size} bytes → {len(frames)} frames hittade", logfile)

                log(f"\n  Första 5 frames:", logfile)
                for i, (offset, frame) in enumerate(frames[:5]):
                    log(f"  Frame {i+1} @ offset {offset}:", logfile)
                    log(hex_row(frame, offset), logfile)

                comparison = compare_frames(frames[:50])
                if comparison:
                    log(f"\n  STABILA bytes (samma i alla frames):", logfile)
                    stable = comparison.get("stable", {})
                    stable_str = " ".join(f"[{pos}]=0x{val:02X}" for pos, val in sorted(stable.items()))
                    log(f"  {stable_str}", logfile)

                    log(f"\n  VARIERANDE bytes (skiljer sig mellan frames):", logfile)
                    varying = comparison.get("varying", {})
                    for pos, vals in sorted(varying.items()):
                        vals_str = " ".join(f"0x{v:02X}" for v in vals[:8])
                        log(f"  Byte[{pos:2d}]: {vals_str}", logfile)

                break

        log(f"\nRÅDATA - Första 200 bytes:", logfile)
        for i in range(0, min(200, len(data)), 16):
            log(hex_row(data[i:i+16], i), logfile)

        log(f"\nLogg sparad: {log_path}", logfile)
        print(f"\n➡️  Klistra in {log_path} innehåll till Claude!")

if __name__ == "__main__":
    main()
