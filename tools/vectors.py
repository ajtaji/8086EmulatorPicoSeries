"""Stream the SingleStepTests 8086 v1 corpus to the board and collect its verdicts.

The board runs Diagnostics/vectors.picow: every test executes ON THE PICO through
Cpu86Run(1) and is checked there. This script only converts the reference JSON
into the compact stream that firmware reads, sends it, and prints what the
board reports. Nothing here executes 8086 code.

  py -3 tools/vectors.py --port COM7 [--per-file N] [--only 80.0,F7.7] [--log docs/x.log]
"""
import argparse, gzip, json, struct, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / 'Diagnostics' / 'upstream' / '8086-v1'
CACHE = ROOT / 'Diagnostics' / 'vectors-bin'
REGS = ['ax', 'bx', 'cx', 'dx', 'cs', 'ss', 'ds', 'es', 'sp', 'bp', 'si', 'di', 'ip', 'flags']
PREFIXES = {0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF1, 0xF2, 0xF3}
FILL = 0xA5

def load_meta():
    return json.loads((CORPUS / 'metadata.json').read_text())['opcodes']

def flag_mask(meta, raw):
    i = 0
    while raw[i] in PREFIXES:
        i += 1
    op = f'{raw[i]:02X}'
    ent = meta.get(op, {})
    if 'reg' in ent:
        reg = str((raw[i + 1] >> 3) & 7)
        ent = ent['reg'].get(reg, {})
    return ent.get('flags-mask', 0xFFFF), raw[i]

def encode(test, meta):
    ini = test['initial']
    fin = test['final']
    r0 = [ini['regs'][k] for k in REGS]
    r1 = [fin['regs'].get(k, ini['regs'][k]) for k in REGS]
    fmask, opcode = flag_mask(meta, test['bytes'])
    init = {a: v for a, v in ini['ram']}
    final = {a: v for a, v in fin['ram']}
    masks = {}
    # A divide error (INT 0 through the vector at 0:0, which the corpus points
    # at linear $400) pushes FLAGS, whose undefined bits are not comparable.
    if (r1[4] * 16 + r1[12]) & 0xFFFFF == 0x400 and opcode in (0xD4, 0xF6, 0xF7):
        fl = (r1[5] * 16 + ((r1[8] + 4) & 0xFFFF)) & 0xFFFFF
        fh = (r1[5] * 16 + ((r1[8] + 5) & 0xFFFF)) & 0xFFFFF
        masks[fl] = fmask & 0xFF
        masks[fh] = (fmask >> 8) & 0xFF
    addrs = list(init)
    for a in final:
        if a not in init:
            addrs.append(a)
    ents = bytearray()
    for a in addrs:
        iv = init.get(a, FILL)
        fv = final.get(a, iv)
        mk = masks.get(a, 0xFF)
        if fv != iv or mk != 0xFF or a not in init:
            ents += struct.pack('<I', a | 0x800000)[:3] + bytes([iv, fv, mk])
        else:
            ents += struct.pack('<I', a)[:3] + bytes([iv])
    payload = struct.pack('<14H', *r0) + struct.pack('<14H', *r1) + struct.pack('<HH', fmask, len(addrs)) + ents
    return b'\x5aT' + struct.pack('<H', len(payload)) + payload

def files():
    return sorted(p.name[:-8] for p in CORPUS.glob('*.json.gz'))

def build(name, meta, per_file):
    tests = json.loads(gzip.decompress((CORPUS / f'{name}.json.gz').read_bytes()))
    tests = tests[:per_file]
    blob = bytearray(b'\x5aG' + bytes([len(name)]) + name.encode())
    for t in tests:
        blob += encode(t, meta)
    blob += b'\x5aE'
    return bytes(blob), [t['name'] for t in tests]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', required=True)
    ap.add_argument('--per-file', type=int, default=2000)
    ap.add_argument('--only', default='')
    ap.add_argument('--skip', default='')
    ap.add_argument('--log', default='')
    ap.add_argument('--wait', type=float, default=40.0)
    args = ap.parse_args()
    import serial
    meta = load_meta()
    names = files()
    if args.only:
        want = args.only.split(',')
        names = [n for n in names if n in want or n.split('.')[0] in want]
    if args.skip:
        skip = args.skip.split(',')
        names = [n for n in names if n not in skip and n.split('.')[0] not in skip]
    log = open(args.log, 'w', encoding='utf-8') if args.log else None
    def out(line):
        print(line, flush=True)
        if log:
            log.write(line + '\n')
            log.flush()
    port = None
    deadline = time.time() + args.wait
    while port is None:
        try:
            port = serial.Serial(args.port, 115200, timeout=0.2, write_timeout=None)
        except Exception:
            if time.time() > deadline:
                raise SystemExit(f'{args.port} did not open within {args.wait} s')
            time.sleep(0.5)
    port.dtr = True
    lines = []
    lock = threading.Condition()
    stop = False
    def reader():
        buf = b''
        while not stop:
            try:
                chunk = port.read(max(1, port.in_waiting))
            except Exception as ex:
                with lock:
                    lines.append(f'READ ERROR {ex}')
                    lock.notify_all()
                return
            if not chunk:
                continue
            buf += chunk
            while b'\n' in buf:
                ln, buf = buf.split(b'\n', 1)
                with lock:
                    lines.append(ln.decode('latin-1').rstrip('\r'))
                    lock.notify_all()
    th = threading.Thread(target=reader, daemon=True)
    th.start()
    seen = 0
    def take(pred, timeout):
        nonlocal seen
        end = time.time() + timeout
        with lock:
            while True:
                while seen < len(lines):
                    ln = lines[seen]
                    seen += 1
                    yield_line(ln)
                    if pred(ln):
                        return ln
                left = end - time.time()
                if left <= 0:
                    return None
                lock.wait(left)
    current = {'names': []}
    def yield_line(ln):
        if ln.startswith('F ') and current['names']:
            parts = ln.split()
            try:
                idx = int(parts[1])
                ln = ln + '   [' + current['names'][idx] + ']'
            except Exception:
                pass
        out(ln)
    if take(lambda l: l.startswith('READY'), args.wait) is None:
        raise SystemExit('the board never printed READY')
    t0 = time.time()
    stats = {'bytes': 0, 'tests': 0}
    groups = []                      # (name, test names) in the order the board reports them
    def sender():
        for n in names:
            blob, tnames = build(n, meta, args.per_file)
            with lock:
                groups.append((n, tnames))
            port.write(blob)
            stats['bytes'] += len(blob)
            stats['tests'] += len(tnames)
        port.write(b'\x5aZ')
    threading.Thread(target=sender, daemon=True).start()
    failed_groups = []
    for k in range(len(names)):
        while True:
            with lock:
                if k < len(groups):
                    current['names'] = groups[k][1]
                    gname = groups[k][0]
                    break
            time.sleep(0.01)
        ln = take(lambda l: l.startswith('G '), 300)
        if ln is None:
            out(f'NO VERDICT for group {gname}')
            failed_groups.append(gname)
            break
        if ' fail=0 ' not in ln:
            failed_groups.append(gname)
    ln = take(lambda l: l.startswith('vectors '), 120)
    dt = time.time() - t0
    out(f"host: {len(names)} files, {stats['tests']} tests, {stats['bytes']} bytes in {dt:.1f} s")
    if failed_groups:
        out('host: groups with failures: ' + ' '.join(failed_groups))
    stop = True
    port.close()
    ok = ln is not None and ln.strip() == 'vectors PASS' and not failed_groups
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
