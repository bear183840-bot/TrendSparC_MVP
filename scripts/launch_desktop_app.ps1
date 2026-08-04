# Launches the TrendSparC Streamlit app as a windowed "desktop app" (Chrome
# app-mode, no tabs/address bar) instead of a normal browser tab.
#
# Always restarts the Streamlit server first, so code edits are picked up on
# every launch instead of relying on Streamlit's file-watcher (which doesn't
# always catch changes reliably).

$ErrorActionPreference = "SilentlyContinue"
$projectPath = "C:\Users\bear1\Desktop\TrendSparC_MVP"
$port = 8501

$existing = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($processId in $existing) {
    Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

Set-Location $projectPath
Start-Process -FilePath "$projectPath\.venv\Scripts\python.exe" `
    -ArgumentList "-m", "streamlit", "run", "reporting\dashboard_streamlit\app.py", `
        "--server.port", $port, "--server.headless", "true" `
    -WindowStyle Hidden

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:$port" -UseBasicParsing -TimeoutSec 1
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chromePath)) {
    $chromePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
}
Start-Process -FilePath $chromePath -ArgumentList "--app=http://localhost:$port", "--window-size=1280,860"
