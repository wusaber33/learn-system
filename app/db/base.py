"""Import all models here so that Base.metadata.create_all() can see them.

In larger projects, Alembic autogenerate uses this module to know models.
"""

from .base_class import Base  # noqa: F401

# Ensure models are imported for metadata
from app.models import education  # noqa: F401, E402
