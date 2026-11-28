param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$InputMedia
)

$ErrorActionPreference = 'Stop'
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$InputMedia = (Resolve-Path -LiteralPath $InputMedia).Path
$data = Join-Path $env:LOCALAPPDATA 'LocalTranscriber'
$app = Join-Path $env:LOCALAPPDATA 'Programs\Local Transcriber'
$models = Join-Path $env:USERPROFILE '.lmstudio\models\local-transcriber'
if ((Test-Path -LiteralPath $data) -or (Test-Path -LiteralPath $app)) {
    throw 'Use a fresh Windows profile or fresh application directories for acceptance.'
}
if (!(Test-Path -LiteralPath (Join-Path $models 'models-manifest.json'))) {
    throw 'Prepare the local model directory for the test profile before starting.'
}
$evidence = Join-Path $env:LOCALAPPDATA ('LocalTranscriber-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $evidence | Out-Null
Write-Output "Evidence: $evidence"
$env:Path = "$env:SystemRoot\System32"
Remove-Item Env:PYTHONPATH,Env:PYTHONHOME,Env:VIRTUAL_ENV,Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
$pythonAbsent = !(Get-Command python.exe,py.exe -ErrorAction SilentlyContinue)
if (!$pythonAbsent) { throw 'An external Python executable is available on PATH.' }

$blocked = foreach ($ip in @('1.1.1.1', '8.8.8.8')) {
    $tcp = [Net.Sockets.TcpClient]::new()
    try {
        $connect = $tcp.ConnectAsync($ip, 443)
        try { $null = $connect.Wait(2000) } catch [AggregateException] {}
        !$tcp.Connected
    } finally {
        $tcp.Dispose()
    }
}
$dnsBlocked = $true
try {
    $lookup = [Net.Dns]::GetHostAddressesAsync('huggingface.co')
    if ($lookup.Wait(3000)) { $dnsBlocked = !$lookup.Result.Count }
} catch [AggregateException] {}
if ($blocked -contains $false -or !$dnsBlocked) { throw 'The test requires offline TCP and DNS.' }
Write-Output 'TCP and DNS are blocked. No external Python executable is on PATH.'

$installSeconds = (Measure-Command {
    $setup = Start-Process -FilePath $Installer -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER',
        ('/DIR="{0}"' -f $app), ('/LOG="{0}"' -f (Join-Path $evidence 'install.log'))
    ) -Wait -PassThru -WindowStyle Hidden
    if ($setup.ExitCode -ne 0) { throw "Installer exit $($setup.ExitCode)." }
}).TotalSeconds
Write-Output ("Installed in {0:N2} seconds." -f $installSeconds)
$cli = Join-Path $app 'LocalTranscriberCLI.exe'
$desktop = Join-Path $app 'LocalTranscriber.exe'
$uninstaller = Join-Path $app 'unins000.exe'
foreach ($required in @($cli, $desktop, $uninstaller)) {
    if (!(Test-Path -LiteralPath $required)) { throw 'Installed executable missing.' }
}

function Invoke-Transcriber([string[]]$Command) {
    & $cli @Command
    if ($LASTEXITCODE -ne 0) { throw "Installed CLI exit $LASTEXITCODE." }
}

$media = Invoke-Transcriber -Command @('inspect-media', $InputMedia) | ConvertFrom-Json
if ($media.estimated_duration_ms -le 0) { throw 'FFprobe did not report a media duration.' }
$config = Join-Path $data 'config.local.json'
$runtime = Invoke-Transcriber -Command @('check-runtime') | ConvertFrom-Json
if ($runtime.device -ne 'cuda') { throw 'The installed runtime did not select CUDA.' }
Write-Output 'Installed FFprobe and CUDA checks passed.'
$programs = [Environment]::GetFolderPath('Programs')
$shortcut = Join-Path $programs 'Local Transcriber.lnk'
if (!(Test-Path -LiteralPath $shortcut)) { throw 'The Start menu shortcut was not created.' }
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$gui = Start-Process -FilePath $desktop -PassThru
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    do {
        Start-Sleep -Milliseconds 250
        $gui.Refresh()
    } until ($gui.HasExited -or $gui.MainWindowTitle -eq 'Local Transcriber' -or [DateTime]::UtcNow -ge $deadline)
    if ($gui.HasExited -or $gui.MainWindowTitle -ne 'Local Transcriber') {
        throw 'The installed GUI did not open its main window.'
    }
    $window = [Windows.Automation.AutomationElement]::FromHandle($gui.MainWindowHandle)
    $scope = [Windows.Automation.TreeScope]::Descendants
    $name = [Windows.Automation.AutomationElement]::NameProperty
    $condition = [Windows.Automation.OrCondition]::new(
        [Windows.Automation.PropertyCondition]::new($name, 'Локальная среда проверена'),
        [Windows.Automation.PropertyCondition]::new($name, 'Local runtime verified')
    )
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    do {
        $verified = $window.FindFirst($scope, $condition)
        if (!$verified) { Start-Sleep -Milliseconds 500 }
    } until ($verified -or $gui.HasExited -or [DateTime]::UtcNow -ge $deadline)
    if (!$verified) { throw 'The installed GUI did not complete its CLI runtime check.' }
    Write-Output 'Installed GUI completed its startup check.'
} finally {
    if (!$gui.HasExited) {
        $null = $gui.CloseMainWindow()
        if (!$gui.WaitForExit(60000)) {
            Stop-Process -Id $gui.Id
            throw 'The installed GUI did not close.'
        }
    }
}

$results = Join-Path $data 'artifacts'
$database = Join-Path $results 'projects.sqlite3'
$run = Join-Path $results 'acceptance'
$runSeconds = (Measure-Command {
    $script:messages = @(Invoke-Transcriber -Command @(
        '--project-db', $database, 'transcribe', $InputMedia, '--run-dir', $run
    ))
}).TotalSeconds
$result = $messages[-1] | ConvertFrom-Json
if ($result.status -ne 'completed' -or $result.speaker_count -ne 2 -or $result.segment_count -lt 1) {
    throw 'The installed full pipeline did not yield the expected two-speaker project.'
}
$metrics = Get-Content -LiteralPath (Join-Path $run 'metrics.json') -Raw | ConvertFrom-Json
foreach ($phase in @('asr', 'alignment', 'diarization', 'merge')) {
    if ($metrics.stage_statuses.$phase -ne 'completed') { throw "Phase $phase is incomplete." }
}
if (Get-ChildItem -LiteralPath $run -Filter '.runtime-*' -Directory) {
    throw 'The pipeline left its temporary runtime cache behind.'
}
$exported = foreach ($format in @('txt', 'docx', 'pdf')) {
    $target = Join-Path $results "transcript.$format"
    $null = Invoke-Transcriber -Command @(
        '--project-db', $database, 'projects', 'export', $result.project_id,
        '--format', $format, '--output', $target
    )
    if ((Get-Item -LiteralPath $target).Length -le 0) { throw "Empty $format export." }
    $format
}

$snapshot = Join-Path $run 'transcript.json'
$manifest = Join-Path $models 'models-manifest.json'
$before = Get-FileHash -LiteralPath $snapshot, $database, $config, $manifest
$uninstallSeconds = (Measure-Command {
    $remove = Start-Process -FilePath $uninstaller -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
    ) -Wait -PassThru -WindowStyle Hidden
    if ($remove.ExitCode -ne 0) { throw "Uninstaller exit $($remove.ExitCode)." }
}).TotalSeconds
if ((Test-Path -LiteralPath $desktop) -or (Test-Path -LiteralPath $cli) -or (Test-Path -LiteralPath $shortcut)) {
    throw 'Program files remained after uninstallation.'
}
foreach ($saved in $before) {
    if ((Get-FileHash -LiteralPath $saved.Path).Hash -ne $saved.Hash) {
        throw 'Uninstallation altered user data.'
    }
}
@{
    external_python_on_path = !$pythonAbsent
    tcp_blocked = $blocked
    dns_blocked = $dnsBlocked
    gui_opened = $true
    installed_device = $runtime.device
    media_duration_ms = $media.estimated_duration_ms
    installation_seconds = [math]::Round($installSeconds, 2)
    pipeline_seconds = [math]::Round($runSeconds, 2)
    speakers = $result.speaker_count
    segments = $result.segment_count
    exported = @($exported)
    uninstallation_seconds = [math]::Round($uninstallSeconds, 2)
    projects_preserved = $true
} | ConvertTo-Json | Tee-Object -FilePath (Join-Path $evidence 'summary.json')
