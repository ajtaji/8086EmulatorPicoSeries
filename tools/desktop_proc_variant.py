"""Write desktop/cpu86_core_proc.pbi: the PC core with PROCEDURE-TABLE dispatch.

It is made mechanically from desktop/cpu86_core.pbi (labels-as-values), so the
two run identical handler code and differ only in how the next handler is
reached: here every opcode handler is a Procedure called through a table of
procedure addresses, and Cpu86Run is a loop around that call. Only built to
measure the two dispatch methods against each other (desktop --bench).
Instruction budget only (#CPU_TIMING = 0).

  py -3 tools/desktop_proc_variant.py
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
src = (ROOT / 'desktop' / 'cpu86_core.pbi').read_text().split('\n')
start = src.index('Procedure.i Cpu86Run(n.i)')
end = max(i for i, l in enumerate(src) if l == 'EndProcedure')
head, body, rest = src[:start], src[start + 1:end], src[end + 1:]
TEMPS = ['m', 't', 'ea', 'eo', 'sb', 'va', 'vb', 'vr', 'cnt', 'x', 'y']
ren = re.compile(r'(?<![A-Za-z0-9_$#@.])(' + '|'.join(TEMPS) + r')(?![A-Za-z0-9_])')

def rename(line):
    if line.lstrip().startswith(';'):
        return line
    code, sep, comment = line.partition(';')
    return ren.sub(lambda m: 'c86_' + m.group(1), code) + sep + comment

TAIL = ['  CompilerIf #CPU_TIMING = 1', None, '    If Left <= 0', '      Goto Done', '    EndIf',
        '  CompilerElse', '    Left = Left - 1', '    If Left = 0', '      Goto Done', '    EndIf',
        '  CompilerEndIf', '  If PIP >= PEnd', '    Goto Resync', '  EndIf',
        '  ! goto *cpu86_dsp[*(unsigned char*)g_pip];']

# split the body at its top-level labels
blocks, cur, name = [], [], None
for l in body:
    m = re.match(r'^([A-Za-z][A-Za-z0-9_]*):\s*$', l)
    if m:
        blocks.append((name, cur))
        name, cur = m.group(1), []
    else:
        cur.append(l)
blocks.append((name, cur))
blocks = [b for b in blocks if b[0] is not None]
names = [b[0] for b in blocks]

def convert(lines):
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        if l == TAIL[0] and all(t is None or lines[i + k] == t for k, t in enumerate(TAIL)):
            out.append('  ProcedureReturn 0')
            i += len(TAIL)
            continue
        m = re.match(r'^(\s*)! cpu86_earet = &&ll_cpu86run_(\w+);$', l)
        if m:
            assert lines[i + 1].strip() == '! goto *cpu86_eat[v_m];', lines[i + 1]
            target = [n for n in names if n.lower() == m.group(2)][0]
            out.append(f'{m.group(1)}CallFunctionFast(EaP(c86_m))')
            out.append(f'{m.group(1)}Goto {target}')
            i += 2
            continue
        m = re.match(r'^(\s*)! cpu86_earet = cpu86_(\w+)m\[\(v_m >> 3\) & 7\];$', l)
        if m:
            assert lines[i + 1].strip() == '! goto *cpu86_eat[v_m];', lines[i + 1]
            out.append(f'{m.group(1)}CallFunctionFast(EaP(c86_m))')
            out.append(f'{m.group(1)}ProcedureReturn CallFunctionFast({m.group(2).upper()}MP((c86_m >> 3) & 7))')
            i += 2
            continue
        m = re.match(r'^(\s*)! goto \*cpu86_(\w+)r\[\(v_m >> 3\) & 7\];$', l)
        if m:
            out.append(f'{m.group(1)}ProcedureReturn CallFunctionFast({m.group(2).upper()}RP((c86_m >> 3) & 7))')
            i += 1
            continue
        if l.strip() == '! goto *cpu86_earet;':
            out.append('  ProcedureReturn 0')
            i += 1
            continue
        if l.strip() == 'CompilerIf #CPU_TIMING = 1':
            # clock-counted-only code without an Else (prefix counting, REP yield):
            # this variant is built instruction-counted only, so it is left out
            j, depth, other = i + 1, 0, False
            while True:
                s = lines[j].strip()
                if s.startswith('CompilerIf'):
                    depth += 1
                elif s == 'CompilerEndIf':
                    if depth == 0:
                        break
                    depth -= 1
                elif s == 'CompilerElse' and depth == 0:
                    other = True
                j += 1
            if not other:
                i = j + 1
                continue
        if l.strip() == 'Goto PrefixNext':
            out.append(l.replace('Goto PrefixNext', 'ProcedureReturn 1'))
            i += 1
            continue
        assert '!' not in l.split(';')[0][:3] and 'Goto Done' not in l and 'Goto Resync' not in l, l
        out.append(rename(l))
        i += 1
    return out

procs, groups = [], set()
i = 0
while i < len(blocks):
    n, lines = blocks[i]
    if n in ('Resync', 'PrefixNext', 'Done'):
        i += 1
        continue
    procs.append(f'Procedure.i {n}()')
    procs += convert(lines)
    # an opcode's memory form (OpXXM) stays inside its procedure as a label
    if i + 1 < len(blocks) and blocks[i + 1][0] == n + 'M':
        procs.append(f'{n}M:')
        procs += convert(blocks[i + 1][1])
        i += 1
    procs.append('  ProcedureReturn 0')
    procs.append('EndProcedure')
    m = re.match(r'^(G[0-9A-F]{2})[RM][0-7]$', n)
    if m:
        groups.add(m.group(1))
    i += 1

out = ['; Generated by tools/desktop_proc_variant.py from cpu86_core.pbi. Do not edit.',
       '; Procedure-table dispatch, for measuring against labels-as-values.']
pre = []
for l in head:
    pre.append(l)
out += pre
out.append('Global ' + ', '.join(f'c86_{t}.i' for t in TEMPS))
out.append('Global Dim DispP.i(256)')
out.append('Global Dim EaP.i(256)')
for g in sorted(groups):
    out.append(f'Global Dim {g}RP.i(8)')
    out.append(f'Global Dim {g}MP.i(8)')
out += procs
init = ['  If Ready = 0',
        '    For InitIndex = 0 To 255',
        '      t = InitIndex ! (InitIndex >> 4)',
        '      t = t ! (t >> 2)',
        '      t = t ! (t >> 1)',
        '      If t & 1',
        '        Par(InitIndex) = 0',
        '      Else',
        '        Par(InitIndex) = 4',
        '      EndIf',
        '    Next']
init += [f'    R8O({k}) = {v}' for k, v in enumerate([0, 2, 4, 6, 1, 3, 5, 7])]
init += [f'    DispP(${k:02X}) = @Op{k:02X}()' for k in range(256)]
init += [f'    EaP(${k:02X}) = @Ea{(k >> 6) if k < 0xC0 else 0}{k & 7}()' for k in range(256)]
for g in sorted(groups):
    init += [f'    {g}RP({k}) = @{g}R{k}()' for k in range(8)]
    init += [f'    {g}MP({k}) = @{g}M{k}()' for k in range(8)]
init += ['    Ready = 1', '  EndIf']
out += ['Procedure.i Cpu86Run(n.i)',
        '  Protected t.i',
        '  If n <= 0',
        '    ProcedureReturn 0',
        '  EndIf'] + init + [
        '  Budget = n',
        '  Left = n',
        'PResync:',
        '  SegD = SegB(3)',
        '  SegS = SegB(2)',
        '  Rep = 0',
        '  If EvPend Or Halted Or (FlagsHi & $100)',
        '    If Cpu86Events() = 0',
        '      Goto PDone',
        '    EndIf',
        '  EndIf',
        '  Cpu86Remap()',
        'PNext:',
        '  While CallFunctionFast(DispP(PeekA(PIP)))',
        '    PIP = PIP + 1',
        '    If PIP >= PEndReal',
        '      Cpu86Remap()',
        '    EndIf',
        '    PEnd = 0',
        '  Wend',
        '  Left = Left - 1',
        '  If Left = 0',
        '    Goto PDone',
        '  EndIf',
        '  If PIP >= PEnd',
        '    Goto PResync',
        '  EndIf',
        '  Goto PNext',
        'PDone:',
        '  ProcedureReturn Budget - Left',
        'EndProcedure'] + rest
(ROOT / 'desktop' / 'cpu86_core_proc.pbi').write_text('\n'.join(out), newline='\n')
print('cpu86_core_proc.pbi', len(out), 'lines,', len(groups), 'groups')
