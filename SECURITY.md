# Security and private deployment data

Never commit generated server configs, REALITY private keys, client UUIDs, connection links, SSH keys, tokens, live server addresses, or private deployment reports. `public.json` is also excluded because it describes a real endpoint. Keep backups encrypted and separate from GitHub.

The root installation directory is mode 0700. The mounted config directory and file are readable by the unprivileged container, while the enclosing host directory prevents ordinary host users from traversing them. Anyone with root or Docker access can still read these files.

The management helper is for a trusted administrator over SSH. No public management API is exposed. Private-network denial uses Xray routing and does not replace host firewall isolation against a compromised process.

If credentials reach Git history, revoke affected users or rotate the REALITY key pair and redistribute profiles as appropriate. Removing a file from the latest commit does not remove it from history or forks. Review the exposure before making a formerly private repository public.

Report security issues using GitHub's private vulnerability reporting if enabled. Otherwise contact the repository owner privately before opening an issue. Do not include live profiles or keys in public issues or logs.
