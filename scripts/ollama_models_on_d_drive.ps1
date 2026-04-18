# 将 Ollama 模型目录统一到 D 盘：在 C:\Users\<你>\.ollama\models 创建指向 D 盘的目录联接（Junction）。
# Ollama 仍使用默认路径，权重文件实际落在 D:\RamboStar\ollama\models。
# 用法：在 PowerShell 中执行  .\scripts\ollama_models_on_d_drive.ps1
# 执行前请完全退出托盘中的 Ollama。

$ErrorActionPreference = "Stop"
$target = "D:\RamboStar\ollama\models"
$link = Join-Path $env:USERPROFILE ".ollama\models"

New-Item -ItemType Directory -Path $target -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "blobs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $target "manifests") -Force | Out-Null

if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        cmd /c "rmdir `"$link`""
    } else {
        throw "已存在普通文件夹 $link ，请先手动备份后删除再运行本脚本。"
    }
}
cmd /c "mklink /J `"$link`" `"$target`""
Write-Host "OK: $link -> $target"
Write-Host "请勿再设置用户环境变量 OLLAMA_MODELS（留空则使用上述默认路径）。"
