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
HERE = Path(__file__).resolve().parent
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


def main():
    argv = sys.argv[1:]
    check_only = '--check-only' in argv
    passthru = argv[argv.index('--') + 1:] if '--' in argv else []
    hb(f'start check_only={check_only} python={sys.executable}')
    if not wait_files():
        return 2
    wait_network()
    if check_only:
        hb('check-only: done')
        return 0
    cmd = [sys.executable, str(PROJECT / 'scripts' / 'run_daily_unattended.py')] + passthru
    hb('running ' + ' '.join(cmd[1:]))
    code = subprocess.call(cmd, cwd=str(PROJECT))
    hb(f'run_daily_unattended exit code {code}')
    return code


if __name__ == '__main__':
    sys.exit(main())
