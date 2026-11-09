#!/usr/bin/env python3
"""Run the bundled usage reporter from this skill's installation."""
from pathlib import Path
import subprocess
import sys


def main() -> int:
    project = Path(__file__).resolve().parents[3]
    reporter = project / "usage_tool" / "codex_usage.py"
    if not reporter.is_file():
        print(
            f"DeepSeek usage reporter not found: {reporter}. "
            "Reinstall codex-deepseek or check the installation directory.",
            file=sys.stderr,
        )
        return 1
    return subprocess.call([sys.executable, str(reporter), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
