"""Placeholder tracking legacy loadable DuckDB extension scripts in archive/tests/.

Covers `archive/tests/test_load.py`, `archive/tests/test_cache_clear.py`, and
`archive/tests/test_pipeline.py`, which targeted the earlier `arrowtiles.duckdb_extension`
loadable binary before the architecture migrated to PyO3 (`arrowtiles_core`).
"""

import pytest


@pytest.mark.skip(
    reason="Legacy loadable arrowtiles.duckdb_extension is superseded by PyO3 arrowtiles_core and out of scope for this revival."
)
def test_legacy_duckdb_loadable_extension() -> None:
    pass
