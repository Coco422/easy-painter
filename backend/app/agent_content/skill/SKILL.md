---
name: easy-painter
description: Generate images or revise an existing Easy Painter image through a connected Easy Painter MCP server, using the user's account and authorized credit budget. Use when the user asks to draw with Easy Painter or 一丝绘画站; not for data plotting, editable vector/PPT generation, or browser-local canvas manipulation.
---

# Easy Painter

Use the connected Easy Painter MCP tools. Tool prefixes depend on the host; discover the available names before calling them. If not connected, read the installation guide at the same site's `/mcp/install.md` and let the user complete browser login and consent. Do not request a website password, copy a browser JWT, or change unrelated agent configuration.

## Plan and quote

- `list_models` reports enabled models, supported sizes, reference support and the user's per-image price. `get_balance` reports credits and the connection's per-job cap. There is no daily spending limit or per-minute generation quota across the website, API or MCP. Both are free.
- Use `estimate_cost(model, size, editing)` before paid submission. Prefer an appropriate enabled model within the user's stated budget. Ask only when required content, cost authorization or model choice is materially unclear.
- Each call creates **one image**. Creating several images requires separate authorized requests. Website/API/MCP share the same credits, reservation and refund rules.
- Clarify the subject, layout, aspect ratio and desired text. Describe required labels, language, placement and hierarchy explicitly. Keep the user's intended content; explain meaningful prompt additions.

## Submit and recover

- `generate_image(prompt, model, size, request_id, max_cost)` returns a durable `job_id` without waiting for the model.
- For revisions use `edit_image(source_job_id, prompt, model, size, request_id, max_cost)`. The source must be the user's owned, still-available job image. Original versions stay intact. This is whole-image model redrawing, not a mask or layer editor. External image URLs and local file uploads are not supported in this release.
- Before a paid call, preserve the exact arguments and a new stable `request_id` in the agent's task state. Set `max_cost` to the quoted cost within the user's authorization. Never silently increase it after a price change or limit error.
- If submission times out or the response is lost, repeat **the same tool and all original arguments including request_id**. Do not generate a replacement ID for an unknown outcome. A reused ID with different arguments is a conflict, not permission to try a new paid request.
- On a 429 flood-protection error, stop sending requests and pause before retrying the original call with the same request_id and arguments.
- Once a job_id is known, call `get_job(job_id)` at the returned polling interval. Resume polling on later turns; connection loss does not cancel or refund a running job.
- Failed jobs refund the reserved credits to the account. A new paid retry after a confirmed failure needs a fresh ID and the user's existing or renewed authorization. Stop on insufficient balance, permission, budget or expiry errors and explain the action needed.

## Deliver

Show the result preview/download link, task status, actual cost and an appropriate website link. Image links expire after at most five minutes and become invalid when authorization or original media expires. Use `get_job` to obtain a fresh link; never expose OAuth access/refresh tokens. Do not claim a file was downloaded unless it was actually saved.

The tools do not provide real-data chart computation, editable SVG/PPTX conversion, scientific accuracy validation, publication acceptance guarantees, or direct access to browser-local canvases/version relationships. Explain these limits only when relevant to the request. Scientific labels and mechanisms should be checked by the user before use.
