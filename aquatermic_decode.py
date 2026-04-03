#!/usr/bin/env python3
"""
Aquatermic RS485 Decoder
Testar Manchester, NRZI, 4x-oversampling och bitförskjutning.
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

def hex_row(data: bytes, offset: int = 0, width: int = 16) -> str:
    hex_part = " ".join(f"{b:02X}" for b in data)
    ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in data)
    return f"  {offset:04X}  {hex_part:<{width*3}}  {ascii_part}"

def to_bits(data: bytes) -> list:
    """Konverterar bytes till lista av bitar (MSB först)."""
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits

def bits_to_bytes(bits: list) -> bytes:
    """Konverterar lista av bitar till bytes."""
    result = []
    for i in range(0, len(bits) - 7, 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        result.append(byte)
    return bytes(result)

def decode_manchester(bits: list, polarity: int = 0) -> bytes:
    """
    Manchester-avkodning.
    Varje databit = 2 råbitar.
    polarity=0: 01→1, 10→0
    polarity=1: 01→0, 10→1
    """
    decoded = []
    i = 0
    errors = 0
    while i < len(bits) - 1:
        pair = (bits[i], bits[i+1])
        if pair == (0, 1):
            decoded.append(1 if polarity == 0 else 0)
        elif pair == (1, 0):
            decoded.append(0 if polarity == 0 else 1)
        else:
            # Ogiltig Manchester-kombination (00 eller 11)
            errors += 1
            decoded.append(0)
        i += 2
    return bits_to_bytes(decoded), errors

def decode_nrzi(bits: list) -> bytes:
    """
    NRZI-avkodning.
    Transition → 1, ingen transition → 0.
    """
    decoded = []
    prev = bits[0] if bits else 0
    for bit in bits[1:]:
        decoded.append(1 if bit != prev else 0)
        prev = bit
    return bits_to_bytes(decoded)

def decode_oversampling(bits: list, factor: int = 4) -> bytes:
    """
    Oversampling-avkodning.
    Majoritetsröstning över 'factor' bitar → 1 databit.
    """
    decoded = []
    for i in range(0, len(bits) - factor + 1, factor):
        chunk = bits[i:i+factor]
        majority = 1 if sum(chunk) > factor // 2 else 0
        decoded.append(majority)
    return bits_to_bytes(decoded)

def decode_bitshift(data: bytes, shift: int) -> bytes:
    """Förskjuter bitströmmen med 'shift' bitar."""
    bits = to_bits(data)
    shifted = bits[shift:]
    return bits_to_bytes(shifted)

def score_data(data: bytes) -> dict:
    """Betygsätter data – hur 'meningsfull' är den?"""
    if not data:
        return {"score": 0}
    
    counter = collections.Counter(data)
    unique = len(counter)
    
    # Andel printable ASCII
    printable = sum(1 for b in data if 32 <= b < 127)
    printable_pct = printable / len(data) * 100
    
    # Vanligaste byte-dominans (hög = brus eller ren idle)
    most_common_pct = counter.most_common(1)[0][1] / len(data) * 100
    
    # Entropi-liknande mått (fler unika värden = mer data)
    entropy_score = min(unique / 50, 1.0)
    
    return {
        "unika_värden": unique,
        "printable_ascii": f"{printable_pct:.1f}%",
        "dominant_byte": f"{most_common_pct:.1f}%",
        "entropy_score": f"{entropy_score:.2f}"
    }

def show_sample(data: bytes, label: str, logfile, n: int = 32):
    log(f"\n  [{label}] Första {n} bytes:", logfile)
    if len(data) >= 16:
        for i in range(0, min(n, len(data)), 16):
            log(hex_row(data[i:i+16], i), logfile)
    scores = score_data(data)
    log(f"  Analys: {scores}", logfile)

def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"decode_{timestamp}.log")

    print(f"\n{'='*60}")
    print(f"  Aquatermic Decoder")
    print(f"  Port: {PORT} @ {BAUD} bps")
    print(f"  Lyssnar {LISTEN_SECONDS} sekunder...")
    print(f"{'='*60}\n")

    with open(log_path, "w") as logfile:
        log(f"Aquatermic Decoder - {timestamp}\n", logfile)

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

        bits = to_bits(raw)
        log(f"Totalt {len(bits)} bitar att avkoda\n", logfile)

        # ── Test 1: Rådata som referens ───────────────────────────────────
        log(f"{'─'*50}", logfile)
        log("TEST 0: RÅDATA (referens)", logfile)
        show_sample(raw, "rådata", logfile)

        # ── Test 2: Manchester polarity 0 ─────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 1: MANCHESTER (01→1, 10→0)", logfile)
        manchester0, errors0 = decode_manchester(bits, polarity=0)
        log(f"  Avkodningsfel: {errors0} av {len(bits)//2} par ({errors0/(len(bits)//2)*100:.1f}%)", logfile)
        show_sample(manchester0, "manchester-0", logfile)

        # ── Test 3: Manchester polarity 1 ─────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 2: MANCHESTER INVERTERAD (01→0, 10→1)", logfile)
        manchester1, errors1 = decode_manchester(bits, polarity=1)
        log(f"  Avkodningsfel: {errors1} av {len(bits)//2} par ({errors1/(len(bits)//2)*100:.1f}%)", logfile)
        show_sample(manchester1, "manchester-1", logfile)

        # ── Test 4: NRZI ──────────────────────────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 3: NRZI", logfile)
        nrzi = decode_nrzi(bits)
        show_sample(nrzi, "nrzi", logfile)

        # ── Test 5: 2x oversampling (verklig baudrate 19200) ──────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 4: 2x OVERSAMPLING (→ 19200 bps verklig)", logfile)
        os2 = decode_oversampling(bits, factor=2)
        show_sample(os2, "2x-oversample", logfile)

        # ── Test 6: 4x oversampling (verklig baudrate 9600) ───────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 5: 4x OVERSAMPLING (→ 9600 bps verklig)", logfile)
        os4 = decode_oversampling(bits, factor=4)
        show_sample(os4, "4x-oversample", logfile)

        # ── Test 7: Bitförskjutning 1-7 bitar ────────────────────────────
        log(f"\n{'─'*50}", logfile)
        log("TEST 6: BITFÖRSKJUTNING (1-7 bitar)", logfile)
        for shift in range(1, 8):
            shifted = decode_bitshift(raw, shift)
            scores = score_data(shifted)
            log(f"  Shift {shift}: unika={scores['unika_värden']} "
                f"printable={scores['printable_ascii']} "
                f"dominant={scores['dominant_byte']}", logfile)

        log(f"\n{'='*60}", logfile)
        log("SAMMANFATTNING", logfile)
        log(f"{'='*60}", logfile)
        log("Jämför 'entropy_score' och 'printable_ascii' ovan.", logfile)
        log("Högre entropy_score + mer printable = troligare rätt avkodning.", logfile)
        log(f"\nLogg sparad: {log_path}", logfile)
        print(f"\n➡️  Klistra in loggen till Claude!")

if __name__ == "__main__":
    main()
