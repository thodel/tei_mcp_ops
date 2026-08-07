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

printf '    # ── SSRQ MCP and friends — generated, all five streamable HTTP ──\n'

for s in ssrq:8002 eos:8000 kf:8001 hls:8004 hbls:8003; do
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

printf '    location / {\n'
