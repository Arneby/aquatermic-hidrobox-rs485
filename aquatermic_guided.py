#!/usr/bin/env python3
"""
Aquatermic RS485 Guided Test – XK57 masterpanel (Hidrobox)
Instruerar dig steg för steg vilken knapp du ska trycka och fångar
exakt vilka bytes som ändras. Bygger en komplett knapp→byte-karta.

Kör: ./venv/bin/python aquatermic_guided.py
"""

import serial
import time
import datetime
import os
import sys
import collections

PORT   = "/dev/tty.usbserial-BG01X9HJ"
BAUD   = 38400
FRAME_SIZE  = 24
FRAME_SYNC  = 0x60
LOG_DIR     = "logs"

# Antal frames att samla per steg
BASELINE_FRAMES  = 20   # "vila"-frames innan test
CAPTURE_FRAMES   = 15   # frames att fånga direkt efter knapptryckning

# ANSI
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BLUE   = "\033[94m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── Testsekvens ────────────────────────────────────────────────────────────────
# Varje steg: (id, label, instruktion)
# Håll det enkelt – en action i taget, vänta på bekräftelse.
TEST_STEPS = [
    # ── Baseline ─────────────────────────────────────────────────────────────
    ("idle",          "VILOLÄGE",                "Rör INGENTING. Låt systemet gå ostört i viloläge."),

    # ── Varmvatten (VVB / DHW) ───────────────────────────────────────────────
    ("dhw_off",       "VVB: STÄNG AV",           "Stäng AV varmvattenberedaren (VVB) via XK57."),
    ("dhw_on",        "VVB: SLÅS PÅ",            "Slå PÅ varmvattenberedaren (VVB) via XK57."),
    ("dhw_mode_keep", "VVB: LÄGE KEEP",          "Sätt VVB i läget KEEP (håll temp konstant)."),
    ("dhw_mode_auto", "VVB: LÄGE AUTO",          "Sätt VVB i läget AUTO (tidsstyrd)."),
    ("dhw_temp_up",   "VVB: TEMP UPP",           "Höj VVB-temperatur ETT steg (▲)."),
    ("dhw_temp_up2",  "VVB: TEMP UPP x2",        "Höj VVB-temperatur YTterligare ETT steg (▲)."),
    ("dhw_temp_dn",   "VVB: TEMP NED",           "Sänk VVB-temperatur ETT steg (▼)."),
    ("dhw_temp_dn2",  "VVB: TEMP NED x2",        "Sänk VVB-temperatur YTterligare ETT steg (▼)."),
    ("dhw_timer",     "VVB: TIMER-INSTÄLLNING",  "Öppna/rör VVB-timern på XK57, stäng sedan."),

    # ── Golvvärme (UFH) ───────────────────────────────────────────────────────
    ("ufh_off",       "UFH: STÄNG AV",           "Stäng AV golvvärmen (UFH) via XK57."),
    ("ufh_on",        "UFH: SLÅS PÅ",            "Slå PÅ golvvärmen (UFH) via XK57."),
    ("ufh_mode_keep", "UFH: LÄGE KEEP",          "Sätt UFH i läget KEEP (håll temp konstant)."),
    ("ufh_mode_auto", "UFH: LÄGE AUTO",          "Sätt UFH i läget AUTO (tidsstyrd)."),
    ("ufh_temp_up",   "UFH: TEMP UPP",           "Höj UFH-temperatur ETT steg (▲)."),
    ("ufh_temp_up2",  "UFH: TEMP UPP x2",        "Höj UFH-temperatur YTterligare ETT steg (▲)."),
    ("ufh_temp_dn",   "UFH: TEMP NED",           "Sänk UFH-temperatur ETT steg (▼)."),
    ("ufh_temp_dn2",  "UFH: TEMP NED x2",        "Sänk UFH-temperatur YTterligare ETT steg (▼)."),
    ("ufh_timer",     "UFH: TIMER-INSTÄLLNING",  "Öppna/rör UFH-timern på XK57, stäng sedan."),

    # ── Klocka ───────────────────────────────────────────────────────────────
    ("clock",         "KLOCKA: JUSTERA",         "Öppna klockinställningen och ändra minuten +1, spara."),

    # ── Navigation ───────────────────────────────────────────────────────────
    ("menu_in",       "MENY: ÖPPNA",             "Öppna huvudmenyn på XK57."),
    ("menu_out",      "MENY: STÄNG",             "Stäng menyn / gå tillbaka till normalvisning."),
]


def now_str() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def read_frames(ser: serial.Serial, count: int, timeout_s: float = 8.0) -> list[bytes]:
    """Samlar 'count' kompletta frames från serieporten."""
    buf = bytearray()
    frames = []
    deadline = time.monotonic() + timeout_s

    while len(frames) < count and time.monotonic() < deadline:
        chunk = ser.read(128)
        if chunk:
            buf.extend(chunk)
        # Extrahera frames
        i = 0
        while i < len(buf):
            if buf[i] != FRAME_SYNC:
                i += 1
                continue
            if i + FRAME_SIZE > len(buf):
                break
            frames.append(bytes(buf[i:i + FRAME_SIZE]))
            i += FRAME_SIZE
        buf = buf[i:]

    return frames


def median_frame(frames: list[bytes]) -> bytes:
    """
    Returnerar 'median' per byte-position (vanligaste värde).
    Filtrerar bort transienta fluktuationer i baseline.
    """
    result = bytearray(FRAME_SIZE)
    for pos in range(FRAME_SIZE):
        vals = [f[pos] for f in frames if pos < len(f)]
        result[pos] = collections.Counter(vals).most_common(1)[0][0]
    return bytes(result)


def diff_frames(ref: bytes, frames: list[bytes]) -> dict:
    """
    Jämför frames mot referens.
    Returnerar {position: set_of_new_values} för alla positioner som ändrades.
    """
    changed: dict[int, set] = {}
    for frame in frames:
        for i in range(min(len(ref), len(frame))):
            if frame[i] != ref[i]:
                changed.setdefault(i, set()).add(frame[i])
    return changed


def fmt_hex_diff(ref: bytes, frame: bytes) -> str:
    parts = []
    for i, b in enumerate(frame):
        if b != ref[i]:
            parts.append(f"{RED}{BOLD}{b:02X}{RESET}")
        else:
            parts.append(f"{DIM}{b:02X}{RESET}")
    return " ".join(parts)


def prompt_ready(step_label: str, instruction: str) -> bool:
    """Visar instruktion och väntar på Enter. Returnerar False om användaren hoppar."""
    print(f"\n{'─'*68}")
    print(f"  {CYAN}{BOLD}STEG: {step_label}{RESET}")
    print(f"  {YELLOW}{instruction}{RESET}")
    print(f"{'─'*68}")
    ans = input(f"  Tryck {BOLD}Enter{RESET} när du är redo "
                f"(eller {DIM}s{RESET}+Enter för att hoppa): ").strip().lower()
    return ans != "s"


def spinner(msg: str, count: int):
    chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    for i in range(count):
        print(f"\r  {chars[i % len(chars)]}  {msg} ({i+1}/{count})", end="", flush=True)
        time.sleep(0.05)
    print(f"\r  ✓  {msg} – klar!{' '*20}")


def main():
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOG_DIR, f"guided_{ts}.log")

    print(f"\n{BOLD}{'═'*68}{RESET}")
    print(f"  {CYAN}{BOLD}Aquatermic XK57 Guided Button Test (Hidrobox masterpanel){RESET}")
    print(f"  Port: {PORT}  @  {BAUD} bps")
    print(f"  Logg: {log_path}")
    print(f"{BOLD}{'═'*68}{RESET}")
    print(f"""
  Jag guidar dig genom testet steg för steg.
  Varje steg:
    1. Du ser instruktionen (vad du ska göra på panelen)
    2. Du trycker Enter när du är redo
    3. Jag ger dig 2 sekunder att utföra åtgärden
    4. Jag fångar frames och visar exakt vad som ändrades

  Hoppa ett steg med {DIM}s{RESET}+Enter om knappen inte finns.
""")

    input(f"  Tryck {BOLD}Enter{RESET} för att starta...")

    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05
        )
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"{RED}FEL: Kan inte öppna {PORT}: {e}{RESET}")
        sys.exit(1)

    logfile = open(log_path, "w", encoding="utf-8")
    logfile.write(f"Aquatermic Guided Test - {ts}\n")
    logfile.write(f"Port: {PORT} @ {BAUD} bps\n\n")

    # Bygg upp resultat-kartan: step_id → {pos: set(values)}
    results: dict[str, dict] = {}
    baseline: bytes | None = None
    step_baselines: dict[str, bytes] = {}   # baseline precis FÖRE varje steg

    for step_id, step_label, instruction in TEST_STEPS:

        if not prompt_ready(step_label, instruction):
            print(f"  {DIM}Hoppade {step_label}{RESET}")
            logfile.write(f"\nSTEG {step_id} ({step_label}): HOPPADES\n")
            continue

        # ── 1. Samla pre-frames (baseline för detta steg) ──────────────────
        print(f"\n  {DIM}Samlar {BASELINE_FRAMES} baseline-frames...{RESET}", end="", flush=True)
        pre_frames = read_frames(ser, BASELINE_FRAMES, timeout_s=10.0)
        if len(pre_frames) < 5:
            print(f"\n  {RED}Fick för få frames ({len(pre_frames)}). Kontrollera koppling.{RESET}")
            logfile.write(f"\nSTEG {step_id}: FÖR FÅ FRAMES ({len(pre_frames)})\n")
            continue

        step_baseline = median_frame(pre_frames)
        step_baselines[step_id] = step_baseline
        if baseline is None:
            baseline = step_baseline
        print(f"  ✓  baseline: {' '.join(f'{b:02X}' for b in step_baseline)}")

        # ── 2. GE ANVÄNDAREN TID att trycka ────────────────────────────────
        if step_id == "idle":
            # Vilosteget behöver ingen väntan – vi har redan baseline
            post_frames = pre_frames
        else:
            print(f"\n  {YELLOW}{BOLD}>>> GÖR DET NU! <<<{RESET}  (3 sekunder)")
            # Ge användaren 1s att reagera, sedan fånga 2s frames
            time.sleep(1.0)
            post_frames = read_frames(ser, CAPTURE_FRAMES, timeout_s=5.0)

        # ── 3. Analysera diff ───────────────────────────────────────────────
        changed = diff_frames(step_baseline, post_frames)
        results[step_id] = changed

        logfile.write(f"\n{'='*60}\n")
        logfile.write(f"STEG: {step_id} ({step_label})\n")
        logfile.write(f"Baseline: {' '.join(f'{b:02X}' for b in step_baseline)}\n")
        logfile.write(f"Post-frames ({len(post_frames)}):\n")
        for pf in post_frames:
            logfile.write(f"  {' '.join(f'{b:02X}' for b in pf)}\n")
        logfile.write(f"Ändrade positioner: {sorted(changed.keys())}\n")
        for pos, vals in sorted(changed.items()):
            logfile.write(f"  [{pos:2d}]: {' '.join(f'0x{v:02X}' for v in sorted(vals))}\n")

        # ── 4. Visa resultat ────────────────────────────────────────────────
        print(f"\n  {BOLD}Resultat – {step_label}:{RESET}")

        # Filtrera bort positioner som redan varierar i baseline
        baseline_noise = diff_frames(step_baseline, pre_frames) if step_id != "idle" else {}

        truly_changed = {p: v for p, v in changed.items() if p not in baseline_noise}
        noisy = {p: v for p, v in changed.items() if p in baseline_noise}

        if not changed:
            print(f"  {DIM}Inga bytes ändrades (ingen skillnad jämfört med baseline){RESET}")
        else:
            if truly_changed:
                print(f"  {GREEN}{BOLD}Signifikanta förändringar (troligtvis knapprelaterade):{RESET}")
                for pos, vals in sorted(truly_changed.items()):
                    old_val = step_baseline[pos]
                    new_vals = sorted(vals)
                    delta = ""
                    if len(new_vals) == 1:
                        d = new_vals[0] - old_val
                        delta = f"  Δ={d:+d}"
                    print(f"    Byte[{pos:2d}]: {DIM}0x{old_val:02X}{RESET} → "
                          f"{RED}{BOLD}{' / '.join(f'0x{v:02X}' for v in new_vals)}{RESET}{delta}")

            if noisy:
                print(f"  {DIM}(bakgrundsvariation – troligen räknare/timer):{RESET}")
                for pos in sorted(noisy.keys()):
                    print(f"    {DIM}Byte[{pos:2d}] (redan varierande){RESET}")

        # Visa upp till 5 post-frames mot baseline
        if post_frames and step_id != "idle":
            print(f"\n  {DIM}Post-frames (max 5):{RESET}")
            for pf in post_frames[:5]:
                print(f"    {fmt_hex_diff(step_baseline, pf)}")

    # ── Slutsammanfattning ──────────────────────────────────────────────────
    ser.close()

    print(f"\n\n{BOLD}{'═'*68}{RESET}")
    print(f"  {CYAN}{BOLD}SAMMANFATTNING – Knapp → Byte-karta{RESET}")
    print(f"{'═'*68}")

    # Hitta vilka positioner som är "noise" (varierar i idle)
    idle_noise = set(results.get("idle", {}).keys())

    logfile.write(f"\n\n{'='*60}\n")
    logfile.write("SAMMANFATTNING\n")
    logfile.write(f"Idle-noise positioner: {sorted(idle_noise)}\n\n")

    all_signal_positions: dict[int, list[str]] = {}

    for step_id, step_label, _ in TEST_STEPS:
        if step_id not in results or step_id == "idle":
            continue
        changed = results[step_id]
        signal = {p: v for p, v in changed.items() if p not in idle_noise}

        label_short = step_label[:20]
        pos_str = ", ".join(f"[{p}]" for p in sorted(signal.keys())) if signal else "–"
        color = GREEN if signal else DIM
        print(f"  {color}{label_short:<22}{RESET}  byte: {BOLD}{pos_str}{RESET}")
        logfile.write(f"{label_short:<22}  byte: {pos_str}\n")

        for pos in signal:
            all_signal_positions.setdefault(pos, []).append(step_id)

    print(f"\n  {BOLD}Byte-positioner och vilka steg som triggar dem:{RESET}")
    logfile.write(f"\nByte-positioner och triggers:\n")
    for pos in sorted(all_signal_positions.keys()):
        steps = ", ".join(all_signal_positions[pos])
        print(f"    Byte[{pos:2d}]: {YELLOW}{steps}{RESET}")
        logfile.write(f"  [{pos:2d}]: {steps}\n")

    print(f"\n  {DIM}Idle-noise (räknare/timer): byte {sorted(idle_noise)}{RESET}")
    print(f"\n  Logg sparad: {log_path}")
    print(f"{BOLD}{'─'*68}{RESET}\n")

    logfile.close()


if __name__ == "__main__":
    main()
