# tei_mcp_ops

Deployment assets shared by the five MCP servers on `tei.dh.unibe.ch`. Each server
lives in its own repository; what is here is what spans all of them — the nginx
routing and the landing pages.

## The fleet

| Server | Repo | Port | Endpoint | Landing page |
|--------|------|------|----------|--------------|
| Königsfelden | [kf_mcp](https://github.com/thodel/kf_mcp) | 8001 | `/mcp/kf/mcp` | `/mcp/kf` |
| SSRQ | [ssrq_mcp](https://github.com/thodel/ssrq_mcp) | 8002 | `/mcp/ssrq/mcp` | `/mcp/ssrq` |
| HLS | [hls_mcp](https://github.com/thodel/hls_mcp) | 8004 | `/mcp/hls/mcp` | `/mcp/hls` |
| HBLS | [hbls_mcp](https://github.com/thodel/hbls_mcp) | 8003 | `/mcp/hbls/mcp` | `/mcp/hbls` |
| EOS / HGB Basel | [eos_mcp](https://github.com/thodel/eos_mcp) | 8000 | `/mcp/eos/mcp` | `/mcp/eos` |

All five run **mcp 2.0** (`MCPServer`) with the **streamable HTTP** transport. None
has authentication.

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

All `/mcp/*` blocks live between a `# ── SSRQ MCP` comment and the catch-all
`location / {`, so they are replaced wholesale:

```bash
CONF=/etc/nginx/sites-available/tei.dh.unibe.ch; sudo cp -a "$CONF" /root/nginx-backups/tei.$(date +%Y%m%d-%H%M) && sudo sed -i --follow-symlinks -e "/SSRQ MCP/r $PWD/nginx/mcp-sections.conf" -e '/SSRQ MCP/,/^    location \/ {/d' "$CONF" && sudo nginx -t && sudo nginx -T | grep -c "location /mcp/[a-z]*/mcp"
```

Prints `5` when it worked. Then `sudo systemctl reload nginx`.

The command is idempotent: the fragment's first line carries the `SSRQ MCP` anchor the
sed deletes, and its last line restores the `location / {` the range consumes, so
running it twice produces the same file.

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
- **`sed -i` on a symlink replaces the symlink with a regular file.** Use
  `--follow-symlinks`, or edit the file in `sites-available/` directly.
- **`docker compose config` normalises `- KEY=value` list entries into `KEY: value`
  map form.** Read the compose file itself to see its real style; mixing the two gives
  `services.<x>.environment.[n]: unexpected type map[string]interface {}`.
- **Claude.ai and Claude Desktop truncate a tool result at ~150,000 characters.** Index
  resources are capped at 1000 rows across the fleet for that reason.
