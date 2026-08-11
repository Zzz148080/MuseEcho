# Tencent Cloud Lighthouse delivery

These scripts prepare and operate one Linux Lighthouse instance. They are
deliberately local-control-plane tools: they do not create Tencent resources,
change DNS, upload credentials, or claim that a public endpoint exists.

## Preconditions

- A Linux Lighthouse with at least 2 vCPU, 4 GiB RAM, and a 20 GiB deployment
  budget beyond operating-system use.
- Docker Engine plus Docker Compose v2, `curl`, and systemd.
- A DNS name already pointed at the instance, with the provider firewall and
  host firewall allowing only TCP 22, 80, and 443.
- Key-based SSH verified before setting `PasswordAuthentication no` in
  `sshd_config`; retain a tested console-recovery route.
- `/etc/museecho/secrets/audio-kek`, owned `10001:10001`, mode `0400`. The
  optional `/etc/museecho/secrets/provider-key` has the same contract and is
  needed only when provider configuration is enabled. Never pass either value
  to these scripts or put it in a shell history, log, `.env`, or release file.

## Install and check

Run the non-mutating prerequisite gate first:

```bash
sudo bash deploy/tencent-cloud/install.sh --check-only
```

After it passes, install the owned directories, systemd unit, and UFW rules
(when UFW is active):

```bash
sudo bash deploy/tencent-cloud/install.sh
sudoedit /srv/museecho/config/runtime.env
# Set MUSEECHO_DOMAIN=music.example.com (this is not a secret).
```

The installer creates `/srv/museecho/data`, `releases`, and `config` as
`root:10001` `0750`; it creates `/etc/museecho/secrets` with the same
traversal boundary. It refuses to overwrite a systemd file it does not own.
It only adds UFW allow rules for 22/80/443 and otherwise prints the required
Lighthouse security-group action. It never disables unrelated firewall rules.

## Deploy and rollback

Only registry image references with a pinned OCI digest are accepted:

```bash
sudo bash deploy/tencent-cloud/deploy.sh \
  --app-image registry.example/museecho-app@sha256:<64-lowercase-hex> \
  --gateway-image registry.example/museecho-gateway@sha256:<64-lowercase-hex>
```

The script pulls both exact identities, writes an immutable release directory,
atomically switches `/srv/museecho/current`, restarts the owned systemd unit,
and checks `https://$MUSEECHO_DOMAIN/api/health`. A failed health check restores
the previous verified release automatically. To manually select the newest
verified prior release and run the same health gate:

```bash
sudo bash deploy/tencent-cloud/rollback.sh
```

Task 20 recorded image IDs and tar hashes, not a pushed registry digest. A
release operator must publish or otherwise obtain the exact digest-qualified
references before this script can be used; a tag such as `:latest` is rejected.

## Backup and recovery boundary

```bash
sudo bash deploy/tencent-cloud/backup.sh
```

Backups contain the SQLite database and non-secret runtime/release metadata,
with `SHA256SUMS` inside the archive. They intentionally exclude encrypted
audio ciphertext and wrapped per-analysis-key material. Restoring audio needs
a separately protected data backup and the KEK that stays outside the archive;
the archive never copies secret files. Regularly test a restore in an isolated
environment before relying on a backup.

## Public smoke record

Once cloud access, domain/DNS, and SSH authorization are supplied, execute the
commands in [`DEPLOYMENT_EVIDENCE.md`](../../DEPLOYMENT_EVIDENCE.md) in order
and record timestamps, host-independent client results, and rollback evidence.
Do not add a URL or a PASS verdict before those real operations occur.
