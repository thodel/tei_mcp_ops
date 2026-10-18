#!/usr/bin/env python3
"""
make_landing.py — regenerate the MCP landing pages from the live servers.

The tool tables, resource lists and corpus counts are read from each server over
MCP, so a page cannot drift from what the server actually exposes. Run it again
after changing any server's tools:

    python3 make_landing.py --out /var/www/html
    python3 make_landing.py --out /var/www/html --only kf

Standard library only — no MCP client library needed. Requires Python 3.8+.
"""
import argparse, html, json, sys, urllib.request
from pathlib import Path

BASE = "https://tei.dh.unibe.ch"

# name → (heading, tagline, project URL, project label, GitHub repo)
SERVERS = {
    "kf": ("Königsfelden MCP Server",
           "Kloster und Hofmeisterei Königsfelden — 1300–1658",
           "https://koenigsfelden.sources-online.org/",
           "koenigsfelden.sources-online.org",
           "https://github.com/thodel/kf_mcp"),
    "ssrq": ("SSRQ MCP Server",
             "Sammlung Schweizerischer Rechtsquellen — Mittelalter bis 1798",
             "https://ssrq-sds-fds.ch/",
             "ssrq-sds-fds.ch",
             "https://github.com/thodel/ssrq_mcp"),
    "hls": ("HLS MCP Server",
            "Historisches Lexikon der Schweiz",
            "https://hls-dhs-dss.ch/",
            "hls-dhs-dss.ch",
            "https://github.com/thodel/hls_mcp"),
    "hbls": ("HBLS MCP Server",
             "Historisch-Biographisches Lexikon der Schweiz — 1921–1934",
             "https://www.digibern.ch/katalog/historisch-biographisches-lexikon-der-schweiz",
             "digibern.ch",
             "https://github.com/thodel/hbls_mcp"),
    "eos": ("EOS MCP Server",
            "Historisches Grundbuch Basel — ca. 1400–1700",
            "https://github.com/thodel/eos_persons",
            "github.com/thodel/eos_persons",
            "https://github.com/thodel/eos_mcp"),
    # mls_mcp is a private repository: no GitHub link on a public page.
    "mls": ("MLS MCP Server",
            "Musiklexikon der Schweiz — Lexika von 1874 bis heute",
            "https://repository.dasch.swiss/dpe/projects/0807",
            "repository.dasch.swiss (DaSCH 0807)",
            None),
}

PROTOCOL = "2025-06-18"


# ── Minimal streamable-HTTP MCP client ────────────────────────────────────────

def _post(url, payload, session=None):
    """One JSON-RPC POST. Returns (parsed message or None, response headers).

    The server answers with an SSE frame (`event: message` / `data: {...}`), so the
    JSON has to be pulled out of the data line; a notification gets 202 and no body.
    """
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", "replace")
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            return json.loads(line[5:].strip()), hdrs
    return (json.loads(raw) if raw.strip() else None), hdrs


class Client:
    """Streamable HTTP needs a session: initialize first, then send the id on every
    later request. A bare tools/call answers 400 'Missing session ID'."""

    def __init__(self, url):
        self.url = url
        msg, hdrs = _post(url, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                       "clientInfo": {"name": "make_landing", "version": "1"}},
        })
        self.session = hdrs.get("mcp-session-id")
        self.info = (msg or {}).get("result", {}).get("serverInfo", {})
        self._id = 1
        _post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, self.session)

    def call(self, method, params=None):
        self._id += 1
        msg, _ = _post(self.url, {"jsonrpc": "2.0", "id": self._id, "method": method,
                                  "params": params or {}}, self.session)
        return (msg or {}).get("result", {})


# ── Rendering ─────────────────────────────────────────────────────────────────

def arg_summary(schema):
    """`query, limit?` — required arguments first, optional ones marked with ?."""
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    if not props:
        return "—"
    names = [p for p in props if p in required] + [p for p in props if p not in required]
    return ", ".join(n if n in required else f"{n}?" for n in names)


def stat_tiles(stats):
    """Count fields, largest first, with the n_ prefix turned into a label."""
    ints = [(k, v) for k, v in (stats or {}).items()
            if isinstance(v, int) and not isinstance(v, bool) and k.startswith("n_")]
    ints.sort(key=lambda kv: -kv[1])
    out = []
    for key, val in ints[:6]:
        label = key[2:].replace("_", " ")
        out.append('      <div class="stat">\n'
                   f'        <span class="val" data-stat="{html.escape(key)}">{val:,}</span>\n'
                   f'        <span class="lbl">{html.escape(label)}</span>\n'
                   '      </div>')
    return "\n".join(out) or '      <div class="stat"><span class="val">—</span></div>'


def render(name, client, tools, resources, templates, stats):
    heading, tagline, proj_url, proj_label, github = SERVERS[name]
    endpoint = f"{BASE}/mcp/{name}/mcp"
    e = html.escape

    rows = "\n".join(
        f'        <tr><td class="tool-name">{e(t["name"])}</td>'
        f'<td class="tool-desc">{e((t.get("description") or "").strip().split(chr(10))[0])}</td>'
        f'<td class="tool-args">{e(arg_summary(t.get("inputSchema") or t.get("input_schema")))}</td></tr>'
        for t in sorted(tools, key=lambda t: t["name"]))

    res_items = [(r.get("uri"), r.get("description") or r.get("name") or "") for r in resources]
    res_items += [(t.get("uriTemplate") or t.get("uri_template"),
                   t.get("description") or t.get("name") or "") for t in templates]
    res_html = "\n".join(
        f'      <span class="resource-uri">{e(str(uri))}</span>\n'
        f'      <span style="font-size:0.82rem; color:var(--muted); padding:0.1rem 0.3rem;">'
        f'{e(desc.strip().split(chr(10))[0])}</span>'
        for uri, desc in res_items if uri)

    year = ""
    if stats.get("year_min") and stats.get("year_max"):
        year = f'{stats["year_min"]} – {stats["year_max"]}'

    version = client.info.get("version") or ""
    return TEMPLATE.format(
        name=e(name), heading=e(heading), tagline=e(tagline), endpoint=e(endpoint),
        proj_url=e(proj_url), proj_label=e(proj_label), github_link=(f'<a href="{e(github)}">GitHub</a>' if github else ''),
        stats=stat_tiles(stats), year=e(year), rows=rows,
        resources=res_html or '      <span class="resource-uri">—</span>',
        server_name=e(client.info.get("name") or name), version=e(version),
        n_tools=len(tools), base=e(BASE), protocol=PROTOCOL,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{heading}</title>
  <style>
    :root {{
      --bg:       #f7f5f0;
      --surface:  #ffffff;
      --border:   #d8d0c4;
      --accent:   #7a3b1e;
      --accent2:  #c05d1a;
      --text:     #2a2018;
      --muted:    #7a6e63;
      --code-bg:  #ede9e1;
      --tag-bg:   #e8e0d4;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
      background: var(--bg); color: var(--text); line-height: 1.6; min-height: 100vh;
    }}
    a {{ color: var(--accent2); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    header {{
      background: var(--accent); color: #fff; padding: 1.75rem 2rem;
      display: flex; align-items: baseline; gap: 1.5rem;
    }}
    header h1 {{ font-size: 1.35rem; font-weight: 600; }}
    .alpha-badge {{
      font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; background: var(--accent2); color: #fff;
      padding: 0.15em 0.6em; border-radius: 3px; vertical-align: middle;
    }}
    header .tagline {{ font-size: 0.9rem; opacity: 0.82; }}
    main {{
      max-width: 900px; margin: 0 auto; padding: 2.5rem 2rem 4rem;
      display: grid; grid-template-columns: 1fr 1fr; gap: 1.75rem;
    }}
    .card {{
      background: var(--surface); border: 1px solid var(--border);
      border-radius: 6px; padding: 1.5rem;
    }}
    .card.full {{ grid-column: 1 / -1; }}
    .card h2 {{
      font-size: 0.75rem; font-weight: 700; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--muted); margin-bottom: 1rem;
      border-bottom: 1px solid var(--border); padding-bottom: 0.5rem;
    }}
    .endpoint-url {{
      font-family: 'Courier New', monospace; font-size: 0.92rem;
      background: var(--code-bg); border: 1px solid var(--border);
      border-radius: 4px; padding: 0.75rem 1rem; margin-bottom: 0.75rem;
      word-break: break-all; user-select: all;
    }}
    .copy-btn {{
      display: inline-block; font-size: 0.78rem; font-weight: 600;
      background: var(--accent); color: #fff; border: none;
      border-radius: 3px; padding: 0.3em 0.8em; cursor: pointer;
      transition: background 0.15s;
    }}
    .copy-btn:hover {{ background: var(--accent2); }}
    .copy-hint {{ font-size: 0.8rem; color: var(--muted); margin-top: 0.4rem; }}
    .stats-grid {{
      display: grid; grid-template-columns: repeat(3, 1fr);
      gap: 0.75rem; margin-bottom: 1rem;
    }}
    .stat {{ background: var(--tag-bg); border-radius: 4px; padding: 0.65rem 0.75rem; text-align: center; }}
    .stat .val {{ display: block; font-size: 1.35rem; font-weight: 700; color: var(--accent); line-height: 1.1; }}
    .stat .lbl {{ display: block; font-size: 0.72rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
    .stats-footer {{ font-size: 0.8rem; color: var(--muted); text-align: right; }}
    table.tools {{ width: 100%; border-collapse: collapse; font-size: 0.875rem; }}
    table.tools th {{ text-align: left; font-size: 0.7rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); padding: 0.3rem 0.5rem; border-bottom: 1px solid var(--border); }}
    table.tools td {{ padding: 0.45rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }}
    table.tools tr:last-child td {{ border-bottom: none; }}
    .tool-name {{ font-family: 'Courier New', monospace; font-size: 0.82rem; color: var(--accent); font-weight: 600; white-space: nowrap; }}
    .tool-desc {{ color: var(--text); }}
    .tool-args {{ font-family: 'Courier New', monospace; font-size: 0.75rem; color: var(--muted); white-space: nowrap; }}
    .resource-list {{ display: flex; flex-direction: column; gap: 0.4rem; }}
    .resource-uri {{ font-family: 'Courier New', monospace; font-size: 0.8rem; background: var(--code-bg); border: 1px solid var(--border); border-radius: 3px; padding: 0.3rem 0.6rem; color: var(--accent); }}
    pre.example {{ background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; padding: 1rem; font-family: 'Courier New', monospace; font-size: 0.8rem; white-space: pre-wrap; word-break: break-word; overflow-x: auto; }}
    footer {{ max-width: 900px; margin: 0 auto 3rem; padding: 0 2rem; display: flex; gap: 1.5rem; flex-wrap: wrap; }}
    footer a {{ font-size: 0.85rem; color: var(--muted); display: flex; align-items: center; gap: 0.35rem; }}
    footer a:hover {{ color: var(--accent2); text-decoration: none; }}
    @media (max-width: 620px) {{
      main {{ grid-template-columns: 1fr; }}
      header {{ flex-direction: column; gap: 0.3rem; }}
    }}
  </style>
</head>
<body>

<header>
  <h1>{heading} <span class="alpha-badge">Alpha</span></h1>
  <span class="tagline">{tagline}</span>
</header>

<main>

  <div class="card full" style="background: var(--accent); border-color: var(--accent2);">
    <p style="font-size: 0.85rem; color: rgba(255,255,255,0.85); margin-bottom: 0.5rem;">{tagline}</p>
    <h2 style="border: none; color: #fff; font-size: 1rem; margin-bottom: 0.5rem;">
      <a href="{proj_url}" style="color: #fff;" target="_blank" rel="noopener">Project Website ↗</a>
    </h2>
    <p style="font-size: 0.8rem; color: rgba(255,255,255,0.65);">{proj_label}</p>
  </div>

  <div class="card">
    <h2>Endpoint</h2>
    <div class="endpoint-url" id="ep-url">{endpoint}</div>
    <button class="copy-btn" onclick="copyUrl()">Copy URL</button>
    <p class="copy-hint">Streamable HTTP · MCP 2.0 · {n_tools} tools · no authentication</p>
  </div>

  <div class="card">
    <h2>Corpus</h2>
    <div class="stats-grid">
{stats}
    </div>
    <p class="stats-footer" id="year-range">{year}</p>
  </div>

  <div class="card full">
    <h2>Add to a client</h2>
    <p class="copy-hint" style="margin-top:0; margin-bottom:0.6rem;">Claude Code — the name and URL are positional:</p>
    <pre class="example">claude mcp add --transport http {name} {endpoint} -s user</pre>
    <p class="copy-hint">Claude Desktop, Cowork or claude.ai: Customize → Connectors → + → Add custom connector, and paste the URL above. Those clients connect from Anthropic's cloud rather than from your machine.</p>
  </div>

  <div class="card full">
    <h2>Available tools</h2>
    <table class="tools">
      <thead>
        <tr><th>Tool</th><th>Description</th><th>Arguments</th></tr>
      </thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>

  <div class="card full">
    <h2>Resources</h2>
    <div class="resource-list">
{resources}
    </div>
  </div>

</main>

<footer>
  <a href="{proj_url}">Project Website ↗</a>
  <a href="{base}">tei.dh.unibe.ch</a>
  {github_link}
  <span style="font-size:0.85rem; color:var(--muted);">{server_name} v{version}</span>
</footer>

<script>
  const MCP_ENDPOINT = '{endpoint}';

  function copyUrl() {{
    navigator.clipboard.writeText(document.getElementById('ep-url').textContent.trim())
      .then(() => {{
        const btn = document.querySelector('.copy-btn');
        btn.textContent = 'Copied!';
        setTimeout(() => btn.textContent = 'Copy URL', 1500);
      }});
  }}

  // Refresh the counts from the live server. Streamable HTTP is a session
  // protocol: initialize first and send the returned id on every later request,
  // or the server answers 400 "Missing session ID". The numbers above are baked
  // in at build time, so this only ever improves on them.
  async function rpc(method, params, id, session) {{
    const headers = {{ 'Content-Type': 'application/json',
                      'Accept': 'application/json, text/event-stream' }};
    if (session) headers['Mcp-Session-Id'] = session;
    const res = await fetch(MCP_ENDPOINT, {{
      method: 'POST', headers,
      body: JSON.stringify(id ? {{ jsonrpc: '2.0', id, method, params }}
                              : {{ jsonrpc: '2.0', method, params }})
    }});
    const sid = res.headers.get('Mcp-Session-Id') || session;
    const text = await res.text();
    for (const line of text.split(/[\\r\\n]+/)) {{
      const t = line.trim();
      if (t.startsWith('data:')) return [JSON.parse(t.slice(5).trim()), sid];
    }}
    return [text.trim() ? JSON.parse(text) : null, sid];
  }}

  async function loadStats() {{
    try {{
      const [, sid] = await rpc('initialize', {{
        protocolVersion: '{protocol}', capabilities: {{}},
        clientInfo: {{ name: 'landing', version: '1' }}
      }}, 1, null);
      await rpc('notifications/initialized', {{}}, null, sid);
      const [msg] = await rpc('tools/call',
        {{ name: 'corpus_stats', arguments: {{}} }}, 2, sid);
      const payload = msg?.result?.structuredContent?.result
                   ?? msg?.result?.structured_content?.result
                   ?? JSON.parse(msg?.result?.content?.[0]?.text ?? 'null');
      if (!payload) return;
      document.querySelectorAll('[data-stat]').forEach(el => {{
        const v = payload[el.dataset.stat];
        if (typeof v === 'number') el.textContent = v.toLocaleString();
      }});
      if (payload.year_min && payload.year_max) {{
        document.getElementById('year-range').textContent =
          payload.year_min + ' – ' + payload.year_max;
      }}
    }} catch (e) {{ /* keep the values baked in at build time */ }}
  }}

  loadStats();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Regenerate the MCP landing pages")
    ap.add_argument("--out", default=".", help="Output directory (e.g. /var/www/html)")
    ap.add_argument("--only", help="Regenerate a single server by name")
    ap.add_argument("--base", default=BASE, help="Public base URL")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = [args.only] if args.only else list(SERVERS)
    failed = []

    for name in names:
        if name not in SERVERS:
            sys.exit(f"unknown server {name!r}; known: {', '.join(SERVERS)}")
        url = f"{args.base}/mcp/{name}/mcp"
        try:
            client = Client(url)
            tools = client.call("tools/list").get("tools", [])
            resources = client.call("resources/list").get("resources", [])
            templates = client.call("resources/templates/list").get("resourceTemplates", [])
            stats = {}
            if any(t["name"] == "corpus_stats" for t in tools):
                res = client.call("tools/call", {"name": "corpus_stats", "arguments": {}})
                sc = res.get("structuredContent") or res.get("structured_content") or {}
                stats = sc.get("result", sc) or json.loads(res["content"][0]["text"])
            page = render(name, client, tools, resources, templates, stats)
            path = out / f"{name}-landing.html"
            path.write_text(page, encoding="utf-8")
            print(f"  {name:5} {len(tools)} tools, {len(resources) + len(templates)} resources "
                  f"→ {path}")
        except Exception as exc:
            failed.append(name)
            print(f"  {name:5} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    if failed:
        sys.exit(f"\n{len(failed)} server(s) failed: {', '.join(failed)} — pages left unchanged")


if __name__ == "__main__":
    main()
