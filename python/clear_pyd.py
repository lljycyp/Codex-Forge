from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parent
PROTECTED_DIRS = [
    PYTHON_DIR / "bridge",
    PYTHON_DIR / "core",
]


def remove_matching(directory, pattern):
    """删除指定模式匹配到的临时编译产物。"""
    for path in directory.glob(pattern):
        if path.is_file():
            path.unlink()


def main():
    """清理后端保护打包产生的扩展模块和中间文件。"""
    for directory in PROTECTED_DIRS:
        remove_matching(directory, "*.pyd")
        remove_matching(directory, "*.c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
