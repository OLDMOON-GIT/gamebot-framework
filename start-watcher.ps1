schtasks /create /f /tn "LincWatcher" /sc onstart /tr '"C:\Users\moony\AppData\Local\Programs\Python\Python311\python.exe" C:\Users\moony\linc-bot\watcher.py'
schtasks /query /tn "LincWatcher" /fo list | Select-String "TaskName|Status"
