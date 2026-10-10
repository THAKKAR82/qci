"""Pydantic models have typed ``__init__`` signatures under mypy (``init_typed = true``).

The ``type: ignore[arg-type]`` below is the static half of the check. ``mypy --strict`` enables
``warn_unused_ignores``, so if ``init_typed`` is turned off the call stops being an error, the
ignore becomes unused, and the mypy gate fails. The test body is the runtime half.
"""

import pytest
from pydantic import ValidationError

from qci.domain.comparison import ComparisonPolicy


def test_old_comparison_policy_version_is_a_type_error_and_rejected_at_runtime() -> None:
    with pytest.raises(ValidationError):
        ComparisonPolicy(version="qci.compare.v2")  # type: ignore[arg-type]
