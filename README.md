# Intel 8086 on the Raspberry Pi Pico series — PureMetal

A fast Intel 8086 interpreter core for the Raspberry Pi Pico W (RP2040) and
Pico 2 W (RP2350), written in PureMetal. The interpreter runs from SRAM and
dispatches through a 256-entry `.Label` table; every handler ends in its own
computed jump, so there is no procedure call per guest instruction.

Status, results and the measured speed are in **Verification** and **Speed**
below. Everything reported there ran on the physical boards.

**On the PC:** the same core, generated from the same handlers, runs as a
Windows program with a Neon Arcade Display Engine front end in [`desktop/`](desktop/README.md):
it passes the same 646,000 reference tests with the board's own test code, and
runs 230-490 M instructions a second.

**A PC around it:** `src/pc86.pmi` is a minimal BIOS-less IBM PC (CGA, 8253,
8259, keyboard on IRQ1), shared by the desktop program and the Pico W
(`src/pc.picow`, picture on the bench's ST7796 panel, in real time). See
**The PC machine** below and [`desktop/README.md`](desktop/README.md) for the
memory map and the ports.

## What it implements

The whole 8086 instruction set, as the real chip behaves:

- every opcode byte `00`â€“`FF`, including the 8086's aliases (`60`â€“`6F` as
  `Jcc`, `C0`/`C1` as `RET`, `C8`/`C9` as `RETF`, `82` as `80`, `F1` as
  `LOCK`, `F6`/`F7 /1` as `TEST`, `FF /7` as `PUSH`), `POP CS` (`0F`),
  `MOV CS` (`8E /1`), `SALC` (`D6`) and `SETMO`/`SETMOC` (`D0`â€“`D3 /6`);
- segment override prefixes on every memory operand (string destinations stay
  on `ES`), `LOCK` accepted, `REP`/`REPE`/`REPNE` on all string instructions;
- `MUL`/`IMUL`/`DIV`/`IDIV`/`AAM`/`AAD`, with the divide-error interrupt
  (type 0, the return address being the next instruction, as on the 8086);
  `IDIV` refuses a quotient of -128 / -32768 as the 8086 does, and a `REP`
  prefix negates the `IDIV` quotient and the `IMUL` product, as the 8086's
  microcode does;
- 8086 specifics: `PUSH SP` pushes the decremented value, shift and rotate
  counts are **not** masked (`CL` up to 255), word accesses at offset `FFFF`
  wrap inside the segment, linear addresses wrap at 1 MB, `FLAGS` bits 12â€“15
  read as 1;
- exact flags including AF and PF, and the undocumented flag results of
  `DAA`, `DAS`, `AAA` and `AAS` that the reference tests check;
- `INT n`, `INT 3`, `INTO`, `IRET`, `HLT`, the trap flag (single step), NMI and
  a maskable interrupt line with the 8086's one-instruction delays after `STI`
  and after a load of `SS`;
- `IN`/`OUT` through port hooks; `ESC` (`D8`â€“`DF`) decodes its operand and does
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
the pointer sends everything else â€” ROM writes, unmapped space, hooks, a word
that crosses a page or the 64 KB segment end â€” to the slow procedures. RAM need
not be contiguous on the host: the demo joins two arrays into one guest range.

Instruction fetch does not go through the tables at all. The instruction
pointer is a host pointer into a *fetch window* â€” the current 4 KB page, cut
short so that any instruction starting inside it has all of its (at most six)
bytes inside the page and inside the code segment. Leaving the window costs one
re-computation; an instruction that crosses a page or the IP wrap is copied
into a six-byte buffer and executed from there.

**How much guest RAM fits.** The interpreter's code runs from SRAM and takes
about 89 KB (88,864 bytes on the RP2040, 87,304 on the RP2350); the page
tables, dispatch tables and registers take about 5 KB more. The SRAM is also
split by the USB serial library's fixed buffers at `$20030000`. The demo gives
the guest **156 KB on the Pico W** (100 KB below the USB buffers, 56 KB above;
about 6 KB of SRAM is left for the program) and **420 KB on the Pico 2 W**
(320 KB + 100 KB). That is the 8086's first 156 KB / 420 KB as RAM; a machine
wanting the full 640 KB needs ROM pages in flash and PSRAM or hook pages for
the rest, none of which needs a change to the core. Re-measured with the
compiler rebuilt on 2026-10-23 (largest-first placement): 160 KB is the most
that fits on the Pico W (1.6 KB of SRAM left), so the demo keeps 156 KB.

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

Ready images: `firmware/8086-picow.uf2` (run on the Pico W; SHA-256
`3c0597b3ab08cb76174993ec98507b7b7bcf0b97cc41eb8e6adb480970b43452`) and
`firmware/8086-pico2w.uf2` (built, not run here; `09e75cf17f9597e8caac60fbf59049b5d773cd3bde7d1c2da223a1e5886b2f26`).
Copy one to the board's BOOTSEL drive and open its USB serial port within 30 s:
it prints the smoke test and then the speed of each mix, once a second.

`build.ps1` compiles first, refuses an image that would reach flash offset
`$50000` (where the bench boards keep a NES ROM store) and only then uploads.
The generated core is checked in; to regenerate it: `py -3 tools/gen_cpu.py`.

## Verification

Everything below ran **on the physical Pico W** (COM7, RP2040 at 200 MHz). The
reference tests are streamed to the board over USB by `tools/vectors.py`, which
only converts the published JSON into a compact stream; the board runs each
test through `Cpu86Run(1)` and checks it itself (`Diagnostics/vectors_body.pmi`):
all fourteen registers, FLAGS under the reference's mask of undefined flags,
every byte the test touches (the pushed FLAGS word of a divide error under the
same mask), and that nothing else was written. Pages the test does not name are
hook pages that count any data access as a failure.

| Check | Build | Result |
|---|---|---|
| SingleStepTests 8086 v1, **every test of every file** (323 files, 2,000 each) | assembly tail, instruction budget | **646,000 of 646,000 pass** |
| SingleStepTests, 100 from every file (32,300) | clock budget (`#CPU_TIMING = 1`) | 32,300 of 32,300 pass |
| SingleStepTests, 100 from every file (32,300) | plain PureMetal tail (`#CPU_ASM_TAIL = 0`) | 32,300 of 32,300 pass |
| API, interrupt and memory-map checks (`Diagnostics/api_body.pmi`) | each of the three builds | 78 of 78 (assembly tail), 77 of 77 (clock budget), 78 of 78 (plain tail) |
| Demo smoke test (sum 1..100, `LOOP`, `HLT`) and copy check | both tails | pass |
| Whole program: `sieve.com` (primes below 10000) through the demo ROM's DOS services, its output compared | assembly tail | pass: `primes below 10000: 1229`, 120,169 instructions in 51 ms |

The API checks cover what single-instruction tests cannot: the run budget, `HLT`,
the interrupt line with the one-instruction `STI` delay and acknowledge, NMI with
IF clear, the trap flag (the trap follows the instruction after `POPF`, and
`IRET` does not trap after itself), the divide-error return address, ROM,
unmapped and hook pages, a word across two host arrays, a word at offset `FFFF`,
instructions across a page boundary and across the IP wrap, self-modifying code,
prefixes within one budget step, `REP MOVS`/`STOS` with overlap, page crossing,
ROM targets and the segment wrap, `PUSH SP` and the port hooks.

Logs: `docs/verify-full-1.log`, `docs/verify-full-2.log`, `docs/verify-timed.log`,
`docs/verify-pure.log`, and `docs/board-*.txt` for the API and demo runs. The
reference corpus is not stored here: `py -3 tools/fetch_tests.py` downloads the
pinned commit (about 180 MB), then

```powershell
.\tools\board.ps1 -Minutes 8 -Jobs @(
  'vectors Diagnostics/vectors.picow Diagnostics/build/vectors.uf2 --per-file 2000 --part 1/2 --log docs/verify-full-1.log',
  'vectors Diagnostics/vectors.picow Diagnostics/build/vectors.uf2 --per-file 2000 --part 2/2 --log docs/verify-full-2.log')
```

builds, uploads and streams it. `board.ps1` takes the bench's COM7 lease through
the shared `C:\PMFBuild\board-leases\lease.ps1` and holds it for the whole
batch; on another bench run `tools/build.ps1 ... -Port <port>` and
`tools/vectors.py --port <port>`. About 64 MB go over USB serial at roughly
200 KB/s, about 5 minutes.

The Pico 2 W builds (`src/demo.pico2w`, `Diagnostics/vectors.pico2w`,
`Diagnostics/api.pico2w`) compile from the same generator with the same
register reservation; they have not been run on a Pico 2 W in this work.

## Speed

Physical Pico W, RP2040 at 200 MHz, instruction budget, 1,000,000 guest
instructions per sample, USB and set-up outside the timed interval
(`src/demo_body.pmi`; logs `docs/board-*.txt`):

| Mix | first version | tuned, assembly tail | tuned, plain PureMetal tail |
|---|---:|---:|---:|
| register / branch (`DEC CX` / `JNZ`) | 3.85 M instr/s | **4.60 M** | 3.96 M |
| ALU (`ADD` `XOR` `SHL` `ADC` `SUB` `INC` on registers) | 2.29 M | **2.41 M** | 2.25 M |
| memory (`MOV`/`ADD` through `[SI]`, `[DI+2]`, immediates) | 1.69 M | **1.83 M** | 1.74 M |
| call / stack (`PUSH` `CALL` `INC` `RET` `POP`) | 2.11 M | **2.47 M** | 2.30 M |
| `REP MOVSW`, 8 KB blocks | 2.07 MB/s | **9.47 MB/s** | 9.47 MB/s |

For scale, a 4.77 MHz IBM PC's 8088 runs well under a million instructions a
second. What made the difference, measured one change at a time:

- the budget counter in r6 and the window end in r11, so the dispatch tail
  decrements the budget in place and compares against the window end directly
  (two Thumb instructions fewer per guest instruction; every mix faster);
- AF kept lazily (`FA` holds the operands' XOR, AF is bit 4 of `FA ^ result`);
- pages 0–15 mirrored above 1 MB, so `segment * 16 + offset` needs no mask;
- one test (`offset ends in F`) sending every possibly-straddling word to the
  slow path, instead of separate page-end and segment-end tests;
- `REP MOVS` / `REP STOS` moving whole runs between host pointers.

Reserving a seventh register for AF is refused by the compiler (the RP2040
allocator needs one of r5/r6 for its spill pool), and r12 cannot hold state
because the flash/SRAM call veneers write it.

## The PC machine on the Pico W

`src/pc.picow` runs a .COM program on the PC machine (`src/pc86.pmi`, the same
device code as the desktop's; memory map and ports in
[`desktop/README.md`](desktop/README.md#the-pc-machine)), with the core counting
8086 clocks: 262 scanlines of 304 clocks, 59.92 frames a second, paced by the
Pico's timer.

```powershell
py -3 tools/make_pcprogram.py desktop/examples/bars.com          # writes src/pcprogram.pmi
.	oolsuild.ps1 -Source src/pc.picow -Output firmware/8086-pc-picow.uf2 -Port COM7
```

- RAM: 128 KB from linear 0 (96 KB + 32 KB, around the USB buffers); CGA 16 KB at
  B8000, mirrored at BC000. A .COM needs 64 KB above 0050:0000.
- Picture: the LAFVIN ST7796 (480 x 320) shows the 200 lines at half width,
  320 x 200, centred; core 1 converts and sends lines by DMA while core 0 runs the
  PC. Lines are drawn by `Pc86RenderHalf`, which writes the panel's pixels
  straight into the line ring, four to a store; `cpu86_pc.exe --halfcheck`
  compares it with the desktop's full-width renderer on every line (pixel x =
  full pixel 2x). No border on the panel.
- USB serial: `OUT E9h` prints there; typed characters become set-1 scan codes
  (make, then break: letters, digits, space, Enter, Esc, Backspace); `OUT F4h`
  ends the run. The run starts once a host opens the port, or after 10 s. Once
  a second it prints frames, clocks a second, CS:IP, the CGA registers and
  where core 0's time went.
- No speaker: the bench Pico W has none; port 61h and PIT channel 2 still work.

On the board (COM7, `docs/pc-*-picow.log`, `docs/board-pc-run.log`):

| Program | Result | clocks/s | core 0 busy (drawing) |
|---|---|---:|---:|
| `pctest.com` | `R=7 T=115`, `PC EXIT code=7` at frame 37: the same as the desktop | | |
| `keytest.com`, typed `abz` | `1E 9E 30 B0 2C AC` | 4.78 M (60 frames/s) | 90% (81%), 80-column text |
| `modes.com`, every CGA mode | all 40 mode/colour pairs, `PC EXIT code=0` at frame 1439 | 4.78 M | about 80% (50%) |
| `bars.com`, $3D9 every line | runs | 4.78 M (60 frames/s) | 84% (43%), 320 x 200 |

So every mode runs at the real 4.77 MHz, with the least room in 80-column text:
a program that keeps the CPU busy there will run a little slow. The image is
built with 32 bytes of SRAM to spare.

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
