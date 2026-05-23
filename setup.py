from pathlib import Path

from mypyc.build import mypycify
from setuptools import setup

modules = [
    str(f) for f in Path("src/mini_agent").rglob("*.py") if f.name != "__init__.py"
]

setup(
    ext_modules=mypycify(
        ["--ignore-missing-imports", *modules],
        opt_level="3",
    ),
)
