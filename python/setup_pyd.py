from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup


PYTHON_DIR = Path(__file__).resolve().parent
PROTECTED_MODULES = [
    "bridge.cli",
    "bridge.commands",
    "core.auth_service",
    "core.codex_source",
    "core.config_store",
    "core.constants",
    "core.oauth_service",
    "core.path_utils",
    "core.profile_service",
]


def module_source(module_name):
    return PYTHON_DIR / Path(*module_name.split(".")).with_suffix(".py")


extensions = [
    Extension(module_name, [str(module_source(module_name))])
    for module_name in PROTECTED_MODULES
]


setup(
    name="codex-multi-launcher-backend-protected",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "embedsignature": False,
        },
    ),
)
