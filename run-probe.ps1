$task = "LincProbe"
$tr = 'C:\Users\moony\linc-bot\probe-run.cmd'
schtasks /create /f /tn $task /sc once /st 23:59 /ru administrator /it /tr $tr
schtasks /run /tn $task
Start-Sleep -Seconds 10
Get-Content C:\Users\moony\linc-bot\debug\probe-done.txt -ErrorAction SilentlyContinue
Get-Content C:\Users\moony\linc-bot\debug\probe-out.txt -ErrorAction SilentlyContinue | Select-Object -Last 5
