"""APT WATCH 06:00 launcher (lives outside OneDrive on purpose).

Task Scheduler starts this file. It
  1. writes to heartbeat.log immediately (local disk),
  2. waits until the project files in OneDrive can actually be read (up to 15 min),
  3. waits until Naver resolves and answers (up to 10 min, network may still be coming up after wake),
  4. runs scripts/run_daily_unattended.py with the given arguments and records its exit code.

Every step is logged so a failed morning shows where it stopped.
usage: pythonw launch_apt_watch.py [--check-only] -- <args passed to run_daily_unattended.py>
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT = Path(r"C:\Users\kimwo\OneDrive\문서\New project\apt-watch")
HERE = Path.home() / '.apt-watch'   # outside AppData: packaged apps redirect AppData writes
LOG = HERE / 'heartbeat.log'
FILE_WAIT_S = 15 * 60
NET_WAIT_S = 10 * 60


def hb(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} launcher pid={os.getpid()} {msg}\n")
    except Exception:
        pass


def wait_files():
    need = [PROJECT / 'scripts' / 'run_daily_unattended.py', PROJECT / 'scripts' / 'daily_operation.py',
            PROJECT / 'collect_naver.py', PROJECT / 'data' / 'fixed-110-panel.json']
    t0 = time.monotonic()
    tries = 0
    while True:
        tries += 1
        try:
            for p in need:
                with open(p, 'rb') as f:
                    f.read()
            hb(f'project files readable after {tries} try/tries, {time.monotonic() - t0:.0f}s')
            return True
        except Exception as e:
            if tries == 1 or tries % 6 == 0:
                hb(f'waiting for project files: {type(e).__name__}: {e}')
            if time.monotonic() - t0 > FILE_WAIT_S:
                hb('gave up waiting for project files')
                return False
            time.sleep(10)


def wait_network():
    t0 = time.monotonic()
    tries = 0
    while True:
        tries += 1
        try:
            socket.getaddrinfo('fin.land.naver.com', 443)
            urllib.request.urlopen(urllib.request.Request('https://fin.land.naver.com/', method='HEAD',
                                   headers={'User-Agent': 'Mozilla/5.0'}), timeout=15)
            hb(f'network ready after {tries} try/tries, {time.monotonic() - t0:.0f}s')
            return True
        except Exception as e:
            if tries == 1 or tries % 6 == 0:
                hb(f'waiting for network: {type(e).__name__}: {e}')
            if time.monotonic() - t0 > NET_WAIT_S:
                hb('network not confirmed; starting anyway (collector has its own retries)')
                return False
            time.sleep(10)


PS_AUMID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'


def notify(title, body, stay=False):
    """Windows toast. stay=True keeps it on screen until dismissed (reminder scenario)."""
    esc = lambda s: s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace("'", "''")
    scenario = ' scenario="reminder"' if stay else ''
    actions = ('<actions><action content="확인" arguments="dismiss" activationType="system"/></actions>'
               if stay else '')
    xml = (f'<toast{scenario}><visual><binding template="ToastGeneric"><text>{esc(title)}</text>'
           f'<text>{esc(body)}</text></binding></visual>{actions}</toast>')
    ps = ("[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
          "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]>$null;"
          f"$x=New-Object Windows.Data.Xml.Dom.XmlDocument;$x.LoadXml('{xml}');"
          f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{PS_AUMID}')"
          ".Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', ps],
                           capture_output=True, timeout=60, creationflags=0x08000000)
        hb(f'notify "{title}" rc={r.returncode}' + (f' err={r.stderr[:200]!r}' if r.returncode else ''))
    except Exception as e:
        hb(f'notify failed: {type(e).__name__}: {e}')


def keep_awake(on):
    """Block idle sleep while this process runs (no power-setting change; lid/power button still act)."""
    try:
        import ctypes
        flags = 0x80000000 | (0x00000001 if on else 0)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        hb(f'keep_awake {on}')
    except Exception as e:
        hb(f'keep_awake failed: {type(e).__name__}: {e}')


def main():
    argv = sys.argv[1:]
    check_only = '--check-only' in argv
    passthru = argv[argv.index('--') + 1:] if '--' in argv else []
    hb(f'start check_only={check_only} python={sys.executable}')
    if check_only:
        notify('APT WATCH 알림 시험', '수집 중에는 이런 알림이 화면에 남습니다.', stay=True)
    if not wait_files():
        return 2
    wait_network()
    if check_only:
        hb('check-only: done')
        return 0
    keep_awake(True)
    notify('APT WATCH 수집 중', '끝날 때까지(약 1.5~2시간) PC를 끄거나 다시 시작하지 마세요. 충전기와 화면 열어 두기.', stay=True)
    cmd = [sys.executable, str(PROJECT / 'scripts' / 'run_daily_unattended.py')] + passthru
    hb('running ' + ' '.join(cmd[1:]))
    code = subprocess.call(cmd, cwd=str(PROJECT))
    hb(f'run_daily_unattended exit code {code}')
    keep_awake(False)
    if code == 0:
        notify('APT WATCH 수집 끝', '오늘 수집·공표가 끝났습니다. 이제 PC를 꺼도 됩니다.')
    else:
        notify('APT WATCH 수집 끝 (확인 필요)', f'수집은 끝났지만 공표되지 않았습니다(코드 {code}). PC는 꺼도 됩니다.')
    return code


if __name__ == '__main__':
    sys.exit(main())
