import json
import sys

from bridge.commands import invoke


def main():
    """命令行桥接入口，供桌面壳调用 Python 白名单能力。"""
    command = sys.argv[1] if len(sys.argv) > 1 else ""
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

