"""Manage local Xray profiles. Run as root in /opt/trusted-vpn."""
import argparse, json, os, pathlib, re, subprocess, uuid
from urllib.parse import urlencode, quote

os.umask(0o077)
parser = argparse.ArgumentParser()
parser.add_argument('--directory', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent,
                    help='Installation directory; defaults to the directory containing this script')
parser.add_argument('action', choices=['list', 'export', 'add', 'remove'])
parser.add_argument('name', nargs='?')
args = parser.parse_args()
BASE = args.directory.resolve()
CONFIG = BASE / 'config/config.json'
config = json.loads(CONFIG.read_text())
clients = config['inbounds'][0]['settings']['clients']
public = json.loads((BASE / 'public.json').read_text())
compose = ['docker', 'compose', '-f', str(BASE / 'compose.yaml')]
if args.action in ['add', 'remove']:
    if not args.name or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', args.name):
        parser.error('Provide a name containing 1-40 letters, digits, underscores or hyphens')
    if args.name == 'all-users':
        parser.error('all-users is reserved for the administrator export')
    found = any(c['email'] == args.name for c in clients)
    if args.action == 'add':
        if found:
            parser.error('User already exists')
        clients.append({'id': str(uuid.uuid4()), 'email': args.name, 'flow': 'xtls-rprx-vision'})
    else:
        if not found:
            parser.error('User does not exist')
        clients[:] = [c for c in clients if c['email'] != args.name]
    original = CONFIG.read_bytes()
    candidate = CONFIG.with_name('candidate.json')
    candidate.write_text(json.dumps(config, indent=2) + '\n')
    candidate.chmod(0o644)
    result = subprocess.run(compose + ['exec', '-T', 'xray', 'xray', 'run', '-test', '-config', '/etc/xray/candidate.json'])
    if result.returncode:
        candidate.unlink()
        raise SystemExit('Validation failed; active configuration unchanged')
    candidate.replace(CONFIG)
    try:
        subprocess.run(compose + ['restart', 'xray'], check=True)
        subprocess.run(compose + ['exec', '-T', 'xray', 'xray', 'version'], check=True)
    except subprocess.CalledProcessError:
        CONFIG.write_bytes(original)
        CONFIG.chmod(0o644)
        subprocess.run(compose + ['restart', 'xray'], check=True)
        raise SystemExit('Change failed; restored previous configuration')
if args.action == 'list':
    print('\n'.join(c['email'] for c in clients))
else:
    export = BASE / 'clients'
    export.mkdir(mode=0o700, exist_ok=True)
    active = {c['email'] for c in clients}
    for path in export.glob('*.txt'):
        if path.stem not in active and path.name != 'all-users.txt':
            path.unlink()
    links = []
    for client in clients:
        query = urlencode({'encryption': 'none', 'security': 'reality', 'sni': public['sni'], 'fp': 'chrome', 'pbk': public['publicKey'], 'sid': public['shortId'], 'type': 'tcp', 'flow': 'xtls-rprx-vision'})
        link = f"vless://{client['id']}@{public['address']}:{public['port']}?{query}#{quote('Europe-' + client['email'])}"
        (export / (client['email'] + '.txt')).write_text(link + '\n')
        links.append(link)
    (export / 'all-users.txt').write_text('\n'.join(links) + ('\n' if links else ''))
    if clients:
        client_config = {'log': {'loglevel': 'warning'}, 'inbounds': [{'listen': '127.0.0.1', 'port': 10808, 'protocol': 'socks', 'settings': {'auth': 'noauth', 'udp': True}}], 'outbounds': [{'protocol': 'vless', 'settings': {'vnext': [{'address': public['address'], 'port': public['port'], 'users': [{'id': clients[0]['id'], 'encryption': 'none', 'flow': 'xtls-rprx-vision'}]}]}, 'streamSettings': {'network': 'raw', 'security': 'reality', 'realitySettings': {'serverName': public['sni'], 'fingerprint': 'chrome', 'password': public['publicKey'], 'shortId': public['shortId']}}}]}
        (BASE / 'test-client.json').write_text(json.dumps(client_config, indent=2))
    else:
        (BASE / 'test-client.json').unlink(missing_ok=True)
    print(f'Exported {len(clients)} profiles to {export}; keep these private.')
