"""Run both development servers with one command: python start.py.

On Render, the production container uses ONE process: FastAPI serves the built
React assets and API on the same origin (no Node process at runtime).
"""
from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / 'frontend'

def main() -> int:
    npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm') or shutil.which('npm')
    if not npm:
        print('Node.js/npm not found. Install Node.js 22+ and restart PowerShell.', file=sys.stderr)
        return 1
    if not (FRONTEND / 'node_modules' / 'vite').is_dir():
        print('Installing frontend dependencies (first run)...', flush=True)
        if subprocess.call([npm, 'install', '--no-audit', '--no-fund'], cwd=FRONTEND) != 0:
            print('npm install failed. Check internet/npm access and retry.', file=sys.stderr)
            return 1
    processes: list[subprocess.Popen] = []
    try:
        processes.append(subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000'], cwd=ROOT))
        processes.append(subprocess.Popen([npm, 'run', 'dev'], cwd=FRONTEND))
        print('\nORANEO running: http://localhost:5173 | API http://127.0.0.1:8000/docs\nPress Ctrl+C to stop both servers.\n', flush=True)
        while True:
            for p in processes:
                if p.poll() is not None:
                    print(f'A development server exited with code {p.returncode}', file=sys.stderr)
                    return p.returncode or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        for p in processes:
            if p.poll() is None: p.terminate()
        for p in processes:
            try: p.wait(timeout=4)
            except subprocess.TimeoutExpired: p.kill()

if __name__ == '__main__':
    sys.exit(main())
