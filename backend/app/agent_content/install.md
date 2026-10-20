# Connect Easy Painter to your agent

Service: `{{MCP_URL}}` — remote Streamable HTTP with OAuth authorization-code + PKCE S256.

1. Add the service in your MCP client. Installation does not grant access.
2. Open the browser authorization flow, sign into Easy Painter, review the client name and callback address, and choose scopes, per-image and daily budgets, and expiry.
3. Test `list_models` and `get_balance`. These checks are free. Do not generate an image merely to test connection unless the user requested it.
4. Optionally download the portable Skill: [easy-painter-skill.zip]({{ORIGIN}}/mcp/easy-painter-skill.zip). Inspect `easy-painter/SKILL.md`, then install it into the user's chosen skill directory. Do not overwrite an existing skill or alter unrelated configuration. Raw source: [SKILL.md]({{ORIGIN}}/mcp/skill/SKILL.md).

## Codex CLI

```bash
codex mcp add easy-painter --url '{{MCP_URL}}'
codex mcp login easy-painter --oauth-client-registration dcr
```

Use a current CLI with OAuth/DCR support. In the desktop/IDE MCP settings, adding the URL and authenticating is an alternative. Official setup: https://developers.openai.com/codex/mcp/

## Claude Code

```bash
claude mcp add --transport http easy-painter '{{MCP_URL}}'
```

Then use `/mcp` to authenticate. For Claude web/desktop use a custom remote connector if enabled for your account/workspace.

## DeepSeek Harness (dsh)

For dsh's MCP plugin without built-in OAuth, save this overlay as `easy-painter.yml`:

```yaml
- insert:
  - id: mcp-easy-painter
    name: '@deepseek-ai/dsh-mcp-client'
    config:
      serverName: easy_painter
      transport: stdio
      command: npx
      args: ['-y', 'mcp-remote@0.15.1', '{{MCP_URL}}', '--host', '127.0.0.1', '--transport', 'http-only']
      failOnStartupError: true
```

Run `dsh --profile headless --patch ./easy-painter.yml "List Easy Painter models and balance"`, or add the overlay to your usual profile. This requires Node.js/npm and a working dsh model login. The [mcp-remote bridge](https://github.com/punkpeye/mcp-remote) opens the browser for authorization and manages credential refresh locally; no token needs to be pasted into the overlay. Keep your existing profile configuration. If the shell resolves an older CLI than the desktop app, use the desktop app's installed CLI path.

## Cursor and other clients

Open [the connection page]({{ORIGIN}}/mcp) for the Cursor install link. Or merge this into the client's MCP configuration without replacing other entries:

```json
{"mcpServers":{"easy-painter":{"url":"{{MCP_URL}}"}}}
```

Clients must support remote HTTP MCP and OAuth; cloud-hosted clients cannot reach a local loopback endpoint. This server supports dynamic public-client registration (DCR), not URL-based client metadata fetching (CIMD).

## Tools and charges

- Free: `list_models`, `get_balance`, `estimate_cost(model,size,editing)`, `get_job(job_id)`.
- Paid: `generate_image(prompt,model,size,request_id,max_cost)` and `edit_image(source_job_id,prompt,model,size,request_id,max_cost)`; one image per request.
- Prices depend on enabled models and user-group pricing. Never hardcode prices. Queued/processing reservations count toward daily budget; final failures refund and release that budget. The day resets in Asia/Shanghai.
- Persist exact arguments and request_id before paid submission. For unknown results replay the identical call; once a job ID is returned, poll get_job. Do not create another paid request just because generation is slow.
- The connection page can lower/increase limits or revoke a grant. Revocation blocks future calls, refresh and result links, but does not cancel already accepted jobs.
- First release: text-to-image, editing owned/unexpired generated images, status and balance. No arbitrary image URLs, local upload, SVG/PPTX conversion, data charts or browser-local canvas access.

## Troubleshooting

401: authorization/access expired or revoked; reconnect or refresh using the client. 403: missing scope or budget exceeded. 402: account credits insufficient. 409: request ID reused with different parameters. Do not auto-increase budgets or use a new request ID to evade these errors.

OAuth credentials are separate from website login tokens. Do not paste passwords or website JWTs into commands, URLs or agent prompts. Result download links are scoped to one job and grant, last at most five minutes, and cannot outlive original media expiry.
