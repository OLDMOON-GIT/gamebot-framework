# PurpleBox 프로세스별 리스닝 포트 매핑
$pb = Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'Purple' }
foreach ($p in $pb) {
    $ports = Get-NetTCPConnection -State Listen -OwningProcess $p.ProcessId -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty LocalPort -Unique
    $cmd = if ($p.CommandLine) { $p.CommandLine.Substring(0, [Math]::Min(150, $p.CommandLine.Length)) } else { '' }
    "PID=$($p.ProcessId) $($p.Name) ports=[$($ports -join ',')]`n  $cmd"
}
