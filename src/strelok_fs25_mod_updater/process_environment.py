from __future__ import annotations

import os


def independent_process_environment() -> dict[str, str]:
    """Give a frozen process its own extraction directory and lifetime."""
    return {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
