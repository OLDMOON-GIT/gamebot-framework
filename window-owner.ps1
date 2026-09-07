Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W3 {
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
}
"@
$hwnd = [IntPtr]854070
$pid_ = 0
[W3]::GetWindowThreadProcessId($hwnd, [ref]$pid_) | Out-Null
"window 854070 owner PID: $pid_"
Get-Process -Id $pid_ | Format-List ProcessName, Path
