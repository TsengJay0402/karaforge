"""The project document (``project.json``) and the ``.kfproj`` folder layout."""

from karaforge.project.schema import (
    SCHEMA_VERSION,
    Analysis,
    Background,
    Line,
    Media,
    Meta,
    Project,
    Render,
    Singer,
    Style,
    Token,
    default_singers,
)
from karaforge.project.store import (
    PROJECT_FILE,
    PROJECT_SUFFIX,
    ProjectPaths,
    ProjectStore,
    slugify,
)

__all__ = [
    "PROJECT_FILE",
    "PROJECT_SUFFIX",
    "SCHEMA_VERSION",
    "Analysis",
    "Background",
    "Line",
    "Media",
    "Meta",
    "Project",
    "ProjectPaths",
    "ProjectStore",
    "Render",
    "Singer",
    "Style",
    "Token",
    "default_singers",
    "slugify",
]
