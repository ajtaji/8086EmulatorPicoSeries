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

Procedure.i Cpu86PortIn(port.i, wide.i)
  Select TestMode
    Case 1 : ProcedureReturn VecPortIn(port, wide)
    Case 2 : ProcedureReturn ApiPortIn(port, wide)
  EndSelect
  If MachineKind = 1 And GateMode = 0
    ProcedureReturn Pc86PortIn(port, wide)
  ElseIf MachineKind = 1
    If (port & $FFFF) <> $E9 And (port & $FFFF) <> $F4 : ProcedureReturn Pc86PortIn(port, wide) : EndIf
  EndIf
  ProcedureReturn MachinePortIn(port, wide)
EndProcedure

Procedure Cpu86PortOut(port.i, v.i, wide.i)
  If TestMode <> 0 : ProcedureReturn : EndIf
  If MachineKind = 1
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
