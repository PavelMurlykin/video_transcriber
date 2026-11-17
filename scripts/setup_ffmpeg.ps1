param([string]$ToolsRoot = (Join-Path $PSScriptRoot '..\.tools'))
$ErrorActionPreference = 'Stop'
$ToolsRoot = [IO.Path]::GetFullPath($ToolsRoot)
New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
$url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
$archive = Join-Path $ToolsRoot 'ffmpeg-release-essentials.zip'
Invoke-WebRequest -Uri $url -OutFile $archive
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
Expand-Archive -LiteralPath $archive -DestinationPath $ToolsRoot -Force
$ffmpeg = Get-ChildItem -LiteralPath $ToolsRoot -Filter ffmpeg.exe -Recurse | Select-Object -First 1
$ffprobe = Get-ChildItem -LiteralPath $ToolsRoot -Filter ffprobe.exe -Recurse | Select-Object -First 1
if (!$ffmpeg -or !$ffprobe) { throw 'FFmpeg binaries not found' }
@{ source=$url; sha256=$hash; ffmpeg=$ffmpeg.FullName; ffprobe=$ffprobe.FullName } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ToolsRoot 'ffmpeg-install.json') -Encoding utf8
& $ffmpeg.FullName -version | Select-Object -First 1
& $ffprobe.FullName -version | Select-Object -First 1
