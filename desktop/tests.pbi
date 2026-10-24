; The board's own test code, run on the PC: Diagnostics/vectors_state.pmi +
; vectors_run.pmi (SingleStepTests 8086, read from a stream file written by
; tools/vectors.py --out) and Diagnostics/api_state.pmi + api_checks.pmi.
; This file supplies only what the board gets from its USB serial port.

Global TestLog$, TestLine$, TestConsole.i, TestMode.i   ; TestMode 0 machine, 1 vectors, 2 API

Procedure TestFlushLine()
  TestLog$ + TestLine$ + #LF$
  If TestConsole
    PrintN(TestLine$)
  EndIf
  TestLine$ = ""
EndProcedure

Procedure Say(text.s)
  TestLine$ + text
EndProcedure

Procedure Num(v.i)
  TestLine$ + Str(v)
EndProcedure

Procedure Eol()
  TestFlushLine()
EndProcedure

Procedure.i Micros()
  ProcedureReturn ElapsedMilliseconds() * 1000
EndProcedure

; ---- SingleStepTests ----
XIncludeFile "../Diagnostics/vectors_state.pmi"

Global *VecStream, VecStreamLen.i, VecStreamPos.i

Procedure.i RxByte()
  Protected c.i = -1
  If VecStreamPos < VecStreamLen
    c = PeekA(*VecStream + VecStreamPos)
    VecStreamPos + 1
  Else
    c = $5A                 ; past the end: behave as an end-of-stream command
    If VecStreamPos = VecStreamLen + 1 : c = 90 : EndIf
    VecStreamPos + 1
  EndIf
  ProcedureReturn c
EndProcedure

Procedure ReportFail(what.s, got.i, want.i)
  GroupFail = GroupFail + 1
  If GroupReported < 6
    GroupReported = GroupReported + 1
    Say("F " + Str(GroupIndex) + " " + what + " got=" + RSet(Hex(got), 5, "0") + " want=" + RSet(Hex(want), 5, "0"))
    Eol()
  EndIf
EndProcedure

Procedure SayGroupName()
  Say(PeekS(@GroupName(0), -1, #PB_Ascii))
EndProcedure

XIncludeFile "../Diagnostics/vectors_run.pmi"

; ---- API checks ----
XIncludeFile "../Diagnostics/api_state.pmi"

Procedure Check(name.s, got.i, want.i)
  Checks = Checks + 1
  If got <> want
    Failures = Failures + 1
    Say("FAIL " + name + " got=" + RSet(Hex(got), 5, "0") + " want=" + RSet(Hex(want), 5, "0"))
    Eol()
  EndIf
EndProcedure

XIncludeFile "../Diagnostics/api_checks.pmi"

; Runs a stream file through the board's runner. Returns the failed tests, or
; -1 if the file cannot be read. *passed receives the passing count.
Procedure.i RunVectorFile(path.s, *passed.Integer)
  Protected f.i, done.i, fails.i
  f = ReadFile(#PB_Any, path)
  If f = 0
    Say("Cannot read " + path + " - write it with: py -3 tools/vectors.py --out " + path) : Eol()
    ProcedureReturn -1
  EndIf
  VecStreamLen = Lof(f)
  *VecStream = AllocateMemory(VecStreamLen + 16)
  ReadData(f, *VecStream, VecStreamLen)
  CloseFile(f)
  VecStreamPos = 0
  Cpu86RepYield = 0                 ; the reference tests count a whole REP as one step
  TestMode = 1
  VecInit()
  TotalPass = 0 : TotalFail = 0
  Repeat
    done = VecStep()
  Until done
  fails = LastFail
  If *passed : *passed\i = LastPass : EndIf
  FreeMemory(*VecStream) : *VecStream = 0
  TestMode = 0
  ProcedureReturn fails
EndProcedure

Procedure.i RunApiChecks()
  Protected f.i
  Cpu86RepYield = 0                 ; the reference tests count a whole REP as one step
  TestMode = 2
  Say("8086 API checks (desktop core) timing=" + Str(#CPU_TIMING)) : Eol()
  f = ApiChecks()
  Say("API checks=" + Str(Checks) + " failures=" + Str(Failures))
  If Failures = 0 : Say(" PASS") : Else : Say(" FAIL") : EndIf
  Eol()
  TestMode = 0
  ProcedureReturn f
EndProcedure
