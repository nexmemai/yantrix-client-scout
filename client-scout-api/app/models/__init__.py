"""
models/__init__.py — Import all ORM models here so Alembic's Base.metadata
sees every table when auto-generating migrations.
"""

from app.models.job import DiscoveryJob       # noqa: F401
from app.models.business import Business       # noqa: F401
from app.models.audit import Audit             # noqa: F401
from app.models.config import NicheConfig      # noqa: F401  (was ScoringConfig)
from app.models.score import Score             # noqa: F401
from app.models.pitch import Pitch             # noqa: F401

__all__ = [
    "DiscoveryJob",
    "Business",
    "Audit",
    "NicheConfig",
    "Score",
    "Pitch",
]
