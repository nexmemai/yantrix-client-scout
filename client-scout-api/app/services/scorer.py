"""
Compatibility wrapper for the legacy scorer module path.

New code should import from app.services.scoring.
"""

from app.services.scoring import *  # noqa: F401,F403
