; The PC machine on the desktop: src/pc86.pmi (the devices, shared with the
; Pico build) given 640 KB of RAM, 16 KB of CGA memory at B800:0000 (mirrored at
; BC00:0000), a screen texture, the keyboard and the speaker through waveOut.
; A program loads at 0050:0100 (#PC86_SEG) as a .COM would; no BIOS, no ROM.

#PC86_SEG = $0050
#PC_W = 640                         ; the picture
#PC_H = 200
#PC_BX = 32                         ; the border (overscan) each side, in the picture's pixels
#PC_BY = 16                         ; and above and below, in scanlines
#PC_FW = #PC_W + 2 * #PC_BX         ; the whole screen: 704 x 232 scanlines
#PC_FH = #PC_H + 2 * #PC_BY
#PC_RATE = 48000
#PC_FRAME_SAMPLES = 800             ; 48000 / 60
#PC_SND_BUFFERS = 6

#PC86_HALF = 0                      ; full-width lines through Pc86PutLine (the Pico draws them at half width)
XIncludeFile "../src/pc86_state.pmi"

Global Dim PcRGBA.l(#PC_FW * #PC_FH)
Global Dim PcTexRows.l(#PC_FW * #PC_FH * 2) ; each line twice: 704 x 464
Global Dim CgaRGBA.l(15)
Global *PcVramMem
Global PcTex.l, PcSprite.GLSprite, PcTexReady.i

Declare Pc86RenderHalf(line.i, dest.i)
Global Dim PcFull.a(#PC_W)
Global Dim PcHalf.a(#PC_W / 2)
Global PcHalfCheck.i, PcHalfLines.i, PcHalfBad.i, PcHalfFirst.s

Procedure Pc86PutLine(line.i)
  Protected x.i, row.i = (line + #PC_BY) * #PC_FW + #PC_BX
  For x = 0 To #PC_W - 1
    PcRGBA(row + x) = CgaRGBA(PcLine(x))
  Next
  If PcHalfCheck                    ; --halfcheck: the Pico's renderer against this one, same registers
    CopyMemory(@PcLine(0), @PcFull(0), #PC_W)
    Pc86RenderHalf(line, @PcHalf(0))
    PcHalfLines + 1
    For x = 0 To #PC_W / 2 - 1
      If PcHalf(x) <> PcFull(x * 2)
        If PcHalfBad = 0
          PcHalfFirst = "frame " + Str(PcFrames) + " line " + Str(line) + " x " + Str(x) + ": " + Str(PcHalf(x)) + " vs " + Str(PcFull(x * 2)) + " mode " + Hex(PcMode)
        EndIf
        PcHalfBad + 1 : Break
      EndIf
    Next
    CopyMemory(@PcFull(0), @PcLine(0), #PC_W)
  EndIf
EndProcedure

; The border: the overscan colour as this scanline begins (latched with $3D8/$3D9,
; before the CPU runs the line). $3D9 bits 0-3, except in 640 x 200 where those
; bits are the foreground and the border is black. Shown: 16 scanlines above the
; picture (the frame's last lines, 246-261), the picture's lines with 32 pixels
; each side, 16 scanlines below it (200-215). Desktop only: the Pico's panel
; draws the picture alone.
Procedure PcBorderLine(line.i)
  Protected c.l, row.i, x.i
  If (PcMode & $12) = $12 : c = CgaRGBA(0) : Else : c = CgaRGBA(PcColor & 15) : EndIf
  If line < #PC86_VISIBLE
    row = (line + #PC_BY) * #PC_FW
    For x = 0 To #PC_BX - 1
      PcRGBA(row + x) = c : PcRGBA(row + #PC_BX + #PC_W + x) = c
    Next
    ProcedureReturn
  ElseIf line < #PC86_VISIBLE + #PC_BY
    row = (line + #PC_BY) * #PC_FW
  ElseIf line >= #PC86_LINES - #PC_BY
    row = (line - (#PC86_LINES - #PC_BY)) * #PC_FW
  Else
    ProcedureReturn
  EndIf
  For x = 0 To #PC_FW - 1
    PcRGBA(row + x) = c
  Next
EndProcedure

XIncludeFile "../src/pc86.pmi"
XIncludeFile "../src/cgafont.pmi"

; One scanline of the PC with its border.
Procedure.i PcRunLine()
  PcBorderLine(PcLineNo)
  ProcedureReturn Pc86RunLine()
EndProcedure

Procedure PcPaletteInit()
  Protected i.i, r.i, g.i, b.i
  For i = 0 To 15
    r = PeekA(?CgaRgb + i * 3) : g = PeekA(?CgaRgb + i * 3 + 1) : b = PeekA(?CgaRgb + i * 3 + 2)
    CgaRGBA(i) = r | (g << 8) | (b << 16) | $FF000000
  Next
EndProcedure

; Fresh PC: zeroed RAM and CGA memory, the map, the devices at power-on.
Procedure PcMap()
  MachineInit()
  PcPaletteInit()
  If *PcVramMem = 0 : *PcVramMem = AllocateMemory($4000) : EndIf
  FillMemory(*MachineRam, $100000, 0)
  FillMemory(*PcVramMem, $4000, 0)
  PcVram = *PcVramMem
  Cpu86MapNone(0, $100000)
  Cpu86MapRam(0, $A0000, *MachineRam)
  Cpu86MapRam($B8000, $4000, *PcVramMem)
  Cpu86MapRam($BC000, $4000, *PcVramMem)
  Pc86Reset()
EndProcedure

; Copy n bytes to 0050:0100, CS=DS=ES=SS=0050, IP=0100, SP=FFFE.
Procedure PcStart(*image, n.i)
  Protected i.i
  PcMap()
  If n > $A0000 - (#PC86_SEG * 16 + $100) : n = $A0000 - (#PC86_SEG * 16 + $100) : EndIf
  If *image And n > 0 : CopyMemory(*image, *MachineRam + #PC86_SEG * 16 + $100, n) : EndIf
  Cpu86Reset()
  For i = 0 To 3 : Cpu86SetSeg(i, #PC86_SEG) : Next
  R(4) = $FFFE
  Cpu86SetIP($100)
  Pc86Reset()
EndProcedure

; ---- screen texture (bottom row first: the engine samples a sprite's top at v = 1) ----
Procedure PcTextureInit()
  glGenTextures_(1, @PcTex)
  glBindTexture_(#GL_TEXTURE_2D, PcTex)
  glTexParameteri_(#GL_TEXTURE_2D, #GL_TEXTURE_MIN_FILTER, #GL_NEAREST)
  glTexParameteri_(#GL_TEXTURE_2D, #GL_TEXTURE_MAG_FILTER, #GL_NEAREST)
  glTexParameteri_(#GL_TEXTURE_2D, #GL_TEXTURE_WRAP_S, #GL_CLAMP_TO_EDGE)
  glTexParameteri_(#GL_TEXTURE_2D, #GL_TEXTURE_WRAP_T, #GL_CLAMP_TO_EDGE)
  glTexImage2D_(#GL_TEXTURE_2D, 0, #GL_RGBA, #PC_FW, #PC_FH * 2, 0, #GL_RGBA, #GL_UNSIGNED_BYTE, @PcTexRows(0))
  PcSprite\TextureID = PcTex : PcSprite\Width = #PC_FW : PcSprite\Height = #PC_FH * 2
  PcTexReady = 1
EndProcedure

Procedure PcTextureUpload()
  Protected y.i
  For y = 0 To #PC_FH - 1
    CopyMemory(@PcRGBA(y * #PC_FW), @PcTexRows((#PC_FH * 2 - 1 - y * 2) * #PC_FW), #PC_FW * 4)
    CopyMemory(@PcRGBA(y * #PC_FW), @PcTexRows((#PC_FH * 2 - 2 - y * 2) * #PC_FW), #PC_FW * 4)
  Next
  glBindTexture_(#GL_TEXTURE_2D, PcTex)
  glTexSubImage2D_(#GL_TEXTURE_2D, 0, 0, 0, #PC_FW, #PC_FH * 2, #GL_RGBA, #GL_UNSIGNED_BYTE, @PcTexRows(0))
EndProcedure

; The current screen, border included, as a PNG (headless runs and the window's screenshot).
Procedure.i PcSavePng(path.s)
  Protected img.i, x.i, y.i, c.l, ok.i
  img = CreateImage(#PB_Any, #PC_FW, #PC_FH * 2, 24)
  If img = 0 : ProcedureReturn 0 : EndIf
  If StartDrawing(ImageOutput(img))
    For y = 0 To #PC_FH - 1
      For x = 0 To #PC_FW - 1
        c = PcRGBA(y * #PC_FW + x)
        Plot(x, y * 2, RGB(c & 255, (c >> 8) & 255, (c >> 16) & 255))
        Plot(x, y * 2 + 1, RGB(c & 255, (c >> 8) & 255, (c >> 16) & 255))
      Next
    Next
    StopDrawing()
    ok = SaveImage(img, path, #PB_ImagePlugin_PNG)
  EndIf
  FreeImage(img)
  ProcedureReturn ok
EndProcedure

; ---- speaker ----
Global Dim PcSnd.w(#PC_FRAME_SAMPLES - 1)
Global Dim PcSndHeader.WAVEHDR(#PC_SND_BUFFERS - 1)
Global Dim *PcSndBuf(#PC_SND_BUFFERS - 1)
Global PcSndDevice.i, PcSndOpen.i, PcSndNext.i, PcSndPhase.d, PcSndMuted.i

Procedure.i PcSoundOpen()
  Protected fmt.WAVEFORMATEX, i.i
  fmt\wFormatTag = #WAVE_FORMAT_PCM : fmt\nChannels = 1 : fmt\nSamplesPerSec = #PC_RATE
  fmt\wBitsPerSample = 16 : fmt\nBlockAlign = 2 : fmt\nAvgBytesPerSec = #PC_RATE * 2 : fmt\cbSize = 0
  If waveOutOpen_(@PcSndDevice, #WAVE_MAPPER, @fmt, 0, 0, #CALLBACK_NULL) <> #MMSYSERR_NOERROR
    ProcedureReturn 0
  EndIf
  For i = 0 To #PC_SND_BUFFERS - 1
    *PcSndBuf(i) = AllocateMemory(#PC_FRAME_SAMPLES * 2)
    PcSndHeader(i)\lpData = *PcSndBuf(i)
    PcSndHeader(i)\dwBufferLength = #PC_FRAME_SAMPLES * 2
    waveOutPrepareHeader_(PcSndDevice, @PcSndHeader(i), SizeOf(WAVEHDR))
    PcSndHeader(i)\dwFlags | #WHDR_DONE
  Next
  PcSndOpen = 1
  ProcedureReturn 1
EndProcedure

Procedure.i PcSoundPending()
  Protected i.i, n.i
  For i = 0 To #PC_SND_BUFFERS - 1
    If (PcSndHeader(i)\dwFlags & #WHDR_DONE) = 0 : n + 1 : EndIf
  Next
  ProcedureReturn n
EndProcedure

; One frame of sound from the per-scanline speaker record of the frame just run.
Procedure PcSoundFrame()
  Protected i.i, line.i, f.i, v.i, k.i = PcSndNext
  For i = 0 To #PC_FRAME_SAMPLES - 1
    line = (i * #PC86_LINES) / #PC_FRAME_SAMPLES
    f = SpkFreq(line)
    If f > 0 And f < 20000
      PcSndPhase + f / #PC_RATE
      If PcSndPhase >= 1.0 : PcSndPhase - Int(PcSndPhase) : EndIf
      If PcSndPhase < 0.5 : v = 6000 : Else : v = -6000 : EndIf
    ElseIf SpkLevel(line)
      v = 6000                          ; port 61h bit 1 driven directly
    Else
      v = 0
    EndIf
    PcSnd(i) = v
  Next
  If PcSndOpen = 0 Or PcSndMuted : ProcedureReturn : EndIf
  If (PcSndHeader(k)\dwFlags & #WHDR_DONE) = 0 : ProcedureReturn : EndIf   ; full: drop a frame
  CopyMemory(@PcSnd(0), *PcSndBuf(k), #PC_FRAME_SAMPLES * 2)
  PcSndHeader(k)\dwFlags & ~#WHDR_DONE
  waveOutWrite_(PcSndDevice, @PcSndHeader(k), SizeOf(WAVEHDR))
  PcSndNext = (k + 1) % #PC_SND_BUFFERS
EndProcedure

Procedure PcSoundClose()
  Protected i.i
  If PcSndOpen = 0 : ProcedureReturn : EndIf
  waveOutReset_(PcSndDevice)
  For i = 0 To #PC_SND_BUFFERS - 1
    waveOutUnprepareHeader_(PcSndDevice, @PcSndHeader(i), SizeOf(WAVEHDR))
    FreeMemory(*PcSndBuf(i))
  Next
  waveOutClose_(PcSndDevice)
  PcSndOpen = 0
EndProcedure

; ---- keyboard: PureBasic key codes to set-1 scan codes ----
Procedure.i PcScanCode(key.i)
  Select key
    Case #PB_Shortcut_Escape : ProcedureReturn $01
    Case #PB_Shortcut_1 : ProcedureReturn $02
    Case #PB_Shortcut_2 : ProcedureReturn $03
    Case #PB_Shortcut_3 : ProcedureReturn $04
    Case #PB_Shortcut_4 : ProcedureReturn $05
    Case #PB_Shortcut_5 : ProcedureReturn $06
    Case #PB_Shortcut_6 : ProcedureReturn $07
    Case #PB_Shortcut_7 : ProcedureReturn $08
    Case #PB_Shortcut_8 : ProcedureReturn $09
    Case #PB_Shortcut_9 : ProcedureReturn $0A
    Case #PB_Shortcut_0 : ProcedureReturn $0B
    Case #PB_Shortcut_Back : ProcedureReturn $0E
    Case #PB_Shortcut_Tab : ProcedureReturn $0F
    Case #PB_Shortcut_Q : ProcedureReturn $10
    Case #PB_Shortcut_W : ProcedureReturn $11
    Case #PB_Shortcut_E : ProcedureReturn $12
    Case #PB_Shortcut_R : ProcedureReturn $13
    Case #PB_Shortcut_T : ProcedureReturn $14
    Case #PB_Shortcut_Y : ProcedureReturn $15
    Case #PB_Shortcut_U : ProcedureReturn $16
    Case #PB_Shortcut_I : ProcedureReturn $17
    Case #PB_Shortcut_O : ProcedureReturn $18
    Case #PB_Shortcut_P : ProcedureReturn $19
    Case #PB_Shortcut_Return : ProcedureReturn $1C
    Case #PB_Shortcut_Control : ProcedureReturn $1D
    Case #PB_Shortcut_A : ProcedureReturn $1E
    Case #PB_Shortcut_S : ProcedureReturn $1F
    Case #PB_Shortcut_D : ProcedureReturn $20
    Case #PB_Shortcut_F : ProcedureReturn $21
    Case #PB_Shortcut_G : ProcedureReturn $22
    Case #PB_Shortcut_H : ProcedureReturn $23
    Case #PB_Shortcut_J : ProcedureReturn $24
    Case #PB_Shortcut_K : ProcedureReturn $25
    Case #PB_Shortcut_L : ProcedureReturn $26
    Case #PB_Shortcut_Shift : ProcedureReturn $2A
    Case #PB_Shortcut_Z : ProcedureReturn $2C
    Case #PB_Shortcut_X : ProcedureReturn $2D
    Case #PB_Shortcut_C : ProcedureReturn $2E
    Case #PB_Shortcut_V : ProcedureReturn $2F
    Case #PB_Shortcut_B : ProcedureReturn $30
    Case #PB_Shortcut_N : ProcedureReturn $31
    Case #PB_Shortcut_M : ProcedureReturn $32
    Case #PB_Shortcut_Alt : ProcedureReturn $38
    Case #PB_Shortcut_Space : ProcedureReturn $39
    Case #PB_Shortcut_F1 : ProcedureReturn $3B
    Case #PB_Shortcut_F2 : ProcedureReturn $3C
    Case #PB_Shortcut_F3 : ProcedureReturn $3D
    Case #PB_Shortcut_F4 : ProcedureReturn $3E
    Case #PB_Shortcut_F5 : ProcedureReturn $3F
    Case #PB_Shortcut_F6 : ProcedureReturn $40
    Case #PB_Shortcut_F7 : ProcedureReturn $41
    Case #PB_Shortcut_F8 : ProcedureReturn $42
    Case #PB_Shortcut_F9 : ProcedureReturn $43
    Case #PB_Shortcut_F10 : ProcedureReturn $44
    Case #PB_Shortcut_Up : ProcedureReturn $48
    Case #PB_Shortcut_Left : ProcedureReturn $4B
    Case #PB_Shortcut_Right : ProcedureReturn $4D
    Case #PB_Shortcut_Down : ProcedureReturn $50
  EndSelect
  ProcedureReturn 0
EndProcedure

DataSection
  CgaRgb:
  Data.a $00,$00,$00, $00,$00,$AA, $00,$AA,$00, $00,$AA,$AA, $AA,$00,$00, $AA,$00,$AA, $AA,$55,$00, $AA,$AA,$AA
  Data.a $55,$55,$55, $55,$55,$FF, $55,$FF,$55, $55,$FF,$FF, $FF,$55,$55, $FF,$55,$FF, $FF,$FF,$55, $FF,$FF,$FF
EndDataSection
