$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$args = '--remote-debugging-port=9333 --remote-allow-origins=* --user-data-dir=C:\Users\moony\linc-bot\chrome-profile --no-first-run --start-maximized https://purpleon.plaync.com/webplay/linclassic'
$action = New-ScheduledTaskAction -Execute $chrome -Argument $args
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "moony"
$principal = New-ScheduledTaskPrincipal -UserId "moony" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "LincChrome" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "LincChrome"
Start-Sleep -Seconds 6
$listening = netstat -ano | Select-String ":9333\s"
if ($listening) { "CHROME_OK" } else { "CHROME_FAIL" }
