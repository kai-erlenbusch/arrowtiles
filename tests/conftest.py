"""Pytest configuration for duckdb-arrowtiles.

Ensures the repository root is importable for `arrowtiles.py` while preferring
the `maturin develop` package in `site-packages` over any stale untracked
`arrowtiles_core.pyd` sitting in the repository root.
"""

from __future__ import annotations

import importlib.util
import site
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _prefer_site_packages_arrowtiles_core() -> None:
    candidate_dirs = list(site.getsitepackages())
    for sp in candidate_dirs:
        pkg_init = Path(sp) / "arrowtiles_core" / "__init__.py"
        if pkg_init.is_file():
            spec = importlib.util.spec_from_file_location(
                "arrowtiles_core",
                pkg_init,
                submodule_search_locations=[str(pkg_init.parent)],
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["arrowtiles_core"] = mod
                spec.loader.exec_module(mod)
                return


_prefer_site_packages_arrowtiles_core()
