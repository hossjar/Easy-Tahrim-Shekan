import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('deploy', ROOT / 'deploy-vpn.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class SetupTests(unittest.TestCase):
    def arguments(self, *extra):
        return deploy.parse_args(['--address', '203.0.113.10', '--server-name', 'target.example.org', *extra])

    def test_configuration_uses_supplied_settings_and_unique_credentials(self):
        args = self.arguments('--port', '9443', '--users', '3', '--bind-address', '192.168.1.2')
        config = deploy.build_config(args, 'A' * 43, '0123456789abcdef')
        inbound = config['inbounds'][0]
        self.assertEqual(inbound['port'], 9443)
        self.assertEqual(inbound['streamSettings']['realitySettings']['target'], 'target.example.org:443')
        users = inbound['settings']['clients']
        self.assertEqual(len({u['id'] for u in users}), 3)
        again = deploy.build_config(args, 'A' * 43, '0123456789abcdef')
        self.assertNotEqual(users[0]['id'], again['inbounds'][0]['settings']['clients'][0]['id'])
        blocked = config['routing']['rules'][0]['ip']
        for network in ['203.0.113.10/32', '192.168.1.2/32', '127.0.0.0/8', '172.16.0.0/12']:
            self.assertIn(network, blocked)
        self.assertIn('"192.168.1.2:9443:9443/tcp"', deploy.build_compose(args))

    def test_invalid_arguments_rejected(self):
        for extra in [('--port', '0'), ('--port', '65536'), ('--users', '0'),
                      ('--address', 'not-an-ip'), ('--server-name', 'https://example.org'),
                      ('--server-name', 'bad\nname.example'), ('--server-name', '-bad.example')]:
            with self.subTest(extra=extra), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.arguments(*extra)

    def test_supported_key_labels_and_invalid_output(self):
        for label in ['PublicKey', 'Password', 'Password (PublicKey)']:
            self.assertEqual(deploy.parse_keys(f'PrivateKey: {"A" * 43}\n{label}: {"B" * 43}'), ('A' * 43, 'B' * 43))
        with self.assertRaises(ValueError):
            deploy.parse_keys('PrivateKey: missing-public-key')

    def test_existing_installation_never_touches_docker(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(deploy.sys, 'platform', 'linux'), \
                patch.object(deploy.os, 'geteuid', return_value=0, create=True), patch.object(deploy, 'run') as run:
            with self.assertRaisesRegex(SystemExit, 'Refusing to overwrite'):
                deploy.main(['--address', '203.0.113.10', '--server-name', 'target.example.org', '--directory', temp])
            run.assert_not_called()


class UserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / 'config').mkdir()
        self.config = self.base / 'config/config.json'
        args = deploy.parse_args(['--address', '203.0.113.10', '--server-name', 'target.example.org', '--users', '1'])
        self.config.write_text(json.dumps(deploy.build_config(args, 'A' * 43, '0123456789abcdef')))
        (self.base / 'public.json').write_text(json.dumps({
            'address': args.address, 'port': args.port, 'sni': args.server_name,
            'publicKey': 'B' * 43, 'shortId': '0123456789abcdef',
        }))
        self.umask = os.umask(0o077)

    def tearDown(self):
        os.umask(self.umask)
        self.temp.cleanup()

    def invoke(self, *args, results=None):
        with patch.object(sys, 'argv', ['vpn-users.py', '--directory', str(self.base), *args]), \
                patch('subprocess.run', side_effect=results, return_value=subprocess.CompletedProcess([], 0)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(ROOT / 'vpn-users.py'), run_name='__main__')

    def test_export_matches_credentials_without_private_key(self):
        self.invoke('export')
        link = (self.base / 'clients/user01.txt').read_text().strip()
        parsed = urlparse(link)
        self.assertEqual(parsed.username, json.loads(self.config.read_text())['inbounds'][0]['settings']['clients'][0]['id'])
        self.assertEqual(parse_qs(parsed.query)['pbk'], ['B' * 43])
        self.assertNotIn('A' * 43, link)

    def test_add_remove_preserves_other_profiles(self):
        self.invoke('export')
        original = (self.base / 'clients/user01.txt').read_text()
        self.invoke('add', 'alice')
        self.assertTrue((self.base / 'clients/alice.txt').exists())
        self.invoke('remove', 'alice')
        self.assertFalse((self.base / 'clients/alice.txt').exists())
        self.assertEqual((self.base / 'clients/user01.txt').read_text(), original)
        self.invoke('remove', 'user01')
        self.assertFalse((self.base / 'test-client.json').exists())
        self.assertEqual((self.base / 'clients/all-users.txt').read_text(), '')

    def test_invalid_names_and_reserved_export_name_rejected(self):
        for name in ['../escape', 'all-users']:
            with self.subTest(name=name), self.assertRaises(SystemExit):
                self.invoke('add', name)

    def test_validation_failure_preserves_active_config(self):
        original = self.config.read_bytes()
        with self.assertRaisesRegex(SystemExit, 'Validation failed'):
            self.invoke('add', 'alice', results=[subprocess.CompletedProcess([], 1)])
        self.assertEqual(self.config.read_bytes(), original)
        self.assertFalse((self.base / 'config/candidate.json').exists())

    def test_restart_failure_restores_previous_config(self):
        original = self.config.read_bytes()
        with self.assertRaisesRegex(SystemExit, 'restored previous'):
            self.invoke('add', 'alice', results=[subprocess.CompletedProcess([], 0),
                        subprocess.CalledProcessError(1, ['docker']), subprocess.CompletedProcess([], 0)])
        self.assertEqual(self.config.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
