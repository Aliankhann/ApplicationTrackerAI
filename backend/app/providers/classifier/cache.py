"""In-memory LRU cache in front of any classifier. Keys are hashes; text is never stored."""

import hashlib
from collections import OrderedDict

from app.providers.classifier.base import ClassifierProvider
from app.providers.classifier.types import ClassificationInput, ClassificationResult


def cache_key(inp: ClassificationInput) -> str:
    raw = "".join(f"{len(f)}:{f}" for f in (inp.from_domain, inp.subject, inp.snippet))
    return hashlib.sha256(raw.encode()).hexdigest()


class CachingProvider:
    def __init__(self, inner: ClassifierProvider, maxsize: int = 10_000) -> None:
        self._inner = inner
        self._maxsize = maxsize
        self._cache: OrderedDict[str, ClassificationResult] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def classify(self, inp: ClassificationInput) -> ClassificationResult:
        key = cache_key(inp)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            self.hits += 1
            return cached
        self.misses += 1
        result = self._inner.classify(inp)
        self._cache[key] = result
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)
        return result
