param([string]$ModelsRoot = (Join-Path $env:USERPROFILE '.lmstudio\models\local-transcriber'))
$ErrorActionPreference = 'Stop'
# Run in your own PowerShell. The token is masked, used only by the child process, and never saved.
Write-Host 'First accept the model conditions at https://huggingface.co/pyannote/speaker-diarization-community-1'
$secret = Read-Host 'Temporary Hugging Face Read token (masked)' -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
$previousToken = $env:HF_TOKEN
try {
    $env:HF_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    python (Join-Path $PSScriptRoot 'download_models.py') --models-root $ModelsRoot --only diarization
    if ($LASTEXITCODE -ne 0) { throw "Community-1 preparation failed, exit $LASTEXITCODE" }
} finally {
    $env:HF_TOKEN = $previousToken
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    $secret.Dispose()
}
