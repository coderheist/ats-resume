"""
Maps a subscription tier's quality label to the LLM task it should run as.

This is the seam between two things that deliberately do not import each
other: app/config.py is pure pricing data (no knowledge of models), and
router.py is pure model data (no knowledge of who is paying). Putting the
join here means a pricing change never edits a model map and a model
change never edits the price list.

Why the join exists at all: the same logical operation is served by
different models depending on what the user paid. A bullet rewrite for a
Free user runs on the cheapest adequate model; the same rewrite for a Pro
user runs on the better one, because the rewrite is the feature people are
actually buying and it is the only place in the request path where model
quality is plainly visible in the output.

Scanning is the opposite case and is intentionally uniform across tiers:
the score itself is computed locally (app/core/scoring), so the model only
phrases an already-ranked suggestion list. Paying more does not buy a
different number, and pretending it did would be dishonest pricing.
"""
from __future__ import annotations

from app.core.llm.router import TaskType

# Quality label (app/config.py's Tier.scan_quality / .rewrite_quality) ->
# the task whose model should serve it. Only these two labels are valid;
# anything else is a typo in the pricing table and should fail loudly
# rather than silently fall back to an arbitrary model.
_QUALITY_TO_TASK: dict[str, TaskType] = {
    "fast": TaskType.FAST_CLASSIFICATION,
    "quality": TaskType.BULLET_REWRITE,
}

VALID_QUALITIES: frozenset[str] = frozenset(_QUALITY_TO_TASK)


def task_for_quality(quality: str) -> TaskType:
    """Raises ValueError on an unknown label -- see the module docstring on
    why this is not forgiving. A bad value here means the pricing table
    and this map have drifted, which is a deploy-time bug, not a
    per-request condition to degrade gracefully around."""
    try:
        return _QUALITY_TO_TASK[quality]
    except KeyError:
        raise ValueError(
            "Unknown model-quality label %r in the pricing table. Valid labels: %s."
            % (quality, ", ".join(sorted(VALID_QUALITIES)))
        ) from None


def rewrite_task_for_tier(tier) -> TaskType:
    """The task type a bullet rewrite should run as for this tier.

    Takes the Tier object rather than a tier id so this module never has
    to import app.config and create a cycle -- callers already hold the
    tier by the time they need to route.
    """
    return task_for_quality(tier.rewrite_quality)


def scan_task_for_tier(tier) -> TaskType:
    """The task type a scan's feedback summary should run as for this tier."""
    return task_for_quality(tier.scan_quality)
