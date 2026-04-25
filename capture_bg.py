#!/usr/bin/env python3
"""Bakgrundsfångst – ingen interaktiv terminal krävs. Kör i 300s."""
import serial, time, datetime, os, collections

PORT       = "/dev/tty.usbserial-BG01X9HJ"
BAUD       = 38400
FRAME_SIZE = 24
PREFIX     = bytes([0x60, 0x06, 0xF8])
LOG_DIR    = "logs"
DURATION   = 300  # sekunder

os.makedirs(LOG_DIR, exist_ok=True)
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_path = os.path.join(LOG_DIR, f"watch_{ts}.log")

ser = serial.Serial(
    port=PORT, baudrate=BAUD,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.01
)
ser.reset_input_buffer()

buf        = bytearray()
prev_frame = None
frame_nr   = 0
byte_changes = [0] * FRAME_SIZE
frame_values  = [collections.Counter() for _ in range(FRAME_SIZE)]

end_time = time.time() + DURATION

with open(log_path, "w", encoding="utf-8") as logfile:
    logfile.write(f"Aquatermic Frame Watcher - {ts}\n")
    logfile.write(f"Prefix: 60 06 F8  Frame: {FRAME_SIZE}B\n\n")

    while time.time() < end_time:
        chunk = ser.read(256)
        if chunk:
            buf.extend(chunk)

        while True:
            idx = buf.find(PREFIX)
            if idx == -1:
                buf = buf[-2:] if len(buf) >= 2 else buf
                break
            if idx + FRAME_SIZE > len(buf):
                buf = buf[idx:]
                break

            frame = bytes(buf[idx:idx + FRAME_SIZE])
            buf   = buf[idx + FRAME_SIZE:]
            frame_nr += 1
            ts_f = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

            for i, b in enumerate(frame):
                frame_values[i][b] += 1
                if prev_frame and frame[i] != prev_frame[i]:
                    byte_changes[i] += 1

            changed_str = ('CHG:' + ','.join(str(i) for i in range(FRAME_SIZE)
                           if prev_frame and prev_frame[i] != frame[i])
                           if prev_frame and any(prev_frame[i] != frame[i] for i in range(FRAME_SIZE))
                           else 'first' if not prev_frame else 'same')

            logfile.write(f"#{frame_nr:<5} {ts_f}  "
                          f"{' '.join(f'{b:02X}' for b in frame)}  {changed_str}\n")

            prev_frame = frame

        if frame_nr % 500 == 0 and frame_nr > 0:
            logfile.flush()

    total = max(frame_nr - 1, 1)
    logfile.write(f"\n--- Klar: {frame_nr} frames på {DURATION}s ---\n")
    logfile.write("Byte-förändringsfrekvens:\n")
    for i in range(FRAME_SIZE):
        pct = byte_changes[i] / total * 100
        top = frame_values[i].most_common(5)
        logfile.write(f"  [{i:2d}] {pct:.1f}%  "
                      f"{' '.join(f'0x{v:02X}({c})' for v, c in top)}\n")
    logfile.flush()

ser.close()
print(f"KLAR: {frame_nr} frames → {log_path}")
