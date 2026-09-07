$candidates = @(
    "C:\Users\Administrator\AppData\Local\NC",
    "C:\Users\Administrator\AppData\Roaming\NC",
    "C:\Users\Administrator\AppData\Local\NCSOFT",
    "C:\Users\Administrator\AppData\Roaming\NCSOFT",
    "C:\Program Files (x86)\NC\Purple\log",
    "C:\ProgramData\NC"
)
foreach ($c in $candidates) {
    if (Test-Path $c) {
        "=== $c"
        Get-ChildItem $c -Recurse -File -ErrorAction SilentlyContinue | Select-Object -First 20 | ForEach-Object { "  $($_.FullName.Substring($c.Length)) ($($_.Length)b)" }
    }
}
