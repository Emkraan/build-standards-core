# Phone access setup: runnable procedure

Applies `standards/hermes-api-access.md`. Every command runs from the core clone with
`python3 hermes/phone_access.py` (stdlib only, Python 3.9). No command prints the API key or a
pairing link. Replace the values in angle brackets with your own. Nothing here names a host, an
address or an account.

Exit codes: 0 ok, 1 drift or a failed check, 2 a bad parameter or pin.

## 1. The push plugin source (rule hermes-api-access.6)

The source is data, not code. The `phone-push` entry in `hermes/tools.json` carries `pin` with
`repository`, `path`, `commit` (the full reviewed sha) and `version`. The order of precedence is a
command line parameter, then a pin file, then the registry.

```bash
# Show what would be installed and whether the installed copy matches. Changes nothing, exit 1 on drift.
python3 hermes/phone_access.py plugin --check

# Install the pinned commit, verify it, enable it (never from a branch).
python3 hermes/phone_access.py plugin
```

A consumer overrides the source without editing the core. A consumer whose plugin repository is
private does exactly this and the core never names it:

```bash
cat > <agent home>/phone-push.pin <<'PIN'
repository=<git url you can read>
path=<plugin folder inside it>
commit=<full 40 character reviewed commit>
version=<plugin.yaml version at that commit>
PIN
python3 hermes/phone_access.py plugin --pin-file <agent home>/phone-push.pin
python3 hermes/phone_access.py plugin --pin-file <agent home>/phone-push.pin --check
```

Moving to a new version is a review of the new commit first, then a change of `commit` and
`version` in the pin (by pull request here for the registry, or in the consumer's own pin file).
Run `plugin --check` from the consumer's own scheduled job so drift is an alert. `--no-enable`
skips the `hermes plugins enable` call, for a host without the agent CLI.

## 2. The API key (rule hermes-api-access.2)

```bash
python3 hermes/phone_access.py key
```

Adds the API server flag and a random key to `<agent home>/.env` only when they are missing, sets
mode 0600, and prints the name, the length and a boolean. Run it again at any time, it changes
nothing. A rotation replaces the value in place by hand and invalidates every earlier pairing.
The API server starts at the next gateway restart.

## 3. The private certificate authority and the edge certificate (rule hermes-api-access.3)

```bash
python3 hermes/phone_access.py tls --dir <tls dir> --host <dns name> --ip <lan address>
```

Give every name and address the edge is reached by (repeat `--host` and `--ip`). It creates the
authority and the edge certificate only when missing or when the names change or the certificate
expires within 30 days, keeps the keys at mode 0600, and prints the authority certificate to
install and trust on the phone (and its SHA-256 fingerprint). A client without that certificate
fails closed.

## 4. The TLS edge on the API port (rule hermes-api-access.1)

```bash
python3 hermes/phone_access.py edge --dir <tls dir> --port 9123 --upstream http://127.0.0.1:8642
```

The reference edge terminates TLS and forwards HTTP, streamed responses and WebSocket upgrades to
the loopback API server. It holds no credential, forwards the Authorization header untouched and
refuses an upstream that is not loopback. It binds all interfaces by default, so pass `--bind
<lan address>` to narrow it. Run it under the host's service manager so it restarts, and write that
installer to be idempotent (rule hermes-api-access.9): stage the key only when missing, wait for an
unloading agent to be gone before loading the new one, and exit non-zero when it is not loaded.

What the reference edge does not do: it does not narrow the session list (section 4 of the
standard). A consumer that wants the narrowing runs its own edge or adds the filter in front of this
one. Check the port answers with TLS and refuses a client without the authority:

```bash
curl --cacert <tls dir>/ca.crt https://<dns name>:9123/health
curl https://<dns name>:9123/health   # must fail the certificate check
```

## 5. Restart the gateway and prove the retired bot is gone (rule hermes-api-access.8)

After the bot's config blocks, env keys and job delivery targets are removed, restart the gateway
and run:

```bash
python3 hermes/phone_access.py gateway-check
# or against a specific log
python3 hermes/phone_access.py gateway-check --log <gateway log>
```

It reads the latest gateway start in the log (default `<agent home>/logs/gateway.log`) and exits 0
only when the API server is the one platform connected and the gateway announced one platform. It
exits 1 when any other platform connected and 2 when the log holds no start, in which case restart
the gateway and run it again. Revoking the bot token at the provider is a separate step the log
cannot prove.

## 6. Pair the phone (rule hermes-api-access.5)

```bash
python3 hermes/phone_access.py pair
```

Runs the plugin's own pair command on this host. It shows the one-time link as a QR in the
terminal. Run it at the host console, never over a shared channel, and never paste or log the link.
The console that wraps it (rule hermes-api-access.6) does the same on loopback only and shows the
QR for 60 seconds.

## Order for a new host

1. `key`, 2. `tls`, 3. restart the gateway, 4. `edge` under the service manager, 5. `plugin`,
6. restart the gateway again so the plugin loads, 7. `gateway-check`, 8. `plugin --check`,
9. `pair`.
