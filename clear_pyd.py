from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
PACKAGE_DIR = PROJECT_ROOT / "src" / "codex_multi_launcher"


def remove_matching(pattern):
    """删除指定模式匹配到的临时编译产物。"""
    for path in PACKAGE_DIR.glob(pattern):
        if path.is_file():
            path.unlink()


def main():
    """清理保护打包产生的扩展模块和中间文件。"""
    remove_matching("app*.pyd")
    remove_matching("app*.c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
