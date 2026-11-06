"""The one place that turns content into `sha256:` digests.

Approvals, history and idempotency keys store these values, so each form is
frozen: changing how a value is serialized changes every digest already saved.
New code uses `canonical_digest` for structured data and `text_digest` /
`bytes_digest` for exact text or files.
"""

import hashlib
import json


def bytes_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def text_digest(text: str) -> str:
    return bytes_digest(text.encode("utf-8"))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(value: object) -> str:
    """Sorted keys, compact separators, UTF-8: the default for structured data."""
    return text_digest(canonical_json(value))


def spaced_json_digest(value: object, *, ensure_ascii: bool = False) -> str:
    """Sorted keys with json's default separators.

    Only for digests that were already persisted in this form before the
    canonical form existed; do not use it for new data.
    """
    return text_digest(json.dumps(value, ensure_ascii=ensure_ascii, sort_keys=True))
