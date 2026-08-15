"""Boucle de goût : 👍/👎 sur les brèves → pondération des sources et blacklist.

Persisté dans dist/feedback.json :
- score par source (les sources appréciées remontent dans la sélection)
- mots-clés détestés (les articles qui les contiennent sont écartés)

Le poids reste léger : la fraîcheur domine toujours, le goût départage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .sources import FeedItem, title_tokens


@dataclass
class Feedback:
    source_scores: dict[str, int] = field(default_factory=dict)
    disliked_keywords: list[str] = field(default_factory=list)


def _path(dist_dir: Path) -> Path:
    return dist_dir / "feedback.json"


def load_feedback(dist_dir: Path) -> Feedback:
    path = _path(dist_dir)
    if not path.exists():
        return Feedback()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Feedback(
            source_scores=data.get("source_scores", {}),
            disliked_keywords=data.get("disliked_keywords", [])[:200],
        )
    except (json.JSONDecodeError, OSError):
        return Feedback()


def save_feedback(dist_dir: Path, feedback: Feedback) -> None:
    path = _path(dist_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(feedback.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def record_vote(
    dist_dir: Path, *, source: str, title: str, good: bool
) -> Feedback:
    """Enregistre un vote : ajuste le score de la source, apprend les rejets."""
    feedback = load_feedback(dist_dir)
    feedback.source_scores[source] = feedback.source_scores.get(source, 0) + (1 if good else -1)
    if not good:
        # On retient les mots significatifs du titre rejeté (sujet à éviter)
        for token in sorted(title_tokens(title), key=len, reverse=True)[:3]:
            if token not in feedback.disliked_keywords:
                feedback.disliked_keywords.append(token)
                if len(feedback.disliked_keywords) > 200:
                    feedback.disliked_keywords.pop(0)
    save_feedback(dist_dir, feedback)
    return feedback


# Bonus exprimés en « heures de fraîcheur » : un article ancien d'autant
# d'heures fait jeu égal. Les additionner à la date garde le tri lisible —
# multiplier un timestamp Unix par un pourcentage donnait des années de bonus
# pour un seul vote, et la fraîcheur ne pesait plus rien.
VOTE_HOURS = 2.0  # par vote sur la source (plafonné à ±5 votes)
SUMMARY_HOURS = 1.0  # résumé assez fourni pour faire une brève
SUMMARY_MIN_CHARS = 200


def item_score(item: FeedItem, feedback: Feedback) -> float:
    """Score de sélection, en secondes : date de publication + bonus.

    Un article sans date part de zéro : il passe donc après tout article daté,
    quel que soit son bonus.
    """
    if item.published is None:
        return 0.0
    votes = max(min(feedback.source_scores.get(item.source_name, 0), 5), -5)
    bonus = votes * VOTE_HOURS
    if len(item.summary) >= SUMMARY_MIN_CHARS:
        bonus += SUMMARY_HOURS
    return item.published.timestamp() + bonus * 3600


def apply_feedback(items: list[FeedItem], feedback: Feedback) -> list[FeedItem]:
    """Trie les items : sources aimées devant, sujets détestés écartés.

    La fraîcheur domine ; le goût et la présence d'un vrai résumé départagent
    à quelques heures près.
    """
    disliked = set(feedback.disliked_keywords)
    kept = [item for item in items if not (disliked & title_tokens(item.title))]
    return sorted(kept, key=lambda item: item_score(item, feedback), reverse=True)
