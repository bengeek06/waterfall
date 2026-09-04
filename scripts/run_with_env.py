from __future__ import annotations

import os
import sys

from dotenv import dotenv_values


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: run_with_env.py COMMAND [ARGUMENT ...]")

    environment = {
        **{key: value for key, value in dotenv_values(".env").items() if value is not None},
        **os.environ,
    }
    os.execvpe(sys.argv[1], sys.argv[1:], environment)


if __name__ == "__main__":
    main()
