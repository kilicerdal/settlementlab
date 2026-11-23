"""Build the standalone HTTP framework from its canonical, domain-free modules.

A distinct namespace avoids file ownership collisions with the reference-app wheel.
No source copy is committed; this build verifies an explicit module allowlist.
"""

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("catalogs", "http_steps", "reporting", "targets", "transport", "external_runner")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist")
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="assurance-wheel-") as directory:
        root = Path(directory)
        package = root / "src/settlementlab_assurance"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            '"""Reusable HTTP assurance; standard-library runtime only."""\n'
        )
        for module in MODULES:
            source = ROOT / "src/settlementlab/assurance" / (module + ".py")
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (
                    node.level > 1 or (node.level == 1 and node.module not in MODULES)
                ):
                    raise RuntimeError("Nonportable import in " + module)
                if isinstance(
                    node, (ast.Import, ast.ImportFrom)
                ) and "settlementlab." in ast.unparse(node):
                    raise RuntimeError("Reference application dependency in " + module)
            shutil.copyfile(source, package / source.name)
        (root / "pyproject.toml").write_text("""[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[project]
name = "settlementlab-assurance"
version = "4.4.0"
description = "Independent declarative HTTP assurance engine"
requires-python = ">=3.9"
dependencies = []
license = {text = "MIT"}
[project.scripts]
settlementlab-http-assure = "settlementlab_assurance.external_runner:main"
[tool.setuptools.packages.find]
where = ["src"]
""")
        shutil.copyfile(ROOT / "LICENSE", root / "LICENSE")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(output),
                str(root),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
