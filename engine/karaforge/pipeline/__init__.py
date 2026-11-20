"""Pipeline framework: stages, the dependency graph runner, caching and profiles."""

from karaforge.pipeline.profiles import DEFAULT_PROFILE, Profile, get_profile, profile_names
from karaforge.pipeline.runner import PipelineRunner, RunReport, StageEvent, StageReport
from karaforge.pipeline.stage import (
    Stage,
    StageContext,
    StageInputs,
    link_or_copy,
    update_project,
)

__all__ = [
    "DEFAULT_PROFILE",
    "PipelineRunner",
    "Profile",
    "RunReport",
    "Stage",
    "StageContext",
    "StageEvent",
    "StageInputs",
    "StageReport",
    "get_profile",
    "link_or_copy",
    "profile_names",
    "update_project",
]
