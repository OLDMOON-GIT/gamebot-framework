# PurpleLauncher.exe에서 ASCII 문자열 추출해 launch 관련 패턴 탐색
$path = "C:\Program Files (x86)\NC\Purple\PurpleLauncher.exe"
$bytes = [System.IO.File]::ReadAllBytes($path)
$text = [System.Text.Encoding]::ASCII.GetString($bytes)
$strings = [regex]::Matches($text, '[ -~]{6,}') | ForEach-Object { $_.Value }
$hits = $strings | Where-Object { $_ -match 'game|launch|play' -and $_ -match '[:/=]' } | Select-Object -First 30
$hits
"---"
$strings | Where-Object { $_ -match '^nc-purple' } | Select-Object -First 10
