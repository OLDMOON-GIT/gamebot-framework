param([string]$CmdFile = "wincap-test.cmd", [string]$Task = "LincWinTest", [int]$Wait = 10)
schtasks /create /f /tn $Task /sc once /st 23:59 /ru administrator /it /tr "C:\Users\moony\linc-bot\$CmdFile"
schtasks /run /tn $Task
Start-Sleep -Seconds $Wait
Get-Content C:\Users\moony\linc-bot\debug\wincap-result.txt -ErrorAction SilentlyContinue
Get-Content C:\Users\moony\linc-bot\debug\wincap-out.txt -ErrorAction SilentlyContinue | Select-Object -Last 5
