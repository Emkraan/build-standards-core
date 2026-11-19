# Hermes API-Only Access and Phone Pairing Standard

Version: 1.1 | Last reviewed: 2026-11-18 | Status: current | Scope: local-ops

This standard covers how a phone app reaches the agent on a host over the gateway's own API server
and nothing else, how that app is paired, how alerts reach the phone while the app is closed, and
how the older surfaces (the dashboard service and a chat-platform bot) are retired. It carries no
host, address, account value of a consumer. Every machine-only value is a parameter in the
consumer's own parameters file. The runnable procedure for the key, the TLS edge, the push plugin,
pairing and the retired bot check is [api-access-setup.md](../hermes/api-access-setup.md).

## 1. One surface, loopback behind a TLS edge

The agent is reached by the desktop app, the command line and the phone app, and the phone app uses
only the gateway's API server. No dashboard service runs, and no second isolated copy of it runs for
the phone. The API server stays bound to loopback. A small TLS edge, signed by the consumer's
private certificate authority, is the only listener on the LAN. It forwards to the API server and
filters (section 4). It holds no credential and makes no access decision, so a client that reaches
the edge still needs the key (section 2).

Why: a dashboard sign-in password is effectively shell access to the host, and each extra surface
needs its own credential, its own restart handling and its own exposure review. One surface is one
thing to secure.

## 2. The key lives in one place and is never shown

Authentication is the API server bearer key, at least 16 characters, generated once into the agent
home env file (mode 0600). That file is the only copy. Status views, logs, tests and chat replies
print the key name, its length and a boolean, never the value. A rotation replaces the value in
place and invalidates every earlier pairing code.

## 3. Transport is HTTPS on a private certificate authority

The edge serves HTTPS with a certificate from the consumer's private authority. Plain HTTP is never
offered on the LAN. The certificate covers only the names and addresses the edge is reached by, and
the pairing code (section 5) offers only those hosts. A client without the authority's certificate
fails closed.

## 4. The edge narrows the session list

The phone app should show the sessions the desktop app shows plus its own chats, not every cron run
and tool run in the session store. The edge narrows the plain session list to that set of sources
by rewriting the query or merging one request per source. A request that names a source or a title
passes through unchanged. A client-sent exclusion list is ignored, so the filter cannot be bypassed
by leaving something out. The set of sources is a parameter.

## 5. The pairing code stays on the host

One pairing code is one link that carries the API address, the key and the connection to use. It is
served only to a client on the loopback interface, by POST, and a LAN client gets 403. The Ops
Center or console shows it as a QR for 60 seconds. It is never rendered as text, logged, cached or
placed in a URL query. The hosts it offers are limited to those the edge certificate covers.

## 6. Alerts while the app is closed use a pinned push plugin

Alerts reach a closed app through a push plugin on the agent. The plugin is installed from a
reviewed commit, never from a branch: the registry (`pin` in the `phone-push` entry of
`hermes/tools.json`) records the repository, the path and the full commit as data a consumer can
override, the installer (`python3 hermes/phone_access.py plugin`) verifies the commit it installed,
and its `--check` mode exits non-zero when the installed plugin differs from the pin. A consumer
whose plugin source is private supplies its own repository, path, commit and version with a pin file
or parameters, and the core never names it. The plugin's native handlers ride the API server, so alert
pairing needs no dashboard. Alert pairing from the console wraps the plugin's own pair, list, test
and remove commands, runs on the loopback interface only, shows the one-time link as a QR for 60
seconds and never logs it. Only the scheduled briefing the owner chose is a push. Every other
scheduled job delivers locally.

The push relay can see that a push happened and when. State that in the page that describes alerts.

## 7. Retiring a dashboard service

1. List every script, card and document that names the dashboard (its port, its service label, its
   idle endpoint) and give each a gateway-only replacement in one table before changing anything.
2. Land the replacements and deploy them. A restart tool that relied on the dashboard's idle proof
   now reads the gateway's health twice, restarts through the draining restart command, checks the
   session store for work that is mid-turn, and treats a desktop-app backend as interactive work it
   never restarts or kills. Say plainly what the replacement proves less than the dashboard did.
3. Stop the service last, with the desktop app closed, because the desktop app only starts its own
   backend when it finds none running. Keep the service definition in place (or a copy beside it)
   for one quiet day, then remove it in a follow-up change.
4. Confirm the port is closed, the gateway and the edge answer, and the desktop app has started its
   own backend.

## 8. Retiring a chat-platform bot

Remove its blocks from the agent config and its keys from the env file (including commented-out
old values), take it out of every scheduled job's delivery target, restart the gateway, and check
the gateway log shows only the API server as a connected platform. The check is
`python3 hermes/phone_access.py gateway-check`: it reads the latest gateway start in the log and
exits non-zero when any other platform connected or the gateway announced more than one. Keep a backup of the removed
config in a scratch folder and delete it once the rollback window passes. Revoke the bot token at
the provider, because removing it from the host does not invalidate it. Replace any health check
that read the bot's authorization with a check of the API server's exposure: key length, loopback
bind and no allow-all flags.

## 9. The edge installer is idempotent

The installer for the edge and its service definition can be run again at any time. It stages the
key only when missing, merges any local override file instead of replacing it, removes the older
service definitions if they exist, waits until an unloading agent has gone before it bootstraps the
new one, and exits non-zero when the agent is not loaded at the end. A test of the installer covers
a second run.

## 10. Design assumption: the phone can reach the host

The phone is always on a network that can reach the host. This standard is designed for that case
and verifies nothing about a phone that is not. The pairing code is only issued for hosts the edge
certificate covers (section 3), so a phone away from the host's network needs its own route to the
edge. Providing that route is the consumer's choice, and nothing here builds or plans for it.
