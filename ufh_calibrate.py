#!/usr/bin/env python3
"""
UFH Setpoint Calibration Tool
==============================
Stegar igenom UFH-setpoints och bygger en lookup-tabell för
H-bus protokollavkodning.

Körning:
    ./venv/bin/python ufh_calibrate.py [--min 25] [--max 50] [--analyze-only]

Workflow:
    1. Skriptet ber dig sätta ett specifikt värde på XK57-panelen
    2. Du bekräftar med Enter
    3. Skriptet fångar 45s data och sparar
    4. Upprepa för alla värden
    5. Skriptet analyserar och skriver ut lookup-tabell + försöker avkoda encoding
"""

import argparse
import collections
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
CAL_DIR  = os.path.join(LOG_DIR, "calibration")
DURATION = 45  # sekunder per capture

RED  = "\033[91m"; YEL = "\033[93m"; GRN = "\033[92m"
CYN  = "\033[96m"; DIM = "\033[2m";  BOLD= "\033[1m"; RST = "\033[0m"

# ── Capture ──────────────────────────────────────────────────────────────────

def capture(setpoint: int) -> dict:
    """Fångar DURATION sekunder H-bus data och returnerar frame-dict."""
    path = pathlib.Path(CAL_DIR) / f"ufh_{setpoint:03d}.json"
    if path.exists():
        print(f"  {DIM}Laddar befintlig capture: {path}{RST}")
        return json.loads(path.read_text())

    print(f"  Lyssnar {DURATION}s ...", end="", flush=True)
    try:
        s = serial.Serial(PORT, BAUD, timeout=0.05)
        s.reset_input_buffer()
        data = bytearray()
        end = time.time() + DURATION
        while time.time() < end:
            data += s.read(512)
        s.close()
    except serial.SerialException as e:
        print(f"\n  {RED}Portfel: {e}{RST}")
        sys.exit(1)

    parts = [p for p in bytes(data).split(SEP) if len(p) >= 8 and p[0] == 0x39]
    result = {}
    for p in parts:
        key = f'{p[1]:02X}_{p[2]:02X}_{len(p):03d}'
        if key not in result:
            result[key] = [[] for _ in range(len(p))]
        for i, b in enumerate(p):
            result[key][i].append(b)

    pathlib.Path(CAL_DIR).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))

    n_target = 0
    for k in result:
        if k.startswith('D9_9E'):
            n_target += len(result[k][0]) if result[k] else 0

    print(f"  {GRN}klar: {len(parts)} frames ({n_target} D9_9E){RST}")
    return result

# ── Analys ───────────────────────────────────────────────────────────────────

def top(lst):
    return max(set(lst), key=lst.count) if lst else None

def find_best_frame_key(captures: dict[int, dict]) -> str:
    """Hitta den D9_9E-frame-typ som finns i flest captures och varierar mest."""
    # Samla alla D9_9E-nycklar
    key_counts = collections.Counter()
    for sp, data in captures.items():
        for k in data:
            if k.startswith('D9_9E'):
                key_counts[k] += 1

    # Preferera keys som finns i alla captures
    all_sps = len(captures)
    candidates = [k for k, cnt in key_counts.items() if cnt >= all_sps * 0.7]

    if not candidates:
        candidates = [k for k, cnt in key_counts.most_common(5)]

    # Bland kandidaterna, välj den med mest variation i data-bytes
    best_key, best_var = None, 0
    for k in candidates:
        vals_per_sp = {}
        for sp, data in captures.items():
            if k in data:
                vals_per_sp[sp] = [top(data[k][pos]) for pos in range(len(data[k]))]
        if len(vals_per_sp) < 2:
            continue
        # Räkna antal positioner som varierar
        flen = len(next(iter(vals_per_sp.values())))
        var = sum(
            1 for pos in range(flen)
            if len(set(v[pos] for v in vals_per_sp.values() if v[pos] is not None)) > 1
        )
        if var > best_var:
            best_var, best_key = var, k
    return best_key

def analyze(captures: dict[int, dict]):
    """Analyserar alla captures och skriver ut lookup-tabell."""
    setpoints = sorted(captures.keys())
    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Analys: {len(setpoints)} setpoints: {setpoints}{RST}")

    key = find_best_frame_key(captures)
    if not key:
        print(f"  {RED}Ingen lämplig D9_9E-frame hittades.{RST}")
        return
    print(f"  Analyserar frame: {key}\n")

    # Samla top-värde per position per setpoint
    matrix = {}  # sp -> [byte0, byte1, ...]
    flen = 0
    for sp in setpoints:
        d = captures[sp].get(key)
        if d:
            flen = max(flen, len(d))
            matrix[sp] = [top(d[pos]) if pos < len(d) and d[pos] else None
                          for pos in range(len(d))]

    if not matrix:
        print(f"  {RED}Ingen data för {key}{RST}")
        return

    # Identifiera intressanta positioner
    varying = []
    for pos in range(flen):
        vals = [matrix[sp][pos] for sp in setpoints if sp in matrix and pos < len(matrix[sp])]
        vals = [v for v in vals if v is not None]
        if len(set(vals)) > 1:
            varying.append(pos)

    print(f"  {len(varying)} varierande positioner: {varying}\n")

    # Skriv matris
    header = f"  {'pos':>4}  " + "  ".join(f"SP={sp:>2}" for sp in setpoints)
    print(header)
    print("  " + "─" * (len(header) - 2))

    for pos in varying:
        row = f"  [{pos:2d}]  "
        for sp in setpoints:
            v = matrix.get(sp, [None]*flen)[pos] if pos < len(matrix.get(sp, [])) else None
            row += f"  0x{v:02X} " if v is not None else "    -- "
        print(row)

    # Försök hitta singel-byte som monotont ökar/minskar med setpoint
    print(f"\n  {BOLD}Monotona positioner (bäst för enkel avkodning):{RST}")
    for pos in varying:
        vals = [(sp, matrix[sp][pos]) for sp in setpoints
                if sp in matrix and pos < len(matrix[sp]) and matrix[sp][pos] is not None]
        if len(vals) < 3:
            continue
        # Kolla monotoni (med hänsyn till wrap-around)
        nums = [v for _, v in vals]
        diffs = [nums[i+1] - nums[i] for i in range(len(nums)-1)]
        if all(d > 0 for d in diffs):
            print(f"    [{pos}] ÖKAR strikt: {' '.join(f'0x{v:02X}' for v in nums)}")
        elif all(d < 0 for d in diffs):
            print(f"    [{pos}] MINSKAR strikt: {' '.join(f'0x{v:02X}' for v in nums)}")
        elif len(set(diffs)) == 1:
            print(f"    [{pos}] KONSTANT STEG {diffs[0]}: {' '.join(f'0x{v:02X}' for v in nums)}")

    # Bygg lookup-tabell
    print(f"\n  {BOLD}Lookup-tabell (setpoint → frame-fingerprint vid varierande pos):{RST}")
    print(f"  {'SP':>4}  fingerprint ({len(varying)} bytes)")
    for sp in setpoints:
        if sp not in matrix:
            continue
        fp = bytes(matrix[sp][pos] for pos in varying if pos < len(matrix[sp]) and matrix[sp][pos] is not None)
        print(f"  {sp:>4}  {fp.hex(' ')}")

    # Exportera som Python-dict
    out = {
        "frame_key": key,
        "varying_positions": varying,
        "lookup": {
            sp: {pos: matrix[sp][pos] for pos in varying
                 if pos < len(matrix.get(sp, [])) and matrix[sp][pos] is not None}
            for sp in setpoints if sp in matrix
        }
    }
    out_path = pathlib.Path(CAL_DIR) / "ufh_lookup.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n  {GRN}Lookup sparad: {out_path}{RST}")

# ── Huvud ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="UFH Setpoint Calibration")
    parser.add_argument('--min', type=int, default=25, help='Lägsta setpoint (default: 25)')
    parser.add_argument('--max', type=int, default=50, help='Högsta setpoint (default: 50)')
    parser.add_argument('--step', type=int, default=1, help='Steg (default: 1)')
    parser.add_argument('--analyze-only', action='store_true', help='Analysera befintliga captures, fånga inget nytt')
    args = parser.parse_args()

    pathlib.Path(CAL_DIR).mkdir(parents=True, exist_ok=True)

    setpoints = list(range(args.min, args.max + 1, args.step))

    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}UFH Setpoint Calibration{RST}")
    print(f"  Setpoints att testa: {setpoints}")
    print(f"  Capture-tid per värde: {DURATION}s")
    print(f"  Data sparas i: {CAL_DIR}/")
    print(f"{BOLD}{'═'*72}{RST}\n")

    captures = {}

    # Ladda befintliga captures från logs/capture_ufhXX.json (äldre format)
    for sp in setpoints:
        old = pathlib.Path(LOG_DIR) / f"capture_ufh{sp}.json"
        if old.exists() and not (pathlib.Path(CAL_DIR) / f"ufh_{sp:03d}.json").exists():
            captures[sp] = json.loads(old.read_text())
            print(f"  {DIM}Importerade äldre capture för UFH={sp}{RST}")

    # Ladda baseline (ufh=39 heter baseline_ufh39.json)
    baseline = pathlib.Path(LOG_DIR) / "baseline_ufh39.json"
    if baseline.exists() and 39 not in captures and not (pathlib.Path(CAL_DIR) / "ufh_039.json").exists():
        captures[39] = json.loads(baseline.read_text())
        print(f"  {DIM}Importerade baseline (UFH=39){RST}")

    if args.analyze_only:
        # Ladda alla befintliga cal-captures
        for sp in setpoints:
            p = pathlib.Path(CAL_DIR) / f"ufh_{sp:03d}.json"
            if p.exists():
                captures[sp] = json.loads(p.read_text())
        analyze(captures)
        return

    # Stega igenom setpoints
    for i, sp in enumerate(setpoints):
        cal_path = pathlib.Path(CAL_DIR) / f"ufh_{sp:03d}.json"

        if sp in captures:
            print(f"  [{i+1}/{len(setpoints)}] UFH={sp} — redan inläst, hoppar över capture")
            continue

        if cal_path.exists():
            captures[sp] = json.loads(cal_path.read_text())
            print(f"  [{i+1}/{len(setpoints)}] UFH={sp} — redan fångad, laddar")
            continue

        print(f"\n{BOLD}  [{i+1}/{len(setpoints)}] Sätt UFH-setpoint till {YEL}{sp}°C{RST}{BOLD} på XK57-panelen.{RST}")
        input(f"  Tryck Enter när displayen visar {sp} ... ")
        captures[sp] = capture(sp)

    # Spara alla till cal-dir
    for sp, data in captures.items():
        p = pathlib.Path(CAL_DIR) / f"ufh_{sp:03d}.json"
        if not p.exists():
            p.write_text(json.dumps(data))

    analyze(captures)

if __name__ == "__main__":
    main()
