; 8086 disassembler for the desktop program's trace pane. Reads guest memory
; through MachinePeek(linear) and decodes one instruction at seg:off,
; including the 8086's aliases and undocumented forms, in Intel syntax.

Global Dim DisR16.s(7)
Global Dim DisR8.s(7)
Global Dim DisSeg.s(3)
Global Dim DisEa.s(7)
Global Dim DisAlu.s(7)
Global Dim DisJcc.s(15)
Global Dim DisShift.s(7)
Global Dim DisGrp3.s(7)
Global DisSegBase.i, DisOff.i, DisPos.i, DisOverride$

Procedure DisInit()
  Protected i.i
  For i = 0 To 7
    DisR16(i) = StringField("ax cx dx bx sp bp si di", i + 1, " ")
    DisR8(i) = StringField("al cl dl bl ah ch dh bh", i + 1, " ")
    DisEa(i) = StringField("bx+si bx+di bp+si bp+di si di bp bx", i + 1, " ")
    DisAlu(i) = StringField("add or adc sbb and sub xor cmp", i + 1, " ")
    DisShift(i) = StringField("rol ror rcl rcr shl shr setmo sar", i + 1, " ")
    DisGrp3(i) = StringField("test test not neg mul imul div idiv", i + 1, " ")
  Next
  For i = 0 To 3
    DisSeg(i) = StringField("es cs ss ds", i + 1, " ")
  Next
  For i = 0 To 15
    DisJcc(i) = StringField("jo jno jb jae je jne jbe ja js jns jp jnp jl jge jle jg", i + 1, " ")
  Next
EndProcedure

Procedure.i DisB()
  Protected v.i = MachinePeek(DisSegBase + ((DisOff + DisPos) & $FFFF))
  DisPos + 1
  ProcedureReturn v
EndProcedure

Procedure.i DisW()
  Protected lo.i = DisB()
  ProcedureReturn lo | (DisB() << 8)
EndProcedure

Procedure.s H2(v.i)
  ProcedureReturn RSet(Hex(v & $FF), 2, "0")
EndProcedure

Procedure.s H4(v.i)
  ProcedureReturn RSet(Hex(v & $FFFF), 4, "0")
EndProcedure

Procedure.s DisSigned8(v.i)
  If v & $80
    ProcedureReturn "-" + H2(256 - v) + "h"
  EndIf
  ProcedureReturn "+" + H2(v) + "h"
EndProcedure

; The E operand of a ModR/M byte (DisPos is just past it). w: 0 byte, 1 word.
Procedure.s DisE(m.i, w.i, ptr.i = 1)
  Protected md.i = m >> 6, rm.i = m & 7, s.s, size.s
  If md = 3
    If w : ProcedureReturn DisR16(rm) : EndIf
    ProcedureReturn DisR8(rm)
  EndIf
  If md = 0 And rm = 6
    s = H4(DisW()) + "h"
  ElseIf md = 0
    s = DisEa(rm)
  ElseIf md = 1
    s = DisEa(rm) + DisSigned8(DisB())
  Else
    s = DisEa(rm) + "+" + H4(DisW()) + "h"
  EndIf
  If ptr
    If w : size = "word " : Else : size = "byte " : EndIf
  EndIf
  ProcedureReturn size + DisOverride$ + "[" + s + "]"
EndProcedure

Procedure.s DisG(m.i, w.i)
  If w : ProcedureReturn DisR16((m >> 3) & 7) : EndIf
  ProcedureReturn DisR8((m >> 3) & 7)
EndProcedure

; One instruction at seg:off. Returns its text; *len receives its length.
Procedure.s Dis86(seg.i, off.i, *len.Integer)
  Protected op.i, m.i, t.s, pre.s, w.i, k.i, d.i, x.i, y.i
  DisSegBase = (seg & $FFFF) << 4 : DisOff = off & $FFFF : DisPos = 0 : DisOverride$ = ""
  Repeat
    op = DisB()
    Select op
      Case $26, $2E, $36, $3E : DisOverride$ = DisSeg((op >> 3) & 3) + ":"
      Case $F0, $F1 : pre + "lock "
      Case $F2 : pre + "repne "
      Case $F3 : pre + "rep "
      Default : Break
    EndSelect
  ForEver
  w = op & 1
  Select op
    Case $00 To $3F
      k = op & 7
      Select k
        Case 0, 1 : m = DisB() : t = DisAlu(op >> 3) + " " + DisE(m, w, 0) + ", " + DisG(m, w)
        Case 2, 3 : m = DisB() : t = DisAlu(op >> 3) + " " + DisG(m, w) + ", " + DisE(m, w, 0)
        Case 4 : t = DisAlu(op >> 3) + " al, " + H2(DisB()) + "h"
        Case 5 : t = DisAlu(op >> 3) + " ax, " + H4(DisW()) + "h"
        Case 6
          If op < $20 : t = "push " + DisSeg(op >> 3) : Else : t = DisSeg((op >> 3) & 3) + ":" : EndIf
        Case 7
          If op < $20
            t = "pop " + DisSeg(op >> 3)
          Else
            t = StringField("daa das aaa aas", ((op >> 3) & 3) + 1, " ")
          EndIf
      EndSelect
    Case $40 To $47 : t = "inc " + DisR16(op & 7)
    Case $48 To $4F : t = "dec " + DisR16(op & 7)
    Case $50 To $57 : t = "push " + DisR16(op & 7)
    Case $58 To $5F : t = "pop " + DisR16(op & 7)
    Case $60 To $7F
      d = DisB() : x = (off + DisPos + PeekB(@d)) & $FFFF
      t = DisJcc(op & 15) + " " + H4(x) + "h"
    Case $80 To $83
      m = DisB() : t = DisAlu((m >> 3) & 7) + " " + DisE(m, w)
      If op = $81 : t + ", " + H4(DisW()) + "h"
      ElseIf op = $83 : d = DisB() : t + ", " + DisSigned8(d)
      Else : t + ", " + H2(DisB()) + "h" : EndIf
    Case $84, $85 : m = DisB() : t = "test " + DisE(m, w, 0) + ", " + DisG(m, w)
    Case $86, $87 : m = DisB() : t = "xchg " + DisE(m, w, 0) + ", " + DisG(m, w)
    Case $88, $89 : m = DisB() : t = "mov " + DisE(m, w, 0) + ", " + DisG(m, w)
    Case $8A, $8B : m = DisB() : t = "mov " + DisG(m, w) + ", " + DisE(m, w, 0)
    Case $8C : m = DisB() : t = "mov " + DisE(m, 1, 0) + ", " + DisSeg((m >> 3) & 3)
    Case $8D : m = DisB() : t = "lea " + DisG(m, 1) + ", " + DisE(m, 1, 0)
    Case $8E : m = DisB() : t = "mov " + DisSeg((m >> 3) & 3) + ", " + DisE(m, 1, 0)
    Case $8F : m = DisB() : t = "pop " + DisE(m, 1)
    Case $90 : t = "nop"
    Case $91 To $97 : t = "xchg ax, " + DisR16(op & 7)
    Case $98 : t = "cbw"
    Case $99 : t = "cwd"
    Case $9A : x = DisW() : y = DisW() : t = "call " + H4(y) + ":" + H4(x)
    Case $9B : t = "wait"
    Case $9C : t = "pushf"
    Case $9D : t = "popf"
    Case $9E : t = "sahf"
    Case $9F : t = "lahf"
    Case $A0 : t = "mov al, " + DisOverride$ + "[" + H4(DisW()) + "h]"
    Case $A1 : t = "mov ax, " + DisOverride$ + "[" + H4(DisW()) + "h]"
    Case $A2 : t = "mov " + DisOverride$ + "[" + H4(DisW()) + "h], al"
    Case $A3 : t = "mov " + DisOverride$ + "[" + H4(DisW()) + "h], ax"
    Case $A4 : t = "movsb"
    Case $A5 : t = "movsw"
    Case $A6 : t = "cmpsb"
    Case $A7 : t = "cmpsw"
    Case $A8 : t = "test al, " + H2(DisB()) + "h"
    Case $A9 : t = "test ax, " + H4(DisW()) + "h"
    Case $AA : t = "stosb"
    Case $AB : t = "stosw"
    Case $AC : t = "lodsb"
    Case $AD : t = "lodsw"
    Case $AE : t = "scasb"
    Case $AF : t = "scasw"
    Case $B0 To $B7 : t = "mov " + DisR8(op & 7) + ", " + H2(DisB()) + "h"
    Case $B8 To $BF : t = "mov " + DisR16(op & 7) + ", " + H4(DisW()) + "h"
    Case $C0, $C2 : t = "ret " + H4(DisW()) + "h"
    Case $C1, $C3 : t = "ret"
    Case $C4 : m = DisB() : t = "les " + DisG(m, 1) + ", " + DisE(m, 1, 0)
    Case $C5 : m = DisB() : t = "lds " + DisG(m, 1) + ", " + DisE(m, 1, 0)
    Case $C6 : m = DisB() : t = "mov " + DisE(m, 0) + ", " + H2(DisB()) + "h"
    Case $C7 : m = DisB() : t = "mov " + DisE(m, 1) + ", " + H4(DisW()) + "h"
    Case $C8, $CA : t = "retf " + H4(DisW()) + "h"
    Case $C9, $CB : t = "retf"
    Case $CC : t = "int 3"
    Case $CD : t = "int " + H2(DisB()) + "h"
    Case $CE : t = "into"
    Case $CF : t = "iret"
    Case $D0 To $D3
      m = DisB() : t = DisShift((m >> 3) & 7) + " " + DisE(m, w)
      If op >= $D2 : t + ", cl" : Else : t + ", 1" : EndIf
    Case $D4 : t = "aam " + H2(DisB()) + "h"
    Case $D5 : t = "aad " + H2(DisB()) + "h"
    Case $D6 : t = "salc"
    Case $D7 : t = "xlat " + DisOverride$ + "[bx+al]"
    Case $D8 To $DF : m = DisB() : t = "esc " + Str(((op & 7) << 3) | ((m >> 3) & 7)) + ", " + DisE(m, 1, 0)
    Case $E0 To $E3, $EB
      d = DisB() : x = (off + DisPos + PeekB(@d)) & $FFFF
      Select op
        Case $E0 : t = "loopne "
        Case $E1 : t = "loope "
        Case $E2 : t = "loop "
        Case $E3 : t = "jcxz "
        Default : t = "jmp short "
      EndSelect
      t + H4(x) + "h"
    Case $E4 : t = "in al, " + H2(DisB()) + "h"
    Case $E5 : t = "in ax, " + H2(DisB()) + "h"
    Case $E6 : t = "out " + H2(DisB()) + "h, al"
    Case $E7 : t = "out " + H2(DisB()) + "h, ax"
    Case $E8 : x = DisW() : t = "call " + H4(off + DisPos + x) + "h"
    Case $E9 : x = DisW() : t = "jmp " + H4(off + DisPos + x) + "h"
    Case $EA : x = DisW() : y = DisW() : t = "jmp " + H4(y) + ":" + H4(x)
    Case $EC : t = "in al, dx"
    Case $ED : t = "in ax, dx"
    Case $EE : t = "out dx, al"
    Case $EF : t = "out dx, ax"
    Case $F4 : t = "hlt"
    Case $F5 : t = "cmc"
    Case $F6, $F7
      m = DisB() : k = (m >> 3) & 7 : t = DisGrp3(k) + " " + DisE(m, w)
      If k < 2
        If w : t + ", " + H4(DisW()) + "h" : Else : t + ", " + H2(DisB()) + "h" : EndIf
      EndIf
    Case $F8 : t = "clc"
    Case $F9 : t = "stc"
    Case $FA : t = "cli"
    Case $FB : t = "sti"
    Case $FC : t = "cld"
    Case $FD : t = "std"
    Case $FE : m = DisB() : t = StringField("inc dec inc dec inc dec inc dec", ((m >> 3) & 7) + 1, " ") + " " + DisE(m, 0)
    Case $FF
      m = DisB() : k = (m >> 3) & 7
      Select k
        Case 0 : t = "inc " + DisE(m, 1)
        Case 1 : t = "dec " + DisE(m, 1)
        Case 2 : t = "call " + DisE(m, 1, 0)
        Case 3 : t = "call far " + DisE(m, 1, 0)
        Case 4 : t = "jmp " + DisE(m, 1, 0)
        Case 5 : t = "jmp far " + DisE(m, 1, 0)
        Default : t = "push " + DisE(m, 1)
      EndSelect
    Default
      t = "db " + H2(op) + "h"
  EndSelect
  If *len : *len\i = DisPos : EndIf
  ProcedureReturn pre + t
EndProcedure
