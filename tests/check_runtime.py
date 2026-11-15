"""Validate generated configs without starting a VPN or changing a live server."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy', root / 'deploy-vpn.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--xray', type=Path, help='Use a local Xray binary instead of Docker for schema validation')
args = parser.parse_args()
settings = deploy.parse_args(['--address', '203.0.113.10', '--server-name', 'target.example.org'])
with tempfile.TemporaryDirectory(prefix='easy-vpn-check-') as temp:
    base = Path(temp)
    compose = base / 'compose.yaml'
    compose.write_text(deploy.build_compose(settings), encoding='utf-8')
    subprocess.run(['docker', 'compose', '-f', str(compose), 'config', '--quiet'], check=True)
    if args.xray:
        command = [str(args.xray.resolve())]
    else:
        subprocess.run(['docker', 'pull', deploy.IMAGE], check=True)
        command = ['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
                   '--read-only', '--user', '65532:65532', '-v', f'{base}:/check:ro', deploy.IMAGE]
    private, _ = deploy.parse_keys(subprocess.check_output(command + ['x25519'], text=True))
    config = base / 'config.json'
    config.write_text(json.dumps(deploy.build_config(settings, private, '0123456789abcdef')), encoding='utf-8')
    config.chmod(0o644)
    # Docker mounts the temp directory; its unprivileged user must be able to traverse it.
    base.chmod(0o755)
    subprocess.run(command + ['run', '-test', '-config', str(config) if args.xray else '/check/config.json'], check=True)
print('Generated Compose and Xray configurations validated; no service started.')
