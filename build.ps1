$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "未找到项目虚拟环境，请先运行：python -m venv .venv"
}

& $python -m PyInstaller --noconfirm --clean (Join-Path $projectRoot "pet.spec")
$pyInstallerExitCode = $LASTEXITCODE
$builtExe = Join-Path $projectRoot "dist\XiaobaiDesktopPet.exe"
$temporaryExe = "$builtExe.notanexecutable"

if ($pyInstallerExitCode -ne 0 -and (Test-Path -LiteralPath $temporaryExe)) {
    Start-Sleep -Seconds 2
    & $python -c "import sys; import pefile; from PyInstaller.utils.win32 import winutils; p=sys.argv[1]; pe=pefile.PE(p, fast_load=False); pe.close(); winutils.update_exe_pe_checksum(p)" $temporaryExe
    if ($LASTEXITCODE -eq 0) {
        Move-Item -LiteralPath $temporaryExe -Destination $builtExe -Force
        $pyInstallerExitCode = 0
    }
}

if ($pyInstallerExitCode -ne 0) {
    throw "PyInstaller 打包失败，退出码：$pyInstallerExitCode"
}

$finalFileName = -join @(
    [char]0x5C0F,
    [char]0x767D,
    [char]0x684C,
    [char]0x5BA0,
    ".exe"
)
$finalExe = Join-Path $projectRoot (Join-Path "dist" $finalFileName)
if (-not (Test-Path -LiteralPath $builtExe)) {
    throw "未找到 PyInstaller 输出：$builtExe"
}
Copy-Item -LiteralPath $builtExe -Destination $finalExe -Force
Remove-Item -LiteralPath $builtExe -Force

Write-Host "打包完成：$finalExe"
