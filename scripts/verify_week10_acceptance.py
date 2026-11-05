"""Read-only acceptance of the original sealed Week 10 board and PR49 inputs."""
from __future__ import annotations
import hashlib
import json
from scripts import seal_week10_board as board

EXPECTED_SEAL_SHA256 = "7868e32c4de6f2154d1f8edfdce01042abf3f7933bb11d3a5509c58f448f9dbd"
ORIGINAL_SOURCE_SHA256 = {'data/ingest/2026-week10-splashsports-screen-capture.csv': '7fc188a42c3af15b29835e25110db6402cc12e4b6ca4a6ff6f9355d39d16da3d', 'data/ingest/2026-week10-splashsports-source-manifest.json': '7157f98ada62c27bb7eae4e06dbed12f640577e431d5f351de5c29fa640cd47e', 'data/ingest/2026-week10-splashsports-README.md': 'a5cac4cad47f070fb9d9d368356b203acb102cf194597506f04ae5ef8dd420f3'}


def verify() -> dict:
    if hashlib.sha256(board.SEAL.read_bytes()).hexdigest() != EXPECTED_SEAL_SHA256:
        raise ValueError("original Week10 seal identity changed; no checksum or status supersession authorized")
    for name, expected in ORIGINAL_SOURCE_SHA256.items():
        if hashlib.sha256((board.ROOT / name).read_bytes()).hexdigest() != expected:
            raise ValueError("original PR49 source bytes changed: " + name)
    result = board.main(True)
    if result["model_policy_change"] or result["eligible_games"] != 57:
        raise ValueError("Week10 identity/policy contradiction")
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
