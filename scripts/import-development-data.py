"""Import the synthetic development data ZIP into an already prepared local environment.

This tool does not install, download, build, start or stop any service or image.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

TABLES = {'user_groups', 'users', 'upstream_providers', 'model_configs',
          'generation_jobs', 'job_charges', 'credit_transactions', 'inspirations',
          'community_submissions', 'favorites', 'reference_images', 'announcements'}


def checked_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError(f'文件缺失或路径越界：{name}')
    return path


def verify_bundle(root: Path) -> dict:
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if hashlib.sha256(checked_file(root, name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'文件校验失败：{name}')
    data = json.loads((root / 'data.json').read_text(encoding='utf-8'))
    if data['format_version'] != 1 or set(data['tables']) != TABLES:
        raise RuntimeError('数据包格式不兼容。')
    if {row['username'] for row in data['tables']['users']} != {'demo', 'vip', 'private'}:
        raise RuntimeError('此导入器只接受开发包中的三个测试账号。')
    for row in data['tables']['upstream_providers']:
        if row['api_key'] != 'not-configured' or row['base_url'] != 'https://upstream-not-configured.invalid':
            raise RuntimeError('数据包含已配置的上游渠道，拒绝导入。')
    if any(row['enabled'] for row in data['tables']['model_configs']):
        raise RuntimeError('开发包的生图模型必须默认禁用。')
    for item in data['objects']:
        body = checked_file(root, item['path']).read_bytes()
        if item['bucket_type'] not in {'media', 'reference'} or hashlib.sha256(body).hexdigest() != item['sha256']:
            raise RuntimeError('图片清单或校验和不正确。')
    return data


def import_data(args, root: Path, data: dict) -> None:
    if not args.confirm_empty_local:
        raise RuntimeError('请确认目标为本地空开发环境，并添加 --confirm-empty-local。')
    if args.repo is None:
        raise RuntimeError('请用 --repo 指定 Easy Painter 源码目录。')
    repo = args.repo.resolve()
    if (repo / 'VERSION').read_text().strip() != data['application_version']:
        raise RuntimeError('源码版本与数据包不一致，请使用包内手册指定的版本。')
    if not (repo / 'backend/app').is_dir():
        raise RuntimeError('--repo 必须指向含 backend/app 的项目根目录。')
    sys.path.insert(0, str(repo / 'backend'))
    # Dependencies come from the colleague's existing backend uv environment.
    import bcrypt
    from minio import Minio
    from minio.error import S3Error
    from sqlalchemy import DateTime, MetaData, create_engine, select, text
    from sqlalchemy.engine import make_url
    from app.core.config import Settings

    settings = Settings(_env_file=repo / '.env')
    if settings.app_env != 'development':
        raise RuntimeError('项目 .env 必须显式设置 APP_ENV=development；不接受生产配置。')
    url = make_url(settings.database_url)
    endpoint = settings.minio_endpoint
    if args.container_network:
        if url.host != 'postgres' or endpoint not in {'rustfs:9000', 'minio:9000'}:
            raise RuntimeError('容器模式只接受 postgres 和 rustfs/minio 本地服务名。')
    else:
        # Like make backend, force local dependency ports; never use a remote host from .env.
        url = url.set(host='127.0.0.1', port=args.db_port)
        endpoint = f'127.0.0.1:{args.s3_port}'
    engine = create_engine(url, connect_args={'connect_timeout': 10})
    storage = Minio(endpoint, access_key=settings.minio_access_key,
                    secret_key=settings.minio_secret_key, secure=settings.minio_secure)
    buckets = {'media': settings.minio_bucket, 'reference': settings.minio_reference_bucket}
    if buckets['media'] == buckets['reference']:
        raise RuntimeError('原图与参考图需要使用两个不同的空 bucket。')
    password = secrets.token_urlsafe(16)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    reference = datetime.fromisoformat(data['reference_time'])
    delta = datetime.now(timezone.utc) - reference
    uploaded = []
    credentials = root / '.local' / 'ACCOUNTS.txt'
    credentials.parent.mkdir(mode=0o700, exist_ok=True)
    pending = credentials.with_suffix('.pending')
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(f'仅用于本地开发，不要转发此文件。\n\n账号：demo、vip、private\n统一密码：{password}\n\n管理员密钥使用你自己项目 .env 中的 ADMIN_SECRET_KEY。\n')
    try:
        with engine.begin() as db:
            # Serialize concurrent imports without creating or changing database schema.
            db.execute(text('SELECT pg_advisory_xact_lock(193001901)'))
            version = db.execute(text('SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank DESC LIMIT 1')).scalar_one()
            if version != data['flyway_version']:
                raise RuntimeError('数据库迁移版本不匹配，请先在空库完成 Flyway V1–V9。')
            metadata = MetaData()
            metadata.reflect(bind=db)
            for table in metadata.sorted_tables:
                if table.name not in {'user_groups', 'flyway_schema_history'} and db.execute(select(table).limit(1)).first() is not None:
                    raise RuntimeError(f'目标数据库非空（{table.name}），已拒绝覆盖。请另建空开发数据库。')
            for bucket in buckets.values():
                if storage.bucket_exists(bucket):
                    if next(storage.list_objects(bucket, recursive=True), None) is not None:
                        raise RuntimeError(f'目标 bucket 非空（{bucket}），已拒绝覆盖。请另建空 bucket。')
                else:
                    storage.make_bucket(bucket)
                try:
                    storage.delete_bucket_policy(bucket)
                except S3Error as exc:
                    if exc.code != 'NoSuchBucketPolicy':
                        raise
            for item in data['objects']:
                bucket = buckets[item['bucket_type']]
                uploaded.append((bucket, item['key']))
                storage.fput_object(bucket, item['key'], str(checked_file(root, item['path'])), content_type=item['content_type'])
                response = storage.get_object(bucket, item['key'])
                try:
                    digest = hashlib.sha256(response.read()).hexdigest()
                finally:
                    response.close(); response.release_conn()
                if digest != item['sha256']:
                    raise RuntimeError('上传后图片校验失败，导入事务将回滚。')
            for table in metadata.sorted_tables:
                if table.name not in TABLES:
                    continue
                for original in data['tables'][table.name]:
                    row = dict(original)
                    for column in table.columns:
                        if isinstance(column.type, DateTime) and row.get(column.name):
                            row[column.name] = datetime.fromisoformat(row[column.name]) + delta
                    if table.name == 'users':
                        row['password_hash'] = password_hash
                    if table.name == 'user_groups' and db.execute(select(table.c.code).where(table.c.code == row['code'])).first():
                        db.execute(table.update().where(table.c.code == row['code']).values(**row))
                    else:
                        db.execute(table.insert().values(**row))
    except Exception:
        # Only remove objects written by this import into buckets verified empty above.
        for bucket, key in uploaded:
            try:
                storage.remove_object(bucket, key)
            except Exception:
                print('有测试对象未能回滚，请检查本地 bucket 后重试。', file=sys.stderr)
        pending.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()
    os.replace(pending, credentials)
    print(f'导入完成：{len(data["tables"]["users"])} 个账号、{len(data["tables"]["generation_jobs"])} 条任务、{len(data["objects"])} 个对象文件。')
    print('全部图片已回读校验；样例时间已平移到本次导入时刻。')
    print(f'本次生成的账号密码：{credentials}')
    print('现在可以按仓库方式启动 API、worker、dispatcher 和前端。')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--check', action='store_true', help='只检查包文件，不连接任何服务')
    parser.add_argument('--confirm-empty-local', action='store_true')
    parser.add_argument('--db-port', type=int, default=5432)
    parser.add_argument('--s3-port', type=int, default=9000)
    parser.add_argument('--container-network', action='store_true', help='仅当在已有后端容器内执行时使用')
    args = parser.parse_args()
    if not all(1024 <= port <= 65535 for port in (args.db_port, args.s3_port)):
        parser.error('端口必须在 1024 到 65535 之间')
    root = args.bundle.resolve()
    data = verify_bundle(root)
    print(f'数据包校验通过：{data["application_version"]}，{len(data["objects"])} 个对象文件。')
    if not args.check:
        import_data(args, root, data)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f'未完成：{exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f'未完成：{type(exc).__name__}。请检查本地依赖、数据库迁移、凭据及空 bucket 条件；未覆盖已有数据。', file=sys.stderr)
        sys.exit(1)
