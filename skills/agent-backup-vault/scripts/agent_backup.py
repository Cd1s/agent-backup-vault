#!/usr/bin/env python3
import argparse, base64, fcntl, getpass, hashlib, json, os, shutil, socket, sys, tarfile, tempfile, time, urllib.error, urllib.parse, urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path.home() / '.config' / 'agent-backup-vault' / 'config.json'
INDEX_APPEND_LOCK = CONFIG.parent / 'index-append.lock'
CHUNK = 1024 * 1024
# The public fallback (last entry of `urls`) is Cloudflare-proxied, which rejects bodies above 100 MB.
PUBLIC_BODY_LIMIT = 95 * 1024 * 1024


def load(profile):
    data = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    cfg = data.get('profiles', {}).get(profile)
    if not cfg:
        raise SystemExit(f'profile not configured: {profile}; run init')
    cfg = dict(cfg)
    cfg['url'] = pick_url(cfg)
    return cfg


def pick_url(cfg):
    """Use the first reachable endpoint: `urls` (tailnet first, public fallback) or the single `url`.

    The choice is cached for 10 minutes so hosts without the tailnet do not pay a probe timeout on every call.
    """
    urls = cfg.get('urls') or [cfg['url']]
    if len(urls) == 1:
        return urls[0]
    cache = CONFIG.parent / '.endpoint-cache.json'
    try:
        cached = json.loads(cache.read_text())
        if cached.get('urls') == urls and time.time() - cached.get('at', 0) < 600:
            return cached['url']
    except (OSError, ValueError):
        pass
    chosen = urls[-1]
    for u in urls[:-1]:
        try:
            req = urllib.request.Request(u, method='OPTIONS', headers={'User-Agent': 'agent-backup-vault', **auth_header(cfg)})
            with urllib.request.urlopen(req, timeout=3):
                chosen = u
                break
        except urllib.error.HTTPError:
            chosen = u
            break
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    try:
        cache.write_text(json.dumps({'urls': urls, 'url': chosen, 'at': time.time()}))
        os.chmod(cache, 0o600)
    except OSError:
        pass
    return chosen


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


class WebDAVHTTPError(RuntimeError):
    def __init__(self, method, path, status, detail=''):
        super().__init__(f'{method} {path}: HTTP {status} {detail}'.rstrip())
        self.method = method
        self.path = path
        self.status = status


def open_response(cfg, method, path='', body=None, headers=None, ok=(200, 201, 204, 207), timeout=60, retries=2):
    """Return an open response. `body` may be bytes or a Path (streamed from disk, re-opened per retry)."""
    h = {'User-Agent': 'curl/8.0 agent-backup-vault'}
    h.update(auth_header(cfg))
    if headers:
        h.update(headers)
    url = join_url(cfg['url'], path)
    for attempt in range(retries + 1):
        fh = None
        data = body
        if isinstance(body, Path):
            fh = body.open('rb')
            data = fh
            h['Content-Length'] = str(body.stat().st_size)
        req = urllib.request.Request(url, data=data, headers=h, method=method)
        opener = urllib.request.build_opener(NoRedirect) if method == 'GET' else urllib.request.build_opener()
        try:
            r = opener.open(req, timeout=timeout)
            if r.status not in ok:
                r.close()
                raise WebDAVHTTPError(method, path, r.status)
            return r
        except urllib.error.HTTPError as e:
            if method == 'GET' and e.code in (301, 302, 303, 307, 308) and e.headers.get('Location'):
                return urllib.request.urlopen(urllib.request.Request(e.headers['Location'], headers={'User-Agent': h['User-Agent']}), timeout=timeout)
            if e.code not in ok:
                raise WebDAVHTTPError(method, path, e.code, e.read().decode(errors="ignore")[:200])
            return e
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt >= retries:
                raise
            time.sleep(min(2 ** attempt, 8))
        finally:
            if fh:
                fh.close()


def request(cfg, method, path='', body=None, headers=None, ok=(200, 201, 204, 207), timeout=60, retries=2):
    with open_response(cfg, method, path, body, headers, ok, timeout, retries) as r:
        return getattr(r, 'status', None) or r.code, r.read()


def mkdirp(cfg, path):
    # One MKCOL in the common case; walk parents only when the server reports 409 (missing parent).
    status, _ = request(cfg, 'MKCOL', path, ok=(200, 201, 204, 403, 405, 409))
    if status != 409:
        return
    cur = ''
    for part in [p for p in path.split('/') if p]:
        cur = f'{cur}/{part}' if cur else part
        request(cfg, 'MKCOL', cur, ok=(200, 201, 204, 403, 405))  # some WebDAVs auto-create parents but forbid MKCOL


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def make_payload(src, name=None):
    if src == '-':
        if not name:
            raise SystemExit('--name required when reading stdin')
        fd, tmp = tempfile.mkstemp(prefix='agent-backup-', suffix='-' + name)
        with os.fdopen(fd, 'wb') as f:
            shutil.copyfileobj(sys.stdin.buffer, f, CHUNK)
        return Path(tmp), name, True
    p = Path(src)
    if not p.exists():
        raise SystemExit(f'not found: {src}')
    if p.is_dir():
        fd, tmp = tempfile.mkstemp(prefix='agent-backup-', suffix='.tar.gz')
        os.close(fd)
        # Level 6 is several times faster than tarfile's default 9 for a few percent more bytes.
        with tarfile.open(tmp, 'w:gz', compresslevel=6) as tar:
            tar.add(p, arcname=p.name)
        return Path(tmp), (name or p.name + '.tar.gz'), True
    return p, (name or p.name), False


def cmd_init(args):
    password = args.password or getpass.getpass('WebDAV password: ')
    cfg = {'url': args.url.rstrip('/'), 'user': args.user, 'password': password, 'root': args.root.strip('/')}
    if args.fallback_url:
        cfg['urls'] = [cfg['url'], args.fallback_url.rstrip('/')]
    if args.index == 'sidecar':
        cfg['index'] = 'sidecar'
    if args.host_label:
        cfg['host_label'] = args.host_label
    save(args.profile, cfg)
    print(f'configured profile={args.profile} root={args.root.strip("/")}')


def cmd_check(args):
    cfg = load(args.profile)
    mkdirp(cfg, cfg.get('root', 'agent-backups'))
    status, _ = request(cfg, 'OPTIONS')
    print(f'ok profile={args.profile} http={status} url={cfg["url"]}')


def remote_path_for(root, backup_id):
    # Backup ids start with the UTC timestamp, so the object path is derivable without the index.
    now = backup_id[:16]
    return f'{root}/{now[:4]}/{now[:6]}/{now[:8]}/{backup_id}'


def find_existing(cfg, host, name, digest):
    try:
        rows = read_index(cfg)
    except (WebDAVHTTPError, urllib.error.URLError, OSError):
        return None
    for r in reversed(rows):
        if r.get('sha256') == digest and r.get('host') == host and r.get('name') == name:
            return r
    return None


def cmd_put(args):
    cfg = load(args.profile)
    root = cfg.get('root', 'agent-backups')
    sidecar = cfg.get('index') == 'sidecar'
    payload, display_name, cleanup = make_payload(args.source, args.name)
    try:
        host = cfg.get('host_label') or socket.gethostname().split('.')[0]
        digest = sha256_file(payload)
        size = payload.stat().st_size
        if sidecar and not args.no_dedup:
            existing = find_existing(cfg, host, display_name, digest)
            if existing:
                print(json.dumps({**existing, 'reused': True}, ensure_ascii=False))
                return
        urls = cfg.get('urls') or []
        if size > PUBLIC_BODY_LIMIT and len(urls) > 1 and cfg['url'] == urls[-1]:
            raise SystemExit(f'{size} bytes exceeds the 100 MB body limit of the public fallback {cfg["url"]}; run from a tailnet host')
        now = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        label = ''.join(c if c.isalnum() or c in '._-' else '-' for c in (args.label or 'backup'))[:80]
        backup_id = f'{now}-{host}-{label}-{digest[:12]}-{display_name}'
        remote_path = remote_path_for(root, backup_id)
        mkdirp(cfg, remote_path.rsplit('/', 1)[0])
        request(
            cfg, 'PUT', remote_path, payload,
            {'Content-Type': 'application/octet-stream'}, timeout=args.timeout,
            retries=max(args.retries, 2),
        )
        record = {
            'id': backup_id, 'time_utc': now, 'host': host, 'label': args.label or 'backup',
            'source': args.source, 'name': display_name, 'size': size, 'sha256': digest, 'path': remote_path,
        }
        if sidecar:
            # Server-side cron folds *.meta.json into index.jsonl; no client read-modify-write race.
            request(cfg, 'PUT', remote_path + '.meta.json', (json.dumps(record, ensure_ascii=False) + '\n').encode(),
                    {'Content-Type': 'application/json'})
        else:
            append_index(cfg, root, record)
    finally:
        if cleanup:
            payload.unlink(missing_ok=True)
    print(json.dumps(record, ensure_ascii=False))


@contextmanager
def index_append_lock():
    """Serialize local GET→PUT index appends so records cannot overwrite peers."""
    INDEX_APPEND_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_APPEND_LOCK.open('a+', encoding='utf-8') as handle:
        try:
            os.chmod(INDEX_APPEND_LOCK, 0o600)
        except OSError as exc:
            raise SystemExit(f'cannot protect local backup index lock: {exc}') from exc
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_index(cfg, root, record):
    # Legacy profiles: the WebDAV index is a read-modify-write JSONL file. Holding this local
    # lock across both requests prevents concurrent local callers (scheduled
    # backup, fast-board YAML backup, and manual backup) from losing a record.
    with index_append_lock():
        index_path = f'{root}/index.jsonl'
        try:
            _, old = request(cfg, 'GET', index_path, ok=(200,))
        except WebDAVHTTPError as exc:
            if exc.status != 404:
                raise
            old = b''
            mkdirp(cfg, root)
        body = old + (json.dumps(record, ensure_ascii=False) + '\n').encode()
        request(cfg, 'PUT', index_path, body, {'Content-Type': 'application/jsonl'})


def read_index(cfg):
    root = cfg.get('root', 'agent-backups')
    try:
        _, data = request(cfg, 'GET', f'{root}/index.jsonl', ok=(200,))
    except WebDAVHTTPError as exc:
        if exc.status == 404 and cfg.get('index') == 'sidecar':
            return []
        raise
    rows = []
    for line in data.decode().splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def resolve(cfg, backup_id):
    root = cfg.get('root', 'agent-backups')
    rows = read_index(cfg)
    matches = [r for r in rows if r['id'] == backup_id or r['id'].startswith(backup_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches and cfg.get('index') == 'sidecar' and len(backup_id) > 30:
        # Not indexed yet (index rebuilds every minute): read the sidecar directly.
        try:
            _, meta = request(cfg, 'GET', remote_path_for(root, backup_id) + '.meta.json', ok=(200,))
            return json.loads(meta)
        except (WebDAVHTTPError, ValueError):
            pass
    raise SystemExit(f'expected one match, got {len(matches)}')


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
    r = resolve(cfg, args.backup_id)
    out = Path(args.output or r['name'])
    if out.is_dir():
        out = out / r['name']
    out.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    tmp = out.with_name(out.name + '.part')
    with open_response(cfg, 'GET', r['path'], ok=(200,), timeout=args.timeout) as resp, tmp.open('wb') as f:
        for chunk in iter(lambda: resp.read(CHUNK), b''):
            h.update(chunk)
            f.write(chunk)
    got = h.hexdigest()
    if got != r['sha256']:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f'sha256 mismatch: {got} != {r["sha256"]}')
    os.replace(tmp, out)
    print(str(out))


def cmd_rm(args):
    cfg = load(args.profile)
    r = resolve(cfg, args.backup_id)
    # 404 is an idempotent already-absent result; 403 must remain an error so
    # retention callers never record an inaccessible object as pruned.
    status, _ = request(cfg, 'DELETE', r['path'], ok=(200, 202, 204, 404))
    if cfg.get('index') == 'sidecar':
        request(cfg, 'DELETE', r['path'] + '.meta.json', ok=(200, 202, 204, 404))
    action = 'already_absent' if status == 404 else 'deleted'
    print(json.dumps({'id': r['id'], 'action': action, 'index_retained': True}))


def add_profile(parser):
    parser.add_argument('--profile', default='default')
    return parser


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(required=True)
    s = add_profile(sub.add_parser('init')); s.add_argument('--url', required=True); s.add_argument('--fallback-url'); s.add_argument('--user', required=True); s.add_argument('--password'); s.add_argument('--root', default='agent-backups'); s.add_argument('--index', choices=('legacy', 'sidecar'), default='legacy'); s.add_argument('--host-label'); s.set_defaults(func=cmd_init)
    s = add_profile(sub.add_parser('check')); s.set_defaults(func=cmd_check)
    s = add_profile(sub.add_parser('put')); s.add_argument('source'); s.add_argument('--name'); s.add_argument('--label'); s.add_argument('--timeout', type=int, default=300); s.add_argument('--retries', type=int, default=2); s.add_argument('--no-dedup', action='store_true'); s.set_defaults(func=cmd_put)
    s = add_profile(sub.add_parser('search')); s.add_argument('query', nargs='*'); s.add_argument('--limit', type=int, default=20); s.set_defaults(func=cmd_search)
    s = add_profile(sub.add_parser('get')); s.add_argument('backup_id'); s.add_argument('--output'); s.add_argument('--timeout', type=int, default=300); s.set_defaults(func=cmd_get)
    s = add_profile(sub.add_parser('rm')); s.add_argument('backup_id'); s.set_defaults(func=cmd_rm)
    args = p.parse_args()
    try:
        args.func(args)
    except WebDAVHTTPError as exc:
        print(f'WebDAV request failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
