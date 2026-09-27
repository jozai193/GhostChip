$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$WebRoot = Join-Path $ProjectRoot "web"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 20.9 or newer is required to build the judge interface."
}
$NodeMajor = [int](node -p "process.versions.node.split('.')[0]")
if ($NodeMajor -lt 20) {
    throw "Node.js 20.9 or newer is required; found $(node --version)."
}

Push-Location $WebRoot
try {
    if (-not (Test-Path -LiteralPath "node_modules")) {
        npm ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
}
finally {
    Pop-Location
}

$RuntimeRoot = (wsl -d Ubuntu --cd /tmp --exec mktemp -d -p /tmp ghostchip-demo-runtime-XXXXXX).Trim()
if (-not $RuntimeRoot.StartsWith("/tmp/ghostchip-demo-runtime-")) {
    throw "Could not create a safe isolated WSL runtime directory."
}

Push-Location $ProjectRoot
try {
    $CopyCommand = "tar.exe --exclude=.git --exclude=.venv --exclude=.venv-wsl --exclude=node_modules --exclude=web/.next --exclude=artifacts --exclude=tmp --exclude=.playwright-cli --exclude=output -cf - . | wsl.exe -d Ubuntu --cd $RuntimeRoot --exec tar -xf -"
    cmd.exe /d /c $CopyCommand
    if ($LASTEXITCODE -ne 0) { throw "Could not copy the source snapshot into WSL." }
}
finally {
    Pop-Location
}

Write-Host "GhostChip will be available at http://localhost:8765"
Write-Host "Isolated runtime: $RuntimeRoot"
wsl -d Ubuntu --cd $RuntimeRoot --exec bash scripts/start-demo.sh
if ($LASTEXITCODE -ne 0) { throw "GhostChip demo server exited with code $LASTEXITCODE" }
