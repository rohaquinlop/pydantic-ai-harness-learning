from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReviewDeps:
    policy_base: Path
    head_sha: str
    changed_files: frozenset[str]
