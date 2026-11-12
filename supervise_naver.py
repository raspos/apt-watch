"""Bound a collector run, including browser-driver startup."""
import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('collector_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.timeout <= 0 or args.collector_args[:1] != ['--']:
        parser.error('use --timeout SECONDS -- followed by collector arguments')
    started = time.monotonic()
    collector = Path(__file__).with_name('collect_naver.py')
    print(f'{datetime.now().astimezone().isoformat()} collector starting', flush=True)
    process = subprocess.Popen(
        [sys.executable, '-u', str(collector), *args.collector_args[1:]],
        start_new_session=os.name != 'nt',
    )
    try:
        code = process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(f'collector exceeded {args.timeout}s; stopping its process tree', flush=True)
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], timeout=15)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)
        code = 124
    print(f'collector exit={code} elapsed={time.monotonic()-started:.2f}s', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
