$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到项目虚拟环境，请先运行：python -m venv .venv"
}

& $python -m PyInstaller --noconfirm --clean (Join-Path $projectRoot "pet.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 打包失败，退出码：$LASTEXITCODE"
}

Write-Host "打包完成：$projectRoot\dist\小白桌宠.exe"
