# Purple를 CDP 디버깅 모드로 재시작 (Electron --remote-debugging-port 시도)
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(Purple|purple-agent|purpleonp|PurpleBox|PurpleLauncher|purpleon)' } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3
Start-Process "C:\Program Files (x86)\NC\Purple\2.26.831.38\Purple.exe" -ArgumentList "--remote-debugging-port=9222","--remote-allow-origins=*"
Start-Sleep -Seconds 12
try {
    $tabs = Invoke-RestMethod -Uri "http://127.0.0.1:9222/json" -TimeoutSec 5
    "CDP_OK"
    $tabs | ForEach-Object { "$($_.type): $($_.title) | $($_.url)" } | Select-Object -First 10
} catch {
    "CDP_FAIL: $($_.Exception.Message.Substring(0, [Math]::Min(100, $_.Exception.Message.Length)))"
}
