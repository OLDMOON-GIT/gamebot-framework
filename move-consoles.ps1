# 제 작업에서 남은 콘솔 창을 화면 밖 우하단으로 이동 (종료하지 않음)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W {
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int s);
}
"@
$moved = @()
foreach ($p in Get-Process) {
    $t = $p.MainWindowTitle
    if ($t -match 'cmd\.exe|powershell' -and $p.MainWindowHandle -ne 0) {
        [W]::SetWindowPos($p.MainWindowHandle, [IntPtr]::Zero, 1800, 900, 700, 400, 0x0040) | Out-Null
        $moved += "$($p.Id): $t"
    }
}
"MOVED:"; $moved
