#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER_TAG_PATTERN = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
CHANGELOG_HEADING_PATTERN = re.compile(r"^## (v\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
CHANGELOG_ITEM_PATTERN = re.compile(r"^\+ \[([^\]]+)\] (.+)$")
ALLOWED_CHANGELOG_TYPES = {"新增", "调整", "优化", "修复", "安全", "文档"}


def normalize_tag(value: str) -> str:
    tag = value.strip()
    if not tag.startswith("v"):
        tag = f"v{tag}"
    if not SEMVER_TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"无效版本号：{value}，必须使用 vX.Y.Z。")
    return tag


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write_text(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def changelog_section(tag: str) -> str:
    content = read_text("CHANGELOG.md")
    heading = re.search(rf"^## {re.escape(tag)} - \d{{4}}-\d{{2}}-\d{{2}}$", content, re.MULTILINE)
    if not heading:
        raise ValueError(f"CHANGELOG.md 缺少 {tag} 发布记录。")
    next_heading = re.search(r"^## ", content[heading.end() :], re.MULTILINE)
    end = heading.end() + next_heading.start() if next_heading else len(content)
    return content[heading.start() : end].strip()


def semver_key(tag: str) -> tuple[int, int, int]:
    match = SEMVER_TAG_PATTERN.fullmatch(tag)
    if not match:
        raise ValueError(f"无效版本号：{tag}，必须使用 vX.Y.Z。")
    return tuple(map(int, match.groups()))


def validate_changelog(content: str) -> list[str]:
    invalid_headings = [
        line
        for line in content.splitlines()
        if line.startswith("## v") and not CHANGELOG_HEADING_PATTERN.fullmatch(line)
    ]
    if invalid_headings:
        raise ValueError(f"CHANGELOG.md 存在无效版本标题：{invalid_headings[0]}")

    release_tags = [tag for tag, _date in CHANGELOG_HEADING_PATTERN.findall(content)]
    if not release_tags:
        raise ValueError("CHANGELOG.md 没有正式版本记录。")
    if len(release_tags) != len(set(release_tags)):
        raise ValueError("CHANGELOG.md 存在重复版本记录。")
    if release_tags != sorted(release_tags, key=semver_key, reverse=True):
        raise ValueError("CHANGELOG.md 的正式版本必须按语义版本从新到旧排列。")

    for tag in release_tags:
        section_lines = changelog_section(tag).splitlines()[1:]
        items = []
        for line in section_lines:
            if not line.strip():
                continue
            match = CHANGELOG_ITEM_PATTERN.fullmatch(line)
            if not match:
                raise ValueError(f"CHANGELOG.md 的 {tag} 存在无效条目：{line}")
            if match.group(1) not in ALLOWED_CHANGELOG_TYPES:
                raise ValueError(f"CHANGELOG.md 的 {tag} 使用了不支持的类型：{match.group(1)}")
            items.append(match)
        if not items:
            raise ValueError(f"CHANGELOG.md 的 {tag} 没有发布条目。")
    return release_tags


def manifest_versions() -> dict[str, str]:
    frontend_package = json.loads(read_text("frontend/package.json"))
    frontend_lock = json.loads(read_text("frontend/package-lock.json"))
    backend_pyproject = read_text("backend/pyproject.toml")
    backend_match = re.search(r'^version = "([^"]+)"$', backend_pyproject, re.MULTILINE)
    backend_lock = read_text("backend/uv.lock")
    backend_lock_match = re.search(
        r'\[\[package\]\]\nname = "easy-painter-backend"\nversion = "([^"]+)"',
        backend_lock,
    )
    return {
        "frontend/package.json": frontend_package["version"],
        "frontend/package-lock.json": frontend_lock["version"],
        "frontend/package-lock.json#root": frontend_lock["packages"][""]["version"],
        "backend/pyproject.toml": backend_match.group(1) if backend_match else "missing",
        "backend/uv.lock": backend_lock_match.group(1) if backend_lock_match else "missing",
    }


def check(tag_value: str | None) -> None:
    version_tag = normalize_tag(tag_value or read_text("VERSION"))
    version_file = read_text("VERSION").strip()
    if version_file != version_tag:
        raise ValueError(f"VERSION 为 {version_file}，期望 {version_tag}。")

    content = read_text("CHANGELOG.md")
    release_tags = validate_changelog(content)
    latest_changelog_tag = release_tags[0]
    if latest_changelog_tag != version_tag:
        raise ValueError(f"CHANGELOG 最新版本为 {latest_changelog_tag}，期望 {version_tag}。")

    expected_manifest_version = version_tag.removeprefix("v")
    mismatches = {
        path: version
        for path, version in manifest_versions().items()
        if version != expected_manifest_version
    }
    if mismatches:
        details = "，".join(f"{path}={version}" for path, version in mismatches.items())
        raise ValueError(f"版本文件未同步：{details}；期望 {expected_manifest_version}。")

    print(f"版本检查通过：{version_tag}")


def set_version(tag_value: str) -> None:
    version_tag = normalize_tag(tag_value)
    version = version_tag.removeprefix("v")
    write_text("VERSION", f"{version_tag}\n")

    package_path = ROOT / "frontend/package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = version
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lock_path = ROOT / "frontend/package-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["version"] = version
    lock["packages"][""]["version"] = version
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pyproject = read_text("backend/pyproject.toml")
    pyproject = re.sub(r'(^\[project\]\nname = "easy-painter-backend"\nversion = ")[^"]+("$)', rf"\g<1>{version}\2", pyproject, count=1, flags=re.MULTILINE)
    write_text("backend/pyproject.toml", pyproject)

    uv_lock = read_text("backend/uv.lock")
    uv_lock = re.sub(
        r'(\[\[package\]\]\nname = "easy-painter-backend"\nversion = ")[^"]+("$)',
        rf"\g<1>{version}\2",
        uv_lock,
        count=1,
        flags=re.MULTILINE,
    )
    write_text("backend/uv.lock", uv_lock)
    print(f"已同步版本文件：{version_tag}")


def notes(tag_value: str) -> None:
    version_tag = normalize_tag(tag_value)
    section = changelog_section(version_tag)
    lines = section.splitlines()
    print("\n".join(lines[1:]).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Easy Painter 版本管理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="检查 VERSION、CHANGELOG 和 manifest 是否一致")
    check_parser.add_argument("version", nargs="?", help="可选版本号，格式 vX.Y.Z")

    set_parser = subparsers.add_parser("set", help="同步 VERSION 和前后端 manifest 版本")
    set_parser.add_argument("version", help="目标版本号，格式 vX.Y.Z")

    notes_parser = subparsers.add_parser("notes", help="提取指定版本的 GitHub Release 说明")
    notes_parser.add_argument("version", help="版本号，格式 vX.Y.Z")

    args = parser.parse_args()
    try:
        if args.command == "check":
            check(args.version)
        elif args.command == "set":
            set_version(args.version)
        else:
            notes(args.version)
    except (KeyError, OSError, ValueError) as error:
        print(f"版本检查失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
