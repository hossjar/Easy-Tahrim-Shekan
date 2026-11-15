# Easy VPN

A small Docker setup for **VLESS + REALITY + XTLS Vision**, with private connection links for a few trusted users. Use a compatible client such as Hiddify on Windows or Android.

No web panel, database, subscription service, traffic accounting, or domain registration is required. The installer creates a separate Compose project and network. It does not restart existing containers or edit their configuration, SSH settings, UFW rules, or the Docker daemon configuration.

This repository contains reusable code, not a backup of a live server. Every fresh installation generates new keys and user credentials. Keep existing installation backups privately if you need to preserve working profiles.

## Requirements

- A Linux VPS with a public IPv4 address and working outbound internet access.
- Python 3.10+ and Docker Engine with the Compose plugin, already installed.
- Root access on the VPS and a free TCP port. The default is **8443**, so an existing HTTPS service can keep TCP 443.
- A suitable REALITY target hostname supporting TLS 1.3. Prefer a stable site on the same hosting network where practical; see the [official REALITY guidance](https://xtls.github.io/en/config/transports/reality.html).

The image is pinned to an immutable digest for Xray 26.11.9. Review upstream releases when maintaining your installation; it does not auto-update. One installation per host is supported by the fixed `trusted-vpn` project and container names. The server currently uses IPv4 egress.

## Install

Clone or copy this repository to the VPS. A private repository requires your own GitHub access; alternatively, transfer the three Python scripts over SCP. Do not put a GitHub access token in a command or file in this repository.

```sh
git clone https://github.com/hossjar/easy_vpn.git
cd easy_vpn
python3 deploy-vpn.py --help
```

Check the intended target before installation, substituting its hostname for `TARGET_HOSTNAME`:

```sh
sudo docker run --rm --cap-drop ALL \
  ghcr.io/xtls/xray-core@sha256:9812e382e229e9ed63fd179bf1a4e3fe244c12ff3ae4fd8128745d79c87575ab \
  tls ping TARGET_HOSTNAME
```

Then install. **Replace the example IPv4 and hostname below**; `203.0.113.10` is a documentation address, not a working VPN endpoint. `www.ovhcloud.com` illustrates a target for an OVH-hosted server; select and test a target appropriate to your VPS.

```sh
sudo python3 deploy-vpn.py \
  --address 203.0.113.10 \
  --server-name www.ovhcloud.com \
  --port 8443 \
  --users 5
```

Options:

| Option | Purpose | Default |
| --- | --- | --- |
| `--address` | Public IPv4 clients connect to | Required |
| `--server-name` | REALITY target and client SNI hostname | Required |
| `--port` | Published TCP port | `8443` |
| `--users` | Number of initial profiles, 1–100 | `5` |
| `--bind-address` | Local IPv4 binding; use `0.0.0.0` behind NAT | Same as `--address` |
| `--directory` | New installation directory; parent must exist | `/opt/trusted-vpn` |

The installer refuses an occupied port, existing installation directory, or existing `trusted-vpn` project/container. It snapshots other containers before creating the VPN, validates the Xray config, starts the VPN, exports profiles and checks container continuity. It does not need any particular pre-existing relay service.

**Networking:** Docker publishes the chosen port using its own firewall rules; on typical Docker bridge setups these bypass UFW's ordinary INPUT policy. If your provider has an external firewall, allow the selected TCP port there. NAT deployments also require port forwarding. This script does not change those settings. Private destinations and the supplied host addresses are denied by Xray routing; this is an application routing rule, not a host firewall security boundary. Add other host public addresses to the deny list if applicable.

## Connect on Windows or Android

1. Install [Hiddify App from its official downloads](https://hiddify.com/app/How-to-install-Hiddify-app/), not Hiddify Manager.
2. Retrieve one profile from `/opt/trusted-vpn/clients/user01.txt` through your existing SSH access.
3. Copy the full `vless://` line, add a profile from the clipboard in Hiddify, and connect.
4. On Android, accept the VPN permission. On Windows, run Hiddify as administrator and enable **VPN/TUN mode** for device-wide traffic. System Proxy mode covers only applications honoring the proxy.
5. Initially use global/all-traffic routing. Verify the public IPv4 is your VPS address, then check DNS and IPv6 leaks from the actual device.

For example, from your computer, replacing the SSH port and address:

```sh
scp -P 22 root@203.0.113.10:/opt/trusted-vpn/clients/user01.txt ./user01.local.txt
```

Each link grants VPN access: share one profile privately with each person. One person can use their profile on multiple devices. `all-users.txt` contains everyone's credentials and should stay with the administrator. Client DNS should go through the VPN; an ISP IPv6 address visible during a leak test indicates incomplete client routing.

## Manage users

Run on the VPS:

```sh
sudo python3 /opt/trusted-vpn/vpn-users.py list
sudo python3 /opt/trusted-vpn/vpn-users.py add alice
sudo cat /opt/trusted-vpn/clients/alice.txt
sudo python3 /opt/trusted-vpn/vpn-users.py remove alice
```

Names can contain letters, digits, underscores and hyphens. `all-users` is reserved. Add/remove operations validate a candidate config, then restart only the VPN container; active VPN connections briefly reconnect. Removing a user revokes that UUID without changing other profiles. Run one management command at a time. A failed validation leaves the active configuration unchanged.

Use `export` to regenerate profile files from the current configuration. If running the helper from a checkout instead of the installation directory, pass `--directory /opt/trusted-vpn`.

## Operations and rollback

```sh
sudo docker compose -f /opt/trusted-vpn/compose.yaml ps
sudo docker compose -f /opt/trusted-vpn/compose.yaml logs --tail 30
sudo docker compose -f /opt/trusted-vpn/compose.yaml exec -T xray xray run -test -config /etc/xray/config.json
sudo docker compose -f /opt/trusted-vpn/compose.yaml restart xray
```

The container restarts with Docker. It runs without root or Linux capabilities, with a read-only root filesystem, a separate network, a 256 MiB memory limit, a one-CPU limit and bounded Docker logs. Access logging and usage accounting are disabled; warning/error logs can still contain operational details.

To stop and remove only this project's container and network, retaining all credentials and files:

```sh
sudo docker compose -f /opt/trusted-vpn/compose.yaml down
```

Start it again with `up -d`. Never use system-wide Docker prune to manage this installation.

If installation fails after creating its directory, inspect the error and retained files. The installer deliberately refuses to overwrite them on a retry. Validate the config and finish with `up -d` and the helper's `export` command, or run this project's `down`, privately archive the failed directory, and retry with a new directory. Do not remove a working installation to bypass this check.

Before upgrading, back up `/opt/trusted-vpn` securely outside Git. Review an official Xray release, update the image digest in the installed Compose file, validate using the new image with `docker compose ... run --rm --no-deps xray run -test -config /etc/xray/config.json`, and recreate only this project. Keep the old image digest and config to roll back. Re-test connections from client devices after an upgrade.

## Verify

`sudo python3 /opt/trusted-vpn/verify-vps.py` compares existing containers with the pre-installation snapshot and checks the VPN's runtime isolation. Run it immediately after installation; later intentional restarts of other services will also cause a difference. It does not test application health behind those containers.

Before relying on the VPN, check HTTPS browsing, public exit IP, UDP/DNS, and DNS/IPv6 leaks from actual devices. Test from each intended Iranian ISP. No protocol guarantees connectivity through IP blocking, port blocking or international shutdowns. Xray warns that non-443 ports can increase blocking risk; using 8443 is a coexistence tradeoff, not a claim of optimal camouflage.

Ordinary Cloudflare HTTP proxying cannot carry this raw REALITY transport. A CDN fallback requires a compatible transport and separate configuration.

## Development

No third-party Python packages are required:

```sh
python -m unittest discover -s tests -v
```

CI additionally validates generated Compose and Xray configurations using the pinned image, with synthetic credentials and no connection to a live VPS. Run that check on a Docker-equipped Linux machine with `python tests/check_runtime.py`.

## Publishing safely

The `.gitignore` excludes live configs, client links, private notes, keys, backups, downloaded binaries and test logs. It cannot protect a renamed secret file or files already committed. Review `git status`, `git diff --cached`, and the repository history before publishing. Keep actual addresses and SSH details in ignored local notes. See [SECURITY.md](SECURITY.md) for credential handling and disclosure guidance.

No license has been selected for this repository yet; choose one before offering it for public reuse. Xray and other referenced projects retain their own licenses. This repository does not vendor their binaries.
