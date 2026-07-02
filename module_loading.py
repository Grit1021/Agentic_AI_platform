import os
import sys
from typing import Dict


def ensure_backend_paths() -> Dict[str, str]:
    """Make bundled backend modules importable from refined modules."""
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    backend_dir = os.path.join(parent_dir, "refined", "backend")
    backend_wo_iterative_dir = os.path.join(backend_dir, "wo_iterative")
    with_iterative_dir = os.path.join(parent_dir, "with_iterative")
    wo_iterative_dir = os.path.join(parent_dir, "wo_iterative")
    utils_dir = os.path.dirname(parent_dir)
    src_dir = os.path.dirname(utils_dir)
    project_root = os.path.dirname(src_dir)

    paths_by_priority = [
        backend_dir,
        backend_wo_iterative_dir,
        parent_dir,
        with_iterative_dir,
        wo_iterative_dir,
        utils_dir,
        src_dir,
        project_root,
    ]

    for path in reversed(paths_by_priority):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)

    return {
        "parent_dir": parent_dir,
        "backend_dir": backend_dir,
        "backend_wo_iterative_dir": backend_wo_iterative_dir,
        "with_iterative_dir": with_iterative_dir,
        "wo_iterative_dir": wo_iterative_dir,
        "utils_dir": utils_dir,
        "src_dir": src_dir,
        "project_root": project_root,
    }
