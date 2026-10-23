# Intel 8086 on the Raspberry Pi Pico series — PureMetal

A fast Intel 8086 interpreter core for the Raspberry Pi Pico W (RP2040) and
Pico 2 W (RP2350), written in PureMetal. The interpreter runs from SRAM and
dispatches through a 256-entry `.Label` table; every handler ends in its own
computed jump, so there is no procedure call per guest instruction.

Status, results and the measured speed are in **Verification** and **Speed**
below. Everything reported there ran on the physical boards.

## What it implements

The whole 8086 instruction set, as the real chip behaves:

- every opcode byte `00`–`FF`, including the 8086's aliases (`60`–`6F` as
  `Jcc`, `C0`/`C1` as `RET`, `C8`/`C9` as `RETF`, `82` as `80`, `F1` as
  `LOCK`, `F6`/`F7 /1` as `TEST`, `FF /7` as `PUSH`), `POP CS` (`0F`),
  `MOV CS` (`8E /1`), `SALC` (`D6`) and `SETMO`/`SETMOC` (`D0`–`D3 /6`);
- segment override prefixes on every memory operand (string destinations stay
  on `ES`), `LOCK` accepted, `REP`/`REPE`/`REPNE` on all string instructions;
- `MUL`/`IMUL`/`DIV`/`IDIV`/`AAM`/`AAD`, with the divide-error interrupt
  (type 0, the return address being the next instruction, as on the 8086);
  `IDIV` refuses a quotient of -128 / -32768 as the 8086 does, and a `REP`
  prefix negates the `IDIV` quotient and the `IMUL` product, as the 8086's
  microcode does;
- 8086 specifics: `PUSH SP` pushes the decremented value, shift and rotate
  counts are **not** masked (`CL` up to 255), word accesses at offset `FFFF`
  wrap inside the segment, linear addresses wrap at 1 MB, `FLAGS` bits 12–15
  read as 1;
- exact flags including AF and PF, and the undocumented flag results of
  `DAA`, `DAS`, `AAA` and `AAS` that the reference tests check;
- `INT n`, `INT 3`, `INTO`, `IRET`, `HLT`, the trap flag (single step), NMI and
  a maskable interrupt line with the 8086's one-instruction delays after `STI`
  and after a load of `SS`;
- `IN`/`OUT` through port hooks; `ESC` (`D8`–`DF`) decodes its operand and does
  nothing (no 8087); `WAIT` returns at once.

Not modelled: the prefetch queue (code modified just ahead of the instruction
pointer takes effect at once, where a real 8086 may already hold the old bytes),
bus timing and wait states, and the 8086's loss of a second prefix when a `REP`
string instruction is interrupted (here a `REP` instruction always completes
inside one `Cpu86Run` step).

## Memory

The 1 MB address space is 256 pages of 4 KB. Each page is RAM, ROM, unmapped
or a hook page:

| Kind | Reads | Writes |
|---|---|---|
| RAM | the host SRAM given to `Cpu86MapRam` | stored |
| ROM | the host memory given to `Cpu86MapRom` (flash or SRAM) | ignored |
| unmapped (`Cpu86MapNone`) | `$FF` | ignored |
| hook (`Cpu86MapHook`) | `Cpu86HookRead(lin)` | `Cpu86HookWrite(lin, v)` |

Two tables hold, per page, a host pointer minus the page's linear base (or 0),
so an ordinary read is `PeekA(PageR(lin >> 12) + lin)` and a single test of
the pointer sends everything else — ROM writes, unmapped space, hooks, a word
that crosses a page or the 64 KB segment end — to the slow procedures. RAM need
not be contiguous on the host: the demo joins two arrays into one guest range.

Instruction fetch does not go through the tables at all. The instruction
pointer is a host pointer into a *fetch window* — the current 4 KB page, cut
short so that any instruction starting inside it has all of its (at most six)
bytes inside the page and inside the code segment. Leaving the window costs one
re-computation; an instruction that crosses a page or the IP wrap is copied
into a six-byte buffer and executed from there.

**How much guest RAM fits.** The RP2040's SRAM is split by the USB serial
library's fixed buffers at `$20030000`, and about 95 KB of it holds the
interpreter. The demo gives the guest **144 KB** on the Pico W (88 KB below the
USB buffers and 56 KB above) and **408 KB** on the Pico 2 W (320 KB + 88 KB).
More can be added from PSRAM or flash-backed ROM pages without touching the
core.

## API

Declare the configuration, define the four hooks, include the core:

```text
#CPU_TIMING = 0       ; 0: Cpu86Run counts instructions; 1: it counts 8086 clocks
#CPU_ASM_TAIL = 1     ; 1: inline-assembly dispatch tail; 0: plain PureMetal Goto
XIncludeFile "src/cpu86.pico"        ; cpu86.pico2 on the Pico 2 W

Procedure.i Cpu86HookRead(lin.i)            ; byte read from a hook page
Procedure Cpu86HookWrite(lin.i, v.i)        ; byte write to a hook page
Procedure.i Cpu86PortIn(port.i, wide.i)     ; IN  (wide = 1 for a word)
Procedure Cpu86PortOut(port.i, v.i, wide.i) ; OUT
```

| Call / state | Meaning |
|---|---|
| `Cpu86Reset()` | power-on state: `CS:IP = FFFF:0000`, other segments 0, `FLAGS = F002` |
| `Cpu86MapRam(lin, bytes, host)` | map RAM; `lin` and `bytes` are multiples of 4096 |
| `Cpu86MapRom(lin, bytes, host)` | map read-only memory (flash or SRAM) |
| `Cpu86MapNone(lin, bytes)` / `Cpu86MapHook(lin, bytes)` | unmapped / hook pages |
| `Cpu86Run(n)` | run until `n` instructions (or clocks) are spent; returns the budget used |
| `Cpu86Irq(vector)` / `Cpu86IrqCancel()` | raise / drop the maskable interrupt line |
| `Cpu86Nmi()` | non-maskable interrupt (INT 2) at the next instruction boundary |
| `Halted` | 1 after `HLT`, until an interrupt is taken; `Cpu86Run` returns early |
| `R(0..7)` | `AX CX DX BX SP BP SI DI` (16-bit array; byte registers are its bytes) |
| `Cpu86GetSeg(i)` / `Cpu86SetSeg(i, v)` | segment registers `0 ES 1 CS 2 SS 3 DS` |
| `Cpu86GetIP()` / `Cpu86SetIP(ip)` | instruction pointer |
| `Cpu86Flags()` / `Cpu86SetFlags(f)` | the packed FLAGS word |
| `Cpu86Fetching` | 1 while a page-crossing instruction is being prefetched (for hooks) |
| `CpuCycles` | spare 32-bit counter for the host |

`Cpu86Run(n)` returns between instructions, so the host services USB, feeds the
watchdog and raises interrupts between windows. A raised `Cpu86Irq` is held
until the guest's IF is 1 and is then taken at an instruction boundary inside
the window, through the vector given. With `#CPU_TIMING = 1` each instruction
charges its 8086 clock count from Intel's tables (base plus effective-address
time; the prefetch queue, odd-address word penalties and wait states are not
modelled) and `Cpu86Run(n)` runs at least `n` clocks.

The core is a single global CPU, not reentrant; keep it on one host core. It
reserves **r4 (PIP), r5 (PEnd), r8 (FZS), r9 (FC), r10 (FO), r11 (Left)**
for the whole program; PureMetal checks every library and inline-assembly block
against the reservation. Read the flags only through `Cpu86Flags()`.

## Build and run

PureMetal Forge (the IDE application, used headless) compiles and uploads:

```powershell
.\tools\build.ps1 -Source src/demo.picow  -Output firmware/8086-picow.uf2  -Port COM7 -Seconds 20
.\tools\build.ps1 -Source src/demo.pico2w -Output firmware/8086-pico2w.uf2
```

`build.ps1` compiles first, refuses an image that would reach flash offset
`$50000` (where the bench boards keep a NES ROM store) and only then uploads.
The generated core is checked in; to regenerate it: `py -3 tools/gen_cpu.py`.

## Verification

(see below)

## Speed

(see below)

## Credits

- Reference tests: [SingleStepTests/8086](https://github.com/SingleStepTests/8086)
  v1 by Daniel Balsom, captured from a real Intel 8086, MIT licence
  (`Diagnostics/upstream/singlestep-8086-LICENSE`), pinned to commit
  `e71c68d215a6bb8c356bd4cb3842de3bef345ca9`; fetched by `tools/fetch_tests.py`,
  hashes in `Diagnostics/upstream/manifest-8086-v1.json`. Not redistributed here.
- The undocumented `DAA`/`DAS`/`AAA`/`AAS` flag rules and the `IDIV` microcode
  behaviour follow the description in [MartyPC](https://github.com/dbalsom/martypc)
  (MIT), confirmed by the hardware tests above.
- The dispatch design follows the PureMetal PDP-11 and 6502 Pico interpreters.

Original core, demo and tools: MIT, see `LICENSE`.
