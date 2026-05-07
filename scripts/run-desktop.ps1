$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$nodeExe = "C:\Program Files\nodejs\node.exe"
$npmCli = "C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js"

if (!(Test-Path $nodeExe)) {
    throw "Node.js nao encontrado em '$nodeExe'."
}

if (!(Test-Path $npmCli)) {
    throw "npm-cli.js nao encontrado em '$npmCli'."
}

Push-Location $projectRoot
try {
    & $nodeExe $npmCli run desktop
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
