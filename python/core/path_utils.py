import os
import stat
import sys
from pathlib import Path


def resource_path(*parts):
    """获取源码运行或打包运行时都可访问的资源路径。"""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_dir.joinpath(*parts)


def sanitize_profile_name(name):
    """把账号名称转换为可作为目录名的安全文本。"""
    cleaned = "".join(ch if ch not in r'<>:"/\|?*' else "_" for ch in name).strip()
    return cleaned or "账号"


def paths_equal(left, right):
    """宽松比较两个路径是否指向同一位置。"""
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return normalize_path_for_match(left) == normalize_path_for_match(right)


def normalize_path_for_match(path):
    """把路径转换为便于在进程命令行中匹配的文本。"""
    return str(path).replace("/", "\\").rstrip("\\").lower()


def normalize_project_config_path(path):
    """归一化 config.toml 中的项目路径键。"""
    normalized = str(path).replace("/", "\\").rstrip("\\")
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return normalized.lower()


def normalize_cap_sid_project_path(path):
    """归一化 cap_sid 中的项目路径键。"""
    normalized = str(path).replace("\\", "/").rstrip("/")
    if normalized.startswith("//?/"):
        normalized = normalized[4:]
    return normalized.lower()


def check_directory_writable(path):
    """检查目录是否可写，不保留测试文件。"""
    if not path.exists() or not path.is_dir():
        return False
    try:
        test_path = path / ".launcher_write_test"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink()
        return True
    except Exception:
        return False


def get_directory_size(path):
    """统计目录文件总大小；遇到不可读文件时跳过。"""
    total = 0
    for root, dirs, files in os.walk(path):
        root_path = Path(root)
        dirs[:] = [
            directory_name
            for directory_name in dirs
            if not is_reparse_point(root_path / directory_name)
        ]
        for file_name in files:
            file_path = root_path / file_name
            if is_reparse_point(file_path):
                continue
            try:
                total += file_path.stat().st_size
            except OSError:
                continue
    return total


def format_size(size):
    """把字节数格式化为更适合提示用户的大小。"""
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def remove_readonly_path(func, path, _exc_info):
    """移除只读文件时先补写权限，再重试删除。"""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        raise


def is_reparse_point(path):
    """判断路径是否是 Windows reparse point，例如 junction。"""
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def format_health_status(health):
    """把账号健康检查结果转换成界面短状态。"""
    if health["running"]:
        return "运行中", "#16803c"
    if health["errors"]:
        return "异常", "#b42318"
    if health["warnings"]:
        return "需处理", "#9a5b00"
    return "就绪", "#666666"

