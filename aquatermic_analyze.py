#!/usr/bin/env python3
"""
Aquatermic RS485 Pattern Analyzer
Läser senaste discovery-loggen och analyserar mönster per baudrate.
"""

import serial
import time
import datetime
import os
import collections

PORT = "/dev/tty.usbserial-BG01X9HJ"
LOG_DIR = "logs"
LISTEN_SECONDS = 10

BAUDRATER_ATT_TESTA = [38400, 57600, 115200]

def hex_dump_short(data: bytes, max_bytes=64) -> str:
    snippet = data[:max_bytes]
    hex_part = " ".join(f"{b:02X}" for b in snippet)
    if len(data) > max_bytes:
        hex_part += f" ... (+{len(data)-max_bytes} bytes)"
    return hex_part

def analyze_bytes(data: bytes) -> dict:
    if not data:
        return {}
    result = {}
    counter = collections.Counter(data)
    result["vanligaste_bytes"] = [(f"0x{b:02X}", count) for b, count in counter.most_common(5)]
    null_pct = data.count(0x00) / len(data) * 100
    result["nollor_procent"] = f"{null_pct:.1f}%"
    ff_pct = data.count(0xFF) / len(data) * 100
    result["FF_procent"] = f"{ff_pct:.1f}%"
    unika = len(set(data))
    result["unika_bytevarden"] = unika
    best_period = None
    best_score = 0
    for period in range(2, 33):
        if len(data) < period * 3:
            continue
        matches = 0
        total = 0
        for i in range(period, len(data) - period):
            if data[i] == data[i - period]:
                matches += 1
            total += 1
        score = matches / total if total > 0 else 0
        if score > best_score:
            best_score = score
            best_period = period
    result["trolig_frame_storlek"] = best_period
    result["repetitions_score"] = f"{best_score:.2f} (1.0=perfekt upprepning)"
    return result

def log(msg: str, logfile):
    print(msg)
    logfile.write(msg + "\n")
    logfile.flush()

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"analyze_{timestamp}.log")

    print(f"\n{'='*60}")
    print(f"  Aquatermic RS485 Pattern Analyzer")
    print(f"  Port: {PORT}")
    print(f"  Lyssnar {LISTEN_SECONDS}s per baudrate")
    print(f"  Testar: {BAUDRATER_ATT_TESTA}")
    print(f"{'='*60}\n")

    with open(log_path, "w") as logfile:
        log(f"Aquatermic Pattern Analyzer - {timestamp}\n", logfile)

        for baud in BAUDRATER_ATT_TESTA:
            log(f"{'='*60}", logfile)
            log(f"BAUDRATE: {baud} bps", logfile)
            log(f"{'='*60}", logfile)

            try:
                ser = serial.Serial(
                    port=PORT,
                    baudrate=baud,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=1
                )
                ser.reset_input_buffer()

                received = bytearray()
                start = time.time()

                while time.time() - start < LISTEN_SECONDS:
                    chunk = ser.read(256)
                    if chunk:
                        received.extend(chunk)

                ser.close()

                data = bytes(received)
                log(f"Mottagna bytes: {len(data)}", logfile)
                log(f"Första 64 bytes: {hex_dump_short(data)}", logfile)

                if len(data) >= 10:
                    analysis = analyze_bytes(data)
                    log(f"\nAnalys:", logfile)
                    for key, val in analysis.items():
                        log(f"  {key}: {val}", logfile)
                else:
                    log("  För lite data för analys.", logfile)

            except serial.SerialException as e:
                log(f"FEL: {e}", logfile)

            log("", logfile)
            time.sleep(1)

        log(f"\nLogg sparad: {log_path}", logfile)
        print(f"\n➡️  Klistra in innehållet i analyze_*.log till Claude för analys!")

if __name__ == "__main__":
    main()
