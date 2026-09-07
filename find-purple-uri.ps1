$hits = Get-ChildItem "C:\Program Files (x86)\NC\Purple\2.26.831.38" -Recurse -Include *.js,*.json -ErrorAction SilentlyContinue |
    Select-String -Pattern 'nc-purple://' -List -ErrorAction SilentlyContinue |
    Select-Object -First 5
foreach ($h in $hits) {
    $line = $h.Line
    $idx = $line.IndexOf('nc-purple://')
    $snippet = $line.Substring($idx, [Math]::Min(150, $line.Length - $idx))
    "$($h.Path)`n  -> $snippet"
}
