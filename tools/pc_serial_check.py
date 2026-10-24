"""Talk to the Pico PC machine (src/pc_body.pmi) over USB serial: wait for its
start, optionally type keys, collect what it prints for a while, check text.

  py -3 tools/pc_serial_check.py --port COM7 --seconds 8 [--type abc] [--expect 1E_9E] [--log file]
Exit 0 when every --expect text was seen."""
import argparse, sys, time
import serial
ap = argparse.ArgumentParser()
ap.add_argument('--port', required=True)
ap.add_argument('--seconds', type=float, default=8)
ap.add_argument('--type', default='')
ap.add_argument('--expect', action='append', default=[])
ap.add_argument('--log', default='')
a = ap.parse_args()
port = None
end = time.time() + 30
while port is None:
    try:
        port = serial.Serial(a.port, 115200, timeout=0.1)
    except Exception:
        if time.time() > end:
            raise SystemExit(f'{a.port} did not open')
        time.sleep(0.5)
port.dtr = True
text = b''
t0 = time.time()
typed = False
while time.time() - t0 < a.seconds:
    text += port.read(4096)
    if a.type and not typed and (b'program bytes=' in text or b'PC frames=' in text) and time.time() - t0 > 2:
        for ch in a.type:
            port.write(ch.encode()); port.flush(); time.sleep(0.15)
        typed = True
port.close()
out = text.decode('latin-1')
print(out)
if a.log:
    open(a.log, 'w', encoding='utf-8').write(out)
missing = [e for e in a.expect if e.replace('_', ' ') not in out]   # '_' stands for a space (board.ps1 splits jobs on spaces)
if missing:
    print('MISSING:', missing)
    sys.exit(1)
print('serial check PASS')
