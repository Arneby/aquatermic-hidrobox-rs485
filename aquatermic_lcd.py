#!/usr/bin/env python3
"""
Aquatermic LCD Analyzer
Offline-analysator: parserar watch-loggar och avkodar LCD-segmentdata (bytes 15-22).

Användning:
    ./venv/bin/python aquatermic_lcd.py [loggfil]
    ./venv/bin/python aquatermic_lcd.py          # analyserar senaste watch-logg

Kända fakta som styr avkodningen:
    byte[22]=0x66 = siffra "4"  (bekräftat – UFH 40°C tens-siffra)
    byte[21]=0x1E = siffra "0"  (troligt  – UFH 40°C units-siffra)
    → Valda encoding-hypotes: A (se SEG_A nedan)
"""

import re
import sys
import os
import glob
from collections import Counter, defaultdict, OrderedDict

LOG_DIR   = "logs"
LCD_SLICE = slice(15, 23)   # bytes 15–22 i varje 24-byte frame
NOISE     = {11, 13, 23}    # bytes som alltid fluktuerar (räknare, enhets-ID)

# ── Segmentkodning A ──────────────────────────────────────────────────────────
#
#  Härledning:
#   "4" = segments b,c,f,g  och  0x66 = 0110 0110 (bits 6,5,2,1)
#   → bit6=f, bit5=g  ELLER  bit6=g, bit5=f
#   "0" = segments a,b,c,d och  0x1E = 0001 1110 (bits 4,3,2,1)
#   → bit4=a, bit3=d  (bits 2,1 delade med "4" → b,c)
#
#  Slutlig mapping: bit0=dp, bit1=c, bit2=b, bit3=d, bit4=a, bit5=f, bit6=g, bit7=e
#
#  Verifiering:
#    "4" = b+c+f+g = bit2+bit1+bit5+bit6 = 0x04+0x02+0x20+0x40 = 0x66 ✓
#    "0" = a+b+c+d = bit4+bit2+bit1+bit3 = 0x10+0x04+0x02+0x08 = 0x1E ✓ (simplified 0)
#    "8" = all     = 0x10+0x04+0x02+0x08+0x80+0x20+0x40 = 0xFE ✓ (if dp=0)
#    "9" = a+b+c+d+f+g = 0x1E+0x60 = 0x7E ✓  (matches common value!)
#    "1" = b+c = 0x06 ✓

SEG_A = {
    'a': 4,   # topp
    'b': 2,   # höger-övre
    'c': 1,   # höger-undre
    'd': 3,   # botten
    'e': 7,   # vänster-undre
    'f': 5,   # vänster-övre
    'g': 6,   # mitten
    'dp': 0,  # decimalpunkt
}

# ── Siffertabell ──────────────────────────────────────────────────────────────
# Standard 7-segment – vilka segment som ska lysa per tecken.
# "0" = förenklad rektangel (a,b,c,d – utan sidosegment) som matchar 0x1E.
DIGITS = OrderedDict([
    (' ',  set()),
    ('0',  set('abcd')),      # 0x1E – förenklad
    ('0F', set('abcdef')),    # 0x9E? – full "0" med alla sidor
    ('1',  set('bc')),
    ('2',  set('abdeg')),
    ('3',  set('abcdg')),
    ('4',  set('bcfg')),
    ('5',  set('acdfg')),
    ('6',  set('acdefg')),
    ('7',  set('abc')),
    ('8',  set('abcdefg')),
    ('9',  set('abcdfg')),
    ('-',  set('g')),
    ('°',  set('abfg')),
    ('C',  set('aefd')),       # vänster C-form: a+e+f+d
    ('H',  set('bcefg')),
    ('F',  set('aefg')),
    ('U',  set('bcde')),
])


def byte_to_segs(val: int, seg_map: dict = SEG_A) -> set:
    return {s for s, bit in seg_map.items() if s != 'dp' and (val >> bit) & 1}

def dp_set(val: int, seg_map: dict = SEG_A) -> bool:
    return bool((val >> seg_map['dp']) & 1)

def segs_to_char(segs: set) -> str:
    if not segs:
        return ' '
    best, best_score = '?', -1
    for ch, std in DIGITS.items():
        if not std:
            continue
        inter = len(segs & std)
        union = len(segs | std)
        score = inter / union if union else 0
        if score > best_score:
            best_score, best = score, ch
    return best if best_score >= 0.55 else '?'

def byte_to_char(val: int) -> str:
    return segs_to_char(byte_to_segs(val))

def draw_digit(val: int) -> list[str]:
    """3-raders ASCII-art för en 7-segment-siffra."""
    s  = byte_to_segs(val)
    dp = '.' if dp_set(val) else ' '
    a = '─' if 'a' in s else ' '
    b = '│' if 'b' in s else ' '
    c = '│' if 'c' in s else ' '
    d = '─' if 'd' in s else ' '
    e = '│' if 'e' in s else ' '
    f = '│' if 'f' in s else ' '
    g = '─' if 'g' in s else ' '
    return [f" {a}  ", f"{f}{g}{b} ", f"{e}{d}{c}{dp}"]

def render_lcd(lcd8: bytes) -> str:
    """Renderar 8 byte-positioner som 7-segment-rader + textrad."""
    digits = [draw_digit(b) for b in lcd8]
    rows   = [''.join(d[r] for d in digits) for r in range(3)]
    chars  = ''.join(byte_to_char(b) for b in lcd8)
    return '\n'.join(rows) + f'\n  "{chars}"'

def render_lcd_compact(lcd8: bytes) -> str:
    """Kompakt vy: hex + decoded text."""
    hex_s  = ' '.join(f'{b:02X}' for b in lcd8)
    chars  = ''.join(byte_to_char(b) for b in lcd8)
    dp_s   = ''.join('·' if dp_set(b) else ' ' for b in lcd8)
    return f'{hex_s}   "{chars}"  dp:[{dp_s}]'

# ── Logg-parsning ─────────────────────────────────────────────────────────────

FRAME_RE = re.compile(
    r'#(\d+)\s+(\d{2}:\d{2}:\d{2}\.\d+)\s+((?:[0-9A-Fa-f]{2}\s+){24})'
)

def parse_log(path: str) -> list:
    frames = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = FRAME_RE.match(line.strip())
            if m:
                nr  = int(m.group(1))
                ts  = m.group(2)
                raw = bytes(int(x, 16) for x in m.group(3).split())
                if len(raw) == 24:
                    frames.append((nr, ts, raw))
    return frames


# ── Analys ────────────────────────────────────────────────────────────────────

def group_by_page(frames: list) -> dict:
    """Gruppera frames per värde på byte[15] ('sida'/LCD-page)."""
    pages: dict[int, list] = defaultdict(list)
    for item in frames:
        pages[item[2][15]].append(item)
    return dict(pages)

def unique_lcd_states(frames: list) -> list[tuple[bytes, int, str, str]]:
    """Unika LCD-8-byte states (15-22), ordnade efter första förekomst."""
    seen: dict[bytes, list] = {}
    order = []
    for _, ts, f in frames:
        k = bytes(f[LCD_SLICE])
        if k not in seen:
            seen[k] = [ts, ts, 0]
            order.append(k)
        seen[k][1] = ts
        seen[k][2] += 1
    return [(k, seen[k][2], seen[k][0], seen[k][1]) for k in order]

def detect_digits(lcd8: bytes) -> dict[int, str]:
    """Returnerar {position: digit_char} för positioner som ser ut som siffror 0-9."""
    digits = {}
    for i, b in enumerate(lcd8):
        ch = byte_to_char(b)
        if ch in '0123456789' or ch in ('0F',):
            digits[i] = ch
    return digits

# ── ANSI-färger ───────────────────────────────────────────────────────────────
RED  = "\033[91m"
YEL  = "\033[93m"
GRN  = "\033[92m"
CYN  = "\033[96m"
DIM  = "\033[2m"
BOLD = "\033[1m"
RST  = "\033[0m"

def hr(char='─', n=72):
    print(char * n)

# ── Huvud ─────────────────────────────────────────────────────────────────────

def pick_log(argv) -> str:
    if len(argv) >= 2 and os.path.isfile(argv[1]):
        return argv[1]
    logs = sorted(glob.glob(os.path.join(LOG_DIR, "watch_*.log")))
    if not logs:
        print(f"{RED}Inga watch-loggar hittades i {LOG_DIR}/{RST}")
        sys.exit(1)
    return logs[-1]

def print_known_digits():
    print(f"\n{BOLD}  Siffertabell – encoding A:{RST}")
    for ch, segs in DIGITS.items():
        if not segs:
            continue
        val = sum(1 << SEG_A[s] for s in segs if s in SEG_A)
        seg_s = '+'.join(sorted(segs))
        print(f"    '{ch}'  = 0x{val:02X}  ({seg_s})")

def main():
    log_path = pick_log(sys.argv)
    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Aquatermic LCD Analyzer{RST}")
    print(f"  Logg : {log_path}")
    print(f"  Enco : A  (bit7=e, bit6=g, bit5=f, bit4=a, bit3=d, bit2=b, bit1=c, bit0=dp)")
    print(f"  Verf : 0x66='4' ✓  0x1E='0' ✓  0xFE='8' ✓  0x7E='9' ✓")
    print(f"{BOLD}{'═'*72}{RST}")

    frames = parse_log(log_path)
    print(f"\n  {len(frames)} frames inlästa.")
    if not frames:
        sys.exit(1)

    # ── 1. Siffertabell ──────────────────────────────────────────────────────
    print_known_digits()

    # ── 2. Per-sida-analys ───────────────────────────────────────────────────
    pages = group_by_page(frames)
    all_states = unique_lcd_states(frames)

    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}LCD-data per sida (byte[15]-värde){RST}")

    for page_val in sorted(pages.keys()):
        page_frames = pages[page_val]
        page_states = unique_lcd_states(page_frames)

        segs_15 = byte_to_segs(page_val)
        ch_15   = byte_to_char(page_val)
        n_sub   = len(page_states)
        t0      = page_frames[0][1]
        t1      = page_frames[-1][1]
        print(f"\n{BOLD}  ── Sida 0x{page_val:02X} ({ch_15}) ──  {n_sub} sub-states  [{t0}–{t1}]{RST}")

        for idx, (lcd8, count, ts0, ts1) in enumerate(page_states):
            # Hitta vad som skiljer denna sub-state från sidan (byte[15] är fast,
            # visa bara bytes 16-22)
            varying = lcd8[1:]   # bytes 16-22 relativt till sidans byte[15]
            hex_s   = ' '.join(f'{b:02X}' for b in lcd8)
            chars   = ''.join(byte_to_char(b) for b in lcd8)

            # Markera siffror i grönt
            colored = []
            for i, b in enumerate(lcd8):
                ch = byte_to_char(b)
                if ch in '0123456789':
                    colored.append(f"{GRN}{b:02X}({ch}){RST}")
                elif ch not in (' ', '?'):
                    colored.append(f"{YEL}{b:02X}({ch}){RST}")
                else:
                    colored.append(f"{DIM}{b:02X}{RST}")
            print(f"    Sub#{idx+1:2d}  {' '.join(colored)}   {count}×")

            # Visuell rendering (komprimerad, bara siffror markeras)
            art = render_lcd(lcd8)
            for line in art.split('\n'):
                print(f"           {line}")
            print()

    # ── 3. Byte-värdestabeller per LCD-position ───────────────────────────────
    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Unika värden per LCD-position (bytes 15-22){RST}")
    print(f"  Format: pos  hex(avk) ... – sorterat efter frekvens\n")

    val_counters = [Counter() for _ in range(24)]
    for _, _, f in frames:
        for i, b in enumerate(f):
            val_counters[i][b] += 1

    for pos in range(15, 23):
        entries = []
        for val, cnt in val_counters[pos].most_common():
            ch = byte_to_char(val)
            if ch in '0123456789':
                mark = f"{GRN}{val:02X}={ch}({cnt}){RST}"
            elif ch not in (' ', '?'):
                mark = f"{YEL}{val:02X}={ch}({cnt}){RST}"
            else:
                mark = f"{DIM}{val:02X}({cnt}){RST}"
            entries.append(mark)
        print(f"  [{pos}]  " + '  '.join(entries))

    # ── 4. Statistik-sammanfattning ───────────────────────────────────────────
    print(f"\n{BOLD}{'═'*72}{RST}")
    print(f"  {CYN}{BOLD}Sammanfattning{RST}")
    print(f"  Totalt unika LCD-states : {len(all_states)}")
    print(f"  Antal sidor (byte[15])  : {len(pages)}")
    print(f"  Sidor: " + ', '.join(f"0x{v:02X}={byte_to_char(v)}" for v in sorted(pages.keys())))
    print()
    print(f"  {YEL}Tips för kalibrering:{RST}")
    print(f"  1. Kör aquatermic_watch.py och notera vilken state som visas")
    print(f"     när displayen visar t.ex. VVB 65°C, UFH 40°C, klockan, etc.")
    print(f"  2. Korrelera state-nummret med vad LCD-bytes avkodar till.")
    print(f"  3. Justera DIGITS-tabellen om avkodningen ser fel ut.\n")

if __name__ == '__main__':
    main()
