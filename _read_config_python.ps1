# 从 config.json 里读出 "python" 这一项，打印出来。
#
# 为什么要单独一个文件：在 .bat 的 for /f 反引号里写一整段 PowerShell，
# 转义（^| ^> 引号嵌套）太脆 —— 试过两次，一次静默返回空、一次直接语法错。
# 抽成文件之后，批处理只写一句 `-File`，没有任何需要转义的东西。
#
# 为什么不用 Get-Content -Encoding UTF8：
#   Windows PowerShell 5.1 会把**无 BOM 的 UTF-8** 当成 ANSI 读，
#   config.json 里的中文注释变成乱码 → ConvertFrom-Json 抛错 →
#   被 catch 吞掉 → **一声不响地返回空**。
#   后果是启动脚本悄悄忽略你配置的 Python，退到 PATH 里另一个去。
#   ReadAllText 显式给编码，在 5.1 和 7 上行为一致。
#
# 用法：  powershell -NoProfile -ExecutionPolicy Bypass -File _read_config_python.ps1
# 输出：  找到就打印路径；找不到就什么也不打印（退出码始终 0，方便批处理判断）

param()

$ErrorActionPreference = 'SilentlyContinue'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Join-Path $here 'config.json'

if (-not (Test-Path -LiteralPath $cfg)) { return }

$text = [System.IO.File]::ReadAllText($cfg, [System.Text.Encoding]::UTF8)
if ([string]::IsNullOrWhiteSpace($text)) { return }

try {
    $obj = $text | ConvertFrom-Json
} catch {
    return
}

$py = $obj.python
if ([string]::IsNullOrWhiteSpace($py)) { return }

# 去掉可能存在的引号
$py = $py.Trim().Trim('"').Trim("'")

# 单个反斜杠结尾会让批处理的引号配对出问题，去掉
$py = $py.TrimEnd('\')

Write-Output $py
