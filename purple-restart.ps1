# Purple 런처 재시작 (게임은 이미 종료됨)
Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(Purple|purple-agent|purpleonp|PurpleBox|PurpleLauncher)' } | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    "killed: $($_.Name) $($_.ProcessId)"
}
Start-Sleep -Seconds 3
Start-Process "C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe"
"RELAUNCHED"
