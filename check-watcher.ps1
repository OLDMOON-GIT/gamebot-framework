$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*watcher.py*' }
foreach ($p in $procs) {
    "PID=$($p.ProcessId) START=$($p.CreationDate) CMD=$($p.CommandLine.Substring(0, [Math]::Min(80, $p.CommandLine.Length)))"
}
if (-not $procs) { "NONE" }
