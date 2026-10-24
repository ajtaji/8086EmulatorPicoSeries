; The core's four hooks, routed by what is running: one of the board's test
; suites (desktop/tests.pbi sets TestMode), the PC machine, or the DOS-style
; demo machine. On the PC machine port E9h is the console and F4h ends the run
; (the PureMetal 8086 back end's convention), as in the gate runner.

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

; cpu86_pc.exe --portlog FRAME:N: the first N PC port accesses from frame FRAME on,
; each with its scanline and the clock within it (timing investigations).
Global PortLogFrom.i = -1, PortLogLeft.i

Procedure PortLog(dir.s, port.i, v.i)
  If PortLogLeft > 0 And PortLogFrom >= 0 And PcFrames >= PortLogFrom
    PortLogLeft - 1
    PrintN(dir + " " + RSet(Hex(port & $FFFF), 4, "0") + " " + RSet(Hex(v & $FFFF), 2, "0") + "  line " + Str(PcLineNo) +
           " clock " + Str(Pc86LineClock()) + "  at " + RSet(Hex(Cpu86GetSeg(1)), 4, "0") + ":" + RSet(Hex(Cpu86GetIP()), 4, "0") + "  IF " + Str(Bool(Cpu86Flags() & $200)))
  EndIf
EndProcedure

Procedure.i Cpu86PortIn(port.i, wide.i)
  Protected v.i
  Select TestMode
    Case 1 : ProcedureReturn VecPortIn(port, wide)
    Case 2 : ProcedureReturn ApiPortIn(port, wide)
  EndSelect
  If MachineKind = 1 And GateMode = 0
    ProcedureReturn Pc86PortIn(port, wide)
  ElseIf MachineKind = 1
    If (port & $FFFF) <> $E9 And (port & $FFFF) <> $F4
      v = Pc86PortIn(port, wide)
      If PortLogLeft : PortLog("IN ", port, v) : EndIf
      ProcedureReturn v
    EndIf
  EndIf
  ProcedureReturn MachinePortIn(port, wide)
EndProcedure

Procedure Cpu86PortOut(port.i, v.i, wide.i)
  If TestMode <> 0 : ProcedureReturn : EndIf
  If MachineKind = 1
    If PortLogLeft And GateMode : PortLog("OUT", port, v) : EndIf
    Select port & $FFFF
      Case $E9, $F4
        If GateMode
          MachinePortOut(port, v, wide)
        ElseIf (port & $FFFF) = $E9
          MachinePortOut($E9, v, 0)
        Else
          MachineExited = 1 : MachineExitCode = v & $FFFF : Left = 1
        EndIf
      Default
        Pc86PortOut(port, v, wide)
    EndSelect
    ProcedureReturn
  EndIf
  MachinePortOut(port, v, wide)
EndProcedure
