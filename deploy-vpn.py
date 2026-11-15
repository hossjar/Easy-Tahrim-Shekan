#!/usr/bin/env python3
"""Install an isolated VLESS/REALITY Docker service on a Linux VPS."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import uuid

# Official Xray 26.11.9 image; updates must be deliberate.
IMAGE = 'ghcr.io/xtls/xray-core@sha256:9812e382e229e9ed63fd179bf1a4e3fe244c12ff3ae4fd8128745d79c87575ab'
PROJECT = 'trusted-vpn'
PRIVATE_NETWORKS = [
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8',
    '169.254.0.0/16', '172.16.0.0/12', '192.168.0.0/16',
    '198.18.0.0/15', '224.0.0.0/4', '240.0.0.0/4',
    '::/128', '::1/128', 'fc00::/7', 'fe80::/10', 'ff00::/8',
]


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', required=True, help='VPS public IPv4 address used by clients')
    parser.add_argument('--bind-address', help='Local IPv4 to bind; defaults to --address (use 0.0.0.0 behind NAT)')
    parser.add_argument('--server-name', required=True, help='REALITY target hostname supporting TLS 1.3')
    parser.add_argument('--port', type=int, default=8443)
    parser.add_argument('--users', type=int, default=5)
    parser.add_argument('--directory', type=Path, default=Path('/opt/trusted-vpn'))
    args = parser.parse_args(argv)
    try:
        args.address = str(ipaddress.IPv4Address(args.address))
        args.bind_address = str(ipaddress.IPv4Address(args.bind_address or args.address))
    except ipaddress.AddressValueError:
        parser.error('address and bind-address must be IPv4 addresses')
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    if not 1 <= args.users <= 100:
        parser.error('users must be between 1 and 100')
    hostname = args.server_name
    if len(hostname) > 253 or '.' not in hostname or not all(
        re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
        for label in hostname.split('.')
    ):
        parser.error('server-name must be a valid DNS hostname, without a port or scheme')
    args.directory = args.directory.expanduser().resolve()
    return args


def parse_keys(output):
    fields = dict(line.split(':', 1) for line in output.splitlines() if ':' in line)
    private = fields.get('PrivateKey', '').strip()
    public = fields.get('Password (PublicKey)', fields.get('Password', fields.get('PublicKey', ''))).strip()
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{43}', value) for value in (private, public)):
        raise ValueError('Cannot parse Xray X25519 keys; no configuration was written')
    return private, public


def build_config(args, private_key, short_id):
    blocked = list(dict.fromkeys(PRIVATE_NETWORKS + [f'{args.address}/32', f'{args.bind_address}/32']))
    return {
        'log': {'loglevel': 'warning', 'access': 'none', 'dnsLog': False},
        'dns': {'servers': ['1.1.1.1', '9.9.9.9'], 'queryStrategy': 'UseIPv4'},
        'inbounds': [{
            'tag': 'reality-in', 'listen': '0.0.0.0', 'port': args.port, 'protocol': 'vless',
            'settings': {'clients': [
                {'id': str(uuid.uuid4()), 'email': f'user{i:02d}', 'flow': 'xtls-rprx-vision'}
                for i in range(1, args.users + 1)
            ], 'decryption': 'none'},
            'streamSettings': {'network': 'raw', 'security': 'reality', 'realitySettings': {
                'show': False, 'target': f'{args.server_name}:443', 'xver': 0,
                'serverNames': [args.server_name], 'privateKey': private_key, 'shortIds': [short_id],
                'limitFallbackUpload': {'afterBytes': 1048576, 'bytesPerSec': 131072, 'burstBytesPerSec': 262144},
                'limitFallbackDownload': {'afterBytes': 1048576, 'bytesPerSec': 131072, 'burstBytesPerSec': 262144},
            }},
        }],
        'outbounds': [
            {'tag': 'direct', 'protocol': 'freedom', 'settings': {},
             'streamSettings': {'sockopt': {'domainStrategy': 'UseIPv4'}}},
            {'tag': 'block', 'protocol': 'blackhole'},
        ],
        'routing': {'domainStrategy': 'IPOnDemand', 'rules': [
            {'type': 'field', 'ip': blocked, 'outboundTag': 'block'},
        ]},
    }


def build_compose(args):
    binding = json.dumps(f'{args.bind_address}:{args.port}:{args.port}/tcp')
    return f'''name: {PROJECT}
services:
  xray:
    image: {IMAGE}
    container_name: trusted-vpn-xray
    command: ["run", "-config", "/etc/xray/config.json"]
    restart: unless-stopped
    user: "65532:65532"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    mem_limit: 256m
    cpus: 1.0
    pids_limit: 128
    ports:
      - {binding}
    volumes:
      - ./config:/etc/xray:ro
    logging:
      driver: json-file
      options:
        max-size: "5m"
        max-file: "2"
'''


def container_snapshot():
    ids = run('docker', 'ps', '-aq').split()
    containers = json.loads(run('docker', 'inspect', *ids)) if ids else []
    return {c['Name'].lstrip('/'): {
        'id': c['Id'], 'started': c['State']['StartedAt'],
        'restarts': c['RestartCount'], 'running': c['State']['Running'],
    } for c in containers}


def main(argv=None):
    args = parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SystemExit('Run this installer as root on the Linux VPS.')
    base = args.directory
    if base.exists():
        raise SystemExit(f'Refusing to overwrite {base}; manage an existing installation with vpn-users.py.')
    run('docker', 'compose', 'version')
    baseline = container_snapshot()
    if 'trusted-vpn-xray' in baseline or run('docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={PROJECT}'):
        raise SystemExit('The trusted-vpn container or Compose project already exists; refusing to replace it.')
    with socket.socket() as probe:
        probe.bind((args.bind_address, args.port))
    subprocess.run(['docker', 'pull', IMAGE], check=True)
    private, public = parse_keys(run('docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL', IMAGE, 'x25519'))
    short_id = secrets.token_hex(8)
    config = build_config(args, private, short_id)
    os.umask(0o077)
    base.mkdir(mode=0o700)
    (base / 'config').mkdir()
    (base / 'config').chmod(0o755)
    config_path = base / 'config/config.json'
    config_path.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
    config_path.chmod(0o644)  # Readable inside the mount; host parent is root-only.
    (base / 'public.json').write_text(json.dumps({
        'address': args.address, 'port': args.port, 'sni': args.server_name,
        'publicKey': public, 'shortId': short_id,
    }, indent=2) + '\n', encoding='utf-8')
    (base / 'compose.yaml').write_text(build_compose(args), encoding='utf-8')
    (base / 'container-baseline.json').write_text(json.dumps(baseline, indent=2) + '\n', encoding='utf-8')
    for filename in ['vpn-users.py', 'verify-vps.py']:
        shutil.copyfile(Path(__file__).resolve().with_name(filename), base / filename)
    compose = ['docker', 'compose', '-f', str(base / 'compose.yaml')]
    subprocess.run(compose + ['run', '--rm', '--no-deps', 'xray', 'run', '-test', '-config', '/etc/xray/config.json'], check=True)
    subprocess.run(compose + ['up', '-d'], check=True)
    subprocess.run([sys.executable, str(base / 'vpn-users.py'), 'export'], check=True)
    subprocess.run([sys.executable, str(base / 'verify-vps.py')], check=True)
    print(f'Deployed on TCP {args.port}. Private profiles: {base / "clients"}')


if __name__ == '__main__':
    main()
