import sys
from pathlib import Path

from mypyc.build import mypycify
from setuptools import setup

if sys.platform == "darwin":
    import sysconfig

    sysconfig._CONFIG_VARS["MACOSX_DEPLOYMENT_TARGET"] = "11.0"

EXCLUDE = {"__init__.py", "plugin.py"}

modules = [
    str(f) for f in Path("src/mini_agent").rglob("*.py") if f.name not in EXCLUDE
]

setup(
    ext_modules=mypycify(
        ["--ignore-missing-imports", *modules],
        opt_level="3",
    ),
)
