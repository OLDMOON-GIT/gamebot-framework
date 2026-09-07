$p = Get-CimInstance Win32_Process -Filter "Name='LC.exe'"
if ($p) { "LC.exe pid=$($p.ProcessId)"; $p.CommandLine } else { "LC.exe 없음" }
"--- Purple 관련 ---"
Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'Purple|purple' } | ForEach-Object { "$($_.ProcessId) $($_.Name)" }
"--- 열린 창 (Lineage/Purple) ---"
Get-Process | Where-Object { $_.MainWindowTitle -match 'Lineage|Purple' } | ForEach-Object { "$($_.ProcessName): $($_.MainWindowTitle)" }
