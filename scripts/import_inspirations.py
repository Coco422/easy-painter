#!/usr/bin/env python3
"""
Import inspirations from awesome-gpt-image-2 README_zh.md into the Easy Painter database.

This script:
1. Parses the README_zh.md markdown file
2. Downloads images from external URLs
3. Uploads images to MinIO storage
4. Creates inspiration records in the database via the admin API
5. Supports deduplication (skips items with existing source + external_id)

Usage:
    # Dry run - parse and preview without uploading
    python scripts/import_inspirations.py --readme-path README_zh.md --api-url http://localhost:8000 --admin-token TOKEN --dry-run

    # Full import
    python scripts/import_inspirations.py --readme-path README_zh.md --api-url http://localhost:8000 --admin-token TOKEN

    # Import with specific batch size
    python scripts/import_inspirations.py --readme-path README_zh.md --api-url http://localhost:8000 --admin-token TOKEN --batch-size 20

Requirements:
    pip install requests
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


def parse_readme(readme_path: str) -> list[dict]:
    """Parse README_zh.md and extract inspiration items."""
    content = Path(readme_path).read_text(encoding="utf-8")

    # Split by ### No. N: pattern
    # Each section starts with ### No. {number}: {category} - {title}
    sections = re.split(r'(?=### No\.\s*\d+:)', content)

    items = []
    for section in sections:
        if not section.strip() or not section.startswith('### No.'):
            continue

        item = parse_section(section)
        if item:
            items.append(item)

    return items


def parse_section(section: str) -> dict | None:
    """Parse a single inspiration section from the README."""
    # Extract number and title
    header_match = re.match(r'### No\.\s*(\d+):\s*(.+?)(?:\n|$)', section)
    if not header_match:
        return None

    item_number = header_match.group(1)
    header_text = header_match.group(2).strip()

    # Split header into category and title
    # Format: "Category - Title" or just "Title"
    if ' - ' in header_text:
        category, title = header_text.split(' - ', 1)
        category = category.strip()
        title = title.strip()
    else:
        category = ''
        title = header_text

    # Extract description
    description = ''
    desc_match = re.search(r'#### 📖 Description\s*\n(.*?)(?=\n####|\n```|\Z)', section, re.DOTALL)
    if desc_match:
        description = desc_match.group(1).strip()

    # Extract prompt (in code block)
    prompt = ''
    prompt_match = re.search(r'#### 📝 Prompt\s*\n```(?:\w*\n)?(.*?)```', section, re.DOTALL)
    if prompt_match:
        prompt = prompt_match.group(1).strip()

    if not prompt:
        return None

    # Extract image URLs
    image_urls = []
    img_matches = re.findall(r'<img\s+[^>]*src=["\']([^"\']+)["\']', section)
    for url in img_matches:
        if url.startswith('http'):
            image_urls.append(url)

    # Also match markdown image syntax
    md_img_matches = re.findall(r'!\[.*?\]\((https?://[^\)]+)\)', section)
    for url in md_img_matches:
        if url not in image_urls:
            image_urls.append(url)

    if not image_urls:
        return None

    # Extract author
    author_name = ''
    author_url = ''
    author_match = re.search(r'\*\*Author:\*\*\s*\[([^\]]+)\]\(([^\)]+)\)', section)
    if author_match:
        author_name = author_match.group(1).strip()
        author_url = author_match.group(2).strip()

    # Extract source link
    source_url = ''
    source_match = re.search(r'\*\*Source:\*\*\s*\[([^\]]+)\]\(([^\)]+)\)', section)
    if source_match:
        source_url = source_match.group(2).strip()

    # Extract published date
    published = ''
    pub_match = re.search(r'\*\*Published:\*\*\s*(\d{4}-\d{2}-\d{2})', section)
    if pub_match:
        published = pub_match.group(1)

    # Build categories list
    categories = []
    if category:
        categories.append(category)

    return {
        'external_id': f'awesome-gpt-image-2:{item_number}',
        'title': title,
        'description': description if description else None,
        'prompt': prompt,
        'image_url': image_urls[0],  # Will be replaced after upload
        'original_image_url': image_urls[0],
        'source': 'awesome-gpt-image-2',
        'source_url': source_url if source_url else None,
        'author_name': author_name if author_name else None,
        'author_url': author_url if author_url else None,
        'language': 'zh',
        'categories': categories if categories else None,
        'is_featured': False,
    }


def download_image(url: str, timeout: int = 30) -> tuple[bytes, str] | None:
    """Download an image from URL. Returns (bytes, content_type) or None."""
    try:
        response = requests.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('content-type', 'image/jpeg')
        if 'image' not in content_type:
            content_type = 'image/jpeg'
        return response.content, content_type
    except Exception as e:
        print(f"  Warning: Failed to download {url}: {e}", file=sys.stderr)
        return None


def upload_single_inspiration(
    api_url: str,
    admin_token: str,
    item: dict,
    image_bytes: bytes,
    content_type: str,
) -> dict | None:
    """Upload a single inspiration with image via admin API."""
    url = f"{api_url}/api/v1/admin/inspirations"
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Build multipart form data
    files = {
        'image': ('image.jpg', image_bytes, content_type),
    }
    data = {
        'title': item['title'],
        'prompt': item['prompt'],
        'source': item['source'],
        'external_id': item['external_id'],
        'language': item.get('language', 'zh'),
    }
    if item.get('description'):
        data['description'] = item['description']
    if item.get('source_url'):
        data['source_url'] = item['source_url']
    if item.get('author_name'):
        data['author_name'] = item['author_name']
    if item.get('author_url'):
        data['author_url'] = item['author_url']
    if item.get('categories'):
        data['categories'] = json.dumps(item['categories'])

    try:
        response = requests.post(url, headers=headers, files=files, data=data, timeout=60)
        if response.status_code == 409:
            print(f"  Skipped (duplicate): {item['title']}")
            return {"skipped": True}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"  Error uploading {item['title']}: {e}", file=sys.stderr)
        if hasattr(e, 'response') and e.response is not None:
            print(f"  Response: {e.response.text[:200]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  Error uploading {item['title']}: {e}", file=sys.stderr)
        return None


def main():
    parser = argparse.ArgumentParser(description='Import inspirations from README_zh.md')
    parser.add_argument('--readme-path', required=True, help='Path to README_zh.md file')
    parser.add_argument('--api-url', required=True, help='Base URL of the Easy Painter API')
    parser.add_argument('--admin-token', required=True, help='Admin JWT token')
    parser.add_argument('--batch-size', type=int, default=10, help='Number of items to process before pausing')
    parser.add_argument('--dry-run', action='store_true', help='Parse and preview without uploading')
    parser.add_argument('--delay', type=float, default=0.5, help='Delay between uploads in seconds')
    args = parser.parse_args()

    print(f"Parsing {args.readme_path}...")
    items = parse_readme(args.readme_path)
    print(f"Found {len(items)} inspiration items.")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for i, item in enumerate(items[:10]):
            print(f"\n[{i+1}] {item['title']}")
            print(f"    Category: {item.get('categories', ['N/A'])[0] if item.get('categories') else 'N/A'}")
            print(f"    Prompt: {item['prompt'][:80]}...")
            print(f"    Image: {item['original_image_url'][:80]}...")
            print(f"    Author: {item.get('author_name', 'N/A')}")
            print(f"    External ID: {item['external_id']}")
        if len(items) > 10:
            print(f"\n... and {len(items) - 10} more items")
        print(f"\nTotal: {len(items)} items to import")
        return

    # Full import
    created = 0
    skipped = 0
    failed = 0

    for i, item in enumerate(items):
        print(f"\n[{i+1}/{len(items)}] {item['title']}")

        # Download image
        print(f"  Downloading image...")
        result = download_image(item['original_image_url'])
        if not result:
            print(f"  FAILED: Could not download image")
            failed += 1
            continue

        image_bytes, content_type = result
        print(f"  Downloaded {len(image_bytes)} bytes ({content_type})")

        # Upload
        print(f"  Uploading to API...")
        response = upload_single_inspiration(
            api_url=args.api_url,
            admin_token=args.admin_token,
            item=item,
            image_bytes=image_bytes,
            content_type=content_type,
        )

        if response is None:
            failed += 1
        elif response.get('skipped'):
            skipped += 1
        else:
            created += 1
            print(f"  Created: {response.get('id', 'unknown')}")

        # Rate limiting
        if args.delay > 0:
            time.sleep(args.delay)

    print(f"\n{'='*50}")
    print(f"Import complete:")
    print(f"  Created: {created}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed:  {failed}")
    print(f"  Total:   {len(items)}")


if __name__ == '__main__':
    main()
