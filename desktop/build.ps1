# Builds the desktop 8086 emulator: cpu86_desktop.exe (the window) and
# cpu86_console.exe (the same program with a console, for --test / --bench / --run).
# The core (cpu86_core.pbi) is generated from the same handlers as the Pico core.
param(
    [string]$Compiler = 'C:\Program Files\PureBasic\Compilers\pbcompilerc.exe',
    [string]$Engine = 'C:/Users/ajtaj/Desktop/Neon-Arcade-Dispay-Engine/'
)
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
& py -3 (Join-Path $here '..\tools\gen_cpu.py')
if ($LASTEXITCODE -ne 0) { throw 'tools/gen_cpu.py failed' }
& py -3 (Join-Path $here '..\tools\make_examples.py') | Out-Null
& py -3 (Join-Path $here '..\tools\desktop_proc_variant.py') | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'tools/desktop_proc_variant.py failed' }
& py -3 (Join-Path $here '..\tools\make_cgafont.py') | Out-Null
$src = Join-Path $here 'cpu86_desktop.pb'
foreach ($b in @(@('cpu86_desktop.exe', @('/CONSTANT', 'CPU_TIMING=1')), @('cpu86_pc.exe', @('/CONSOLE', '/CONSTANT', 'CPU_TIMING=1')), @('cpu86_console.exe', @('/CONSOLE')), @('cpu86_console_proctable.exe', @('/CONSOLE', '/CONSTANT', 'CPU86_PROCTABLE=1')))) {
    $exe = Join-Path $here $b[0]
    $args = @($src, '/EXE', $exe, '/THREAD', '/DPIAWARE', '/OPTIMIZER', '/CONSTANT', "GL_ENGINE_DIR$=$Engine") + $b[1]
    # The 8086 back end's gates run cpu86_console.exe: while one runs, the linker cannot
    # replace it ("permission denied"), so a failed link is retried for up to a minute.
    for ($try = 1; $try -le 12; $try++) {
        $out = & $Compiler @args 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -and (Test-Path $exe)) { break }
        if ($out -notmatch 'permission denied' -or $try -eq 12) { $out; throw "Build failed: $($b[0])" }
        Start-Sleep -Seconds 5
    }
}
Get-FileHash -Algorithm SHA256 (Join-Path $here 'cpu86_desktop.exe'), (Join-Path $here 'cpu86_console.exe') | Format-Table -AutoSize
