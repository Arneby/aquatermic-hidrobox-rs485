#!/usr/bin/env python3
"""H-bus rå bakgrundsfångst – ingen prefix-filtrering, sparar råbytes + timing."""
import serial, time, datetime, os, collections, struct

PORT     = "/dev/tty.usbserial-BG01X9HJ"
BAUD     = 38400
LOG_DIR  = "logs"
DURATION = 300

os.makedirs(LOG_DIR, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
raw_path  = os.path.join(LOG_DIR, f"hbus_raw_{ts}.bin")
log_path  = os.path.join(LOG_DIR, f"hbus_{ts}.log")

ser = serial.Serial(port=PORT, baudrate=BAUD,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.01)
ser.reset_input_buffer()

end_time   = time.time() + DURATION
total_bytes = 0
bursts     = []   # (timestamp, bytes)
last_rx    = None
BURST_GAP  = 0.010  # 10ms tystnad = burst-gräns

raw_file = open(raw_path, 'wb')

current_burst = bytearray()
current_ts    = None

print(f"Fångar H-bus i {DURATION}s → {log_path}")

while time.time() < end_time:
    chunk = ser.read(256)
    now = time.time()
    if chunk:
        raw_file.write(chunk)
        total_bytes += len(chunk)
        if current_ts is None:
            current_ts = now
        if last_rx and (now - last_rx) > BURST_GAP and current_burst:
            bursts.append((current_ts, bytes(current_burst)))
            current_burst = bytearray()
            current_ts = now
        current_burst.extend(chunk)
        last_rx = now

if current_burst:
    bursts.append((current_ts, bytes(current_burst)))

raw_file.close()
ser.close()

# ── Analys ──
byte_counter = collections.Counter()
for _, burst in bursts:
    for b in burst:
        byte_counter[b] += 1

burst_sizes = collections.Counter(len(b) for _, b in bursts)

# Hitta vanligaste burst-storleken
common_sizes = burst_sizes.most_common(10)

# Sök prefix-kandidater: 3-byte sekvenser som förekommer ofta i burst-starts
prefix_counter = collections.Counter()
for _, burst in bursts:
    if len(burst) >= 3:
        prefix_counter[burst[:3]] += 1

# Sök återkommande 3-byte sekvenser globalt
seq3_counter = collections.Counter()
for _, burst in bursts:
    for i in range(len(burst) - 2):
        seq3_counter[burst[i:i+3]] += 1

with open(log_path, 'w', encoding='utf-8') as f:
    f.write(f"H-bus fångst {ts}\n")
    f.write(f"Totalt: {total_bytes} bytes, {len(bursts)} bursts på {DURATION}s\n\n")

    f.write("=== Burst-storlekar (antal bytes per burst) ===\n")
    for size, cnt in common_sizes:
        f.write(f"  {size:4d} bytes: {cnt:5d}x\n")

    f.write("\n=== Vanligaste burst-prefix (3 bytes) ===\n")
    for seq, cnt in prefix_counter.most_common(20):
        f.write(f"  {seq.hex(' ')}: {cnt}x\n")

    f.write("\n=== Vanligaste 3-byte sekvenser globalt ===\n")
    for seq, cnt in seq3_counter.most_common(30):
        f.write(f"  {seq.hex(' ')}: {cnt}x\n")

    f.write("\n=== Byte-frekvens (top 20) ===\n")
    for b, cnt in byte_counter.most_common(20):
        pct = cnt / total_bytes * 100
        f.write(f"  0x{b:02X}: {cnt:6d}x  {pct:.1f}%\n")

    f.write("\n=== Exempelbursts (första 40) ===\n")
    for i, (bts, burst) in enumerate(bursts[:40]):
        dt = datetime.datetime.fromtimestamp(bts).strftime("%H:%M:%S.%f")[:-3]
        f.write(f"  #{i+1:4d} {dt} [{len(burst):3d}B] {burst.hex(' ')}\n")

    # Försök hitta frame-struktur via alignment
    f.write("\n=== Kandidat-frame-storlekar (om regelbunden) ===\n")
    for size in [8, 12, 16, 18, 20, 24, 32]:
        matches = sum(1 for _, b in bursts if len(b) % size == 0 and len(b) > 0)
        pct = matches / len(bursts) * 100 if bursts else 0
        f.write(f"  {size:2d}-byte frame: {matches}/{len(bursts)} bursts delbara ({pct:.0f}%)\n")

print(f"KLAR: {total_bytes} bytes, {len(bursts)} bursts → {log_path}")
