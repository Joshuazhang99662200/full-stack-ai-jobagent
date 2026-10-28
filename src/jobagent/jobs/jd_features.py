# ruff: noqa: RUF001 -- Preserve Chinese source punctuation.
"""Exact-span deterministic extraction from configurable private terms."""

import re

from jobagent.schemas.jd_snapshot import JDSnapshot
from jobagent.schemas.lexicon import JDFeature, JDFeatureSet, Lexicon


def span_attributes(text: str, start: int, end: int) -> dict[str, str]:
    before = re.split(r"[。；;\n]", text[:start])[-1]
    after = re.split(r"[。；;\n]", text[end:])[0]
    context = before[-24:] + text[start:end] + after[:24]
    negated = bool(
        re.search(r"不要求|无需|不需要|不涉及|非必须|not required|no need", context, re.I)
    )
    preferred = bool(re.search(r"优先|加分|preferred|nice to have", context, re.I))
    required = bool(re.search(r"必须|要求|熟练|熟悉|must|required", context, re.I))
    return {
        "polarity": "negated" if negated else "positive",
        "requirement_level": "preferred"
        if preferred
        else "required"
        if required
        else "unspecified",
    }


def summarize(features: list[JDFeature]) -> str:
    return " × ".join(
        dimension
        + "="
        + "/".join(
            sorted(
                {f.term for f in features if f.dimension == dimension and f.polarity == "positive"}
            )
        )
        for dimension in ["domain", "scenario", "tech", "role"]
        if any(f.dimension == dimension and f.polarity == "positive" for f in features)
    )


def extract_features(snapshot: JDSnapshot, lexicon: Lexicon) -> JDFeatureSet:
    features: list[JDFeature] = []
    if snapshot.completeness == "full":
        seen: set[tuple[str, str, int, int]] = set()
        for term in lexicon.terms:
            for alias in dict.fromkeys([term.term, *term.aliases]):
                pattern = re.escape(alias)
                if alias.isascii() and alias[0].isalnum() and alias[-1].isalnum():
                    pattern = r"(?<![A-Za-z0-9_])" + pattern + r"(?![A-Za-z0-9_])"
                for match in re.finditer(pattern, snapshot.jd_text, re.I):
                    key = (term.dimension, term.term, match.start(), match.end())
                    if key in seen:
                        continue
                    seen.add(key)
                    features.append(
                        JDFeature.model_validate(
                            {
                                "dimension": term.dimension,
                                "term": term.term,
                                "evidence": match.group(),
                                "start": match.start(),
                                "end": match.end(),
                                **span_attributes(snapshot.jd_text, match.start(), match.end()),
                            }
                        )
                    )
    features.sort(key=lambda f: (f.start, f.end, f.dimension, f.term))
    return JDFeatureSet(
        snapshot_id=snapshot.snapshot_id,
        job_id=snapshot.job_id,
        snapshot_version=snapshot.snapshot_version,
        jd_text_hash=snapshot.jd_text_hash,
        features=features,
        factor_summary=summarize(features),
    )
