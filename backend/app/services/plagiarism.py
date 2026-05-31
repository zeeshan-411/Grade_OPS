"""Cross-paper similarity scoring for plagiarism detection.

The real implementation is a per-question pairwise cosine on word-bag vectors
of the OCR-extracted answers. The synthetic path generates deterministic
plausible pairs from student/question IDs, used when no extracted text exists
(e.g. in DEMO_MODE).
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

# Pairs at or above this score get persisted and flagged.
SIMILARITY_THRESHOLD = 0.65


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> Counter[str]:
    return Counter(t.lower() for t in _TOKEN_RE.findall(text))


def _cosine(a: Counter[str], b: Counter[str]) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    dot = sum(a[w] * b[w] for w in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _normalise_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def compute_pairs_from_text(
    answers: list[dict],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """Find suspicious pairs given a list of {student_id, question_id, text}.

    Returns: [{question_id, student_a, student_b, score}, ...]
    """
    by_q: dict[str, list[tuple[str, Counter[str]]]] = {}
    for a in answers:
        qid = str(a.get("question_id", ""))
        sid = str(a.get("student_id", ""))
        text = str(a.get("text", "") or "")
        if not qid or not sid or not text.strip():
            continue
        by_q.setdefault(qid, []).append((sid, _tokens(text)))

    pairs: list[dict] = []
    for qid, items in by_q.items():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                sa, va = items[i]
                sb, vb = items[j]
                if sa == sb:
                    continue
                score = _cosine(va, vb)
                if score >= threshold:
                    s_a, s_b = _normalise_pair(sa, sb)
                    pairs.append(
                        {
                            "question_id": qid,
                            "student_a": s_a,
                            "student_b": s_b,
                            "score": round(score, 3),
                        }
                    )
    return pairs


def _seed(*parts: str) -> float:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def synthesize_pairs(
    student_ids: list[str], question_ids: list[str]
) -> list[dict]:
    """Deterministic pseudo-pairs for environments without OCR text.

    For each question, considers every (a, b) pair and emits one if its seed
    crosses a threshold. Scores fall in [0.7, 0.95].
    """
    pairs: list[dict] = []
    sids = sorted(set(student_ids))
    for qid in sorted(set(question_ids)):
        for i in range(len(sids)):
            for j in range(i + 1, len(sids)):
                s = _seed(qid, sids[i], sids[j])
                if s > 0.78:  # roughly 1 in 5 pairs flagged
                    pairs.append(
                        {
                            "question_id": qid,
                            "student_a": sids[i],
                            "student_b": sids[j],
                            "score": round(0.70 + 0.25 * s, 3),
                        }
                    )
    return pairs
