"""Own only the packaged CPU server; never download assets or reuse a service."""
import atexit
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


class LocalServer:
    def __init__(self, root, config, popen=None, transport=None):
        self.root = Path(root).resolve()
        self.config = config
        self.popen = popen or subprocess.Popen
        # Local requests must not be routed through system proxy settings.
        self.transport = transport or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        self.process = None
        self.base_url = ''
        atexit.register(self.close)

    def _asset(self, relative, folder):
        relative = Path(relative)
        path = (self.root/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(self.root/folder):
            raise ValueError('Runtime assets must stay inside their package folder')
        if not path.is_file():
            raise FileNotFoundError('Packaged runtime asset is missing')
        return str(path)

    def available(self):
        """Validate packaged assets without spawning or connecting to anything."""
        try:
            cfg = self.config['builtin_local']
            self._asset(cfg['binary'], 'runtime')
            self._asset(cfg['model_path'], 'models')
            return True
        except (OSError, ValueError, KeyError):
            return False

    def start(self):
        if self.process is not None and self.process.poll() is None:
            return self.base_url
        cfg = self.config['builtin_local']
        binary = self._asset(cfg['binary'], 'runtime')
        model = self._asset(cfg['model_path'], 'models')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.base_url = f'http://127.0.0.1:{port}/v1'
        argv = [binary, '-m', model, '--host', '127.0.0.1', '--port', str(port),
                '-c', str(cfg['context_size']), '-t', str(cfg['threads']),
                '-ngl', '0', '--offline', '--no-webui', '--parallel', '1',
                '--jinja', '--flash-attn', 'on', '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0']
        # Fail closed: do not overlap any existing inference server.
        import os
        powershell = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        check = subprocess.run([powershell, '-NoProfile', '-Command',
            "if (Get-Process -Name 'llama-server' -ErrorAction SilentlyContinue) { exit 7 }; exit 0"],
            capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if check.returncode != 0:
            raise RuntimeError('Another inference server is active or process gate failed')
        self.process = self.popen(argv, cwd=str(self.root), shell=False,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + float(self.config['startup_timeout_s'])
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Local server exited during startup')
                try:
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/health')
                    with self.transport(req, timeout=max(.001, min(1., deadline-time.monotonic()))) as response:
                        response.read()
                    return self.base_url
                except (OSError, TimeoutError):
                    time.sleep(min(.05, max(0., deadline-time.monotonic())))
            raise TimeoutError('Local server startup timed out')
        except Exception:
            self.close()
            raise

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
