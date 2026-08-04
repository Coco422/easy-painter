---
name: release
description: Use this skill when the user asks to release, bump a version, create a tag, publish a GitHub Release, or says "发版", "版本更新", "打 tag", "release", or "push tag". It maintains VERSION and the Chinese CHANGELOG, validates the monorepo version, creates an annotated semantic-version tag, and pushes only when explicitly authorized.
---

# Release Workflow

Easy Painter releases the frontend and backend together from one repository. `VERSION` is the canonical version source, while `CHANGELOG.md` is the only source for human-written release notes and GitHub Release content.

## Safety Rules

- Preserve unrelated local changes and stage only explicit release paths.
- Never use destructive cleanup, amend, force push, overwrite a tag, or bypass hooks.
- Do not create a commit, tag, or push unless the user explicitly authorizes that action.
- A release must not proceed when version checks, relevant tests, or builds fail.
- GitHub Release notes must come from `CHANGELOG.md`; do not generate a second feat-only commit list.

## Required Workflow

### 1. Inspect state and determine the version

Run:

```bash
git status
git log --oneline -10
git tag --sort=-v:refname | head -20
```

Use strict `vMAJOR.MINOR.PATCH` tags:

- Patch for compatible fixes and small operational changes.
- Minor for backward-compatible user-visible features or APIs.
- Major for breaking contracts or migrations requiring manual intervention.

Stop if the target tag already exists; never replace it without explicit approval.

### 2. Write the Chinese changelog

Review commits since the latest semantic-version tag and summarize user-visible changes under a new heading directly below `## Unreleased`:

```md
## vX.Y.Z - YYYY-MM-DD

+ [新增] 新能力。
+ [调整] 行为或结构调整。
+ [优化] 体验或性能优化。
+ [修复] 问题修复。
```

Allowed types are `新增`、`调整`、`优化`、`修复`、`安全` and `文档`. Keep `## Unreleased` for future work, avoid implementation trivia, and do not duplicate an existing version section.

### 3. Synchronize and validate

Run:

```bash
python3 scripts/version.py set vX.Y.Z
python3 scripts/version.py check vX.Y.Z
python3 scripts/version.py notes vX.Y.Z
```

Review the notes output because it is exactly what the tag workflow will publish to GitHub Release.

Run the relevant gates before release:

```bash
cd frontend && npm run build
cd ../backend && uv run pytest -q
cd .. && git diff --check
```

Use narrower tests only when the user explicitly requests a partial validation; never tag known failing code.

### 4. Commit only authorized files

Review the diff and stage explicit paths. The normal version release set includes `VERSION`, `CHANGELOG.md`, frontend/backend manifests and lockfiles, plus actual feature files intended for this release. Never use `git add .` or `git add -A` in a dirty worktree.

Create a new Conventional Commit in the repository's Chinese style. Do not amend unless explicitly requested.

### 5. Create an annotated tag

After the release commit succeeds:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
```

Confirm the tag points to the intended commit and that `python3 scripts/version.py check vX.Y.Z` still passes.

### 6. Push only with authorization

When the user explicitly asks to publish or push:

```bash
git push origin <current-branch>
git push origin vX.Y.Z
```

Do not force push. The tag workflow validates the repository and creates the GitHub Release from `CHANGELOG.md`. If the workflow fails, diagnose it instead of recreating or moving the tag.

## Final Report

Report the version, commit hash, tag, validation results, push result, and any unrelated local files intentionally excluded.
