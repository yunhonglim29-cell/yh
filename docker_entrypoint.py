"""Prepare the runtime data volume, then run the app without root privileges."""
import os
from pathlib import Path
import sys

if __name__ == '__main__':
    directory = Path(os.getenv('DATA_DIR', '/data')).resolve()
    if str(directory) in {'/', '/app', '/usr', '/etc', '/var', '/home', '/tmp'}:
        raise RuntimeError('DATA_DIR must be a dedicated data directory, not a system directory.')
    directory.mkdir(parents=True, exist_ok=True)
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        uid, gid = 10001, 10001
        os.chown(directory, uid, gid)
        for base, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs + files:
                path = Path(base) / name
                if not path.is_symlink():
                    os.chown(path, uid, gid)
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
    os.umask(0o077)
    os.execv(sys.executable, [sys.executable, '/app/run.py'])
