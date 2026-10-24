# PUREMETAL 8086 - a PC demo written in PureMetal

A demo for the PC machine of this emulator (CGA, the 8253 timer and its speaker, the 8259, no BIOS), written
in PureMetal and compiled by PureMetal Forge's 8086 back end - no hand-written assembly.

| File | What it is |
|---|---|
| `demo.pc8086` | the demo |
| `demo_assets.pc8086` | its tables, written by `make_demo_assets.py` (do not edit by hand) |
| `make_demo_assets.py` | the sine table, the speaker's note divisors, the plasma's colour ramp, the title letters, the tune |
| `demo.com` | the built demo |

## What it shows

1. **The title** - 80 x 25 text with blink off, so 16 background colours. PUREMETAL and 8086 in big block
   letters whose colours roll, under **raster bars in the border**: the border colour (port $3D9) is
   changed in the horizontal blank, a new colour every third scan line, so the bars are drawn by timing alone.
2. **The plasma** - 40 x 25 text: every cell a shade character (25 / 50 / 75 / 100 %) between two of the sixteen
   colours, so 64 steps of colour from a 16-colour screen; two sine waves across and two down, recomputed
   every frame; a rainbow **scroller** on the bottom row.
3. **The copper** - 320 x 200 x 4, where colour 0 IS the background register: the same per-line trick
   now paints bars right across the screen behind the picture, and the lower half of the screen switches to
   the other palette with intensity, so the logo's colours change at the line where the palette does.
4. **The music** - one voice on the **PC speaker**, from the 8253's channel 2, driven by the timer
   interrupt (`ProcedureInterrupt Timer()`, IRQ0 at 60 Hz): a melody, with the chords as fast arpeggios between
   its notes. Original, written for this demo.

The parts loop forever: ten seconds of title, twenty-five of plasma, ten of copper.

## Build and run

    PureMetalForge.exe --compile demo.pc8086           (writes demo.com; needs the 8086 back end, compiler of 2026-10-23 or later)
    desktop\cpu86_pc.exe --com demo.com --pc            (the window, with sound)
    py -3 tools\make_pcprogram.py demo\demo.com          (then build src\pc.picow for the Pico W)

`py -3 make_demo_assets.py --check` fails if `demo_assets.pc8086` is not what the script writes.
