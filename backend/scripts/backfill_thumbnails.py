"""Bounded preview warmup; use from backend: uv run python -m scripts.backfill_thumbnails."""
import argparse
from app.db.session import SessionLocal
from app.services.thumbnails import backfill_thumbnails


def main():
    parser = argparse.ArgumentParser(description='补齐仍有效图片的 WebP 缩略图，不修改原图期限或任务状态。')
    parser.add_argument('--limit', type=int, default=20, help='每类资产本次最多处理数量（1–100）')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100:
        parser.error('--limit 必须在 1–100 之间')
    with SessionLocal() as db:
        count = backfill_thumbnails(db, limit=args.limit)
    print(f'本次补齐 {count} 张缩略图；失败记录按退避时间自动重试。')


if __name__ == '__main__':
    main()
