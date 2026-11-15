#!/usr/bin/env python3
"""Compare existing containers to the snapshot taken before installation."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    base = args.directory.resolve()
    baseline = json.loads((base / 'container-baseline.json').read_text())
    for name, expected in baseline.items():
        d = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
        actual = {'id': d['Id'], 'started': d['State']['StartedAt'],
                  'restarts': d['RestartCount'], 'running': d['State']['Running']}
        if actual != expected:
            raise SystemExit(f'{name}: state differs from the pre-installation snapshot; investigate before continuing.')
        print(f'{name}: unchanged container ID, start time, restart count and running state')
    d = json.loads(subprocess.check_output(['docker', 'inspect', 'trusted-vpn-xray']))[0]
    if not d['State']['Running'] or d['RestartCount'] != 0:
        raise SystemExit('VPN is stopped or has automatically restarted; inspect its logs.')
    if not d['HostConfig']['ReadonlyRootfs'] or d['Config']['User'] != '65532:65532':
        raise SystemExit('Unexpected VPN filesystem permissions or user.')
    if set(d['NetworkSettings']['Networks']) != {'trusted-vpn_default'}:
        raise SystemExit('VPN is attached to unexpected Docker networks.')
    print('VPN running as non-root, with a read-only root filesystem and a separate network.')
    print('This checks container continuity, not application health or connectivity from Iran.')


if __name__ == '__main__':
    main()
