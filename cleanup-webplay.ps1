# 웹플레이 경로 잔여물 정리 (네이티브 클라이언트 경로로 전환됨)
# 1) 디버그 크롬(9333) 종료
$chrome = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like '*linc-bot*' }
foreach ($p in $chrome) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; "chrome killed: $($p.ProcessId)" }
# 2) 웹플레이 watcher 종료
$w = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*watcher.py*' }
foreach ($p in $w) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; "watcher killed: $($p.ProcessId)" }
# 3) 웹플레이용 예약작업/시작프로그램 제거
schtasks /delete /f /tn LincWatcher 2>$null
schtasks /delete /f /tn LincChrome 2>$null
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\linc-chrome.cmd" -Force -ErrorAction SilentlyContinue
Remove-Item ([Environment]::GetFolderPath("Desktop") + "\linc-chrome.cmd") -Force -ErrorAction SilentlyContinue
Remove-Item ([Environment]::GetFolderPath("Desktop") + "\linc-bot-start.cmd") -Force -ErrorAction SilentlyContinue
"CLEANUP_DONE"
# 4) 현재 LincBot/게임 상태
schtasks /query /tn LincBot /fo list | Select-String "TaskName|Status"
Get-CimInstance Win32_Process -Filter "Name='LC.exe'" | ForEach-Object { "LC.exe alive pid=$($_.ProcessId)" }
