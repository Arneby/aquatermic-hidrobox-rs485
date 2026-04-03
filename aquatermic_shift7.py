#!/usr/bin/env python3
"""
Aquatermic Shift-7 Decoder
Vi vet att data är 1 bit förskjuten. Detta skriptet korrigerar det.
"""

import serial
import time
import datetime
import os
import collections

PORT = "/dev/tty.usbserial-BG01X9HJ"
BAUD = 38400
LOG_DIR = "logs"
LISTEN_SECONDS = 15

def log(msg: str, logfile):
    print(msg)
    logfile.write(msg + "\n")
    logfile.flush()

def hex_row(data: bytes, offset: int = 0) -> str:
    hex_part = " ".join(f"{b:02X}" for b in data)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"  {offset:04X}  {hex_part:<48}  {ascii_part}"

def to_bits(data: bytes) -> list:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits

def bits_to_bytes(bits: list) -> bytes:
    result = []
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        result.append(byte)
    return bytes(result)

def apply_shift(data: bytes, shift: int) -> bytes:
    bits = to_bits(data)
    return bits_to_bytes(bits[shift:])

def find_repeating_pattern(data: bytes, min_len: int = 4, max_len: int = 64) -> tuple:
    """Letar efter längsta upprepande sekvens."""
    best_period = 0
    best_score = 0
    for period in range(min_len, min(max_len, len(data) // 3)):
        matches = sum(1 for i in range(period, len(data)) if data[i] == data[i - period])
        score = matches / (len(data) - period)
        if score > best_score:
            best_score = score
            best_period = period
    return best_period, best_score

def find_frame_boundaries(data: bytes, frame_size: int) -> list:
    """Försöker hitta frames med känd storlek."""
    frames = []
    # Hitta synkpunkt – leta efter upprepande byte på position 0
    candidates = collections.Counter(data[i] for i in range(0, min(1000, len(data)), frame_size))
    if not candidates:
        return frames
    sync_byte = candidates.most_common(1)[0][0]
    
    # Hitta första förekomsten
    start = -1
    for i in range(len(data) - frame_size):
        if data[i] == sync_byte and data[i + frame_size] == sync_byte:
            start = i
            break
    
    if start == -1:
        return frames
    
    i = start
    while i + frame_size <= len(data):
        frames.append(data[i:i+frame_size])
        i += frame_size
    
    return frames, sync_byte

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"shift7_{timestamp}.log")

    print(f"\n{'='*60}")
    print(f"  Aquatermic Shift-7 Decoder")
    print(f"  Port: {PORT} @ {BAUD} bps")
    print(f"  Lyssnar {LISTEN_SECONDS} sekunder...")
    print(f"{'='*60}\n")

    with open(log_path, "w") as logfile:
        log(f"Aquatermic Shift-7 Decoder - {timestamp}\n", logfile)

        # ── Samla rådata ──────────────────────────────────────────────────
        ser = serial.Serial(
            port=PORT, baudrate=BAUD,
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
        raw = bytes(received)
        log(f"Rådata: {len(raw)} bytes\n", logfile)

        # ── Applicera shift 7 ─────────────────────────────────────────────
        shifted = apply_shift(raw, 7)
        log(f"{'─'*50}", logfile)
        log("SHIFT-7 KORRIGERAD DATA:", logfile)
        log(f"Bytes: {len(shifted)}\n", logfile)

        log("Första 128 bytes:", logfile)
        for i in range(0, min(128, len(shifted)), 16):
            log(hex_row(shifted[i:i+16], i), logfile)

        # ── Frekvensanalys av shiftad data ────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("BYTEFREKVENS efter shift-7 (topp 15):", logfile)
        counter = collections.Counter(shifted)
        for byte_val, count in counter.most_common(15):
            bar = "█" * int(count / len(shifted) * 60)
            log(f"  0x{byte_val:02X} ({byte_val:3d})  {count:5d} ({count/len(shifted)*100:5.1f}%)  {bar}", logfile)

        # ── Hitta upprepande mönster ──────────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("MÖNSTERANALYS:", logfile)
        period, score = find_repeating_pattern(shifted)
        log(f"  Trolig frame-storlek: {period} bytes", logfile)
        log(f"  Upprepnings-score: {score:.3f} (1.0 = perfekt)", logfile)

        # ── Försök extrahera frames ───────────────────────────────────────
        if period > 0:
            log(f"\n{'─'*50}", logfile)
            log(f"FRAME-EXTRAKTION (period={period}):", logfile)

            result = find_frame_boundaries(shifted, period)
            if isinstance(result, tuple) and len(result) == 2:
                frames, sync_byte = result
                log(f"  Synkbyte: 0x{sync_byte:02X}", logfile)
                log(f"  Antal frames: {len(frames)}", logfile)

                if frames:
                    log(f"\n  Första 10 frames:", logfile)
                    for i, frame in enumerate(frames[:10]):
                        log(f"  Frame {i+1:2d}: {' '.join(f'{b:02X}' for b in frame)}", logfile)

                    # Stabila vs varierande bytes
                    log(f"\n  Byte-analys per position:", logfile)
                    for pos in range(min(period, 32)):
                        vals = [f[pos] for f in frames if pos < len(f)]
                        unique_vals = set(vals)
                        if len(unique_vals) == 1:
                            log(f"  [{pos:2d}] STABIL  0x{list(unique_vals)[0]:02X}", logfile)
                        else:
                            sample = sorted(unique_vals)[:6]
                            log(f"  [{pos:2d}] varierar: {' '.join(f'0x{v:02X}' for v in sample)}", logfile)

        # ── Parity/stopbit-kontroll ───────────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("PARITY-TEST (testar Even/Odd parity):", logfile)
        for parity_name, parity in [("NONE", serial.PARITY_NONE),
                                     ("EVEN", serial.PARITY_EVEN),
                                     ("ODD", serial.PARITY_ODD)]:
            log(f"  {parity_name}: (körs i nästa steg om shift-7 ger struktur)", logfile)

        log(f"\nLogg sparad: {log_path}", logfile)
        print(f"\n➡️  Klistra in loggen till Claude!")

if __name__ == "__main__":
    main()
