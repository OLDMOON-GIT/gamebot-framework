Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'lin|classic|LineageClassic|ncsoft|x64' -or $_.CommandLine -match 'Lineage' } | ForEach-Object {
    "$($_.ProcessId) $($_.Name) START=$($_.CreationDate)"
}
"--- 최근 5분 내 시작된 프로세스 ---"
$cut = (Get-Date).AddMinutes(-10)
Get-CimInstance Win32_Process | Where-Object { $_.CreationDate -gt $cut } | Sort-Object CreationDate | ForEach-Object { "$($_.CreationDate.ToString('HH:mm:ss')) $($_.Name) pid=$($_.ProcessId)" }
