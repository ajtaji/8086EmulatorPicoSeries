; The desktop machine around the 8086 core: the full 1 MB as RAM except a
; 4 KB ROM at F000:0000 with a few DOS/BIOS services, a console port, and a
; loader for .COM and raw programs.
;
;   port $E9 out   console character (as Bochs' debug port)
;   port $EA out   the program exits with AL as its code (then HLT)
;   INT 20h, INT 21h AH=00h/4Ch   exit;  AH=02h  DL to the console
;   INT 21h AH=09h  DS:DX '$'-terminated string to the console
;   INT 10h AH=0Eh  AL to the console (teletype)
; Every other interrupt vector points at an IRET. Text written to the CGA
; screen at B800:0000 is shown in the Screen tab.

#MACHINE_SEG = $1000              ; a .COM's PSP is at 1000:0000, the code at 1000:0100

Global *MachineRam, *MachineRom
Global MachineConsole$, MachineExited.i, MachineExitCode.i
Global MachineName$ = "(none)", MachineLoadBytes.i
Global *MachineImage, MachineImageLen.i

XIncludeFile "../src/dosrom.pmi"

Procedure MachineInit()
  If *MachineRam = 0
    *MachineRam = AllocateMemory($100000)
    *MachineRom = AllocateMemory($1000)
  EndIf
EndProcedure

; Fresh 1 MB: zeroed RAM, the ROM, the vector table, the core mapped onto it.
Procedure MachineMap()
  Protected i.i
  MachineInit()
  FillMemory(*MachineRam, $100000, 0)
  FillMemory(*MachineRom, $1000, $CF)                ; anything else: IRET
  CopyMemory(?DosRom, *MachineRom, ?DosRomEnd - ?DosRom)
  For i = 0 To 255
    PokeU(*MachineRam + i * 4, #DOSROM_IRET) : PokeU(*MachineRam + i * 4 + 2, $F000)
  Next
  PokeU(*MachineRam + $20 * 4, #DOSROM_INT20)
  PokeU(*MachineRam + $21 * 4, #DOSROM_INT21)
  PokeU(*MachineRam + $10 * 4, #DOSROM_INT10)
  Cpu86MapRam(0, $F0000, *MachineRam)
  Cpu86MapRom($F0000, $1000, *MachineRom)
  Cpu86MapRam($F1000, $F000, *MachineRam + $F1000)
EndProcedure

Procedure.i MachineHookRead(lin.i)
  ProcedureReturn $FF
EndProcedure

Procedure MachineHookWrite(lin.i, v.i)
EndProcedure

Procedure.i MachinePortIn(port.i, wide.i)
  If wide : ProcedureReturn $FFFF : EndIf
  ProcedureReturn $FF
EndProcedure

; Gate mode (cpu86_console.exe --com / --raw, for the compiler's tests): a bare
; CPU with the whole 1 MB as RAM; port E9h prints straight to stdout, a write to
; port F4h ends the run at once with that value.
Global GateMode.i, GateExit.i, GateExitCode.i, GateExitAt.i

Procedure MachineBare()
  MachineInit()
  FillMemory(*MachineRam, $100000, 0)
  Cpu86MapRam(0, $100000, *MachineRam)
EndProcedure

Procedure MachinePortOut(port.i, v.i, wide.i)
  If GateMode
    Select port & $FFFF
      Case $E9
        Print(Chr(v & 255))
      Case $F4
        GateExit = 1 : GateExitCode = v & $FFFF
        GateExitAt = Budget - Left + 1 ; instructions of this Cpu86Run, the OUT included
        Left = 1                       ; the core stops after this instruction
    EndSelect
    ProcedureReturn
  EndIf
  Select port & $FFFF
    Case $E9
      v & 255
      If v = 13
      ElseIf v = 10 Or v = 9 Or (v >= 32 And v < 127)
        MachineConsole$ + Chr(v)
      Else
        MachineConsole$ + "<" + RSet(Hex(v), 2, "0") + ">"
      EndIf
      If Len(MachineConsole$) > 40000 : MachineConsole$ = Right(MachineConsole$, 32000) : EndIf
    Case $EA
      MachineExited = 1 : MachineExitCode = v & 255
  EndSelect
EndProcedure

; The core's four hooks, routed by what is running: the machine, or one of
; the board's test suites (desktop/tests.pbi sets TestMode).
Procedure.i Cpu86HookRead(lin.i)
  Select TestMode
    Case 1 : ProcedureReturn VecHookRead(lin)
    Case 2 : ProcedureReturn ApiHookRead(lin)
  EndSelect
  ProcedureReturn MachineHookRead(lin)
EndProcedure

Procedure Cpu86HookWrite(lin.i, v.i)
  Select TestMode
    Case 1 : VecHookWrite(lin, v)
    Case 2 : ApiHookWrite(lin, v)
    Default : MachineHookWrite(lin, v)
  EndSelect
EndProcedure

Procedure.i Cpu86PortIn(port.i, wide.i)
  Select TestMode
    Case 1 : ProcedureReturn VecPortIn(port, wide)
    Case 2 : ProcedureReturn ApiPortIn(port, wide)
  EndSelect
  ProcedureReturn MachinePortIn(port, wide)
EndProcedure

Procedure Cpu86PortOut(port.i, v.i, wide.i)
  If TestMode = 0
    MachinePortOut(port, v, wide)
  EndIf
EndProcedure

; Put the loaded image back and start it: CS=DS=ES=SS=1000h, IP=0100h,
; SP=FFFEh with a 0 on the stack (a RET goes to the PSP's INT 20h).
Procedure MachineReset()
  Protected i.i
  MachineMap()
  If *MachineImage
    CopyMemory(*MachineImage, *MachineRam + #MACHINE_SEG * 16 + $100, MachineImageLen)
  EndIf
  PokeA(*MachineRam + #MACHINE_SEG * 16, $CD) : PokeA(*MachineRam + #MACHINE_SEG * 16 + 1, $20)
  Cpu86Reset()
  For i = 0 To 3
    Cpu86SetSeg(i, #MACHINE_SEG)
  Next
  R(4) = $FFFE
  Cpu86SetIP($100)
  MachineExited = 0 : MachineExitCode = 0
EndProcedure

Procedure.i MachineLoadMemory(*src, n.i, name.s)
  If n > $FF00 : n = $FF00 : EndIf
  If *MachineImage : FreeMemory(*MachineImage) : EndIf
  *MachineImage = AllocateMemory(n + 1)
  CopyMemory(*src, *MachineImage, n)
  MachineImageLen = n
  MachineName$ = name
  MachineLoadBytes = n
  MachineConsole$ = ""
  MachineReset()
  ProcedureReturn 1
EndProcedure

; A .COM (or any raw binary, treated the same way) up to 65,280 bytes.
Procedure.i MachineLoadFile(path.s)
  Protected f.i, n.i, *b, ok.i
  f = ReadFile(#PB_Any, path)
  If f = 0 : ProcedureReturn 0 : EndIf
  n = Lof(f)
  If n > $FF00 : n = $FF00 : EndIf
  *b = AllocateMemory(n + 1)
  ReadData(f, *b, n)
  CloseFile(f)
  ok = MachineLoadMemory(*b, n, GetFilePart(path))
  FreeMemory(*b)
  ProcedureReturn ok
EndProcedure

; A program given as hex text ("B86400...").
Procedure.i MachineLoadHex(hex.s, name.s)
  Protected n.i = Len(hex) / 2, i.i, *b, ok.i
  *b = AllocateMemory(n + 1)
  For i = 0 To n - 1
    PokeA(*b + i, Val("$" + Mid(hex, i * 2 + 1, 2)))
  Next
  ok = MachineLoadMemory(*b, n, name)
  FreeMemory(*b)
  ProcedureReturn ok
EndProcedure

Procedure.i MachinePeek(lin.i)
  ProcedureReturn Cpu86Rd8(lin & $FFFFF)
EndProcedure
