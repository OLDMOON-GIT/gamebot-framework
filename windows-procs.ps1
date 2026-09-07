Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public class W4 {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
    public delegate bool EnumProc(IntPtr h, IntPtr l);
    public struct RECT { public int l, t, r, b; }
}
"@
[W4]::EnumWindows([W4+EnumProc]{
    param($h, $l)
    if ([W4]::IsWindowVisible($h)) {
        $sb = New-Object System.Text.StringBuilder 512
        [W4]::GetWindowTextW($h, $sb, 512) | Out-Null
        $t = $sb.ToString().Trim()
        if ($t) {
            $procId = 0
            [W4]::GetWindowThreadProcessId($h, [ref]$procId) | Out-Null
            $pname = (Get-Process -Id $procId -ErrorAction SilentlyContinue).ProcessName
            $r = New-Object W4+RECT
            [W4]::GetWindowRect($h, [ref]$r) | Out-Null
            "hwnd=$h [$($r.l),$($r.t),$($r.r),$($r.b)] pid=$procId ($pname) $t"
        }
    }
    return $true
}, [IntPtr]::Zero) | Out-Null
