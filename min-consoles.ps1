# 남은 콘솔 창 최소화 (종료 아님)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class W2 {
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int s);
}
"@
foreach ($p in Get-Process) {
    $t = $p.MainWindowTitle
    if ($t -match 'cmd\.exe|powershell|pwsh' -and $p.MainWindowHandle -ne 0) {
        [W2]::ShowWindow($p.MainWindowHandle, 6) | Out-Null  # SW_MINIMIZE
        "minimized: $($p.Id) $t"
    }
}
