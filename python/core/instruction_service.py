import json
import re
import shutil
import uuid
from pathlib import Path

from core.constants import CONFIG_DIR
from core.profile_service import get_active_codex_dir, get_active_config_path


TEMPLATE_DIR = CONFIG_DIR / "instruction_templates"
TEMPLATE_INDEX_PATH = TEMPLATE_DIR / "index.json"


def list_instruction_templates(_payload=None):
    """读取本地指令模板列表，并标记当前启用项。"""
    templates = _load_index()
    current_file = _get_current_instruction_file()
    return {
        "templates": [
            {
                **template,
                "content": _template_path(template["filename"]).read_text(encoding="utf-8"),
                "enabled": bool(current_file and current_file == template["filename"]),
            }
            for template in templates
            if _template_path(template["filename"]).exists()
        ],
        "currentInstructionFile": current_file or "",
        "activeConfigPath": str(get_active_config_path()),
    }


def save_instruction_template(payload):
    """保存一个自定义指令模板到启动器本地目录。"""
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    template_id = str(payload.get("id") or "").strip() or uuid.uuid4().hex
    if not title:
        raise ValueError("模板名称不能为空")
    if not content:
        raise ValueError("模板内容不能为空")

    templates = _load_index()
    old_template = next((item for item in templates if item["id"] == template_id), None)
    current_file = _get_current_instruction_file()
    filename = _safe_filename(payload.get("filename") or title)
    if old_template and old_template["filename"] != filename:
        old_path = _template_path(old_template["filename"])
        if old_path.exists():
            old_path.unlink()
    _write_text_atomic(_template_path(filename), content + "\n")
    updated_template = {"id": template_id, "title": title, "filename": filename}
    if old_template:
        templates = [updated_template if item["id"] == template_id else item for item in templates]
    else:
        templates.append(updated_template)
    _save_index(templates)
    if old_template and current_file == old_template["filename"]:
        target = get_active_codex_dir() / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_template_path(filename), target)
        _set_instruction_file(f"./{filename}")
    return list_instruction_templates()


def delete_instruction_template(payload):
    """删除未启用的本地指令模板。"""
    template_id = str(payload.get("id") or "").strip()
    template = _find_template(template_id)
    current_file = _get_current_instruction_file()
    if current_file and current_file == template["filename"]:
        raise ValueError("当前启用的模板不能删除，请先禁用")
    path = _template_path(template["filename"])
    if path.exists():
        path.unlink()
    _save_index([item for item in _load_index() if item["id"] != template_id])
    return list_instruction_templates()


def enable_instruction_template(payload):
    """启用指定模板，写入当前 Codex 目录并更新 config.toml。"""
    template = _find_template(str(payload.get("id") or "").strip())
    source = _template_path(template["filename"])
    if not source.exists():
        raise FileNotFoundError("模板文件不存在")
    target = get_active_codex_dir() / template["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    _set_instruction_file(f"./{template['filename']}")
    return list_instruction_templates()


def disable_instruction_template(_payload=None):
    """禁用指令模板，只移除配置字段，不删除用户模板。"""
    _set_instruction_file("")
    return list_instruction_templates()


def _load_index():
    """读取模板索引，坏文件直接当空列表处理。"""
    if not TEMPLATE_INDEX_PATH.exists():
        return []
    try:
        data = json.loads(TEMPLATE_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        filename = _safe_filename(item.get("filename") or title)
        if template_id and title:
            result.append({"id": template_id, "title": title, "filename": filename})
    return result


def _save_index(templates):
    """原子保存模板索引，避免异常中断留下半截文件。"""
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(templates, ensure_ascii=False, indent=2)
    _write_text_atomic(TEMPLATE_INDEX_PATH, payload + "\n")


def _find_template(template_id):
    """按编号查找模板。"""
    for template in _load_index():
        if template["id"] == template_id:
            return template
    raise ValueError("模板不存在")


def _template_path(filename):
    """返回模板文件路径。"""
    return TEMPLATE_DIR / _safe_filename(filename)


def _safe_filename(value):
    """把用户输入转换成安全的 Markdown 文件名。"""
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip()).strip(".-")
    if not name:
        name = "instruction"
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    return name[:80]


def _get_current_instruction_file():
    """读取当前配置中的 model_instructions_file 文件名。"""
    config_path = get_active_config_path()
    if not config_path.exists():
        return ""
    text = config_path.read_text(encoding="utf-8")
    match = re.search(r'(?m)^\s*model_instructions_file\s*=\s*"([^"]*)"', text)
    if not match:
        return ""
    return Path(match.group(1).replace("\\", "/")).name


def _set_instruction_file(relative_path):
    """更新当前 config.toml 的 model_instructions_file 字段。"""
    config_path = get_active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    lines = text.splitlines()
    output = []
    replaced = False
    pattern = re.compile(r"^\s*model_instructions_file\s*=")
    for line in lines:
        if pattern.match(line):
            if relative_path:
                output.append(f'model_instructions_file = "{relative_path}"')
            replaced = True
            continue
        output.append(line)
    if relative_path and not replaced:
        output.insert(0, f'model_instructions_file = "{relative_path}"')
    _write_text_atomic(config_path, "\n".join(output).rstrip() + "\n")


def _write_text_atomic(path, text):
    """用临时文件替换目标文件，避免写入中断。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
