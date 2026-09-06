$names = @("Purple", "purple-agent", "purpleonp", "PurpleBox")
foreach ($n in $names) {
    Get-CimInstance Win32_Process -Filter "Name='$n.exe'" | ForEach-Object {
        "=== $($n) PID=$($_.ProcessId)"
        $_.CommandLine
    }
}
""
"--- 28500/49278 HTTP probe ---"
foreach ($p in 28500, 49278) {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$p/" -TimeoutSec 3 -UseBasicParsing
        "$p : HTTP $($r.StatusCode) $($r.Content.Substring(0, [Math]::Min(200, $r.Content.Length)))"
    } catch {
        "$p : $($_.Exception.Message.Substring(0, [Math]::Min(120, $_.Exception.Message.Length)))"
    }
}
