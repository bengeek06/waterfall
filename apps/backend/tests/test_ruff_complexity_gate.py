from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# One branch per letter keeps this deterministic and readable while comfortably clearing the
# configured mccabe threshold of 15 (26 branches): each elif is its own decision point.
_TOO_COMPLEX_FUNCTION = "\n".join(
    ["def too_complex(value: str) -> str:"]
    + [
        f'    {"if" if letter == "a" else "elif"} value == "{letter}":\n        return "{letter}"'
        for letter in "abcdefghijklmnopqrstuvwxyz"
    ]
    + ["    return value"]
)


def _run_ruff_c90(source: str) -> subprocess.CompletedProcess[str]:
    # Written under BACKEND_DIR (not tmp_path) so ruff picks up pyproject.toml's real
    # [tool.ruff.lint.mccabe] max-complexity, exercising the actual configured gate rather than a
    # hardcoded threshold that could drift from it.
    target = BACKEND_DIR / "_ruff_c90_gate_check.py"
    target.write_text(source + "\n")
    try:
        return subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--select", "C90", target.name],
            cwd=BACKEND_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        target.unlink()


def test_gate_rejects_a_function_above_the_configured_threshold() -> None:
    result = _run_ruff_c90(_TOO_COMPLEX_FUNCTION)
    assert result.returncode != 0
    assert "C901" in result.stdout


def test_gate_accepts_the_same_function_once_explicitly_suppressed() -> None:
    suppressed = _TOO_COMPLEX_FUNCTION.replace(
        "def too_complex(value: str) -> str:",
        "def too_complex(value: str) -> str:  # noqa: C901 -- test fixture, not real code",
    )
    result = _run_ruff_c90(suppressed)
    assert result.returncode == 0, result.stdout
