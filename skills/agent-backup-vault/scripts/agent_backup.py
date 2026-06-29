#!/usr/bin/env python3
import argparse, base64, getpass, hashlib, json, os, socket, sys, tarfile, tempfile, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path.home() / '.config' / 'agent-backup-vault' / 'config.json'


def load(profile):
    data = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    cfg = data.get('profiles', {}).get(profile)
    if not cfg:
        raise SystemExit(f'profile not configured: {profile}; run init')
    return cfg


def save(profile, cfg):
    data = json.loads(CONFIG.read_text()) if CONFIG.exists() else {'profiles': {}}
    data.setdefault('profiles', {})[profile] = cfg
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(CONFIG, 0o600)


def auth_header(cfg):
    token = base64.b64encode(f"{cfg['user']}:{cfg['password']}".encode()).decode()
    return {'Authorization': 'Basic ' + token}


def join_url(base, *parts):
    url = base.rstrip('/') + '/'
    quoted = '/'.join(urllib.parse.quote(str(p).strip('/')) for p in parts if str(p).strip('/'))
    return url + quoted


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(cfg, method, path='', body=None, headers=None, ok=(200, 201, 204, 207)):
    h = {'User-Agent': 'curl/8.0 agent-backup-vault'}
    h.update(auth_header(cfg))
    if headers:
        h.update(headers)
    req = urllib.request.Request(join_url(cfg['url'], path), data=body, headers=h, method=method)
    opener = urllib.request.build_opener(NoRedirect) if method == 'GET' else urllib.request.build_opener()
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read()
            if r.status not in ok:
                raise SystemExit(f'{method} {path}: HTTP {r.status}')
            return r.status, data
    except urllib.error.HTTPError as e:
        if method == 'GET' and e.code in (301, 302, 303, 307, 308) and e.headers.get('Location'):
            with urllib.request.urlopen(urllib.request.Request(e.headers['Location'], headers={'User-Agent': h['User-Agent']}), timeout=60) as r:
                return r.status, r.read()
        if e.code not in ok:
            raise SystemExit(f'{method} {path}: HTTP {e.code} {e.read().decode(errors="ignore")[:200]}')
        return e.code, e.read()


def mkdirp(cfg, path):
    cur = ''
    for part in [p for p in path.split('/') if p]:
        cur = f'{cur}/{part}' if cur else part
        request(cfg, 'MKCOL', cur, ok=(200, 201, 204, 403, 405))  # ponytail: some WebDAVs auto-create parents but forbid MKCOL


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def make_payload(src, name=None):
    if src == '-':
        if not name:
            raise SystemExit('--name required when reading stdin')
        fd, tmp = tempfile.mkstemp(prefix='agent-backup-', suffix='-' + name)
        with os.fdopen(fd, 'wb') as f:
            while True:
                chunk = sys.stdin.buffer.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
        return Path(tmp), name, True
    p = Path(src)
    if not p.exists():
        raise SystemExit(f'not found: {src}')
    if p.is_dir():
        fd, tmp = tempfile.mkstemp(prefix='agent-backup-', suffix='.tar.gz')
        os.close(fd)
        with tarfile.open(tmp, 'w:gz') as tar:
            tar.add(p, arcname=p.name)
        return Path(tmp), (name or p.name + '.tar.gz'), True
    return p, (name or p.name), False


def cmd_init(args):
    password = args.password or getpass.getpass('WebDAV password: ')
    save(args.profile, {'url': args.url.rstrip('/'), 'user': args.user, 'password': password, 'root': args.root.strip('/')})
    print(f'configured profile={args.profile} root={args.root.strip("/")}')


def cmd_check(args):
    cfg = load(args.profile)
    mkdirp(cfg, cfg.get('root', 'agent-backups'))
    status, _ = request(cfg, 'OPTIONS')
    print(f'ok profile={args.profile} http={status} url={cfg["url"]}')


def cmd_put(args):
    cfg = load(args.profile)
    root = cfg.get('root', 'agent-backups')
    payload, display_name, cleanup = make_payload(args.source, args.name)
    now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    host = socket.gethostname().split('.')[0]
    label = ''.join(c if c.isalnum() or c in '._-' else '-' for c in (args.label or 'backup'))[:80]
    digest = sha256_file(payload)
    size = payload.stat().st_size
    backup_id = f'{now}-{host}-{label}-{digest[:12]}-{display_name}'
    remote_dir = f'{root}/{now[:4]}/{now[:6]}/{now[:8]}'
    remote_path = f'{remote_dir}/{backup_id}'
    mkdirp(cfg, remote_dir)
    request(cfg, 'PUT', remote_path, payload.read_bytes(), {'Content-Type': 'application/octet-stream'})
    record = {
        'id': backup_id, 'time_utc': now, 'host': host, 'label': args.label or 'backup',
        'source': args.source, 'name': display_name, 'size': size, 'sha256': digest, 'path': remote_path,
    }
    append_index(cfg, root, record)
    if cleanup:
        payload.unlink(missing_ok=True)
    print(json.dumps(record, ensure_ascii=False))


def append_index(cfg, root, record):
    index_path = f'{root}/index.jsonl'
    try:
        _, old = request(cfg, 'GET', index_path, ok=(200,))
    except SystemExit:
        old = b''
        mkdirp(cfg, root)
    body = old + (json.dumps(record, ensure_ascii=False) + '\n').encode()
    request(cfg, 'PUT', index_path, body, {'Content-Type': 'application/jsonl'})


def read_index(cfg):
    root = cfg.get('root', 'agent-backups')
    _, data = request(cfg, 'GET', f'{root}/index.jsonl', ok=(200,))
    return [json.loads(line) for line in data.decode().splitlines() if line.strip()]


def cmd_search(args):
    cfg = load(args.profile)
    q = ' '.join(args.query).lower()
    rows = read_index(cfg)
    if q:
        rows = [r for r in rows if q in json.dumps(r, ensure_ascii=False).lower()]
    for r in rows[-args.limit:]:
        print(f'{r["id"]}\t{r["size"]}\t{r["sha256"][:12]}\t{r["path"]}')


def cmd_get(args):
    cfg = load(args.profile)
    rows = read_index(cfg)
    matches = [r for r in rows if r['id'] == args.backup_id or r['id'].startswith(args.backup_id)]
    if len(matches) != 1:
        raise SystemExit(f'expected one match, got {len(matches)}')
    r = matches[0]
    _, data = request(cfg, 'GET', r['path'], ok=(200,))
    out = Path(args.output or r['name'])
    if out.is_dir():
        out = out / r['name']
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    got = hashlib.sha256(data).hexdigest()
    if got != r['sha256']:
        raise SystemExit(f'sha256 mismatch: {got} != {r["sha256"]}')
    print(str(out))


def cmd_rm(args):
    cfg = load(args.profile)
    rows = read_index(cfg)
    matches = [r for r in rows if r['id'] == args.backup_id or r['id'].startswith(args.backup_id)]
    if len(matches) != 1:
        raise SystemExit(f'expected one match, got {len(matches)}')
    request(cfg, 'DELETE', matches[0]['path'], ok=(200, 202, 204, 403, 404))
    print('deleted object only; index retained:', matches[0]['id'])


def add_profile(parser):
    parser.add_argument('--profile', default='default')
    return parser


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)
    s = add_profile(sub.add_parser('init')); s.add_argument('--url', required=True); s.add_argument('--user', required=True); s.add_argument('--password'); s.add_argument('--root', default='agent-backups'); s.set_defaults(func=cmd_init)
    s = add_profile(sub.add_parser('check')); s.set_defaults(func=cmd_check)
    s = add_profile(sub.add_parser('put')); s.add_argument('source'); s.add_argument('--name'); s.add_argument('--label'); s.set_defaults(func=cmd_put)
    s = add_profile(sub.add_parser('search')); s.add_argument('query', nargs='*'); s.add_argument('--limit', type=int, default=20); s.set_defaults(func=cmd_search)
    s = add_profile(sub.add_parser('get')); s.add_argument('backup_id'); s.add_argument('--output'); s.set_defaults(func=cmd_get)
    s = add_profile(sub.add_parser('rm')); s.add_argument('backup_id'); s.set_defaults(func=cmd_rm)
    args = p.parse_args(); args.func(args)


if __name__ == '__main__':
    main()
