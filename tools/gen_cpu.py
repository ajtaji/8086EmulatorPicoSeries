"""Generate the PureMetal Intel 8086 core: src/cpu86.pico (RP2040) and src/cpu86.pico2 (RP2350).

Edit this generator, never the generated files. Run:  py -3 tools/gen_cpu.py

Design (README.md has the full story):
  * 256-entry .Label dispatch table, every handler ends in its own computed jump.
  * The instruction pointer is a HOST pointer, PIP, into a fetch window: the
    guest IP is PIP - PBase. A window is one 4 KB page of RAM or ROM, cut short
    so that any instruction starting below PEnd has all six of its bytes inside
    the page and inside the 64 KB code segment. An instruction that would cross
    either is copied into Buf and run from there. Leaving the window (PIP >= PEnd)
    lands in Resync, which also restores prefix state and delivers interrupts.
  * Flags are lazy: FZS is the sign-extended result (ZF = bits 0..16 zero,
    SF = bit 31, PF = parity of the low byte of FZS ^ (FZS >> 17)), FC holds CF
    in bit 31, FO holds OF in bit 31, FA holds AF in bit 4.
  * Guest memory is 256 pages of 4 KB. PageR/PageW hold host pointers minus the
    page's linear base (so a byte is PeekA(PageR(lin >> 12) + lin)); 0 means
    "not plain memory" and sends the access to the slow procedures, which serve
    ROM (write ignored), unmapped (reads $FF) and hook pages.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
import os
VARIANT = os.environ.get('CPU86_VARIANT', '')
REP_BLOCK = False   # REP MOVS/STOS block path (emit_rep_block)

# ---------------------------------------------------------------- emitter
OUT = []
def e(s=''):
    OUT.append(s)

# Byte register number -> byte offset inside R.u(8): AL CL DL BL AH CH DH BH
R8OFF = [0, 2, 4, 6, 1, 3, 5, 7]
AX, CX, DX, BX, SP, BP, SI, DI = range(8)
ES, CS, SS, DS = range(4)

def rd_reg8_const(i):
    return f'PeekA(@R(0) + {R8OFF[i]})'

def wr_reg8_const(i, v):
    e(f'  PokeA(@R(0) + {R8OFF[i]}, {v})')

# Cycle accounting: Charge(c) only exists when #CPU_TIMING = 1.
def charge(c):
    if c:
        e(f'  Charge({c})')

def tail(cyc):
    e(f'  NextOp({cyc})')

# ---------------------------------------------------------------- memory helpers
# All take/produce locals of CpuRun: ea (linear address), eo (offset), sb (segment base).
def rd8(dst, ea='ea'):
    e(f'  t = PageR({ea} >> 12)')
    e(f'  If t <> 0')
    e(f'    {dst} = PeekA(t + {ea})')
    e(f'  Else')
    e(f'    {dst} = Cpu86Rd8({ea})')
    e(f'  EndIf')

def wr8(v, ea='ea'):
    e(f'  t = PageW({ea} >> 12)')
    e(f'  If t <> 0')
    e(f'    PokeA(t + {ea}, {v})')
    e(f'  Else')
    e(f'    Cpu86Wr8({ea}, {v})')
    e(f'  EndIf')

def rd16(dst, sb='sb', eo='eo', ea='ea'):
    e(f'  t = PageR({ea} >> 12)')
    e(f'  If (~{ea} << 28) = 0              ; xxxF: maybe a page or segment end')
    e(f'    t = 0')
    e(f'  EndIf')
    e(f'  If t <> 0')
    e(f'    {dst} = PeekA(t + {ea}) | (PeekA(t + {ea} + 1) << 8)')
    e(f'  Else')
    e(f'    {dst} = Cpu86Rd16({sb}, {eo})')
    e(f'  EndIf')

def wr16(v, sb='sb', eo='eo', ea='ea'):
    e(f'  t = PageW({ea} >> 12)')
    e(f'  If (~{ea} << 28) = 0              ; xxxF: maybe a page or segment end')
    e(f'    t = 0')
    e(f'  EndIf')
    e(f'  If t <> 0')
    e(f'    PokeA(t + {ea}, {v})')
    e(f'    PokeA(t + {ea} + 1, {v} >> 8)')
    e(f'  Else')
    e(f'    Cpu86Wr16({sb}, {eo}, {v})')
    e(f'  EndIf')

def push16(v):
    """Push v (an expression that does not use eo/ea/t) on SS:SP."""
    e(f'  eo = (R({SP}) - 2) & $FFFF')
    e(f'  R({SP}) = eo')
    e(f'  ea = SegB({SS}) + eo')
    wr16(v, sb=f'SegB({SS})')

def pop16(dst):
    e(f'  eo = R({SP})')
    e(f'  ea = SegB({SS}) + eo')
    rd16(dst, sb=f'SegB({SS})')
    e(f'  R({SP}) = eo + 2')

def ip_now():
    """Expression: the guest IP of PIP (masked)."""
    return '((PIP - PBase) & $FFFF)'

def jump_near(target):
    """IP := target (already masked to 16 bits) within the current CS."""
    e(f'  PIP = PBase + {target}')
    e(f'  If PIP < PStart')
    e(f'    PEnd = 0')
    e(f'  EndIf')

def jump_rel(expr_disp, length):
    """Relative jump from the end of an instruction of `length` bytes at PIP."""
    e(f'  PIP = PIP + {length} + {expr_disp}')
    e(f'  If PIP < PStart')
    e(f'    PEnd = 0')
    e(f'  EndIf')

def far_jump(cs_expr, ip_expr):
    """CS:IP := cs:ip. Values must be held in locals that are not ea/eo/t."""
    e(f'  SegV({CS}) = {cs_expr}')
    e(f'  SegB({CS}) = ({cs_expr}) << 4')
    e(f'  PBase = 0')
    e(f'  PIP = {ip_expr}')
    e(f'  PEnd = 0')

# ---------------------------------------------------------------- flags
def sz(w):
    """(shift for CF, shift for OF, shift for sign extension)"""
    return (15, 16, 16) if w else (23, 24, 24)

def set_zs(w, v):
    s = sz(w)[2]
    e(f'  FZS = ({v} << {s}) >> {s}')

def alu(op, w, a='va', b='vb', r='vr'):
    """Emit vr = a <op> b with flags. op in ADD OR ADC SBB AND SUB XOR CMP TEST."""
    sc, so, _ = sz(w)
    if op == 'ADD':
        e(f'  {r} = {a} + {b}')
    elif op == 'ADC':
        e(f'  {r} = {a} + {b} + ((FC >> 31) & 1)')
    elif op in ('SUB', 'CMP'):
        e(f'  {r} = {a} - {b}')
    elif op == 'SBB':
        e(f'  {r} = {a} - {b} - ((FC >> 31) & 1)')
    elif op in ('AND', 'TEST'):
        e(f'  {r} = {a} & {b}')
    elif op == 'OR':
        e(f'  {r} = {a} | {b}')
    elif op == 'XOR':
        e(f'  {r} = {a} ! {b}')
    else:
        raise ValueError(op)
    if op in ('ADD', 'ADC'):
        e(f'  FC = {r} << {sc}')
        e(f'  FO = (({a} ! {r}) & ({b} ! {r})) << {so}')
        e(f'  FA = {a} ! {b}')
    elif op in ('SUB', 'CMP', 'SBB'):
        e(f'  FC = {r} << {sc}')
        e(f'  FO = (({a} ! {b}) & ({a} ! {r})) << {so}')
        e(f'  FA = {a} ! {b}')
    else:
        e(f'  FC = 0')
        e(f'  FO = 0')
        e(f'  FA = {r}')
    set_zs(w, r)
    return op not in ('CMP', 'TEST')

ALU_OPS = ['ADD', 'OR', 'ADC', 'SBB', 'AND', 'SUB', 'XOR', 'CMP']

# ---------------------------------------------------------------- operand access
# A "modrm instruction" has a register path (mod = 3) and a memory path.
# body(kind) emits the operation; kind is 'r' or 'm'. Accessors below read/write
# the E operand; the register path has already advanced PIP past opcode+modrm,
# the memory path past opcode+modrm+displacement, so an immediate is at PIP.
def e_read(kind, w, dst):
    if kind == 'r':
        if w:
            e(f'  {dst} = R(m & 7)')
        else:
            e(f'  {dst} = PeekA(@R(0) + R8O(m & 7))')
    else:
        if w:
            rd16(dst)
        else:
            rd8(dst)

def e_write(kind, w, v):
    if kind == 'r':
        if w:
            e(f'  R(m & 7) = {v}')
        else:
            e(f'  PokeA(@R(0) + R8O(m & 7), {v})')
    else:
        if w:
            wr16(v)
        else:
            wr8(v)

def g_read(w, dst):
    if w:
        e(f'  {dst} = R((m >> 3) & 7)')
    else:
        e(f'  {dst} = PeekA(@R(0) + R8O((m >> 3) & 7))')

def g_write(w, v):
    if w:
        e(f'  R((m >> 3) & 7) = {v}')
    else:
        e(f'  PokeA(@R(0) + R8O((m >> 3) & 7), {v})')

def imm(w, dst, signext=False):
    if w and not signext:
        e(f'  {dst} = PeekA(PIP) | (PeekA(PIP + 1) << 8)')
        e(f'  PIP = PIP + 2')
    elif signext:
        e(f'  {dst} = PeekB(PIP) & $FFFF')
        e(f'  PIP = PIP + 1')
    else:
        e(f'  {dst} = PeekA(PIP)')
        e(f'  PIP = PIP + 1')

HANDLERS = {}     # opcode -> label
SUBLABELS = []    # (table name, size)

def modrm_handler(label, body, rcyc, mcyc):
    """Opcode with a ModR/M byte. body(kind) emits the work, then the tail is added."""
    e(f'{label}:')
    e(f'  m = PeekA(PIP + 1)')
    e(f'  If m < $C0')
    e(f'    EaRet = ?{label}M')
    e(f'    Goto EaTab(m)')
    e(f'  EndIf')
    e(f'  PIP = PIP + 2')
    body('r')
    tail(rcyc)
    e(f'{label}M:')
    body('m')
    tail(mcyc)

def group_handler(label, table, bodies, rcyc, mcyc):
    """Opcode with a ModR/M byte whose reg field selects the operation."""
    e(f'{label}:')
    e(f'  m = PeekA(PIP + 1)')
    e(f'  If m < $C0')
    e(f'    EaRet = {table}M((m >> 3) & 7)')
    e(f'    Goto EaTab(m)')
    e(f'  EndIf')
    e(f'  PIP = PIP + 2')
    e(f'  Goto {table}R((m >> 3) & 7)')
    SUBLABELS.append(table)
    for k in range(8):
        for kind in 'rm':
            e(f'{table}{kind.upper()}{k}:')
            bodies[k](kind)
            c = (rcyc if kind == 'r' else mcyc)
            c = c[k] if isinstance(c, (list, tuple)) else c
            tail(c)

# ---------------------------------------------------------------- the generator
def generate(target):
    OUT.clear()
    SUBLABELS.clear()
    rp2350 = target == 'rp2350'
    e('; Generated by tools/gen_cpu.py. Edit the generator, then regenerate.')
    e('; Intel 8086 interpreter core for the Raspberry Pi Pico series, PureMetal.')
    e(f'; Target: {target}. See README.md for the API, memory map and limits.')
    e(';')
    e('; Configuration, declared by the including program before XIncludeFile:')
    e(';   #CPU_TIMING   0 = budget in instructions, 1 = budget in 8086 clocks')
    e(';   #CPU_ASM_TAIL 1 = inline-assembly dispatch tail, 0 = PureMetal Goto')
    e(';')
    e('; The including program defines four procedures (any order):')
    e(';   Cpu86HookRead.i(lin.i)            byte read from a hook page')
    e(';   Cpu86HookWrite(lin.i, v.i)        byte write to a hook page')
    e(';   Cpu86PortIn.i(port.i, wide.i)     IN: wide = 0 byte, 1 word')
    e(';   Cpu86PortOut(port.i, v.i, wide.i) OUT')
    e('EnableExplicit')
    e('')
    e('#CPU86_PAGES = 256              ; 1 MB in 4 KB pages')
    e('#CPU86_RAM = 0                  ; page kinds')
    e('#CPU86_ROM = 1')
    e('#CPU86_NONE = 2')
    e('#CPU86_HOOK = 3')
    e('')
    e('Global Dim R.u(8)               ; AX CX DX BX SP BP SI DI')
    e('Global Dim SegV.u(4)            ; ES CS SS DS')
    e('Global Dim SegB.i(4)            ; segment bases (value << 4)')
    e('Global Dim PageR.i(#CPU86_PAGES + 16) ; 256-271 mirror 0-15: seg + off < $110000')
    e('Global Dim PageW.i(#CPU86_PAGES + 16)')
    e('Global Dim PageK.a(#CPU86_PAGES)')
    e('Global Dim PageH.i(#CPU86_PAGES) ; host base of a ROM/RAM page (for slow paths)')
    e('Global Dim Dispatch.Label(256)')
    e('Global Dim EaTab.Label(256)')
    e('Global Dim EaSmall.Label(32)     ; mod * 8 + rm')
    e('Global Dim Par.a(256)           ; 4 when the byte has even parity')
    e('Global Dim R8O.a(8)             ; byte register -> byte offset in R')
    e('Global Dim Buf.a(8)             ; instructions that cross a page or IP wrap')
    e('Global EaRet.Label')
    e('Global PIP.i, PEnd.i, FZS.i, FC.i, FO.i, Left.i, FA.i')
    e('Global PBase.i, PStart.i, PEndReal.i')
    e('Global SegD.i, SegS.i, Rep.i')
    e('Global FlagsHi.i, DirStep.i, DirStep2.i')
    e('Global EvPend.i, IrqVector.i, Halted.i')
    e('Global Budget.i, Ready.i, CpuCycles.i, InitIndex.i, Cpu86Fetching.i')
    # Left in r6 lets the tail decrement it in place; r5 must stay free (the
    # RP2040 allocator needs one of r5/r6 for its spill pool).
    e('ReserveRegister PIP = r4, Left = r6, FZS = r8, FC = r9, FO = r10, PEnd = r11')
    e('')
    e('; EvPend bits: 1 trap armed, 2 NMI, 4 IRQ, 8 inhibit interrupts for one boundary.')
    e('')
    e('Macro Charge(c)')
    e('  CompilerIf #CPU_TIMING = 1')
    e('    Left = Left - (c)')
    e('  CompilerEndIf')
    e('EndMacro')
    e('')
    emit_slow_procs()
    emit_api()
    emit_run(rp2350)
    return '\n'.join(OUT) + '\n'

def emit_slow_procs():
    e('; ------------------------------------------------------------ slow memory paths')
    e('; Any linear address, any page kind. Hook pages call the program\'s hooks.')
    e('ProcedureRAM.i Cpu86Rd8(lin.i)')
    e('  Protected k.i')
    e('  lin = lin & $FFFFF')
    e('  k = PageK(lin >> 12)')
    e('  If k = #CPU86_HOOK')
    e('    ProcedureReturn Cpu86HookRead(lin) & 255')
    e('  EndIf')
    e('  If k = #CPU86_NONE')
    e('    ProcedureReturn 255')
    e('  EndIf')
    e('  ProcedureReturn PeekA(PageH(lin >> 12) + (lin & $FFF))')
    e('EndProcedure')
    e('')
    e('ProcedureRAM Cpu86Wr8(lin.i, v.i)')
    e('  Protected k.i')
    e('  lin = lin & $FFFFF')
    e('  k = PageK(lin >> 12)')
    e('  If k = #CPU86_RAM')
    e('    PokeA(PageH(lin >> 12) + (lin & $FFF), v)')
    e('  ElseIf k = #CPU86_HOOK')
    e('    Cpu86HookWrite(lin, v & 255)')
    e('  EndIf')
    e('EndProcedure')
    e('')
    e('; Word at seg:off; the second byte is at seg:(off + 1) & $FFFF, as on the 8086.')
    e('ProcedureRAM.i Cpu86Rd16(sb.i, off.i)')
    e('  Protected lo.i')
    e('  lo = Cpu86Rd8(sb + off)')
    e('  ProcedureReturn lo | (Cpu86Rd8(sb + ((off + 1) & $FFFF)) << 8)')
    e('EndProcedure')
    e('')
    e('ProcedureRAM Cpu86Wr16(sb.i, off.i, v.i)')
    e('  Cpu86Wr8(sb + off, v)')
    e('  Cpu86Wr8(sb + ((off + 1) & $FFFF), v >> 8)')
    e('EndProcedure')
    e('')

def emit_api():
    e('; ------------------------------------------------------------ flags')
    e('ProcedureRAM.i Cpu86Flags()')
    e('  Protected f.i')
    e('  f = FlagsHi')
    e('  If FC < 0')
    e('    f = f | 1')
    e('  EndIf')
    e('  f = f | Par((FZS ! (FZS >> 17)) & 255)')
    e('  f = f | ((FA ! FZS) & $10)')
    e('  If (FZS << 15) = 0')
    e('    f = f | $40')
    e('  EndIf')
    e('  If FZS < 0')
    e('    f = f | $80')
    e('  EndIf')
    e('  If FO < 0')
    e('    f = f | $800')
    e('  EndIf')
    e('  ProcedureReturn f')
    e('EndProcedure')
    e('')
    e('; Load all flags. Bits 12-15 read as 1 and bits 3 and 5 as 0 on the 8086.')
    e('ProcedureRAM Cpu86SetFlags(f.i)')
    e('  Protected z.i')
    e('  FC = (f & 1) << 31')
    e('  FO = (f & $800) << 20')
    e('  If f & $40')
    e('    z = 0')
    e('    If (f & 4) = 0')
    e('      z = $20000')
    e('    EndIf')
    e('  Else')
    e('    z = 1')
    e('    If f & 4')
    e('      z = $20001')
    e('    EndIf')
    e('  EndIf')
    e('  If f & $80')
    e('    z = z | $80000000')
    e('  EndIf')
    e('  FZS = z')
    e('  FA = (f & $10) ! z')
    e('  If (f & $300) & ~(FlagsHi & $300)')
    e('    PEnd = 0                     ; TF or IF just set: check at the next boundary')
    e('  EndIf')
    e('  FlagsHi = (f & $0700) | $F002')
    e('  If f & $400')
    e('    DirStep = -1')
    e('    DirStep2 = -2')
    e('  Else')
    e('    DirStep = 1')
    e('    DirStep2 = 2')
    e('  EndIf')
    e('EndProcedure')
    e('')
    e('; ------------------------------------------------------------ registers')
    e('Procedure.i Cpu86GetIP()')
    e(f'  ProcedureReturn {ip_now()}')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86SetIP(ip.i)')
    e('  PBase = 0')
    e('  PIP = ip & $FFFF')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('; Segment register i: 0 ES, 1 CS, 2 SS, 3 DS.')
    e('Procedure Cpu86SetSeg(i.i, v.i)')
    e('  Protected ip.i')
    e(f'  ip = {ip_now()}')
    e('  SegV(i) = v & $FFFF')
    e('  SegB(i) = (v & $FFFF) << 4')
    e('  PBase = 0')
    e('  PIP = ip')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('Procedure.i Cpu86GetSeg(i.i)')
    e('  ProcedureReturn SegV(i)')
    e('EndProcedure')
    e('')
    e('; ------------------------------------------------------------ memory map')
    e('; Pages are 4 KB; lin and bytes must be multiples of 4096. host is the')
    e('; address of the first byte (SRAM for RAM, flash or SRAM for ROM).')
    e('Procedure Cpu86MapPages(lin.i, bytes.i, kind.i, host.i)')
    e('  Protected p.i, n.i')
    e('  p = (lin >> 12) & 255')
    e('  n = bytes >> 12')
    e('  While n > 0')
    e('    PageK(p) = kind')
    e('    PageH(p) = host')
    e('    PageR(p) = 0')
    e('    PageW(p) = 0')
    e('    If kind = #CPU86_RAM')
    e('      PageR(p) = host - (p << 12)')
    e('      PageW(p) = host - (p << 12)')
    e('    ElseIf kind = #CPU86_ROM')
    e('      PageR(p) = host - (p << 12)')
    e('    EndIf')
    e('    If p < 16                   ; the mirror above 1 MB (the 8086 wraps there)')
    e('      PageR(p + 256) = 0')
    e('      PageW(p + 256) = 0')
    e('      If PageR(p)')
    e('        PageR(p + 256) = PageR(p) - $100000')
    e('      EndIf')
    e('      If PageW(p)')
    e('        PageW(p + 256) = PageW(p) - $100000')
    e('      EndIf')
    e('    EndIf')
    e('    host = host + 4096')
    e('    p = (p + 1) & 255')
    e('    n = n - 1')
    e('  Wend')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86MapRam(lin.i, bytes.i, host.i)')
    e('  Cpu86MapPages(lin, bytes, #CPU86_RAM, host)')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86MapRom(lin.i, bytes.i, host.i)')
    e('  Cpu86MapPages(lin, bytes, #CPU86_ROM, host)')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86MapHook(lin.i, bytes.i)')
    e('  Cpu86MapPages(lin, bytes, #CPU86_HOOK, 0)')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86MapNone(lin.i, bytes.i)')
    e('  Cpu86MapPages(lin, bytes, #CPU86_NONE, 0)')
    e('EndProcedure')
    e('')
    e('; ------------------------------------------------------------ fetch window')
    e('; Recompute PIP/PBase/PStart/PEnd for the current CS:IP. Prefix state is')
    e('; untouched, so a prefix may call this in the middle of an instruction.')
    e('ProcedureRAM Cpu86Remap()')
    e('  Protected ip.i, lin.i, p.i, en.i, k.i')
    e(f'  ip = {ip_now()}')
    e(f'  lin = (SegB({CS}) + ip) & $FFFFF')
    e('  p = PageR(lin >> 12)')
    e('  If ip > $FFFA')
    e('    p = 0')
    e('  EndIf')
    e('  If (lin & $FFF) > $FFA')
    e('    p = 0')
    e('  EndIf')
    e('  If p <> 0')
    e('    PBase = p + lin - ip')
    e('    PIP = p + lin')
    e('    PStart = p + (lin & $FF000)')
    e('    en = p + (lin | $FFF) - 4')
    e('    k = PBase + $FFFB')
    e('    If k < en')
    e('      en = k')
    e('    EndIf')
    e('    PEndReal = en')
    e('  Else')
    e('    Cpu86Fetching = 1           ; hooks: this is an instruction prefetch')
    e('    For k = 0 To 5')
    e(f'      Buf(k) = Cpu86Rd8(SegB({CS}) + ((ip + k) & $FFFF))')
    e('    Next')
    e('    Cpu86Fetching = 0')
    e('    PBase = @Buf(0) - ip')
    e('    PIP = @Buf(0)')
    e('    PStart = $7FFFFFFF')
    e('    PEndReal = PIP + 1')
    e('  EndIf')
    e('  PEnd = PEndReal')
    e('  If FlagsHi & $100')
    e('    PEnd = 0')
    e('  EndIf')
    e('  If EvPend & 11')
    e('    PEnd = 0')
    e('  EndIf')
    e('  If (EvPend & 4) And (FlagsHi & $200)')
    e('    PEnd = 0')
    e('  EndIf')
    e('EndProcedure')
    e('')
    e('; ------------------------------------------------------------ interrupts')
    e('; Push FLAGS, CS, IP (the IP of PIP); clear IF and TF; jump through the IVT.')
    e('ProcedureRAM Cpu86Interrupt(n.i)')
    e('  Protected f.i, ip.i, sp.i, ncs.i, nip.i')
    e('  f = Cpu86Flags()')
    e(f'  ip = {ip_now()}')
    e(f'  sp = (R({SP}) - 2) & $FFFF')
    e(f'  Cpu86Wr16(SegB({SS}), sp, f)')
    e('  sp = (sp - 2) & $FFFF')
    e(f'  Cpu86Wr16(SegB({SS}), sp, SegV({CS}))')
    e('  sp = (sp - 2) & $FFFF')
    e(f'  Cpu86Wr16(SegB({SS}), sp, ip)')
    e(f'  R({SP}) = sp')
    e('  FlagsHi = FlagsHi & ~$300')
    e('  EvPend = EvPend & ~1')
    e('  nip = Cpu86Rd16(0, (n & 255) << 2)')
    e('  ncs = Cpu86Rd16(0, ((n & 255) << 2) + 2)')
    e(f'  SegV({CS}) = ncs')
    e(f'  SegB({CS}) = ncs << 4')
    e('  PBase = 0')
    e('  PIP = nip')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('; At an instruction boundary with EvPend or Halted set. Returns 0 when the CPU')
    e('; is halted with nothing to wake it.')
    e('ProcedureRAM.i Cpu86Events()')
    e('  If EvPend & 8')
    e('    EvPend = EvPend & ~8')
    e('  ElseIf EvPend & 1')
    e('    Cpu86Interrupt(1)')
    e('  ElseIf EvPend & 2')
    e('    EvPend = EvPend & ~2')
    e('    Halted = 0')
    e('    Cpu86Interrupt(2)')
    e('  ElseIf (EvPend & 4) And (FlagsHi & $200)')
    e('    EvPend = EvPend & ~4')
    e('    Halted = 0')
    e('    Cpu86Interrupt(IrqVector)')
    e('  EndIf')
    e('  If Halted')
    e('    ProcedureReturn 0')
    e('  EndIf')
    e('  If FlagsHi & $100')
    e('    EvPend = EvPend | 1')
    e('  EndIf')
    e('  ProcedureReturn 1')
    e('EndProcedure')
    e('')
    e('; Maskable interrupt request: held until IF = 1, then taken through `vector`.')
    e('Procedure Cpu86Irq(vector.i)')
    e('  IrqVector = vector & 255')
    e('  EvPend = EvPend | 4')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86IrqCancel()')
    e('  EvPend = EvPend & ~4')
    e('EndProcedure')
    e('')
    e('Procedure Cpu86Nmi()')
    e('  EvPend = EvPend | 2')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')
    e('; Power-on state: CS:IP = FFFF:0000, other segments 0, FLAGS = F002.')
    e('Procedure Cpu86Reset()')
    e('  Protected i.i')
    e('  For i = 0 To 7')
    e('    R(i) = 0')
    e('  Next')
    e('  For i = 0 To 3')
    e('    SegV(i) = 0')
    e('    SegB(i) = 0')
    e('  Next')
    e(f'  SegV({CS}) = $FFFF')
    e(f'  SegB({CS}) = $FFFF0')
    e('  Cpu86SetFlags($F002)')
    e('  EvPend = 0')
    e('  Halted = 0')
    e('  Rep = 0')
    e('  CpuCycles = 0')
    e('  PBase = 0')
    e('  PIP = 0')
    e('  PEnd = 0')
    e('EndProcedure')
    e('')

# ---------------------------------------------------------------- CpuRun
EACYC = {  # mod 0/1/2 rm -> clocks (Intel 8086 manual)
    0: [7, 8, 8, 7, 5, 5, 6, 5],
    1: [11, 12, 12, 11, 9, 9, 9, 9],
    2: [11, 12, 12, 11, 9, 9, 9, 9],
}
EABASE = ['(R(3) + R(6))', '(R(3) + R(7))', '(R(5) + R(6))', '(R(5) + R(7))',
          'R(6)', 'R(7)', 'R(5)', 'R(3)']

def emit_ea():
    for mod in range(3):
        for rm in range(8):
            e(f'Ea{mod}{rm}:')
            seg = 'SegS' if rm in (2, 3) or (rm == 6 and mod != 0) else 'SegD'
            if mod == 0 and rm == 6:
                e('  eo = PeekA(PIP + 2) | (PeekA(PIP + 3) << 8)')
                e('  PIP = PIP + 4')
            elif mod == 0 and rm >= 4:
                e(f'  eo = {EABASE[rm]}')
                e('  PIP = PIP + 2')
            elif mod == 0:
                e(f'  eo = {EABASE[rm]} & $FFFF')
                e('  PIP = PIP + 2')
            elif mod == 1:
                e(f'  eo = ({EABASE[rm]} + PeekB(PIP + 2)) & $FFFF')
                e('  PIP = PIP + 3')
            else:
                e(f'  eo = ({EABASE[rm]} + (PeekA(PIP + 2) | (PeekA(PIP + 3) << 8))) & $FFFF')
                e('  PIP = PIP + 4')
            e(f'  sb = {seg}')
            e('  ea = sb + eo')
            charge(EACYC[mod][rm])
            e('  Goto EaRet')

def emit_run(rp2350):
    e('; ------------------------------------------------------------ the interpreter')
    e('; Cpu86Run(n): execute until the budget n is spent (instructions, or clocks')
    e('; with #CPU_TIMING = 1). A REP string instruction is one instruction. Returns')
    e('; the budget used; stops early when the CPU halts (Halted = 1).')
    e('ProcedureRAM.i Cpu86Run(n.i)')
    e('  Protected m.i, t.i, ea.i, eo.i, sb.i, va.i, vb.i, vr.i, cnt.i, x.i, y.i')
    e('Macro NextOp(c)')
    e('  CompilerIf #CPU_TIMING = 1')
    e('    Left = Left - (c)')
    e('    If Left <= 0')
    e('      Goto Done')
    e('    EndIf')
    e('    CompilerIf #CPU_ASM_TAIL = 1')
    if rp2350:
        e('      ASM Uses PIP, PEnd')
        e('        cmp r4, ' + 'r11')
        e('        bhs __ul_cpu86run_resync')
        e('        ldrb r0, [r4]')
        e('        lsls r0, r0, #2')
        e('        ldr r1, =global_dispatch')
        e('        ldr r1, [r1, r0]')
        e('        bx r1')
        e('      EndASM')
    else:
        e('      ASM Uses PIP, PEnd')
        e('        cmp r4, ' + 'r11')
        e('        bhs __ul_cpu86run_resync')
        e('        ldrb r0, [r4]')
        e('        lsls r0, r0, #2')
        e('        ldr r1, =global_dispatch')
        e('        ldr r1, [r1, r0]')
        e('        bx r1')
        e('      EndASM')
    e('    CompilerElse')
    e('      If PIP >= PEnd')
    e('        Goto Resync')
    e('      EndIf')
    e('      Goto Dispatch(PeekA(PIP))')
    e('    CompilerEndIf')
    e('  CompilerElse')
    e('    CompilerIf #CPU_ASM_TAIL = 1')
    e('      ASM Uses Left, PIP, PEnd')
    if True:  # Left in r6, PEnd in r11 (measured faster than PEnd r5 / Left r11)
        e('        subs r6, #1')
        e('        beq __ul_cpu86run_done')
        e('        cmp r4, r11')
        e('        bhs __ul_cpu86run_resync')
    else:
        e('        mov r0, r11')
        e('        subs r0, #1')
        e('        mov r11, r0')
        e('        beq __ul_cpu86run_done')
        e('        cmp r4, r5')
        e('        bhs __ul_cpu86run_resync')
    e('        ldrb r0, [r4]')
    e('        lsls r0, r0, #2')
    e('        ldr r1, =global_dispatch')
    e('        ldr r1, [r1, r0]')
    e('        bx r1')
    e('      EndASM')
    e('    CompilerElse')
    e('      Left = Left - 1')
    e('      If Left = 0')
    e('        Goto Done')
    e('      EndIf')
    e('      If PIP >= PEnd')
    e('        Goto Resync')
    e('      EndIf')
    e('      Goto Dispatch(PeekA(PIP))')
    e('    CompilerEndIf')
    e('  CompilerEndIf')
    e('EndMacro')
    e('  If n <= 0')
    e('    ProcedureReturn 0')
    e('  EndIf')
    e('  If Ready = 0')
    e('    For InitIndex = 0 To 255')
    e('      t = InitIndex ! (InitIndex >> 4)')
    e('      t = t ! (t >> 2)')
    e('      t = t ! (t >> 1)')
    e('      If t & 1')
    e('        Par(InitIndex) = 0')
    e('      Else')
    e('        Par(InitIndex) = 4')
    e('      EndIf')
    e('    Next')
    for i, o in enumerate(R8OFF):
        e(f'    R8O({i}) = {o}')
    for op in range(256):
        e(f'    Dispatch(${op:02X}) = ?Op{op:02X}')
    for mod in range(3):
        for rm in range(8):
            e(f'    EaSmall({mod * 8 + rm}) = ?Ea{mod}{rm}')
    e('    For InitIndex = 0 To 255')
    e('      EaTab(InitIndex) = EaSmall(((InitIndex >> 3) & $18) | (InitIndex & 7))')
    e('    Next')
    e('    InitTables()')
    e('    Ready = 1')
    e('  EndIf')
    e('  Budget = n')
    e('  Left = n')
    e('  Goto Resync')
    e('')
    # Resync: instruction boundary slow path.
    e('Resync:')
    e(f'  SegD = SegB({DS})')
    e(f'  SegS = SegB({SS})')
    e('  Rep = 0')
    e('  If EvPend Or Halted Or (FlagsHi & $100)')
    e('    If Cpu86Events() = 0')
    e('      Goto Done')
    e('    EndIf')
    e('  EndIf')
    e('  Cpu86Remap()')
    e('  Goto Dispatch(PeekA(PIP))')
    e('')
    e('PrefixNext:')
    e('  PIP = PIP + 1')
    e('  If PIP >= PEndReal')
    e('    Cpu86Remap()')
    e('  EndIf')
    e('  PEnd = 0')
    e('  Goto Dispatch(PeekA(PIP))')
    e('')
    emit_ea()
    emit_handlers()
    e('Done:')
    e('  ProcedureReturn Budget - Left')
    e('EndProcedure')
    # Sub-label tables, filled once from CpuRun's init (labels belong to CpuRun,
    # so the table fill must be written inside it: done via InitTables macro).
    tables = []
    for tname in SUBLABELS:
        tables.append(tname)
    # Insert the table declarations and InitTables macro before CpuRun.
    decl = []
    for tname in tables:
        decl.append(f'Global Dim {tname}R.Label(8)')
        decl.append(f'Global Dim {tname}M.Label(8)')
    decl.append('Macro InitTables()')
    for tname in tables:
        for k in range(8):
            decl.append(f'  {tname}R({k}) = ?{tname}R{k}')
            decl.append(f'  {tname}M({k}) = ?{tname}M{k}')
    decl.append('EndMacro')
    idx = OUT.index('; ------------------------------------------------------------ the interpreter')
    OUT[idx:idx] = decl + ['']

# ---------------------------------------------------------------- handlers
def emit_handlers():
    defined = set()

    def op(n):
        defined.add(n)
        e(f'Op{n:02X}:')

    # ---- ALU block 00-3F
    for i, name in enumerate(ALU_OPS):
        base = i * 8
        for form in range(6):
            n = base + form
            w = form & 1
            if form in (0, 1):            # E, G
                def body(kind, name=name, w=w):
                    e_read(kind, w, 'va')
                    g_read(w, 'vb')
                    if alu(name, w):
                        e_write(kind, w, 'vr')
                defined.add(n)
                rc, mc = (3, 16 if name != 'CMP' else 9)
                modrm_handler(f'Op{n:02X}', body, rc, mc)
            elif form in (2, 3):          # G, E
                def body(kind, name=name, w=w):
                    g_read(w, 'va')
                    e_read(kind, w, 'vb')
                    if alu(name, w):
                        g_write(w, 'vr')
                defined.add(n)
                modrm_handler(f'Op{n:02X}', body, 3, 9)
            elif form == 4:               # AL, ib
                op(n)
                e(f'  va = {rd_reg8_const(0)}')
                e('  vb = PeekA(PIP + 1)')
                e('  PIP = PIP + 2')
                if alu(name, 0):
                    wr_reg8_const(0, 'vr')
                tail(4)
            else:                         # AX, iw
                op(n)
                e('  va = R(0)')
                e('  vb = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
                e('  PIP = PIP + 3')
                if alu(name, 1):
                    e('  R(0) = vr')
                tail(4)

    # ---- segment push/pop, prefixes, BCD
    for sr, (pu, po) in enumerate([(0x06, 0x07), (0x0E, 0x0F), (0x16, 0x17), (0x1E, 0x1F)]):
        op(pu)
        e('  PIP = PIP + 1')
        push16(f'SegV({sr})')
        tail(10)
        op(po)
        e('  PIP = PIP + 1')
        pop16('va')
        emit_set_seg(sr, 'va')
        tail(8)
    for sr, pre in enumerate([0x26, 0x2E, 0x36, 0x3E]):
        op(pre)
        e(f'  SegD = SegB({sr})')
        e(f'  SegS = SegB({sr})')
        charge(2)
        e('  Goto PrefixNext')
    emit_bcd(op)

    # ---- INC/DEC/PUSH/POP r16
    for r in range(8):
        op(0x40 + r)
        e(f'  va = R({r})')
        e('  vr = va + 1')
        e('  FO = (vr & ~va) << 16')
        e('  FA = va                 ; AF = bit 4 of FA ^ result (the 1 adds nothing there)')
        set_zs(1, 'vr')
        e(f'  R({r}) = vr')
        e('  PIP = PIP + 1')
        tail(2)
        op(0x48 + r)
        e(f'  va = R({r})')
        e('  vr = va - 1')
        e('  FO = (va & ~vr) << 16')
        e('  FA = va                 ; AF = bit 4 of FA ^ result (the 1 adds nothing there)')
        set_zs(1, 'vr')
        e(f'  R({r}) = vr')
        e('  PIP = PIP + 1')
        tail(2)
        op(0x50 + r)
        e('  PIP = PIP + 1')
        if r == SP:
            e('  eo = (R(4) - 2) & $FFFF')
            e('  R(4) = eo')
            e(f'  ea = SegB({SS}) + eo')
            wr16('eo', sb=f'SegB({SS})')
        else:
            e(f'  va = R({r})')
            push16('va')
        tail(11)
        op(0x58 + r)
        e('  PIP = PIP + 1')
        pop16('va')
        e(f'  R({r}) = va')
        tail(8)

    # ---- Jcc (70-7F) and their 8086 aliases (60-6F)
    conds = [
        'FO < 0', 'FO >= 0', 'FC < 0', 'FC >= 0',
        '(FZS << 15) = 0', '(FZS << 15) <> 0',
        '(FC < 0) Or ((FZS << 15) = 0)', '(FC >= 0) And ((FZS << 15) <> 0)',
        'FZS < 0', 'FZS >= 0',
        'Par((FZS ! (FZS >> 17)) & 255) <> 0', 'Par((FZS ! (FZS >> 17)) & 255) = 0',
        '(FZS ! FO) < 0', '(FZS ! FO) >= 0',
        '((FZS ! FO) < 0) Or ((FZS << 15) = 0)', '((FZS ! FO) >= 0) And ((FZS << 15) <> 0)',
    ]
    for k in range(16):
        for base in (0x70, 0x60):
            op(base + k)
            e(f'  If {conds[k]}')
            jump_rel('PeekB(PIP + 1)', 2)
            charge(12)
            e('  Else')
            e('    PIP = PIP + 2')
            e('  EndIf')
            tail(4)

    # ---- group 1: 80 81 82 83
    for opc in (0x80, 0x81, 0x82, 0x83):
        w = 1 if opc in (0x81, 0x83) else 0
        bodies = []
        for k, name in enumerate(ALU_OPS):
            def body(kind, name=name, w=w, opc=opc):
                e_read(kind, w, 'va')
                imm(w, 'vb', signext=(opc == 0x83))
                if alu(name, w):
                    e_write(kind, w, 'vr')
            bodies.append(body)
        defined.add(opc)
        group_handler(f'Op{opc:02X}', f'G{opc:02X}', bodies, 4, [17] * 7 + [10])

    # ---- TEST, XCHG, MOV
    for n, w in ((0x84, 0), (0x85, 1)):
        def body(kind, w=w):
            e_read(kind, w, 'va')
            g_read(w, 'vb')
            alu('TEST', w)
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 3, 9)
    for n, w in ((0x86, 0), (0x87, 1)):
        def body(kind, w=w):
            e_read(kind, w, 'va')
            g_read(w, 'vb')
            e_write(kind, w, 'vb')
            g_write(w, 'va')
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 4, 17)
    for n, w in ((0x88, 0), (0x89, 1)):
        def body(kind, w=w):
            g_read(w, 'va')
            e_write(kind, w, 'va')
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 2, 9)
    for n, w in ((0x8A, 0), (0x8B, 1)):
        def body(kind, w=w):
            e_read(kind, w, 'va')
            g_write(w, 'va')
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 2, 8)
    # 8C: MOV Ew, Sw (reg & 3)
    def body8c(kind):
        e('  va = SegV((m >> 3) & 3)')
        e_write(kind, 1, 'va')
    defined.add(0x8C)
    modrm_handler('Op8C', body8c, 2, 9)
    # 8D: LEA (register form undefined; treated as using the register value)
    def body8d(kind):
        if kind == 'r':
            e('  va = R(m & 7)')
            g_write(1, 'va')
        else:
            g_write(1, 'eo')
    defined.add(0x8D)
    modrm_handler('Op8D', body8d, 2, 2)
    # 8E: MOV Sw, Ew (reg & 3; MOV CS is legal on the 8086)
    def body8e(kind):
        e_read(kind, 1, 'va')
        e('  x = (m >> 3) & 3')
        e('  If x = 1')
        e(f'    x = {ip_now()}')
        far_jump('va', 'x')
        e('  ElseIf x = 2')
        e(f'    SegV({SS}) = va')
        e(f'    SegB({SS}) = va << 4')
        e(f'    SegS = SegB({SS})')
        e('    EvPend = EvPend | 8')
        e('    PEnd = 0')
        e('  Else')
        e('    SegV(x) = va')
        e('    SegB(x) = va << 4')
        e(f'    SegD = SegB({DS})')
        e('  EndIf')
    defined.add(0x8E)
    modrm_handler('Op8E', body8e, 2, 8)
    # 8F: POP Ew (reg field ignored)
    def body8f(kind):
        pop16('va')
        if kind == 'm':
            # The EA was computed before SP moved; ea/eo/sb were overwritten by pop16.
            pass
        e_write_after_pop(kind)
    defined.add(0x8F)
    emit_8f()

    # ---- 90-9F
    for r in range(8):
        op(0x90 + r)
        if r:
            e(f'  va = R({r})')
            e(f'  R({r}) = R(0)')
            e('  R(0) = va')
        e('  PIP = PIP + 1')
        tail(3)
    op(0x98)  # CBW
    e(f'  R(0) = PeekB(@R(0))')
    e('  PIP = PIP + 1')
    tail(2)
    op(0x99)  # CWD
    e('  If R(0) & $8000')
    e('    R(2) = $FFFF')
    e('  Else')
    e('    R(2) = 0')
    e('  EndIf')
    e('  PIP = PIP + 1')
    tail(5)
    op(0x9A)  # CALL far
    e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
    e('  y = PeekA(PIP + 3) | (PeekA(PIP + 4) << 8)')
    e('  PIP = PIP + 5')
    e(f'  va = SegV({CS})')
    push16('va')
    e(f'  va = {ip_now()}')
    push16('va')
    far_jump('y', 'x')
    tail(28)
    op(0x9B)  # WAIT
    e('  PIP = PIP + 1')
    tail(3)
    op(0x9C)  # PUSHF
    e('  PIP = PIP + 1')
    e('  va = Cpu86Flags()')
    push16('va')
    tail(10)
    op(0x9D)  # POPF
    e('  PIP = PIP + 1')
    pop16('va')
    e('  Cpu86SetFlags(va)')
    tail(8)
    op(0x9E)  # SAHF
    e('  Cpu86SetFlags((Cpu86Flags() & $FF00) | PeekA(@R(0) + 1))')
    e('  PIP = PIP + 1')
    tail(4)
    op(0x9F)  # LAHF
    e('  PokeA(@R(0) + 1, Cpu86Flags())')
    e('  PIP = PIP + 1')
    tail(4)

    # ---- A0-A3 MOV acc, moffs
    for n in range(0xA0, 0xA4):
        op(n)
        e('  eo = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
        e('  sb = SegD')
        e('  ea = sb + eo')
        e('  PIP = PIP + 3')
        if n == 0xA0:
            rd8('va')
            wr_reg8_const(0, 'va')
        elif n == 0xA1:
            rd16('va')
            e('  R(0) = va')
        elif n == 0xA2:
            e(f'  va = {rd_reg8_const(0)}')
            wr8('va')
        else:
            e('  va = R(0)')
            wr16('va')
        tail(10)

    emit_strings(op)

    # ---- A8/A9 TEST acc, imm
    op(0xA8)
    e(f'  va = {rd_reg8_const(0)}')
    e('  vb = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    alu('TEST', 0)
    tail(4)
    op(0xA9)
    e('  va = R(0)')
    e('  vb = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
    e('  PIP = PIP + 3')
    alu('TEST', 1)
    tail(4)

    # ---- B0-BF MOV r, imm
    for r in range(8):
        op(0xB0 + r)
        wr_reg8_const(r, 'PeekA(PIP + 1)')
        e('  PIP = PIP + 2')
        tail(4)
    for r in range(8):
        op(0xB8 + r)
        e(f'  R({r}) = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
        e('  PIP = PIP + 3')
        tail(4)

    # ---- returns (C0-C3, C8-CB with 8086 aliases)
    for n in (0xC2, 0xC0):
        op(n)
        e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
        pop16('va')
        e(f'  R({SP}) = R({SP}) + x')
        jump_near('va')
        tail(12)
    for n in (0xC3, 0xC1):
        op(n)
        pop16('va')
        jump_near('va')
        tail(8)
    for n in (0xCA, 0xC8):
        op(n)
        e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
        pop16('y')
        pop16('va')
        e(f'  R({SP}) = R({SP}) + x')
        far_jump('va', 'y')
        tail(17)
    for n in (0xCB, 0xC9):
        op(n)
        pop16('y')
        pop16('va')
        far_jump('va', 'y')
        tail(18)
    # LES / LDS
    for n, sr in ((0xC4, ES), (0xC5, DS)):
        def body(kind, sr=sr):
            if kind == 'r':
                # Undefined on the 8086 (not exercised by the reference tests).
                e('  va = R(m & 7)')
                g_write(1, 'va')
                return
            rd16('va')
            e('  eo = (eo + 2) & $FFFF')
            e('  ea = sb + eo')
            rd16('vb')
            g_write(1, 'va')
            e(f'  SegV({sr}) = vb')
            e(f'  SegB({sr}) = vb << 4')
            if sr == DS:
                e(f'  SegD = SegB({DS})')
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 2, 16)
    # C6/C7 MOV Ev, imm (reg field ignored)
    for n, w in ((0xC6, 0), (0xC7, 1)):
        def body(kind, w=w):
            imm(w, 'va')
            e_write(kind, w, 'va')
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 4, 10)
    # INT 3, INT n, INTO, IRET
    op(0xCC)
    e('  PIP = PIP + 1')
    e('  Cpu86Interrupt(3)')
    tail(52)
    op(0xCD)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  Cpu86Interrupt(x)')
    tail(51)
    op(0xCE)
    e('  PIP = PIP + 1')
    e('  If FO < 0')
    e('    Cpu86Interrupt(4)')
    charge(49)
    e('  EndIf')
    tail(4)
    op(0xCF)
    pop16('y')
    pop16('va')
    pop16('vb')
    e('  Cpu86SetFlags(vb)')
    far_jump('va', 'y')
    tail(24)

    emit_shifts()

    # ---- D4 AAM, D5 AAD, D6 SALC, D7 XLAT
    op(0xD4)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  If x = 0')
    e('    Cpu86Interrupt(0)')
    e('  Else')
    e(f'    va = {rd_reg8_const(0)}')
    e('    PokeA(@R(0) + 1, va / x)')
    e('    vr = va % x')
    e('    PokeA(@R(0), vr)')
    set_zs(0, 'vr')
    e('    FC = 0')
    e('    FO = 0')
    e('    FA = vr')
    e('  EndIf')
    tail(83)
    op(0xD5)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e(f'  va = {rd_reg8_const(0)}')
    e('  vb = (PeekA(@R(0) + 1) * x) & 255')
    alu('ADD', 0)
    e('  R(0) = vr & 255')
    tail(60)
    op(0xD6)
    e('  If FC < 0')
    e('    PokeA(@R(0), 255)')
    e('  Else')
    e('    PokeA(@R(0), 0)')
    e('  EndIf')
    e('  PIP = PIP + 1')
    tail(4)
    op(0xD7)
    e('  eo = (R(3) + PeekA(@R(0))) & $FFFF')
    e('  ea = SegD + eo')
    rd8('va')
    e('  PokeA(@R(0), va)')
    e('  PIP = PIP + 1')
    tail(11)
    # ESC D8-DF: decode the operand, do nothing.
    for n in range(0xD8, 0xE0):
        def body(kind):
            pass
        defined.add(n)
        modrm_handler(f'Op{n:02X}', body, 2, 8)

    # ---- E0-E3 LOOPNZ LOOPZ LOOP JCXZ
    for n in range(0xE0, 0xE4):
        op(n)
        if n == 0xE3:
            e('  If R(1) = 0')
        else:
            e('  R(1) = R(1) - 1')
            if n == 0xE2:
                e('  If R(1) <> 0')
            elif n == 0xE1:
                e('  If (R(1) <> 0) And ((FZS << 15) = 0)')
            else:
                e('  If (R(1) <> 0) And ((FZS << 15) <> 0)')
        jump_rel('PeekB(PIP + 1)', 2)
        charge(12)
        e('  Else')
        e('    PIP = PIP + 2')
        e('  EndIf')
        tail(5)
    # ---- IN / OUT
    op(0xE4)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  PokeA(@R(0), Cpu86PortIn(x, 0))')
    tail(10)
    op(0xE5)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  R(0) = Cpu86PortIn(x, 1)')
    tail(10)
    op(0xE6)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  Cpu86PortOut(x, PeekA(@R(0)), 0)')
    tail(10)
    op(0xE7)
    e('  x = PeekA(PIP + 1)')
    e('  PIP = PIP + 2')
    e('  Cpu86PortOut(x, R(0), 1)')
    tail(10)
    op(0xEC)
    e('  PIP = PIP + 1')
    e('  PokeA(@R(0), Cpu86PortIn(R(2), 0))')
    tail(8)
    op(0xED)
    e('  PIP = PIP + 1')
    e('  R(0) = Cpu86PortIn(R(2), 1)')
    tail(8)
    op(0xEE)
    e('  PIP = PIP + 1')
    e('  Cpu86PortOut(R(2), PeekA(@R(0)), 0)')
    tail(8)
    op(0xEF)
    e('  PIP = PIP + 1')
    e('  Cpu86PortOut(R(2), R(0), 1)')
    tail(8)
    # ---- CALL / JMP
    op(0xE8)
    e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
    e('  PIP = PIP + 3')
    e(f'  va = {ip_now()}')
    push16('va')
    jump_near('((va + x) & $FFFF)')
    tail(19)
    op(0xE9)
    e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
    e(f'  PIP = PIP + 3')
    e(f'  x = ({ip_now()} + x) & $FFFF')
    jump_near('x')
    tail(15)
    op(0xEA)
    e('  x = PeekA(PIP + 1) | (PeekA(PIP + 2) << 8)')
    e('  y = PeekA(PIP + 3) | (PeekA(PIP + 4) << 8)')
    far_jump('y', 'x')
    tail(15)
    op(0xEB)
    jump_rel('PeekB(PIP + 1)', 2)
    tail(15)
    # ---- prefixes F0-F3
    for n in (0xF0, 0xF1):
        op(n)
        charge(2)
        e('  Goto PrefixNext')
    op(0xF2)
    e('  Rep = 1')
    charge(2)
    e('  Goto PrefixNext')
    op(0xF3)
    e('  Rep = 2')
    charge(2)
    e('  Goto PrefixNext')
    op(0xF4)  # HLT
    e('  PIP = PIP + 1')
    e('  Halted = 1')
    e('  PEnd = 0')
    tail(2)
    op(0xF5)  # CMC
    e('  FC = FC ! $80000000')
    e('  PIP = PIP + 1')
    tail(2)
    emit_grp3()
    for n, code in ((0xF8, ['FC = 0']), (0xF9, ['FC = $80000000']),
                    (0xFA, ['FlagsHi = FlagsHi & ~$200']),
                    (0xFB, ['If (FlagsHi & $200) = 0', '  FlagsHi = FlagsHi | $200',
                            '  EvPend = EvPend | 8', '  PEnd = 0', 'EndIf']),
                    (0xFC, ['FlagsHi = FlagsHi & ~$400', 'DirStep = 1', 'DirStep2 = 2']),
                    (0xFD, ['FlagsHi = FlagsHi | $400', 'DirStep = -1', 'DirStep2 = -2'])):
        op(n)
        for c in code:
            e('  ' + c)
        e('  PIP = PIP + 1')
        tail(2)
    emit_grp45()
    for n in (0xF6, 0xF7, 0xFE, 0xFF, 0xD0, 0xD1, 0xD2, 0xD3):
        defined.add(n)
    missing = [n for n in range(256) if n not in defined]
    if missing:
        raise SystemExit('opcodes without a handler: ' + ' '.join(f'{n:02X}' for n in missing))

def emit_set_seg(sr, v):
    if sr == CS:
        e(f'  x = {ip_now()}')
        far_jump(v, 'x')
    else:
        e(f'  SegV({sr}) = {v}')
        e(f'  SegB({sr}) = {v} << 4')
        if sr == DS:
            e(f'  SegD = SegB({DS})')
        if sr == SS:
            e(f'  SegS = SegB({SS})')
            e('  EvPend = EvPend | 8')
            e('  PEnd = 0')

def e_write_after_pop(kind):
    pass

def emit_8f():
    # POP Ew: the operand address is decoded first (the 8086 computes it before
    # the stack read), the popped word written there; SP moves by 2.
    e('Op8F:')
    e('  m = PeekA(PIP + 1)')
    e('  If m < $C0')
    e('    EaRet = ?Op8FM')
    e('    Goto EaTab(m)')
    e('  EndIf')
    e('  PIP = PIP + 2')
    e(f'  eo = R({SP})')
    e(f'  ea = SegB({SS}) + eo')
    rd16('va', sb=f'SegB({SS})')
    e(f'  R({SP}) = eo + 2')
    e('  R(m & 7) = va')
    tail(8)
    e('Op8FM:')
    e('  x = ea')
    e('  y = eo')
    e('  cnt = sb')
    e(f'  eo = R({SP})')
    e(f'  ea = SegB({SS}) + eo')
    rd16('va', sb=f'SegB({SS})')
    e(f'  R({SP}) = eo + 2')
    e('  ea = x')
    e('  eo = y')
    e('  sb = cnt')
    wr16('va')
    tail(17)

def emit_bcd(op):
    # 27 DAA
    op(0x27)
    e(f'  va = {rd_reg8_const(0)}')
    e('  x = (FC >> 31) & 1')
    e('  y = ((FA ! FZS) >> 4) & 1')
    e('  vr = va')
    e('  FO = 0')
    e('  If x')
    e('    If (va >= $1A) And (va <= $7F)')
    e('      FO = $80000000')
    e('    EndIf')
    e('  ElseIf (va >= $7A) And (va <= $7F)')
    e('    FO = $80000000')
    e('  EndIf')
    e('  If ((va & 15) > 9) Or y')
    e('    vr = (vr + 6) & 255')
    e('    FA = $10')
    e('  Else')
    e('    FA = 0')
    e('  EndIf')
    e('  cnt = $99')
    e('  If y')
    e('    cnt = $9F')
    e('  EndIf')
    e('  If (va > cnt) Or x')
    e('    vr = (vr + $60) & 255')
    e('    FC = $80000000')
    e('  Else')
    e('    FC = 0')
    e('  EndIf')
    e('  PokeA(@R(0), vr)')
    set_zs(0, 'vr')
    e('  FA = FA ! vr')
    e('  PIP = PIP + 1')
    tail(4)
    # 2F DAS
    op(0x2F)
    e(f'  va = {rd_reg8_const(0)}')
    e('  x = (FC >> 31) & 1')
    e('  y = ((FA ! FZS) >> 4) & 1')
    e('  vr = va')
    e('  FO = 0')
    e('  If (x = 0) And (y = 0)')
    e('    If (va >= $9A) And (va <= $DF)')
    e('      FO = $80000000')
    e('    EndIf')
    e('  ElseIf x = 0')
    e('    If ((va >= $80) And (va <= $85)) Or ((va >= $A0) And (va <= $E5))')
    e('      FO = $80000000')
    e('    EndIf')
    e('  ElseIf y = 0')
    e('    If (va >= $80) And (va <= $DF)')
    e('      FO = $80000000')
    e('    EndIf')
    e('  Else')
    e('    If (va >= $80) And (va <= $E5)')
    e('      FO = $80000000')
    e('    EndIf')
    e('  EndIf')
    e('  If ((va & 15) > 9) Or y')
    e('    vr = (vr - 6) & 255')
    e('    FA = $10')
    e('  Else')
    e('    FA = 0')
    e('  EndIf')
    e('  cnt = $99')
    e('  If y')
    e('    cnt = $9F')
    e('  EndIf')
    e('  If (va > cnt) Or x')
    e('    vr = (vr - $60) & 255')
    e('    FC = $80000000')
    e('  Else')
    e('    FC = 0')
    e('  EndIf')
    e('  PokeA(@R(0), vr)')
    set_zs(0, 'vr')
    e('  FA = FA ! vr')
    e('  PIP = PIP + 1')
    tail(4)
    # 37 AAA
    op(0x37)
    e(f'  va = {rd_reg8_const(0)}')
    e('  If ((va & 15) > 9) Or ((FA ! FZS) & $10)')
    e('    PokeA(@R(0) + 1, PeekA(@R(0) + 1) + 1)')
    e('    vr = (va + 6) & 255')
    e('    FA = $10')
    e('    FC = $80000000')
    e('  Else')
    e('    vr = va')
    e('    FA = 0')
    e('    FC = 0')
    e('  EndIf')
    e('  PokeA(@R(0), vr & 15)')
    e('  FO = 0')
    e('  If (va >= $7A) And (va <= $7F)')
    e('    FO = $80000000')
    e('  EndIf')
    # ZF/PF from vr, SF from the range rule
    e('  If (va >= $7A) And (va <= $F9)')
    e('    FZS = $80000000 | vr')
    e('  Else')
    e('    FZS = vr')
    e('  EndIf')
    e('  If vr = 0')
    e('    FZS = FZS & $80000000')
    e('  EndIf')
    e('  FA = FA ! vr')
    e('  PIP = PIP + 1')
    tail(4)
    # 3F AAS
    op(0x3F)
    e(f'  va = {rd_reg8_const(0)}')
    e('  y = ((FA ! FZS) >> 4) & 1')
    e('  If ((va & 15) > 9) Or y')
    e('    vr = (va - 6) & 255')
    e('    PokeA(@R(0) + 1, PeekA(@R(0) + 1) - 1)')
    e('    FA = $10')
    e('    FC = $80000000')
    e('  Else')
    e('    vr = va')
    e('    FA = 0')
    e('    FC = 0')
    e('  EndIf')
    e('  PokeA(@R(0), vr & 15)')
    e('  FO = 0')
    e('  x = 0')
    e('  If y And (va >= $80) And (va <= $85)')
    e('    FO = $80000000')
    e('  EndIf')
    e('  If (y = 0) And (va >= $80)')
    e('    x = 1')
    e('  EndIf')
    e('  If y And ((va <= 5) Or (va >= $86))')
    e('    x = 1')
    e('  EndIf')
    e('  FZS = vr')
    e('  If x')
    e('    FZS = FZS | $80000000')
    e('  EndIf')
    e('  If vr = 0')
    e('    FZS = FZS & $80000000')
    e('  EndIf')
    e('  FA = FA ! vr')
    e('  PIP = PIP + 1')
    tail(4)

def emit_rep_block(kind, w, iter_cyc):
    """REP MOVS / REP STOS going up (DF = 0): copy whole runs that stay inside
    one RAM page and one 64 KB segment on each side straight between host
    pointers. Elements are still moved one at a time and in order, each read
    before it is written, so overlapping copies give the 8086's result. An
    element that cannot (page or segment edge, ROM, hooks) is done through
    the slow procedures, one at a time, and the block path resumes after it."""
    sh = 1 if w else 0
    size = 2 if w else 1
    e('  If (Rep <> 0) And (cnt <> 0) And (DirStep = 1)')
    e('    While cnt <> 0')
    e(f'      y = SegB({ES}) + R({DI})')
    e('      vr = PageW(y >> 12)')
    e(f'      va = ($1000 - (y & $FFF)) >> {sh}')
    e(f'      vb = ($10000 - R({DI})) >> {sh}')
    e('      If vb < va')
    e('        va = vb')
    e('      EndIf')
    if kind == 'MOVS':
        e(f'      x = SegD + R({SI})')
        e('      t = PageR(x >> 12)')
        e(f'      vb = ($1000 - (x & $FFF)) >> {sh}')
        e('      If vb < va')
        e('        va = vb')
        e('      EndIf')
        e(f'      vb = ($10000 - R({SI})) >> {sh}')
        e('      If vb < va')
        e('        va = vb')
        e('      EndIf')
        e('      If t = 0')
        e('        va = 0')
        e('      EndIf')
    e('      If vr = 0')
    e('        va = 0')
    e('      EndIf')
    e('      If cnt < va')
    e('        va = cnt')
    e('      EndIf')
    e('      If va = 0')
    if kind == 'MOVS':
        if w:
            e(f'        vb = Cpu86Rd16(SegD, R({SI}))')
            e(f'        Cpu86Wr16(SegB({ES}), R({DI}), vb)')
        else:
            e(f'        vb = Cpu86Rd8(SegD + R({SI}))')
            e(f'        Cpu86Wr8(SegB({ES}) + R({DI}), vb)')
        e(f'        R({SI}) = R({SI}) + {size}')
    else:
        if w:
            e(f'        Cpu86Wr16(SegB({ES}), R({DI}), R(0))')
        else:
            e(f'        Cpu86Wr8(SegB({ES}) + R({DI}), PeekA(@R(0)))')
    e(f'        R({DI}) = R({DI}) + {size}')
    e('        cnt = cnt - 1')
    charge(iter_cyc)
    e('      Else')
    e('        vr = vr + y')
    e(f'        ea = vr + (va << {sh})')
    if kind == 'MOVS':
        e('        t = t + x')
        e('        While vr < ea')
        if w:
            e('          vb = PeekA(t) | (PeekA(t + 1) << 8)')
            e('          PokeA(vr, vb)')
            e('          PokeA(vr + 1, vb >> 8)')
            e('          t = t + 2')
            e('          vr = vr + 2')
        else:
            e('          PokeA(vr, PeekA(t))')
            e('          t = t + 1')
            e('          vr = vr + 1')
        e('        Wend')
        e(f'        R({SI}) = R({SI}) + (va << {sh})')
    else:
        if w:
            e('        vb = R(0)')
            e('        While vr < ea')
            e('          PokeA(vr, vb)')
            e('          PokeA(vr + 1, vb >> 8)')
            e('          vr = vr + 2')
            e('        Wend')
        else:
            e('        vb = PeekA(@R(0))')
            e('        While vr < ea')
            e('          PokeA(vr, vb)')
            e('          vr = vr + 1')
            e('        Wend')
    e(f'        R({DI}) = R({DI}) + (va << {sh})')
    e('        cnt = cnt - va')
    charge(f'{iter_cyc} * va')
    e('      EndIf')
    e('    Wend')
    e('    R(1) = 0')
    e('  EndIf')

def emit_strings(op):
    # Source DS:SI (overridable, SegD), destination ES:DI. Rep: 0 none, 1 REPNZ, 2 REPZ.
    def src_ea():
        e(f'  eo = R({SI})')
        e('  sb = SegD')
        e('  ea = sb + eo')
    def dst_ea():
        e(f'  eo = R({DI})')
        e(f'  sb = SegB({ES})')
        e('  ea = sb + eo')
    def loop(n, w, kind, once_cyc, iter_cyc):
        op(n)
        step = 'DirStep2' if w else 'DirStep'
        e('  PIP = PIP + 1')
        e('  If Rep = 0')
        e('    cnt = 1')
        e('  Else')
        e('    cnt = R(1)')
        e('  EndIf')
        if kind in ('MOVS', 'STOS') and REP_BLOCK:
            emit_rep_block(kind, w, iter_cyc)
        e('  While cnt <> 0')
        if kind == 'MOVS':
            src_ea()
            (rd16 if w else rd8)('va')
            dst_ea()
            (wr16 if w else wr8)('va')
            e(f'  R({SI}) = R({SI}) + {step}')
            e(f'  R({DI}) = R({DI}) + {step}')
        elif kind == 'CMPS':
            src_ea()
            (rd16 if w else rd8)('va')
            dst_ea()
            (rd16 if w else rd8)('vb')
            alu('CMP', w)
            e(f'  R({SI}) = R({SI}) + {step}')
            e(f'  R({DI}) = R({DI}) + {step}')
        elif kind == 'STOS':
            dst_ea()
            if w:
                e('  va = R(0)')
                wr16('va')
            else:
                e('  va = PeekA(@R(0))')
                wr8('va')
            e(f'  R({DI}) = R({DI}) + {step}')
        elif kind == 'LODS':
            src_ea()
            (rd16 if w else rd8)('va')
            if w:
                e('  R(0) = va')
            else:
                e('  PokeA(@R(0), va)')
            e(f'  R({SI}) = R({SI}) + {step}')
        elif kind == 'SCAS':
            dst_ea()
            (rd16 if w else rd8)('vb')
            if w:
                e('  va = R(0)')
            else:
                e('  va = PeekA(@R(0))')
            alu('CMP', w)
            e(f'  R({DI}) = R({DI}) + {step}')
        e('  If Rep = 0')
        e('    Break')
        e('  EndIf')
        e('  R(1) = R(1) - 1')
        e('  cnt = R(1)')
        charge(iter_cyc)
        if kind in ('CMPS', 'SCAS'):
            e('  If Rep = 2')
            e('    If (FZS << 15) <> 0')
            e('      Break')
            e('    EndIf')
            e('  Else')
            e('    If (FZS << 15) = 0')
            e('      Break')
            e('    EndIf')
            e('  EndIf')
        e('  Wend')
        tail(once_cyc)
    loop(0xA4, 0, 'MOVS', 18, 17)
    loop(0xA5, 1, 'MOVS', 18, 17)
    loop(0xA6, 0, 'CMPS', 22, 22)
    loop(0xA7, 1, 'CMPS', 22, 22)
    loop(0xAA, 0, 'STOS', 11, 10)
    loop(0xAB, 1, 'STOS', 11, 10)
    loop(0xAC, 0, 'LODS', 12, 13)
    loop(0xAD, 1, 'LODS', 12, 13)
    loop(0xAE, 0, 'SCAS', 15, 15)
    loop(0xAF, 1, 'SCAS', 15, 15)

def emit_shifts():
    # D0/D1 count 1, D2/D3 count CL (not masked on the 8086).
    # reg: 0 ROL 1 ROR 2 RCL 3 RCR 4 SHL 5 SHR 6 SETMO 7 SAR
    for opc in (0xD0, 0xD1, 0xD2, 0xD3):
        w = opc & 1
        W = 16 if w else 8
        mask = '$FFFF' if w else '$FF'
        msb = 15 if w else 7
        bodies = []
        for k in range(8):
            def body(kind, k=k, opc=opc, w=w):
                e_read(kind, w, 'va')
                if opc in (0xD0, 0xD1):
                    e('  cnt = 1')
                else:
                    e('  cnt = PeekA(@R(0) + 2)')
                e('  If cnt <> 0')
                shift_body(k, w, W, mask, msb)
                e_write(kind, w, 'vr')
                charge(4 if opc >= 0xD2 else 0)
                e('  EndIf')
            bodies.append(body)
        group_handler(f'Op{opc:02X}', f'G{opc:02X}', bodies, 8 if opc >= 0xD2 else 2,
                      20 if opc >= 0xD2 else 15)

def shift_body(k, w, W, mask, msb):
    sc = 31 - W   # shift to move bit W into bit 31
    if k == 0:    # ROL
        e(f'    x = cnt % {W}')
        e(f'    vr = ((va << x) | (va >> ({W} - x))) & {mask}')
        e('    FC = (vr & 1) << 31')
        e(f'    FO = ((vr >> {msb}) ! vr) << 31')
    elif k == 1:  # ROR
        e(f'    x = cnt % {W}')
        e(f'    vr = ((va >> x) | (va << ({W} - x))) & {mask}')
        e(f'    FC = (vr >> {msb}) << 31')
        e(f'    FO = ((vr >> {msb}) ! (vr >> {msb - 1})) << 31')
    elif k == 2:  # RCL through a W+1 bit value
        e(f'    x = cnt % {W + 1}')
        e(f'    y = va | (((FC >> 31) & 1) << {W})')
        e(f'    y = (y << x) | (y >> ({W + 1} - x))')
        e(f'    vr = y & {mask}')
        e(f'    FC = ((y >> {W}) & 1) << 31')
        e(f'    FO = ((vr >> {msb}) ! (y >> {W})) << 31')
    elif k == 3:  # RCR
        e(f'    x = cnt % {W + 1}')
        e(f'    y = va | (((FC >> 31) & 1) << {W})')
        e(f'    y = (y >> x) | (y << ({W + 1} - x))')
        e(f'    vr = y & {mask}')
        e(f'    FC = ((y >> {W}) & 1) << 31')
        e(f'    FO = ((vr >> {msb}) ! (vr >> {msb - 1})) << 31')
    elif k == 4:  # SHL
        e('    If cnt > 31')
        e('      y = 0')
        e('    Else')
        e('      y = va << cnt')
        e('    EndIf')
        e(f'    vr = y & {mask}')
        e(f'    FC = y << {sc}')
        e(f'    FO = ((vr >> {msb}) ! (y >> {W})) << 31')
        e('    FA = vr')
        set_zs_i(w, 'vr')
    elif k == 5:  # SHR
        e('    If cnt > 31')
        e('      y = 0')
        e('    Else')
        e('      y = va >> (cnt - 1)')
        e('    EndIf')
        e('    vr = y >> 1')
        e('    FC = y << 31')
        e(f'    FO = (y >> {msb}) << 31')
        e('    FA = vr')
        set_zs_i(w, 'vr')
    elif k == 6:  # SETMO / SETMOC: all ones, flags as OR with ones
        e(f'    vr = {mask}')
        e('    FC = 0')
        e('    FO = 0')
        e('    FA = vr')
        set_zs_i(w, 'vr')
    else:         # SAR
        s = 32 - W
        e(f'    y = (va << {s}) >> {s}')
        e('    If cnt > 31')
        e('      cnt = 31')
        e('    EndIf')
        e('    y = y >> (cnt - 1)')
        e(f'    vr = (y >> 1) & {mask}')
        e('    FC = y << 31')
        e('    FO = 0')
        e('    FA = vr')
        set_zs_i(w, 'vr')
    if k < 4:
        # Rotates leave SF, ZF, PF, AF alone. Normalise CF/OF to bit 31 only.
        e('    FC = FC & $80000000')
        e('    FO = FO & $80000000')

def set_zs_i(w, v):
    s = sz(w)[2]
    e(f'    FZS = ({v} << {s}) >> {s}')

def emit_grp3():
    # F6/F7: 0 TEST, 1 TEST (alias), 2 NOT, 3 NEG, 4 MUL, 5 IMUL, 6 DIV, 7 IDIV
    for opc in (0xF6, 0xF7):
        w = opc & 1
        bodies = []
        def test_b(kind, w=w):
            e_read(kind, w, 'va')
            imm(w, 'vb')
            alu('TEST', w)
        def not_b(kind, w=w):
            e_read(kind, w, 'va')
            e('  vr = ~va')
            e_write(kind, w, 'vr')
        def neg_b(kind, w=w):
            e_read(kind, w, 'va')
            e('  vb = va')
            e('  va = 0')
            alu('SUB', w)
            e_write(kind, w, 'vr')
        def mul_b(kind, w=w):
            e_read(kind, w, 'vb')
            if w:
                e('  vr = R(0) * vb')
                e('  If Rep')
                e('    vr = 0 - vr')
                e('  EndIf')
                e('  R(0) = vr')
                e('  x = (vr >> 16) & $FFFF')
                e('  R(2) = x')
                e('  FZS = (x << 16) >> 16')
            else:
                e('  vr = PeekA(@R(0)) * vb')
                e('  If Rep')
                e('    vr = 0 - vr')
                e('  EndIf')
                e('  R(0) = vr')
                e('  x = (vr >> 8) & $FF')
                e('  FZS = (x << 24) >> 24')
            e('  If x <> 0')
            e('    FC = $80000000')
            e('    FO = $80000000')
            e('  Else')
            e('    FC = 0')
            e('    FO = 0')
            e('  EndIf')
            e('  FA = FZS')
        def imul_b(kind, w=w):
            e_read(kind, w, 'vb')
            if w:
                e('  vr = PeekW(@R(0)) * ((vb << 16) >> 16)      ; PeekW: AX read signed')
                e('  If Rep')
                e('    vr = 0 - vr')
                e('  EndIf')
                e('  R(0) = vr')
                e('  R(2) = vr >> 16')
                e('  x = (vr << 16) >> 16')
                e('  FZS = (vr >> 16) << 16 >> 16')
            else:
                e('  vr = PeekB(@R(0)) * ((vb << 24) >> 24)')
                e('  If Rep')
                e('    vr = 0 - vr')
                e('  EndIf')
                e('  R(0) = vr')
                e('  x = (vr << 24) >> 24')
                e('  FZS = (vr << 16) >> 24')
            e('  If x <> vr')
            e('    FC = $80000000')
            e('    FO = $80000000')
            e('  Else')
            e('    FC = 0')
            e('    FO = 0')
            e('  EndIf')
            e('  FA = FZS')
        def div_b(kind, w=w):
            e_read(kind, w, 'vb')
            if w:
                # DX:AX / src in two 16-by-8-bit steps, so every value stays
                # positive in a signed 32-bit integer.
                e('  If R(2) >= vb')
                e('    Cpu86Interrupt(0)')
                e('  Else')
                e('    x = (R(2) << 8) | (R(0) >> 8)')
                e('    y = x / vb')
                e('    x = x - y * vb')
                e('    x = (x << 8) | (R(0) & 255)')
                e('    cnt = x / vb')
                e('    x = x - cnt * vb')
                e('    R(0) = (y << 8) | cnt')
                e('    R(2) = x')
                e('  EndIf')
            else:
                e('  va = R(0)')
                e('  If (va >> 8) >= vb')
                e('    Cpu86Interrupt(0)')
                e('  Else')
                e('    R(0) = (va / vb) | ((va % vb) << 8)')
                e('  EndIf')
        def idiv_b(kind, w=w):
            # Magnitudes, as the 8086 microcode does it: |quotient| must fit in
            # 7 (15) bits, so -128 (-32768) is a divide error on the 8086.
            e_read(kind, w, 'vb')
            if w:
                e('  va = (R(2) << 16) | R(0)')
                e('  y = (vb << 16) >> 16')
                e('  x = 0')
                e('  If va < 0')
                e('    va = 0 - va')
                e('    x = 1')
                e('  EndIf')
                e('  cnt = x')
                e('  If y < 0')
                e('    y = 0 - y')
                e('    cnt = cnt ! 1')
                e('  EndIf')
                e('  If Rep')
                e('    cnt = cnt ! 1')
                e('  EndIf')
                e('  If ((va >> 16) & $FFFF) >= y')
                e('    Cpu86Interrupt(0)')
                e('  Else')
                e('    vr = va / y')
                e('    vb = va - vr * y')
                e('    If vr > $7FFF')
                e('      Cpu86Interrupt(0)')
                e('    Else')
                e('      If cnt')
                e('        vr = 0 - vr')
                e('      EndIf')
                e('      If x')
                e('        vb = 0 - vb')
                e('      EndIf')
                e('      R(0) = vr')
                e('      R(2) = vb')
                e('    EndIf')
                e('  EndIf')
            else:
                e('  va = PeekW(@R(0))                       ; AX read signed')
                e('  y = (vb << 24) >> 24')
                e('  x = 0')
                e('  If va < 0')
                e('    va = 0 - va')
                e('    x = 1')
                e('  EndIf')
                e('  cnt = x')
                e('  If y < 0')
                e('    y = 0 - y')
                e('    cnt = cnt ! 1')
                e('  EndIf')
                e('  If Rep')
                e('    cnt = cnt ! 1')
                e('  EndIf')
                e('  If ((va >> 8) & 255) >= y')
                e('    Cpu86Interrupt(0)')
                e('  Else')
                e('    vr = (va & $FFFF) / y')
                e('    vb = (va & $FFFF) % y')
                e('    If vr > $7F')
                e('      Cpu86Interrupt(0)')
                e('    Else')
                e('      If cnt')
                e('        vr = 0 - vr')
                e('      EndIf')
                e('      If x')
                e('        vb = 0 - vb')
                e('      EndIf')
                e('      R(0) = (vr & 255) | ((vb & 255) << 8)')
                e('    EndIf')
                e('  EndIf')
        bodies = [test_b, test_b, not_b, neg_b, mul_b, imul_b, div_b, idiv_b]
        group_handler(f'Op{opc:02X}', f'G{opc:02X}', bodies,
                      [5, 5, 3, 3, 74 if not w else 128, 89 if not w else 141, 85 if not w else 153, 107 if not w else 175],
                      [11, 11, 16, 16, 80 if not w else 134, 95 if not w else 147, 91 if not w else 159, 113 if not w else 181])

def emit_grp45():
    # FE: 0 INC Eb, 1 DEC Eb, others undefined (not exercised): treated as INC/DEC.
    bodies = []
    for k in range(8):
        def body(kind, k=k):
            e_read(kind, 0, 'va')
            if k % 2 == 0:
                e('  vr = va + 1')
                e('  FO = (vr & ~va) << 24')
            else:
                e('  vr = va - 1')
                e('  FO = (va & ~vr) << 24')
            e('  FA = va                 ; AF = bit 4 of FA ^ result (the 1 adds nothing there)')
            set_zs(0, 'vr')
            e_write(kind, 0, 'vr')
        bodies.append(body)
    group_handler('OpFE', 'GFE', bodies, 3, 15)
    # FF: 0 INC, 1 DEC, 2 CALL near, 3 CALL far, 4 JMP near, 5 JMP far, 6/7 PUSH
    def inc(kind):
        e_read(kind, 1, 'va')
        e('  vr = va + 1')
        e('  FO = (vr & ~va) << 16')
        e('  FA = va                 ; AF = bit 4 of FA ^ result (the 1 adds nothing there)')
        set_zs(1, 'vr')
        e_write(kind, 1, 'vr')
    def dec(kind):
        e_read(kind, 1, 'va')
        e('  vr = va - 1')
        e('  FO = (va & ~vr) << 16')
        e('  FA = va                 ; AF = bit 4 of FA ^ result (the 1 adds nothing there)')
        set_zs(1, 'vr')
        e_write(kind, 1, 'vr')
    def calln(kind):
        e_read(kind, 1, 'vb')
        e(f'  va = {ip_now()}')
        push16('va')
        jump_near('vb')
    def callf(kind):
        if kind == 'r':
            # Undefined on the 8086 (not exercised): treated as a near call.
            calln(kind)
            return
        rd16('y')
        e('  eo = (eo + 2) & $FFFF')
        e('  ea = sb + eo')
        rd16('vb')
        e(f'  va = SegV({CS})')
        push16('va')
        e(f'  va = {ip_now()}')
        push16('va')
        far_jump('vb', 'y')
    def jmpn(kind):
        e_read(kind, 1, 'vb')
        jump_near('vb')
    def jmpf(kind):
        if kind == 'r':
            jmpn(kind)
            return
        rd16('y')
        e('  eo = (eo + 2) & $FFFF')
        e('  ea = sb + eo')
        rd16('vb')
        far_jump('vb', 'y')
    def push(kind):
        if kind == 'r':
            # PUSH SP pushes the decremented SP, as 50+4 does.
            e('  If (m & 7) = 4')
            e('    va = (R(4) - 2) & $FFFF')
            e('  Else')
            e('    va = R(m & 7)')
            e('  EndIf')
        else:
            rd16('va')
        push16('va')
    group_handler('OpFF', 'GFF', [inc, dec, calln, callf, jmpn, jmpf, push, push],
                  [2, 2, 16, 16, 11, 11, 11, 11], [15, 15, 21, 37, 18, 24, 16, 16])

def main():
    import os
    out = Path(os.environ.get('CPU86_OUT', ROOT / 'src'))
    for target, name in (('rp2040', 'cpu86.pico'), ('rp2350', 'cpu86.pico2')):
        text = generate(target)
        (out / name).write_text(text, newline='\n')
        print(name, len(text.splitlines()), 'lines')

if __name__ == '__main__':
    main()
