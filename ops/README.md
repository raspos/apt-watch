# 06:00 launcher

`launch_apt_watch.py` is a reference copy. The live copy sits outside OneDrive and outside AppData at
`%USERPROFILE%\.apt-watch\launch_apt_watch.py`. The Task Scheduler job `APT_WATCH_Daily_Collection` runs

    pythonw.exe "%USERPROFILE%\.apt-watch\launch_apt_watch.py" -- --manifest "<project>\data\fixed-110-panel.json" --workers 2 --timeout 10800

with working directory `%USERPROFILE%\.apt-watch`. It logs to `%USERPROFILE%\.apt-watch\heartbeat.log`, waits for the
OneDrive project files (15 min) and the network (10 min), then runs `scripts/run_daily_unattended.py`.

Why not AppData: files written under AppData from a packaged (MSIX) app, such as the Claude desktop app, are redirected
into that app's private storage. Task Scheduler cannot see them (0x8007010B / exit 2 on 2026-11-20). The same applies
to `playwright install`: browsers installed from such a session are invisible to the scheduled run, so the collector
uses the system Chrome (`--channel chrome`) and retries its launch up to 3 times with a 60 s timeout.

Morning check: `heartbeat.log` -> `data/logs/unattended_<day>_*.summary.json` -> `data/logs/collector/<day>/worker_*.log`.
