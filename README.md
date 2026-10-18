# tei_mcp_ops

Deployment assets shared by the MCP servers published on `tei.dh.unibe.ch`. Each
server lives in its own repository; what is here is what spans all of them — the
nginx routing, the tunnel layer that brings each server to a local port on tei,
and the landing pages.

## The fleet

| Server | Repo | Runs on | Port on tei | Endpoint | Landing page | Key |
|--------|------|---------|-------------|----------|--------------|-----|
| Königsfelden | [kf_mcp](https://github.com/thodel/kf_mcp) | idhefix | 8001 | `/mcp/kf/mcp` | `/mcp/kf` | none |
| SSRQ | [ssrq_mcp](https://github.com/thodel/ssrq_mcp) | idhefix | 8002 | `/mcp/ssrq/mcp` | `/mcp/ssrq` | none |
| HLS | [hls_mcp](https://github.com/thodel/hls_mcp) | idhefix | 8004 | `/mcp/hls/mcp` | `/mcp/hls` | none |
| HBLS | [hbls_mcp](https://github.com/thodel/hbls_mcp) | idhefix | 8003 | `/mcp/hbls/mcp` | `/mcp/hbls` | none |
| EOS / HGB Basel | [eos_mcp](https://github.com/thodel/eos_mcp) | idhefix | 8000 | `/mcp/eos/mcp` | `/mcp/eos` | none |
| Musiklexikon der Schweiz | mls_mcp (private) | idhefix | 8015 | `/mcp/mls/mcp` | `/mcp/mls` | none |
| Wikidata pre-1500 | [wikidata_pre1500_mcp](https://github.com/thodel/wikidata_pre1500_mcp) | idhefix | 8011 | `/mcp/wd-pre1500/mcp` | — | none |
| Swiss libraries | docker container `swisslib-mcp` on tei (image `swisslib-mcp:latest`, no repository under `thodel`) | tei | 8005 | `/mcp/swiss-lib/mcp` | — | none |
| ATR operations (starts jobs) | [agentic_historian](https://github.com/thodel/agentic_historian) `mcp_atr` | tei | — | `/mcp/atr/mcp` | — | OAuth |
| ATR results (read-only) | [training-atr-models](https://github.com/thodel/training-atr-models) `atr_results_mcp` | **asteraix** | 8013 | `/mcp/atr-results/mcp` | — | `auth_basic`, user `atr-results` |

The six in the first block are the generated ones: identical nginx blocks,
**mcp 2.0** (`MCPServer`), streamable HTTP, no authentication. The others differ
in one way each and are documented where they differ: the two `include`d snippets
(`mcp-atr.conf`, `mcp-wd-pre1500.conf`, maintained on the host under
`/etc/nginx/snippets/`), the hand-written swiss-lib block after the catch-all,
and the atr-results block, which the generator emits with its `auth_basic` lines
(training-atr-models#214).

**Keys.** Two endpoints are not public: `/history-bot/` and
`/mcp/atr-results/mcp`, each with `auth_basic` and its own file,
`/etc/nginx/.htpasswd-history-bot` and `/etc/nginx/.htpasswd-atr-results`
(`root:www-data`, mode 640). There is no `htpasswd` binary on tei; a line is made
with `printf 'user:%s\n' "$(openssl passwd -apr1 "$SECRET")"`. Rotating a key is
a new line, `install -o root -g www-data -m 640` and `systemctl reload nginx` —
the server behind it is untouched. The atr-results secret is kept outside the
repository (`~dh/.atr-results-key` on tei, `~/.atr-results-key` on the laptop,
both 0600); the client sends it as `Authorization: Basic …`.

## The one rule

**Each server is mounted at its own public path.** `<NAME>_HTTP_PATH` in the server's
`docker-compose.yml` and the nginx `location` must be the same string, so nginx can
`proxy_pass` without rewriting:

```
HLS_HTTP_PATH=/mcp/hls/mcp   ⟷   location /mcp/hls/mcp { proxy_pass http://127.0.0.1:8004; }
```

A mismatch returns a bare plain-text `Not Found` from Starlette. The startup line
prints the path actually served, which is the fastest diagnosis:

```bash
docker logs hls-mcp 2>&1 | grep -i starting | tail -1
# Starting HLS MCP server on 0.0.0.0:8004/mcp/hls/mcp
```

**Do not use the SSE transport behind a sub-path.** Its handshake advertises an
absolute `/messages/` path computed from the app's own mount point, which the client
cannot reach through a prefix. The only proxy-side fix is an nginx `sub_filter` on the
event stream (needing `sub_filter_types text/event-stream` and a cleared
`Accept-Encoding`). Streamable HTTP has one endpoint and no such handshake.

## The tunnel layer

`proxy_pass http://127.0.0.1:<port>` looks local and mostly is not. On most of
those ports an `ssh` process listens, a dh **user unit** that forwards the port
from the box where the server really runs (`ss -tlnp` shows it; `loginctl` has
linger on for dh, so the units survive a logout). Measured 11.10.2026:

| Unit (dh user unit) | Local end on tei | Remote end | Box | Serves |
|---|---|---|---|---|
| `mcp-tunnel-nginx@8000,8001,8002,8003,8004,8015` | `127.0.0.1:%i` | `172.17.0.1:%i` (docker bridge) | idhefix `130.92.59.240` | the six generated servers (8015 = mls, ch-h-bot#541) |
| `mcp-tunnel-nginx@8011` | `127.0.0.1:8011` | `172.17.0.1:8011` | idhefix | Wikidata pre-1500 |
| `mcp-tunnel-asteraix@8013` | `127.0.0.1:8013` | `127.0.0.1:8013` (the unit binds loopback, no docker) | **asteraix** `130.92.59.242` | atr-results |
| `mcp-tunnel@8006,8007,8008,8009` | `172.17.0.1:%i` | `172.17.0.1:%i` | idhefix, **although the unit says "asterAIx"** | nothing routed — see [#1](https://github.com/thodel/tei_mcp_ops/issues/1) |

Not tunnelled: 8005 (the swisslib container on tei) and the ATR operations MCP
(a tei process behind its own snippet).

Two templates, two bind addresses, on purpose: `mcp-tunnel-nginx@` binds
**loopback** because nginx says `127.0.0.1:%i`; `mcp-tunnel@` binds the docker
**bridge** for providers the bot's container reaches directly and nginx never
sees. The same port number on both ends is what lets a provider move boxes
without an nginx change; `ExitOnForwardFailure=yes` makes the unit refuse to
start while the local port is still taken, instead of silently doing nothing.

Each key is restricted on the far box to its port(s):
`permitopen="127.0.0.1:8013"` (or the bridge address) **and `command="/bin/false"`**.
`restrict` alone forbids pty, agent and X11 forwarding, but **not a command** —
the first atr-results key test ran `id` on asteraix until the forced command was
added (training-atr-models#214). The four idhefix keys should be checked for the
same (#1).

Adding a server on another box, in order: the server binds loopback on its port
over there (mounted at its public path) → a new ed25519 key on tei, its public
half in the far box's `authorized_keys` with the restriction above → a template
unit named after the real box, `systemctl --user enable --now <unit>@<port>` →
`curl 127.0.0.1:<port>/<path>` on tei answers → the nginx block → the landing
page, if any.

## Deploying

Order matters: containers first, nginx second. Reloading nginx before a container is
rebuilt leaves the two halves pointing at different paths.

### 1. Servers

```bash
cd ~/<name>_mcp && git pull && docker compose build && docker compose up -d
```

`docker compose up -d` alone reuses the existing image — without `build`, a `git pull`
leaves the old code running.

### 2. nginx

The generated range lives between the `# ── SSRQ MCP` comment and the catch-all
`location / {`, so it is replaced wholesale. **The live file is
`/etc/nginx/sites-enabled/tei.dh.unibe.ch`, a regular file, not a symlink**:
`sites-available/tei.dh.unibe.ch` is a stale copy (last written 01.10.2026,
checked 11.10.2026), and editing it changes nothing nginx serves.

```bash
CONF=/etc/nginx/sites-enabled/tei.dh.unibe.ch; sudo mkdir -p /root/nginx-backups && sudo cp -a "$CONF" /root/nginx-backups/tei.$(date +%Y%m%d-%H%M) && sudo sed -i -e "/SSRQ MCP/r $PWD/nginx/mcp-sections.conf" -e '/SSRQ MCP/,/^    location \/ {/d' "$CONF" && sudo nginx -t && sudo nginx -T | grep -c "location /mcp/[a-z0-9-]*/mcp"
```

Prints `9` when it worked (six generated, atr-results, wd-pre1500 from its
snippet, swiss-lib after the catch-all; the ATR operations snippet matches no
`/mcp/<name>/mcp` line). Then `sudo systemctl reload nginx`.

The command is idempotent: the fragment's first line carries the `SSRQ MCP` anchor the
sed deletes, and its last line restores the `location / {` the range consumes, so
running it twice produces the same file.

What the range holds besides the six generated servers, and therefore what the
generator has to emit or the next deploy silently drops: the two `include`
lines for the snippets, the atr-results block with its `auth_basic` lines, and
the note above `location / {`. `make-sections.sh` emits all of them; on
11.10.2026 its output matched the live range line for line, except that the
hand-inserted atr-results block sat before the hls block and the generator puts
it last — the next deploy moves it, which changes nothing.

Regenerate the fragment after adding a server:

```bash
sh nginx/make-sections.sh > nginx/mcp-sections.conf
```

### 3. Landing pages

```bash
sudo python3 make_landing.py --out /var/www/html
```

Reads `tools/list`, `resources/list` and `corpus_stats` from each live server, so a
page cannot drift from what the server actually exposes. Standard library only.
`--only <name>` for one server. If a server is unreachable it exits non-zero and leaves
the existing pages alone. Static files, so no reload is needed.

Run it again whenever a server's tools change.

## Verifying

```bash
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://tei.dh.unibe.ch/mcp/kf/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

`200` means live. `404` is a path mismatch between the app and the `location`. `405` on
a `/sse` path is expected — SSE endpoints are GET-only.

Note that streamable HTTP is a **session** protocol: a bare `tools/call` answers
`400 Missing session ID`. Call `initialize` first, keep the `Mcp-Session-Id` response
header, and send it on every later request. `make_landing.py` implements exactly that
in about forty lines if you need a reference.

## Connecting a client

```bash
claude mcp add --transport http kf https://tei.dh.unibe.ch/mcp/kf/mcp -s user
```

The name and URL are positional — there is no `--url` flag. `-s user` makes the server
available in every project; the default `local` scope is only the current one.

For Claude Desktop, Cowork or claude.ai: Customize → Connectors → **+** → *Add custom
connector*. Those clients connect **from Anthropic's cloud**, not from your machine, so
the server has to be reachable over the public internet — which these are.

## Gotchas worth remembering

- **nginx backups belong outside `sites-enabled/`.** That directory is globbed, so a
  backup left there is loaded as a second server block: `duplicate default server`.
  It happened again on 11.10.2026: `nginx -t` failed on the backup, the `&&` chain
  stopped before the reload, and the edited file sat unloaded while the old
  configuration kept answering 404 — which looks like a wrong block, not a missed
  reload. Check the nginx master's start time (`ps -o lstart= -p $(cat /run/nginx.pid)`)
  before debugging the block.
- **A server behind nginx answers `421 Misdirected Request` until it knows its
  public host.** The MCP SDK's DNS-rebinding protection allows loopback Hosts only;
  nginx forwards `Host: tei.dh.unibe.ch`. Testing against `127.0.0.1` cannot show
  this. The fix is on the server side (`TransportSecuritySettings` with the public
  host in `allowed_hosts`, protection left on — `agentic_historian/mcp_atr/server.py`
  and `atr_results_mcp --public-host` do it), not a rewritten `Host` header in nginx.
- **`restrict` in `authorized_keys` does not forbid running a command.** A tunnel-only
  key needs `command="/bin/false"` as well; `ssh -N` never runs the forced command,
  so the forward still works.
- **`sed -i` on a symlink replaces the symlink with a regular file.** Use
  `--follow-symlinks`, or edit the file in `sites-available/` directly.
- **`docker compose config` normalises `- KEY=value` list entries into `KEY: value`
  map form.** Read the compose file itself to see its real style; mixing the two gives
  `services.<x>.environment.[n]: unexpected type map[string]interface {}`.
- **Claude.ai and Claude Desktop truncate a tool result at ~150,000 characters.** Index
  resources are capped at 1000 rows across the fleet for that reason.
