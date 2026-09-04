$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*linc-bot*bot.py*' }
foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force; "killed $($p.ProcessId)" }
if (-not $procs) { "no bot.py running" }
