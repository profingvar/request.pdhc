# Upgrade procedure — request.pdhc

How to ship a new release of request.pdhc to miserver without breaking sibling services or losing data.

## 0) Pre-flight

Before any upgrade:

- [ ] All tests green locally: `cd gateway && pytest -q`
- [ ] `progress.md` updated with what's in the release
- [ ] `changed_files.md` lists every touched file (Rule 17)
- [ ] Today's DB backup exists at `~/backups/<YYYY-MM-DD>` on miserver
- [ ] No alembic migration with `down_revision = None` (would clobber the chain)
- [ ] You've reviewed any new config in `.env.example` and updated production `.env` accordingly

## 1) Pack

On dev Mac:

```bash
cd ~/T7_sidewinder/request.pdhc
./pack_deploy.sh                # creates request_pdhc_deploy_<timestamp>.tar.gz
```

Excludes: venv, __pycache__, .git, results/, logs/, .env (secrets).

## 2) Transfer

```bash
scp request_pdhc_deploy_<timestamp>.tar.gz miserver@192.168.1.154:~
```

## 3) Apply on miserver

SSH in. Use the release-symlink layout (see CLAUDE.md §7):

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
cd /usr/local/www/request.pdhc/releases
mkdir -p $TS && cd $TS
tar xzf ~/request_pdhc_deploy_<timestamp>.tar.gz
ln -sf releases/$TS ../current
```

The `current` symlink is what `start.sh` and the reverse-proxy reference. Rollback = `ln -sfn releases/<old> current`.

**Important**: rebuild the Python venv inside the new release directory — never copy a venv across releases (shebangs are absolute paths into the OLD release; pruning the old release breaks the new one).

```bash
rm -rf gateway/venv
/opt/homebrew/opt/python@3.14/bin/python3.14 -m venv gateway/venv
gateway/venv/bin/pip install -r gateway/requirements.txt
```

## 4) Migrations

```bash
cd /usr/local/www/request.pdhc/current/gateway
source venv/bin/activate
flask db upgrade
deactivate
```

If `flask db upgrade` fails:
- Reads its head revision from `alembic_version` in the DB. If migrations have diverged (server has rev `X`, your tarball expects `Y` with `Y` not in the chain), rollback before retry.
- Common cause: forgot to commit a new migration locally.

## 5) Start

```bash
cd /usr/local/www/request.pdhc/current
./safe_restart.sh
```

Verify:

```bash
curl -sS https://request.pdhc.se/api/health
# expected: 200 with {"status":"ok","database":"connected"}
```

## 6) Smoke test the new behaviour

Don't declare success on `/api/health` alone — actually exercise whatever the release changed:

- New endpoint? `curl` it with a real token.
- New field on an existing model? Read a known record and confirm the field is present.
- Migration? Spot-check one or two affected rows.
- New role guard? Try with an unauthorised user; should get 403.

## 7) Roll back if needed

If the smoke test fails:

```bash
cd /usr/local/www/request.pdhc
ls -t releases/ | head -3              # find the previous release
ln -sfn releases/<previous-release> current
cd current && ./safe_restart.sh
```

DB migrations don't auto-rollback. If the new release ran a forward migration, you'll need to run `flask db downgrade <previous-revision>` from the **old** release's venv (which still has the migration files) **before** restarting.

## 8) Clean up

After a release has been stable for 48h:

- Delete release dirs older than 30 days: `find releases -maxdepth 1 -mtime +30 -exec rm -rf {} +`
- Keep the most recent 2 releases regardless of age (rollback targets).
- Update `~/T7_sidewinder/backups/` retention if needed.

## 9) Notify

- If the release affects API surface, post to the integrations Slack channel.
- If it affects partner-facing endpoints, email the partner contacts named in `wire_provider.py providers.yaml`.
- If it includes a new role or scope, update `admin-manual.md`.

## 10) Post-deploy bookkeeping

Append an entry to `changed_files.md` with the timestamp, release tag, and anything operator-only that needed to be done on the server (e.g. ALTER USER, manual purge). Update `progress.md` with the test results.
