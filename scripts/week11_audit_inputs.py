"""Immutable PR53 input access. This module never executes captured prediction code."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tarfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = 'bcdd78fb2755f9552e45ccfc5f891bd25e012eef'
EVIDENCE = ROOT / 'outputs/2026-week11-postgame-evidence'
SOURCE = EVIDENCE / 'pr53-source.tar.gz'
BOARD = 'outputs/2026-week11-prospective/'
DB_SHA = '09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842'
LINE_SHA = 'a27f367a38918e188cc2e8aa417b9a1970049ca02d0501789d00ccfdb0b12c22'
SEAL_SHA = 'd6d163f2500fa638ad73da8b4b0da244e9cad4fe456e42d80ea65e36e073868c'
ARCHIVE_SHA = '035591e6eac8f2cc64e7564c4fd184f44e117c55f5308909f7f6490da37f3510'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=1)
def source_files() -> dict[str, bytes]:
    manifest_raw=(EVIDENCE / 'pr53-source-manifest.json').read_bytes()
    if sha(manifest_raw)!='78d853b8f21a94d480f07716a4561a1a766626c60d33fc605010210b61666cba':
        raise ValueError('Original PR53 inventory changed')
    manifest = json.loads(manifest_raw)
    if manifest['commit'] != SOURCE_COMMIT or manifest['archive_sha256'] != ARCHIVE_SHA:
        raise ValueError('PR53 archive custody failure')
    # PR53 has merged. Verify all 870 original members byte for byte against
    # the identical inventory, without duplicating its 114 MB archive in Git.
    result = {}
    for name in manifest['files_sha256']:
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Missing or unsafe original PR53 member: '+name)
        result[name]=path.read_bytes()
    if {p: sha(b) for p, b in result.items()} != manifest['files_sha256']:
        raise ValueError('PR53 source member custody failure')
    for path, expected in [('production-weeks/2026-week11-splashsports.csv', LINE_SHA),
                           (BOARD + 'week11_initial_seal_manifest.json', SEAL_SHA)]:
        if sha(result[path]) != expected:
            raise ValueError('Original source identity mismatch: ' + path)
    return result


def source_json(path: str):
    return json.loads(source_files()[path])


def source_csv(path: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(source_files()[path].decode('utf-8-sig'))))


def board_csv(name: str) -> list[dict]:
    return source_csv(BOARD + 'week11_' + name + '.csv')
