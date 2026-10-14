<#
.SYNOPSIS
把「省纸打印」注册到 Windows 资源管理器的「发送到」菜单。

.DESCRIPTION
在 %APPDATA%\Microsoft\Windows\SendTo 下生成一个 .cmd：选中若干 PDF → 右键
「发送到 → 省纸打印」，就会调用本插件的 pack.py 一键拼版，跑完停在窗口里显示省纸账。
多个 PDF 会被合并成一份输出（与命令行传多个文件的行为一致）。

.PARAMETER SendToDir
「发送到」目录，默认取当前用户的 SendTo（测试时可指向临时目录）。

.PARAMETER PackPy
pack.py 的路径，默认取本脚本上一级 skills/pdf-print-pack/scripts/pack.py。

.PARAMETER PythonExe
Python 解释器（默认 python，可用绝对路径）。

.PARAMETER Remove
卸载：删除「省纸打印.cmd」。

.EXAMPLE
powershell -ExecutionPolicy Bypass -File install-sendto.ps1
powershell -ExecutionPolicy Bypass -File install-sendto.ps1 -Remove
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$SendToDir = [Environment]::GetFolderPath('SendTo'),
    [string]$PackPy = '',
    [string]$PythonExe = 'python',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

# 注意：PowerShell 5.1 在参数默认值阶段 $PSScriptRoot 可能为空，所以在正文里解析
if (-not $PackPy) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $PackPy = Join-Path $scriptDir '..\skills\pdf-print-pack\scripts\pack.py'
}
if (-not $SendToDir) {
    throw "找不到「发送到」目录，请用 -SendToDir 指定"
}
$target = Join-Path $SendToDir '省纸打印.cmd'

if ($Remove) {
    if (Test-Path -LiteralPath $target) {
        if ($PSCmdlet.ShouldProcess($target, '删除发送到快捷方式')) {
            Remove-Item -LiteralPath $target -Force
            Write-Host "已移除：$target"
        }
    } else {
        Write-Host "没有找到：$target（无需卸载）"
    }
    exit 0
}

$packFull = (Resolve-Path -LiteralPath $PackPy).Path
if (-not (Test-Path -LiteralPath $packFull)) {
    throw "找不到 pack.py：$PackPy"
}
if (-not (Test-Path -LiteralPath $SendToDir)) {
    if ($PSCmdlet.ShouldProcess($SendToDir, '创建发送到目录')) {
        New-Item -ItemType Directory -Path $SendToDir -Force | Out-Null
    }
}

$cmd = @"
@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"$PythonExe" "$packFull" %*
set CODE=%ERRORLEVEL%
echo.
if not %CODE%==0 (
  echo [省纸打印] 处理失败，退出码 %CODE%
) else (
  echo [省纸打印] 完成，可关闭本窗口。
)
pause
"@
$cmd = $cmd -replace "`r`n", "`n" -replace "`n", "`r`n"   # 统一为 CRLF，cmd.exe 更稳

if ($PSCmdlet.ShouldProcess($target, '写入发送到快捷方式')) {
    Set-Content -LiteralPath $target -Value $cmd -Encoding OEM
    Write-Host "已安装：$target"
    Write-Host "用法：资源管理器中选中一个或多个 PDF → 右键 → 发送到 → 省纸打印"
}
