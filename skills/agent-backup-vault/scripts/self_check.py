#!/usr/bin/env python3
import http.server, json, os, subprocess, sys, tempfile, threading
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix='dav-root-')); (ROOT / 'dav').mkdir()
CFG_HOME = Path(tempfile.mkdtemp(prefix='dav-home-'))
SCRIPT = Path(__file__).with_name('agent_backup.py')

class H(http.server.BaseHTTPRequestHandler):
    def p(self):
        return ROOT / self.path.lstrip('/')
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('DAV', '1, 2'); self.end_headers()
    def do_MKCOL(self):
        p = self.p()
        if p.exists(): self.send_response(405)
        elif not p.parent.exists(): self.send_response(409)
        else: p.mkdir(); self.send_response(201)
        self.end_headers()
    def do_PUT(self):
        p = self.p(); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
        self.send_response(201); self.end_headers()
    def do_GET(self):
        p = self.p()
        if not p.exists(): self.send_response(404); self.end_headers(); return
        b = p.read_bytes(); self.send_response(200); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_DELETE(self):
        try: self.p().unlink()
        except FileNotFoundError: pass
        self.send_response(204); self.end_headers()
    def log_message(self, format, *args): pass

srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{srv.server_port}/dav'
env = os.environ | {'HOME': str(CFG_HOME)}

def run(*args, input=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], input=input, text=True, capture_output=True, check=True, env=env)

sample = CFG_HOME / 'sample.txt'; sample.write_text('hello backup')
run('init', '--url', url, '--user', 'u', '--password', 'p')
run('check')
put = run('put', str(sample), '--label', 'self-check')
rec = json.loads(put.stdout)
search = run('search', 'self-check').stdout
assert rec['id'] in search
out = CFG_HOME / 'restored.txt'
run('get', rec['id'][:20], '--output', str(out))
assert out.read_text() == 'hello backup'
run('rm', rec['id'])

# sidecar profile (multi-host primary store): no client-side index rewrite, server builder folds sidecars
run('init', '--profile', 'sc', '--url', url, '--user', 'u', '--password', 'p', '--index', 'sidecar', '--host-label', 'hostA')
big = CFG_HOME / 'big.bin'; big.write_bytes(os.urandom(3 * 1024 * 1024))
rec2 = json.loads(run('put', '--profile', 'sc', str(big), '--label', 'sc-check').stdout)
assert rec2['host'] == 'hostA' and not rec2.get('reused')
out2 = CFG_HOME / 'big.out'
run('get', '--profile', 'sc', rec2['id'], '--output', str(out2))   # before index rebuild: sidecar lookup
assert out2.read_bytes() == big.read_bytes()
subprocess.run([sys.executable, str(SCRIPT.with_name('agent_backup_index.py')), str(ROOT / 'dav' / 'agent-backups')], check=True)
assert rec2['id'] in run('search', '--profile', 'sc', 'sc-check').stdout
rec3 = json.loads(run('put', '--profile', 'sc', str(big), '--label', 'sc-check').stdout)
assert rec3.get('reused') and rec3['id'] == rec2['id']
run('rm', '--profile', 'sc', rec2['id'])
assert not (ROOT / rec2['path'].replace('agent-backups', 'dav/agent-backups', 1)).exists()
print('self-check ok')
