; desktop/controls.pbi - every key the window takes, in ONE table. The keyboard code
; (cpu86_desktop.pb's event loop, PcScanCode) looks each key up here, the Controls tab
; draws this same table, and tools/controls_readme.py writes README.md's "Controls" from
; it, so the three cannot disagree.
;
; A row: group (a PC key or the window's own action), when (always, in the window only,
; in full screen only), the key (a PureBasic #PB_Shortcut_ code; -1 for a row that is
; only shown), the value (a PC key: its set-1 scan code; the window: an action), the
; keys as shown, and what it does.

#CTL_PC = 0                               ; a key of the emulated PC's keyboard
#CTL_WINDOW = 1                           ; the window's own action

#CTL_ALWAYS = 0
#CTL_WINDOWED = 1
#CTL_FULL = 2

#CTL_FULLSCREEN = 1                       ; the window's actions
#CTL_LEAVEFULL = 2

Structure CtlRow
  group.l
  when.l
  key.l
  value.l
  keys$
  what$
EndStructure

Global NewList CtlRows.CtlRow()

Procedure CtlLoad()
  Protected n.l, i.l
  ClearList(CtlRows())
  Restore CtlTable
  Read.l n
  For i = 1 To n
    AddElement(CtlRows())
    Read.l CtlRows()\group : Read.l CtlRows()\when : Read.l CtlRows()\key : Read.l CtlRows()\value
    Read.s CtlRows()\keys$ : Read.s CtlRows()\what$
  Next
EndProcedure

; The row for a key, in full screen or not: returns its value (a PC key's scan code, or
; the window's action) and sets CtlHitGroup; -1 when the key is not in the table.
Global CtlHitGroup.l
Procedure.l CtlFind(key.l, full.l)
  If key < 0 : ProcedureReturn -1 : EndIf
  ForEach CtlRows()
    If key = CtlRows()\key
      If CtlRows()\when = #CTL_ALWAYS Or (CtlRows()\when = #CTL_WINDOWED And full = 0) Or (CtlRows()\when = #CTL_FULL And full)
        CtlHitGroup = CtlRows()\group
        ProcedureReturn CtlRows()\value
      EndIf
    EndIf
  Next
  ProcedureReturn -1
EndProcedure

DataSection
  CtlTable:
  Data.l 63
  ; the PC's keys (set-1 scan codes); they reach the PC on the PC screen tab, or in full
  ; screen, while it runs
  Data.l #CTL_PC, #CTL_WINDOWED, #PB_Shortcut_Escape, $01
  Data.s "Esc", "Esc (in full screen Esc leaves full screen: use F12)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F12, $01
  Data.s "F12", "Esc, in the window and in full screen (the PC/XT keyboard has no F12)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_1, $02 : Data.s "1", "1"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_2, $03 : Data.s "2", "2"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_3, $04 : Data.s "3", "3"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_4, $05 : Data.s "4", "4"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_5, $06 : Data.s "5", "5"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_6, $07 : Data.s "6", "6"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_7, $08 : Data.s "7", "7"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_8, $09 : Data.s "8", "8"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_9, $0A : Data.s "9", "9"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_0, $0B : Data.s "0", "0"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Back, $0E : Data.s "Backspace", "Backspace"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Tab, $0F : Data.s "Tab", "Tab"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Q, $10 : Data.s "Q", "Q"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_W, $11 : Data.s "W", "W"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_E, $12 : Data.s "E", "E"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_R, $13 : Data.s "R", "R"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_T, $14 : Data.s "T", "T"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Y, $15 : Data.s "Y", "Y"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_U, $16 : Data.s "U", "U"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_I, $17 : Data.s "I", "I"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_O, $18 : Data.s "O", "O"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_P, $19 : Data.s "P", "P"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Return, $1C : Data.s "Enter", "Enter"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Control, $1D : Data.s "Ctrl", "Ctrl"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_A, $1E : Data.s "A", "A"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_S, $1F : Data.s "S", "S"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_D, $20 : Data.s "D", "D"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F, $21 : Data.s "F", "F"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_G, $22 : Data.s "G", "G"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_H, $23 : Data.s "H", "H"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_J, $24 : Data.s "J", "J"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_K, $25 : Data.s "K", "K"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_L, $26 : Data.s "L", "L"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Shift, $2A : Data.s "Shift", "Shift (left)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Z, $2C : Data.s "Z", "Z"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_X, $2D : Data.s "X", "X"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_C, $2E : Data.s "C", "C"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_V, $2F : Data.s "V", "V"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_B, $30 : Data.s "B", "B"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_N, $31 : Data.s "N", "N"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_M, $32 : Data.s "M", "M"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Alt, $38 : Data.s "Alt", "Alt"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Space, $39 : Data.s "Space", "Space"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F1, $3B : Data.s "F1", "F1"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F2, $3C : Data.s "F2", "F2"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F3, $3D : Data.s "F3", "F3"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F4, $3E : Data.s "F4", "F4"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F5, $3F : Data.s "F5", "F5"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F6, $40 : Data.s "F6", "F6"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F7, $41 : Data.s "F7", "F7"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F8, $42 : Data.s "F8", "F8"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F9, $43 : Data.s "F9", "F9"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_F10, $44 : Data.s "F10", "F10"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Up, $48 : Data.s "Up", "Up (keypad 8)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Left, $4B : Data.s "Left", "Left (keypad 4)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Right, $4D : Data.s "Right", "Right (keypad 6)"
  Data.l #CTL_PC, #CTL_ALWAYS, #PB_Shortcut_Down, $50 : Data.s "Down", "Down (keypad 2)"
  ; the window's own
  Data.l #CTL_WINDOW, #CTL_ALWAYS, #PB_Shortcut_F11, #CTL_FULLSCREEN
  Data.s "F11", "full screen on / off (the PC machine; also the Full screen button)"
  Data.l #CTL_WINDOW, #CTL_FULL, #PB_Shortcut_Escape, #CTL_LEAVEFULL
  Data.s "Esc, in full screen", "leaves full screen"
  Data.l #CTL_WINDOW, #CTL_ALWAYS, -1, 0
  Data.s "Mouse wheel", "scrolls the memory view, the Controls list and the output"
  Data.l #CTL_WINDOW, #CTL_ALWAYS, -1, 0
  Data.s "Click a disassembly line", "sets or clears the breakpoint there"
EndDataSection
