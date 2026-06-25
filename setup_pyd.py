from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup


PROJECT_ROOT = Path(__file__).resolve().parent
APP_SOURCE = PROJECT_ROOT / "src" / "codex_multi_launcher" / "app.py"


extensions = [
    Extension(
        "codex_multi_launcher.app",
        [str(APP_SOURCE)],
    )
]


setup(
    name="codex-multi-launcher-protected",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "embedsignature": False,
        },
    ),
)
