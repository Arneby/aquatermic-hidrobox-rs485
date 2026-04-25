#!/usr/bin/env python3
"""
H-bus live diff monitor
========================
Visar ENBART CF_33-frames (från XK57) och visar när bytes ändras.
Filtrerar bort känd colon-blink.
Ändra setpointen och se vilka bytes som lyser rött.

Körning:
    ./venv/bin/python live_diff.py [--all-frames]
"""

import argparse
import serial
import sys
import time

PORT = "/dev/tty.usbserial-BG01X9HJ"
BAUD = 38400
SEP  = bytes([0xb3, 0x6e])

RED  = "\033[91m"; GRN = "\033[92m"; YEL = "\033[93m"
CYN  = "\033[96m"; DIM = "\033[2m";  BOLD= "\033[1m"; RST = "\033[0m"

# Known colon-blink pairs: (frame_key_prefix, pos, val_a, val_b)
# These are suppressed unless --all-frames
BLINK_SUPPRESS = {
    # CF_33_014: pos[10] toggles 0x4e <-> 0x1e  (confirmed colon blink)
    ("CF_33_014", 10, 0x4e, 0x1e),
    ("CF_33_014", 10, 0x1e, 0x4e),
}

def split_frames(data: bytes) -> list[bytes]:
    parts = data.split(SEP)
    return [p for p in parts if len(p) >= 8 and p[0] == 0x39]

def frame_key(f: bytes) -> str:
    return f"{f[1]:02X}_{f[2]:02X}_{len(f):03d}"

def is_blink_only(key: str, new_f: bytes, old_f: bytes) -> bool:
    """Returns True if the only changes are known colon-blink positions."""
    changes = [i for i in range(min(len(new_f), len(old_f))) if new_f[i] != old_f[i]]
    for i in changes:
        if (key, i, old_f[i], new_f[i]) not in BLINK_SUPPRESS:
            return False
    return bool(changes)

def print_diff(key: str, new_f: bytes, old_f: bytes | None, ts: str):
    if old_f is None:
        row = " ".join(f"{b:02x}" for b in new_f)
        print(f"{DIM}[{ts}] {key}  (new)  {row}{RST}")
        return

    changed = [i for i in range(min(len(new_f), len(old_f))) if new_f[i] != old_f[i]]
    len_diff = len(new_f) != len(old_f)

    if not changed and not len_diff:
        return

    def fmt(i, b):
        if i in changed:
            return f"{RED}{BOLD}{b:02x}{RST}"
        return f"{b:02x}"

    row_new = " ".join(fmt(i, b) for i, b in enumerate(new_f))
    row_old = " ".join(f"{b:02x}" for b in old_f)

    print(f"[{ts}] {CYN}{BOLD}{key}{RST}  "
          f"{RED}*** {len(changed)} byte(s) changed ***{RST}")
    print(f"  was: {row_old}")
    print(f"  now: {row_new}")
    for i in sorted(changed):
        ov, nv = old_f[i], new_f[i]
        d = (nv - ov) & 0xFF
        print(f"    pos[{i:2d}]  0x{ov:02x}={ov:08b}b  →  0x{nv:02x}={nv:08b}b  "
              f"(XOR=0x{ov^nv:02x})")
    print()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--all-frames', action='store_true',
                        help='Visa alla frame-typer, inte bara CF_33')
    parser.add_argument('--no-filter', action='store_true',
                        help='Visa även colon-blink ändringar')
    args = parser.parse_args()

    print(f"{BOLD}H-bus live diff monitor{RST}")
    print(f"Port: {PORT}, {BAUD} bps")
    if not args.all_frames:
        print(f"Visar: {CYN}CF_33{RST} frames (XK57-master)")
    else:
        print(f"Visar: alla frame-typer")
    if not args.no_filter:
        print(f"Filtrerar: kända colon-blink-ändringar")
    print(f"\nÄndra setpointen på XK57 och titta på {RED}röda bytes{RST}.")
    print(f"Ctrl-C för att avsluta.\n")

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.05)
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"Portfel: {e}", file=sys.stderr)
        sys.exit(1)

    last: dict[str, bytes] = {}
    buf = bytearray()
    t_last = time.time()
    frame_count = 0

    while True:
        chunk = ser.read(512)
        if chunk:
            buf += chunk

        now = time.time()
        if len(buf) > 256 or (buf and now - t_last > 0.15):
            frames = split_frames(bytes(buf))
            buf.clear()
            t_last = now

            for f in frames:
                k = frame_key(f)

                # Filter to CF_33 unless --all-frames
                if not args.all_frames and not k.startswith("CF_33"):
                    last[k] = f
                    continue

                old = last.get(k)
                frame_count += 1

                if old is not None:
                    # Suppress blink-only diffs
                    if not args.no_filter and is_blink_only(k, f, old):
                        last[k] = f
                        continue

                ts = time.strftime("%H:%M:%S")
                print_diff(k, f, old, ts)
                last[k] = f

if __name__ == "__main__":
    main()
