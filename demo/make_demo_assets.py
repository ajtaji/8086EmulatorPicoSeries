#!/usr/bin/env python3
"""
make_demo_assets.py - the tables the 8086 PC demo reads, written as PureMetal
DataSection source (demo_assets.pc8086).

  py -3 make_demo_assets.py           write demo_assets.pc8086
  py -3 make_demo_assets.py --check   fail if the file on disk is not what this writes

Everything here is computed: a sine table, the PC speaker's divisors for the
notes, the plasma's colour ramp, the big letters of the title, and the tune
(original, written for this demo).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demo_assets.pc8086")
PIT_HZ = 1193182


def data_lines(label, kind, values, per=16):
    out = [label + ":"]
    for i in range(0, len(values), per):
        out.append("  Data.%s %s" % (kind, ", ".join(str(v) for v in values[i:i + per])))
    return out


def sine_table():
    # 256 steps a turn, 0..63 (centre 32): plasma and bar positions add these.
    return [int(round(31.5 + 31.5 * math.sin(2 * math.pi * i / 256))) for i in range(256)]


def note_divisors():
    # MIDI notes 0..95 as 8253 channel 2 divisors; 0 (and too-low notes) -> 0 = silence.
    out = []
    for n in range(96):
        f = 440.0 * 2 ** ((n - 69) / 12.0)
        d = int(round(PIT_HZ / f))
        out.append(d if 19 < d < 65536 and n >= 24 else 0)
    return out


# The plasma's 64-step ramp: CGA text cells (character | attribute << 8).
# Shade characters between two colours give in-between steps: 176 (25%),
# 177 (50%), 178 (75%), 219 (full).
RAMP_COLOURS = [0, 1, 9, 11, 15, 14, 12, 4, 5, 13, 15, 11, 3, 2, 10, 15, 7, 8]


def plasma_ramp():
    steps = []
    cols = RAMP_COLOURS
    chars = [219, 178, 177, 176]          # mostly "from" .. mostly "to"
    for i in range(len(cols) - 1):
        a, b = cols[i], cols[i + 1]
        for c in chars:
            steps.append(c | ((a | (b << 4)) << 8))      # blink off: 16 background colours
    # exactly 64 entries, wrapping smoothly
    while len(steps) < 64:
        steps.append(steps[len(steps) % len(steps)])
    return steps[:64]


# A 5x5 font for the title, one byte a row (bit 4 = leftmost).
FONT = {
    "P": ["11110", "10001", "11110", "10000", "10000"],
    "U": ["10001", "10001", "10001", "10001", "01110"],
    "R": ["11110", "10001", "11110", "10010", "10001"],
    "E": ["11111", "10000", "11110", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10001", "10001"],
    "T": ["11111", "00100", "00100", "00100", "00100"],
    "A": ["01110", "10001", "11111", "10001", "10001"],
    "L": ["10000", "10000", "10000", "10000", "11111"],
    "8": ["01110", "10001", "01110", "10001", "01110"],
    "0": ["01110", "10011", "10101", "11001", "01110"],
    "6": ["01110", "10000", "11110", "10001", "01110"],
    " ": ["00000"] * 5,
}


def title_bits(text):
    rows = []
    for r in range(5):
        v = []
        for ch in text:
            v.append(int(FONT[ch][r], 2))
        rows.append(v)
    return rows


# ----------------------------------------------------------------------
# THE TUNE. One voice (the speaker), 7 timer ticks a row at 60 Hz. A row is a
# melody note, or 0: then the chord arpeggiates, one note a tick. Chords are
# the root's MIDI note and the shape (minor 0, major 1). Original.
# ----------------------------------------------------------------------
A3, C4, D4, E4, F4, G4, A4, B4, C5, D5, E5, F5, G5, A5 = 57, 60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77, 79, 81
CHORDS = [(57, 0), (53, 1), (60, 1), (55, 1)]          # Am F C G, a bar each
MELODY = [
    # bar 1 Am
    A4, 0, C5, 0, E5, 0, D5, C5, 0, 0, B4, 0, C5, 0, 0, 0,
    # bar 2 F
    A4, 0, A4, C5, 0, 0, F5, 0, E5, 0, D5, 0, C5, 0, 0, 0,
    # bar 3 C
    G4, 0, C5, 0, E5, 0, G5, 0, E5, 0, D5, C5, 0, 0, D5, 0,
    # bar 4 G
    B4, 0, D5, 0, G5, 0, F5, E5, D5, 0, B4, 0, G4, 0, 0, 0,
]
MELODY_B = [
    # bars 5-8: the answer, higher
    E5, 0, E5, 0, A5, 0, G5, E5, 0, 0, C5, 0, D5, E5, 0, 0,
    F5, 0, E5, 0, D5, 0, C5, 0, A4, 0, C5, 0, F5, 0, 0, 0,
    E5, 0, G5, 0, C5, 0, E5, 0, D5, 0, C5, 0, G4, 0, 0, 0,
    D5, 0, B4, 0, G4, 0, B4, D5, G5, 0, F5, 0, D5, 0, B4, 0,
]


def song():
    rows = MELODY + MELODY_B
    chord_of_row = []
    for bar in range(8):
        chord_of_row += [bar % 4] * 16
    return rows, chord_of_row


def main():
    lines = ["; demo_assets.pc8086 - WRITTEN BY make_demo_assets.py; do not edit by hand.",
             "; The tables of the 8086 PC demo (demo.pc8086).", "", "DataSection"]
    lines += data_lines("SineTable", "a", sine_table())
    lines += data_lines("NoteDivisor", "u", note_divisors())
    lines += data_lines("PlasmaRamp", "u", plasma_ramp(), per=8)
    title = "PUREMETAL"
    sub = "8086"
    lines += data_lines("TitleBits", "a", sum(title_bits(title), []), per=len(title))
    lines += data_lines("SubBits", "a", sum(title_bits(sub), []), per=len(sub))
    rows, chord = song()
    lines += data_lines("SongRows", "a", rows)
    lines += data_lines("SongChord", "a", chord)
    chords = []
    for root, shape in CHORDS:
        third = 3 if shape == 0 else 4
        chords += [root, root + third, root + 7]
    lines += data_lines("ChordNotes", "a", chords, per=3)
    msg = ("PUREMETAL ON THE INTEL 8086 ... COMPILED, NOT HAND-WRITTEN ... "
           "A TEXT-MODE PLASMA, BORDER BARS AND THE PC SPEAKER, ALL FROM ONE .COM ...     ")
    lines += data_lines("ScrollText", "a", [ord(c) for c in msg] + [0])
    lines += ["EndDataSection", ""]
    text = "\n".join(lines)
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        if cur != text:
            print("demo_assets.pc8086 is STALE - run make_demo_assets.py")
            return 1
        print("demo_assets.pc8086 is current")
        return 0
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
