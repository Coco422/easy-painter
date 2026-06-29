---
name: release
description: Use this skill whenever the user asks to release, publish a version, bump a version, create a git tag, push a tagged release, or says "发版", "版本更新", "打 tag", "release", or "push tag". It performs the project release workflow: inspect git state, cleanly stage only intended files, create a commit, determine the next semantic version from existing tags, create the git tag, and push branch plus tag to origin.
---

# Release Workflow

Use this skill for this repository's release flow. The goal is a safe, repeatable release: preserve unrelated work, commit only intended changes, choose the correct semantic version, tag the exact release commit, and push both branch and tag.

## Core Principles

- Preserve unrelated local work. This repo may have another Claude session or a human editing files at the same time.
- Never use destructive cleanup (`git reset --hard`, `git checkout --`, `git clean -fd`, branch deletion, force push) unless the user explicitly asks for that exact destructive action.
- Do not stage everything blindly. Prefer explicit file paths based on the release scope.
- Do not bypass hooks (`--no-verify`) or signing checks.
- Use a new commit. Do not amend unless the user explicitly asks.
- Push only after commit and tag creation succeed.

## Required Workflow

### 1. Inspect repository state

Run these checks first:

```bash
git status
git log --oneline -10
git tag --sort=-v:refname | head -10
```

If there are unrelated modified or untracked files, leave them unstaged and call them out briefly. Continue with only the files that belong to the requested release.

### 2. Review intended changes

Run `git diff -- <paths>` for the files you intend to release. If the user did not specify files, infer intended files from the current task context and recently edited files, then use explicit paths.

If the diff includes secrets, `.env`, credentials, generated caches, build artifacts, or unrelated imports/uploads, stop and ask the user what to include.

### 3. Validate before commit

Run the cheapest relevant checks for the changed areas:

- Frontend changes: `cd frontend && npx vue-tsc --noEmit`
- Backend Python changes: at minimum parse changed Python files with `python -m py_compile <files>` or run relevant tests if available
- If the user asks for a full release verification, run the repository's documented checks from `CLAUDE.md`

If checks fail, fix the issue before committing. Do not tag a failing release.

### 4. Stage only intended files

Use explicit paths:

```bash
git add path/to/file1 path/to/file2
```

Avoid `git add .` or `git add -A` because this repository often has parallel work and generated import assets.

### 5. Create the commit

Inspect recent commit style and write a concise message in the repo's style, usually Chinese Conventional Commit style such as:

- `feat: ...`
- `fix: ...`
- `chore: ...`

Always pass the commit message via heredoc:

```bash
git commit -m "$(cat <<'EOF'
feat: 简短说明本次发布内容

- 关键变化 1
- 关键变化 2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If there is nothing staged, do not create an empty commit unless the user explicitly requests one.

### 6. Determine the next version

Inspect existing tags with:

```bash
git tag --sort=-v:refname | head -20
```

Use strict semantic versioning tags in the format `vMAJOR.MINOR.PATCH`.

Version bump rules:

- Patch (`vX.Y.Z+1`) for bug fixes, small UI tweaks, docs, scripts, or operational changes.
- Minor (`vX.Y+1.0`) for new user-visible features, new API fields/endpoints, or backward-compatible functionality.
- Major (`vX+1.0.0`) for breaking changes, data migrations requiring manual intervention, incompatible API changes, or behavior that could break existing clients.

When in doubt:

- Prefer patch for fixes.
- Prefer minor for new feature work.
- Ask one targeted question only if the release type is genuinely ambiguous and materially changes the version.

### 7. Create the tag

Tag the commit you just created. Use an annotated tag:

```bash
git tag vX.Y.Z -m "$(cat <<'EOF'
vX.Y.Z

- 关键变化 1
- 关键变化 2

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

If the tag already exists, stop and inspect it. Do not overwrite or delete an existing tag unless the user explicitly approves.

### 8. Push branch and tag

After commit and tag succeed:

```bash
git push origin <current-branch> --tags
```

Do not force push. If push is rejected, report the rejection and inspect `git status` / branch divergence before doing anything else.

### 9. Final response

Report:

- Commit hash
- Tag name
- Remote push result
- Any unrelated local files intentionally left out

Keep it short.

## Common Local Noise In This Repo

Do not include these unless explicitly requested:

- `scripts/__pycache__/`
- `inspirations/`
- `README_zh.md`
- inspiration upload/download scripts from a parallel import session
- `.claude/settings.local.json`
- `.claude/worktrees/`

The project release skill itself is the exception: `.claude/skills/release/SKILL.md` is intended to be tracked.
