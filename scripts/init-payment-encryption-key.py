#!/usr/bin/env python3
"""Initialize a private Fernet master key in an existing env file, without printing it."""
import argparse
import base64
import os
from pathlib import Path
import secrets
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    path = args.env_file.resolve(strict=True)
    content = path.read_text(encoding='utf-8')
    name = 'PAYMENT_CONFIG_ENCRYPTION_KEY'
    lines = content.splitlines()
    entries = [line.split('=', 1)[1].strip().strip('\"\'') for line in lines if line.startswith(name + '=')]
    if len(entries) > 1:
        raise SystemExit('Duplicate encryption key entries; resolve them privately before initialization.')
    if entries and entries[0]:
        try:
            assert len(base64.urlsafe_b64decode(entries[0])) == 32
        except (ValueError, AssertionError):
            raise SystemExit('Existing encryption key is invalid; it was not overwritten.') from None
        print('Payment encryption master key already exists; preserved.')
        return
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('ascii')
    lines = [line for line in lines if not line.startswith(name + '=')]
    lines.append(name + '=' + key)
    fd, temporary = tempfile.mkstemp(prefix='.env-payment-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write('\n'.join(lines) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    print('Payment encryption master key initialized; value not displayed. Back up the private env file.')


if __name__ == '__main__':
    main()
