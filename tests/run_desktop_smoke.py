"""Run desktop smoke checks directly or with an available Linux Xvfb binary."""
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys

script = Path(__file__).with_name('smoke_desktop.py')
if os.name == 'nt' or sys.platform == 'darwin' or os.environ.get('DISPLAY'):
    raise SystemExit(subprocess.call([sys.executable, str(script)]))
xvfb = os.environ.get('HOCHI_XVFB') or shutil.which('Xvfb')
if not xvfb:
    raise SystemExit('Xvfb is required on headless Linux. Set HOCHI_XVFB to its executable path.')
read_fd, write_fd = os.pipe()
process = subprocess.Popen([xvfb, '-displayfd', str(write_fd), '-screen', '0', '1280x900x24', '-nolisten', 'tcp'], pass_fds=(write_fd,), stderr=subprocess.DEVNULL)
os.close(write_fd)
try:
    if not select.select([read_fd], [], [], 10)[0]:
        raise RuntimeError('Xvfb startup timed out')
    display = os.read(read_fd, 64).decode().strip()
    if not display.isdigit():
        raise RuntimeError('Xvfb could not start')
    env = dict(os.environ, DISPLAY=':' + display)
    raise SystemExit(subprocess.call([sys.executable, str(script)], env=env))
finally:
    os.close(read_fd)
    process.terminate()
    process.wait(timeout=10)
