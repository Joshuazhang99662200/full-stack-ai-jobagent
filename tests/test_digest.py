"""Persisted digests bind approvals and history; their bytes must never drift."""

from jobagent.digest import bytes_digest, canonical_digest, spaced_json_digest, text_digest

VALUE = {"b": [1, "中文"], "a": {"y": None, "x": True}}


def test_canonical_digest_is_sorted_compact_utf8() -> None:
    assert canonical_digest(VALUE) == (
        "sha256:037ae4a8fff306a6c7af5f6a075d9d44ef8eee9654261158068495114ddf29e2"
    )
    assert canonical_digest({"x": True, "y": None}) == canonical_digest({"y": None, "x": True})


def test_spaced_json_digest_keeps_the_frozen_legacy_forms() -> None:
    assert spaced_json_digest(VALUE) == (
        "sha256:bf038776b5f0326ecdf0b1c819c6ca96887f8791dce6275d084ec7b13235d4c9"
    )
    assert spaced_json_digest(VALUE, ensure_ascii=True) == (
        "sha256:c4cb42624dc798370003a3901365dbc3629f2d5b09ef0f9343bd389569146a27"
    )


def test_text_and_bytes_digests() -> None:
    assert text_digest("岗位 JD") == (
        "sha256:1243a8df3c1b75afafdfeb96068c9ee5e6e1316c7d4b7bd5784a11a616c9e260"
    )
    assert bytes_digest(b"\x00\xff") == (
        "sha256:06eb7d6a69ee19e5fbdf749018d3d2abfa04bcbd1365db312eb86dc7169389b8"
    )
