#!/usr/bin/env python3
"""Install the local ODA CLI as `oda-admin` and `oda` for terminal use."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _link(target: Path, link: Path) -> None:
    if link.exists() and not link.is_symlink():
        raise RuntimeError(f"Refusing to replace non-symlink command: {link}")
    if link.is_symlink():
        link.unlink()
    link.symlink_to(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    parser.add_argument("--no-shell-config", action="store_true", help="Do not update ~/.zshrc.")
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parent.parent
    venv_dir = repo_dir / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)

    subprocess.run([str(venv_python), "-m", "pip", "install", "--editable", str(repo_dir)], check=True)
    args.bin_dir.mkdir(parents=True, exist_ok=True)
    _link(venv_dir / "bin" / "oda-admin", args.bin_dir / "oda-admin")
    _link(venv_dir / "bin" / "oda", args.bin_dir / "oda")

    shell_rc = Path.home() / ".zshrc"
    path_line = f'export PATH="{args.bin_dir}:$PATH"'
    if not args.no_shell_config:
        existing = shell_rc.read_text() if shell_rc.exists() else ""
        if path_line not in existing:
            with shell_rc.open("a") as file:
                file.write(f"\n# OCI ODA Admin CLI\n{path_line}\n")

    print("Installed commands:\n  oda-admin\n  oda")
    print(f"Open a new terminal, or run:\n  source {shell_rc}")
    print("Try:\n  oda --help\n  oda validate")


if __name__ == "__main__":
    main()
