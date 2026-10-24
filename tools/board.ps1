# Board work on the shared Pico W (COM7) under ONE lease for a batch of jobs,
# taken and released only through the bench's shared C:\PMFBuild\board-leases\lease.ps1.
#
#   .\tools\board.ps1 -Minutes 8 -Jobs @(
#       'flash Diagnostics/api.picow Diagnostics/build/api.uf2 10',
#       'vectors Diagnostics/vectors.picow Diagnostics/build/vectors.uf2 --per-file 100 --log docs/x.log')
#
#   flash   <source> <output.uf2> [seconds]              build, upload, capture output
#   vectors <source> <output.uf2> <vectors.py args...>   build, upload, stream the reference tests
# COM7 leases are limited to 15 minutes: split the full corpus with --part 1/2 and 2/2.
param(
    [Parameter(Mandatory)][string[]]$Jobs,
    [int]$Minutes = 5,
    [string]$Port = 'COM7'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
. C:\PMFBuild\board-leases\lease.ps1
$l = Get-BoardLease -Port $Port -Owner 'cg-8086' -Minutes $Minutes
"lease taken $(Get-Date -Format HH:mm:ss)"
try {
    foreach ($job in $Jobs) {
        $w = $job -split ' '
        try {
            switch ($w[0]) {
                'flash' {
                    $sec = 0; if ($w.Count -gt 3) { $sec = [int]$w[3] }
                    & (Join-Path $PSScriptRoot 'build.ps1') -Source $w[1] -Output $w[2] -Port $Port -Seconds $sec
                }
                'vectors' {
                    & (Join-Path $PSScriptRoot 'build.ps1') -Source $w[1] -Output $w[2] -Port $Port -Seconds 0
                    $a = @((Join-Path $PSScriptRoot 'vectors.py'), '--port', $Port) + $w[3..($w.Count - 1)]
                    & py -3 @a
                    "vectors exit $LASTEXITCODE"
                }
                default { "unknown job: $job" }
            }
        } catch {
            "JOB FAILED: $job - $($_.Exception.Message)"
        }
    }
} finally {
    Release-BoardLease $l
    "lease released $(Get-Date -Format HH:mm:ss)"
}
