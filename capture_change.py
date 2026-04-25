#!/usr/bin/env python3
"""
H-bus setpoint change capture
==============================
Kör i bakgrunden, sparar ALLA frames vid en setpoint-ändring.
Detekterar ändringar via XOR mot rullande baseline.

Workflow:
  1. Starta skriptet: ./venv/bin/python capture_change.py
  2. Ändra UFH-setpoint ett steg på XK57-panelen
  3. Skriptet sparar raw data + diff-analys till logs/change_*.json

Körning (non-interactive, kör tills Ctrl-C):
    ./venv/bin/python capture_change.py [--duration 120]
"""

import argparse
import collections
import datetime
import json
import os
import pathlib
import serial
import sys
import time

PORT     = "/dev/tty.usbserial-BG01X9HJ"
BAUD     = 38400
SEP      = bytes([0xb3, 0x6e])
LOG_DIR  = "logs"
BASELINE_WINDOW = 30   # sekunder för baseline-inlärning
CHANGE_WINDOW   = 10   # sekunder att spara efter detekterad ändring

def split_frames(data: bytes) -> list[bytes]:
    parts = data.split(SEP)
    return [p for p in parts if len(p) >= 8 and p[0] == 0x39]

def frame_key(p: bytes) -> str:
    return f'{p[1]:02X}_{p[2]:02X}_{len(p):03d}'

def top(lst):
    return max(set(lst), key=lst.count) if lst else None

def capture_raw(ser: serial.Serial, duration: float) -> bytes:
    data = bytearray()
    end = time.time() + duration
    while time.time() < end:
        data += ser.read(512)
    return bytes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=int, default=300,
                        help='Total körtid i sekunder (default 300)')
    parser.add_argument('--threshold', type=float, default=0.3,
                        help='Minst denna andel frames måste ändras för att utlösa (default 0.3)')
    args = parser.parse_args()

    pathlib.Path(LOG_DIR).mkdir(exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"=== H-bus setpoint change capture ===")
    print(f"Port: {PORT}, {BAUD} bps")
    print(f"Bygger baseline under {BASELINE_WINDOW}s...")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.02)
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"Portfel: {e}", file=sys.stderr)
        sys.exit(1)

    # Bygg baseline
    baseline_data = capture_raw(ser, BASELINE_WINDOW)
    baseline_frames = split_frames(baseline_data)

    # Baseline: modal byte per position per frame-typ
    baseline = {}  # key -> [modal_byte_at_pos_i, ...]
    for f in baseline_frames:
        k = frame_key(f)
        if k not in baseline:
            baseline[k] = [[] for _ in range(len(f))]
        for i, b in enumerate(f):
            if i < len(baseline[k]):
                baseline[k][i].append(b)

    baseline_modal = {}
    for k, positions in baseline.items():
        baseline_modal[k] = [top(p) for p in positions]

    print(f"Baseline: {len(baseline_frames)} frames, {len(baseline)} unika typer")
    print(f"Lyssnar nu i {args.duration}s, ändra setpointen när du vill...\n")

    # Löpande capture och jämförelse
    chunk_duration = 5.0  # sekunder per chunk
    start = time.time()
    end = start + args.duration
    change_events = []
    prev_chunk_frames = {}

    while time.time() < end:
        chunk_data = capture_raw(ser, chunk_duration)
        chunk_frames = split_frames(chunk_data)

        # Räkna ändrade positioner mot baseline
        changed_keys = collections.Counter()
        chunk_by_key = collections.defaultdict(list)
        for f in chunk_frames:
            chunk_by_key[frame_key(f)].append(f)

        for k, frames in chunk_by_key.items():
            if k not in baseline_modal:
                continue
            bm = baseline_modal[k]
            for f in frames:
                diff_count = sum(1 for i, b in enumerate(f) if i < len(bm) and bm[i] is not None and b != bm[i])
                changed_keys[k] += diff_count

        total_diffs = sum(changed_keys.values())
        total_checked = sum(len(frames) * len(baseline_modal.get(k, [])) for k, frames in chunk_by_key.items())
        change_ratio = total_diffs / max(total_checked, 1)

        elapsed = time.time() - start
        print(f"  [{elapsed:5.0f}s] frames={len(chunk_frames):4d}  diffs={total_diffs:5d}  ratio={change_ratio:.3f}", end="")

        if change_ratio > args.threshold and total_diffs > 50:
            print(f"  *** CHANGE DETECTED! ***")
            change_events.append({
                'time': elapsed,
                'ratio': change_ratio,
                'total_diffs': total_diffs,
                'changed_keys': dict(changed_keys),
                'frames': [f.hex() for f in chunk_frames],
            })
        else:
            print()

        prev_chunk_frames = chunk_by_key

    ser.close()

    # Spara resultat
    result = {
        'timestamp': ts,
        'baseline_frame_count': len(baseline_frames),
        'baseline_types': len(baseline_modal),
        'change_events': change_events,
    }

    out_path = pathlib.Path(LOG_DIR) / f"change_{ts}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(f"\nSparat {len(change_events)} change-events → {out_path}")

    if change_events:
        print("\n=== Analys av ändrade frames ===")
        for ev in change_events:
            print(f"  t={ev['time']:.0f}s: ratio={ev['ratio']:.3f}, diffs={ev['total_diffs']}")
            for k, n in sorted(ev['changed_keys'].items(), key=lambda x: -x[1])[:5]:
                print(f"    {k}: {n} diffs")


if __name__ == "__main__":
    main()
