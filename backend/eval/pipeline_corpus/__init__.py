"""Synthetic end-to-end corpora: realistic sender names, subjects, Gmail-style snippets and bodies.

`tune` is for writing rules; `holdout` is measurement only (never read its misses to tune).
"""

from eval.pipeline_corpus.corpus import build_corpus
from eval.pipeline_corpus.holdout import build_holdout
from eval.pipeline_corpus.model import Case

SPLITS = ("tune", "holdout")


def load_split(split: str) -> list[Case]:
    if split == "tune":
        return build_corpus()
    if split == "holdout":
        return build_holdout()
    raise ValueError(f"unknown split {split!r}")
