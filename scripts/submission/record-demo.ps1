param(
    [string]$Url = "http://127.0.0.1:8765",
    [string]$OutputDirectory = "artifacts/submission/raw-clips",
    [string]$Session = "ghostchip-demo-recording"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$outputRoot = Join-Path $repoRoot $OutputDirectory
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

$npx = (Get-Command npx.cmd -ErrorAction Stop).Source
$base = @("--yes", "--package", "@playwright/cli", "playwright-cli")

function Invoke-Pw([string[]]$Arguments) {
    & $npx @base @Arguments --session $Session
    if ($LASTEXITCODE -ne 0) { throw "playwright-cli failed: $($Arguments -join ' ')" }
}

function Start-Clip([int]$Number) {
    $target = Join-Path $outputRoot ("clip-{0:D2}.webm" -f $Number)
    Invoke-Pw @("video-start", $target, "--size", "1600x900", "--fps", "30", "--cursor")
}

function Stop-Clip { Invoke-Pw @("video-stop") }
function Hold([double]$Seconds) { Start-Sleep -Milliseconds ([int]($Seconds * 1000)) }
function Scroll-To([string]$Selector, [string]$Block = "center") {
    $js = "() => document.querySelector('$Selector')?.scrollIntoView({behavior:'smooth',block:'$Block'})"
    Invoke-Pw @("eval", $js)
    Hold 1.4
}
function Click-Button([string]$Label) {
    $escaped = $Label.Replace("'", "\'")
    $js = "() => { const button = [...document.querySelectorAll('button')].find((node) => node.textContent?.includes('$escaped')); if (!button) throw new Error('Button not found: $escaped'); button.click(); }"
    Invoke-Pw @("eval", $js)
}

Push-Location $repoRoot
try {
    Invoke-Pw @("open", $Url)
    Invoke-Pw @("resize", "1600", "900")
    Hold 3

    Start-Clip 1; Hold 11; Stop-Clip

    Start-Clip 2
    Scroll-To "#pipeline"
    Hold 18
    Stop-Clip

    Start-Clip 3
    Click-Button "Run BME280 demo"
    Hold 15
    Stop-Clip

    Start-Clip 4
    Scroll-To ".result-top" "start"
    Hold 15
    Stop-Clip

    Start-Clip 5
    Scroll-To ".failure-card"
    Hold 10
    Stop-Clip

    Start-Clip 6
    Click-Button "Generate repair"
    Hold 8
    Scroll-To ".repair-panel" "start"
    Hold 10
    Stop-Clip

    Start-Clip 7
    Scroll-To ".diff"
    Hold 11
    Click-Button "Apply & verify"
    Hold 8
    Stop-Clip

    Start-Clip 8
    Hold 9
    Scroll-To ".repair-verified"
    Hold 5
    Stop-Clip

    Start-Clip 9
    Scroll-To ".identity-section"
    Hold 18
    Stop-Clip

    Start-Clip 10
    Scroll-To ".generalization"
    Hold 14
    Stop-Clip

    Start-Clip 11
    Scroll-To "#top" "start"
    Hold 10
    Stop-Clip
}
finally {
    try { Invoke-Pw @("video-stop") } catch { }
    try { Invoke-Pw @("close") } catch { }
    Pop-Location
}

Write-Output "Recorded real-browser clips to $outputRoot"
