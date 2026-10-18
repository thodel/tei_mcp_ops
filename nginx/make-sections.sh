#!/bin/sh
# make-sections.sh — regenerate nginx/mcp-sections.conf.
#
# Every server's block is identical apart from its name and port, so the fragment
# is generated rather than maintained by hand. Generating it also keeps it short
# enough to paste into a terminal, which a 120-line heredoc is not.
#
#   sh nginx/make-sections.sh > nginx/mcp-sections.conf
#
# Two properties the sed in ../README.md depends on:
#   - the first line contains "SSRQ MCP" (the sed's anchor, which it deletes and
#     re-inserts from this file — that is what makes re-running it idempotent)
#   - the last line is "    location / {" (the sed's range ends on that line, so
#     the catch-all has to be restored here)

set -eu

printf '    # ── SSRQ MCP and friends — generated, all six streamable HTTP ──\n'

# Two servers whose blocks differ from the pattern live in snippets, included
# here so the generated range keeps them: the ATR operations MCP (OAuth, four
# blocks, /etc/nginx/snippets/mcp-atr.conf) and the pre-1500 Wikidata persons
# (mcp-tunnel-nginx@8011, /etc/nginx/snippets/mcp-wd-pre1500.conf). The
# snippets are maintained on the host, not in this repository.
printf '    include /etc/nginx/snippets/mcp-atr.conf;\n'
printf '    include /etc/nginx/snippets/mcp-wd-pre1500.conf;\n'
printf '\n'

# mls (Musiklexikon der Schweiz) runs on idhefix and arrives through
# mcp-tunnel-nginx@8015 like the five before it (ch-h-bot#541).
for s in ssrq:8002 eos:8000 kf:8001 hls:8004 hbls:8003 mls:8015; do
    n=${s%%:*}
    p=${s##*:}
    printf '    location /mcp/%s/mcp {\n' "$n"
    printf '        proxy_http_version 1.1;\n'
    printf '        proxy_set_header Connection "";\n'
    printf '        proxy_set_header Host $host;\n'
    printf '        proxy_set_header X-Real-IP $remote_addr;\n'
    printf '        proxy_set_header X-Forwarded-Proto $scheme;\n'
    printf '        proxy_buffering off;\n'
    printf '        proxy_cache off;\n'
    printf '        proxy_read_timeout 3600s;\n'
    printf '        chunked_transfer_encoding on;\n'
    printf '        proxy_pass http://127.0.0.1:%s;\n' "$p"
    printf '        proxy_redirect off;\n'
    printf '    }\n'
    printf '    location /mcp/%s {\n        return 302 /mcp/%s/landing;\n    }\n' "$n" "$n"
    printf '    location /mcp/%s/landing {\n' "$n"
    printf '        alias /var/www/html/%s-landing.html;\n' "$n"
    printf '        default_type text/html;\n    }\n'
done

# The HBLS app also exposes /health as a custom route.
printf '    location = /mcp/hbls/health {\n'
printf '        proxy_http_version 1.1;\n'
printf '        proxy_set_header Host $host;\n'
printf '        proxy_buffering off;\n'
printf '        rewrite ^/mcp/hbls/health$ /health break;\n'
printf '        proxy_pass http://127.0.0.1:8003;\n'
printf '        proxy_redirect off;\n    }\n'

# atr-results: the read-only view of the ATR training programme, served from
# asteraix through mcp-tunnel-asteraix@8013 and behind a key — the one block
# in this range with auth_basic. No landing page: nothing on it is public.
# (training-atr-models#214)
printf '    # atr-results: read-only view of the ATR training programme (UBELIX + asteraix).\n'
printf '    # Upstream is the MCP on asteraix, reached through mcp-tunnel-asteraix@8013\n'
printf '    # (dh user unit) -> 127.0.0.1:8013 here. Mounted at its public path on the\n'
printf '    # upstream (--path /mcp/atr-results/mcp), so proxy_pass carries no URI part.\n'
printf '    # Key: auth_basic, user atr-results (training-atr-models#214, A4).\n'
printf '    location /mcp/atr-results/mcp {\n'
printf '        auth_basic           "atr-results";\n'
printf '        auth_basic_user_file /etc/nginx/.htpasswd-atr-results;\n'
printf '        proxy_http_version 1.1;\n'
printf '        proxy_set_header Connection "";\n'
printf '        proxy_set_header Host $host;\n'
printf '        proxy_set_header X-Real-IP $remote_addr;\n'
printf '        proxy_set_header X-Forwarded-Proto $scheme;\n'
printf '        proxy_buffering off;\n'
printf '        proxy_cache off;\n'
printf '        proxy_read_timeout 3600s;\n'
printf '        chunked_transfer_encoding on;\n'
printf '        proxy_pass http://127.0.0.1:8013;\n'
printf '        proxy_redirect off;\n'
printf '    }\n'

# The live file carries this note above the catch-all; the sed's range ends on
# the `location / {` line, so the note has to be restored from here too.
printf '    # Nothing is served at the root. TEI Publisher answered here until 2026-09-24\n'
printf '    # (adr/0001-headroom.md); proxying to its dead port made every unmatched path\n'
printf '    # answer 502, which reads as "tei is broken" to a monitor and to a person.\n'
printf '    location / {\n'
