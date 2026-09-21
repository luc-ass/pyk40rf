"""The version the package reports is the version that was built.

``__version__`` is exported for consumers -- the integration logs it in its
diagnostics, which is how a contributed report says which library produced it.
It lives in two places, and 0.1.7 went out with it still reading 0.1.6: the
release workflow checks the git tag against pyproject.toml and had nothing to
say about the module. This closes that gap from the other side.
"""

from __future__ import annotations

from pathlib import Path
import tomllib

import pyk40rf


def test_the_module_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text())["project"]["version"]
    assert pyk40rf.__version__ == declared
