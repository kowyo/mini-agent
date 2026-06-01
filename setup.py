import sys
from pathlib import Path

from mypyc.build import mypycify
from setuptools import setup

if sys.platform == "darwin":
    import sysconfig

    sysconfig._CONFIG_VARS["MACOSX_DEPLOYMENT_TARGET"] = "11.0"

modules = [
    str(f) for f in Path("src/mini_agent").rglob("*.py") if f.name != "__init__.py"
]

setup(
    ext_modules=mypycify(
        ["--ignore-missing-imports", *modules],
        opt_level="3",
    ),
)
