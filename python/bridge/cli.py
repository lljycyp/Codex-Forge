import json
import sys

from bridge.commands import invoke


def main():
    """命令行桥接入口，供桌面壳调用 Python 白名单能力。"""
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "run_load_balancer":
        from core.load_balancer import run_service

        return run_service()
    if command in ("get_load_balancer_preferences", "disable_load_balancer"):
        from core.config_store import load_config
        from core.load_balancer import save_enabled

        if command == "disable_load_balancer":
            save_enabled(False)
        config = load_config()
        print(json.dumps({"ok": True, "data": {
            "enabled": bool(config.get("load_balancer_enabled")),
            "port": config.get("load_balancer_port", 19380),
        }, "error": ""}))
        return 0
    payload_text = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        payload = {}
    result = invoke(command, payload)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

