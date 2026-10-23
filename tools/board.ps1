# Board work on the shared Pico W, under its lease:
#   C:\PMFBuild\board-leases\COM7.lease is created exclusively before the upload
#   and deleted as soon as the upload and capture are over.
# Builds and uploads -Source; then either streams vectors (-Vectors '<args for
# tools/vectors.py>') or captures the program's output for -Seconds.
param(
    [string]$Source,
    [string]$Output,
    [string]$Port = 'COM7',
    [int]$Seconds = 0,
    [string]$Vectors = '',
    [string]$Log = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$leaseDir = 'C:\PMFBuild\board-leases'
$lease = Join-Path $leaseDir ($Port + '.lease')
New-Item -ItemType Directory -Force $leaseDir | Out-Null
while ($true) {
    try { New-Item -ItemType File $lease -ErrorAction Stop | Out-Null; break }
    catch {
        $held = Get-Item $lease -ErrorAction SilentlyContinue
        if (-not $held) { Start-Sleep -Seconds 1; continue }
        $age = (Get-Date) - $held.LastWriteTime
        if ($age.TotalMinutes -gt 30) {
            "lease is $([int]$age.TotalMinutes) min old (" + (Get-Content $lease -Raw) + "): removing it"
            Remove-Item $lease -Force
        } else {
            "lease held: " + (Get-Content $lease -Raw -ErrorAction SilentlyContinue) + " - waiting 30 s"
            Start-Sleep -Seconds 30
        }
    }
}
$tag = "8086-emulator worker " + (Get-Date -Format o)
Set-Content $lease $tag
try {
    & (Join-Path $PSScriptRoot 'build.ps1') -Source $Source -Output $Output -Port $Port -Seconds $Seconds
    if ($Vectors) {
        $a = @((Join-Path $PSScriptRoot 'vectors.py'), '--port', $Port) + ($Vectors -split ' ')
        if ($Log) { $a += @('--log', $Log) }
        & py -3 @a
        $code = $LASTEXITCODE
        "vectors exit $code"
    }
} finally {
    $now = ''
    try { $now = [IO.File]::ReadAllText($lease) } catch { $now = '(unreadable: ' + $_.Exception.Message + ')' }
    if ($now -and $now.Trim() -eq $tag) {
        Remove-Item $lease -Force
        "lease released"
    } else {
        "lease file no longer ours at release (now: '$now') - left alone"
    }
}
