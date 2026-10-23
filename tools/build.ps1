# Build a PureMetal source; with -Port, check the image and then upload it.
# The image must end below flash offset $50000, where the bench Pico W keeps
# its NES ROM store: the build is checked BEFORE anything is uploaded.
param(
    [string]$Compiler = 'C:\Users\ajtaj\Desktop\Github\PureBasicCode\OpenGl Work\ArduinoBasic\PureMetalForge.exe',
    [string]$Source = 'src/demo.picow',
    [string]$Output = 'firmware/8086-picow.uf2',
    [string]$Port = '',
    [int]$Seconds = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$sourcePath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Source))
$outputPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
[IO.Directory]::CreateDirectory((Split-Path $outputPath -Parent)) | Out-Null
function Invoke-Forge([string]$extra) {
    $arguments = '--compile "' + $sourcePath + '" -S -o "' + $outputPath + '"' + $extra
    $stdoutPath = $outputPath + '.build.log'
    $stderrPath = $outputPath + '.stderr.log'
    $process = Start-Process -FilePath $Compiler -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    Get-Content $stdoutPath | Select-String -Pattern 'ERROR|error:|PM[0-9]{4}|bytes of code|SRAM left|refus|UPLOAD|NATIVE|^[^>\[]' | ForEach-Object { $_.Line }
    Get-Content $stderrPath
    if ($process.ExitCode -ne 0) { throw "Compiler exit $($process.ExitCode): $stdoutPath" }
}
Invoke-Forge ''
if ($outputPath.EndsWith('.uf2')) {
    $uf2 = [IO.File]::ReadAllBytes($outputPath); $imageEnd = 0
    for ($o = 0; $o -lt $uf2.Length; $o += 512) {
        $blockEnd = [BitConverter]::ToUInt32($uf2, $o + 12) + [BitConverter]::ToUInt32($uf2, $o + 16)
        if ($blockEnd -gt $imageEnd) { $imageEnd = $blockEnd }
    }
    'image ends at 0x{0:X8}' -f $imageEnd
    if ($imageEnd -gt 0x10050000) { throw ('Image reaches 0x{0:X8}, past the NES ROM store at 0x10050000: not uploaded' -f $imageEnd) }
}
Get-FileHash -Algorithm SHA256 -LiteralPath $outputPath | Format-Table -AutoSize
if ($Port) {
    $extra = ' --port ' + $Port
    if ($Seconds -gt 0) { $extra += ' --seconds ' + $Seconds }
    Invoke-Forge $extra
}
