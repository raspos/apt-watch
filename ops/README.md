# 06:00 launcher

`launch_apt_watch.py` is a reference copy. The live copy must sit outside OneDrive at
`%LOCALAPPDATA%pt-watch\launch_apt_watch.py`; the Task Scheduler job APT_WATCH_Daily_Collection runs it with
`pythonw.exe "...\launch_apt_watch.py" -- --manifest "<project>\dataixed-110-panel.json" --workers 2 --timeout 10800`.
It logs to `%LOCALAPPDATA%pt-watch\heartbeat.log`, waits for the OneDrive project files (15 min) and the network
(10 min), then runs `scripts/run_daily_unattended.py`.
