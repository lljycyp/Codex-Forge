import ctypes
import ctypes.wintypes
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path


_held_locks = threading.local()


@contextmanager
def _exclusive_file_lock(lock_path, timeout_seconds=60):
    """跨进程互斥，同一线程内允许重入。"""
    lock_path = Path(lock_path).resolve()
    held = getattr(_held_locks, "paths", None)
    if held is None:
        held = _held_locks.paths = set()
    if lock_path in held:
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds
    file_handle = None
    while True:
        try:
            file_handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(file_handle, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if _remove_stale_process_lock(lock_path):
                continue
            if time.time() >= deadline:
                raise TimeoutError(f"等待账号 App Server 锁超时：{lock_path}")
            time.sleep(0.08)
    held.add(lock_path)
    try:
        yield
    finally:
        held.remove(lock_path)
        if file_handle is not None:
            os.close(file_handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _remove_stale_process_lock(lock_path):
    """锁内进程已退出时清理残留锁。"""
    try:
        owner_pid = int(lock_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return False
    if _is_process_running(owner_pid):
        return False
    try:
        if lock_path.read_text(encoding="utf-8").strip() != str(owner_pid):
            return False
        lock_path.unlink()
        return True
    except (FileNotFoundError, OSError):
        return False


def _is_process_running(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        handle = kernel32.OpenProcess(0x00100000, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() != 87
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


