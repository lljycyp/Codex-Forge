import re
import shutil
import uuid
from pathlib import Path

from core import db
from core.constants import CONFIG_DIR
from core.path_utils import resource_path
from core.profile_service import get_active_codex_dir, get_active_config_path


DEFAULT_TEMPLATE_DIR = CONFIG_DIR / "instruction_templates"
BUILTIN_TEMPLATES = (
    {
        "id": "builtin-gpt-5.5-unrestricted",
        "title": "GPT-5.5 破除限制",
        "filename": "gpt5.5-unrestricted.md",
    },
    {
        "id": "builtin-gpt-5.6-sol-unrestricted",
        "title": "GPT-5.6 Sol 破除限制",
        "filename": "gpt-5.6-sol-unrestricted.md",
    },
)


def list_instruction_templates(_payload=None):
    """读取本地指令模板列表，并标记当前启用项。"""
    payload = _payload or {}
    template_dir = _template_dir(payload)
    ensure_builtin_instruction_templates(payload)
    templates = _load_index(template_dir)
    config_path = Path(payload.get("configPath") or get_active_config_path())
    current_file = _get_current_instruction_file(config_path)
    return {
        "templates": [
            {
                **template,
                "content": _template_path(template["filename"], template_dir).read_text(encoding="utf-8"),
                "enabled": bool(current_file and current_file == template["filename"]),
            }
            for template in templates
            if _template_path(template["filename"], template_dir).exists()
        ],
        "currentInstructionFile": current_file or "",
        "activeConfigPath": str(config_path),
    }


def ensure_builtin_instruction_templates(payload=None):
    """补齐内置指令模板，但不覆盖同名模板，也不自动启用。"""
    template_dir = _template_dir(payload)
    templates = _load_index(template_dir)
    filenames = {template["filename"] for template in templates}
    changed = False
    for builtin in BUILTIN_TEMPLATES:
        filename = builtin["filename"]
        target = _template_path(filename, template_dir)
        if not target.exists():
            source = resource_path("docs", "propmt", filename)
            if not source.is_file():
                raise FileNotFoundError(f"内置指令模板不存在：{filename}")
            _write_text_atomic(target, source.read_text(encoding="utf-8"))
        if filename not in filenames:
            templates.append(dict(builtin))
            filenames.add(filename)
            changed = True
    if changed:
        _save_index(templates, template_dir)


def save_instruction_template(payload):
    """保存一个自定义指令模板到启动器本地目录。"""
    payload = payload or {}
    template_dir = _template_dir(payload)
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    template_id = str(payload.get("id") or "").strip() or uuid.uuid4().hex
    if not title:
        raise ValueError("模板名称不能为空")
    if not content:
        raise ValueError("模板内容不能为空")

    templates = _load_index(template_dir)
    old_template = next((item for item in templates if item["id"] == template_id), None)
    config_path = Path(payload.get("configPath") or get_active_config_path())
    current_file = _get_current_instruction_file(config_path)
    filename = _safe_filename(payload.get("filename") or title)
    if old_template and old_template["filename"] != filename:
        old_path = _template_path(old_template["filename"], template_dir)
        if old_path.exists():
            old_path.unlink()
    _write_text_atomic(_template_path(filename, template_dir), content + "\n")
    updated_template = {"id": template_id, "title": title, "filename": filename}
    if old_template:
        templates = [updated_template if item["id"] == template_id else item for item in templates]
    else:
        templates.append(updated_template)
    _save_index(templates, template_dir)
    if old_template and current_file == old_template["filename"]:
        target = Path(payload.get("codexHome") or get_active_codex_dir()) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_template_path(filename, template_dir), target)
        _set_instruction_file(f"./{filename}", config_path)
    return list_instruction_templates({**payload, "configPath": str(config_path)})


def delete_instruction_template(payload):
    """删除未启用的本地指令模板。"""
    payload = payload or {}
    template_dir = _template_dir(payload)
    template_id = str(payload.get("id") or "").strip()
    template = _find_template(template_id, template_dir)
    config_path = Path(payload.get("configPath") or get_active_config_path())
    current_file = _get_current_instruction_file(config_path)
    if current_file and current_file == template["filename"]:
        raise ValueError("当前启用的模板不能删除，请先禁用")
    path = _template_path(template["filename"], template_dir)
    if path.exists():
        path.unlink()
    _save_index([item for item in _load_index(template_dir) if item["id"] != template_id], template_dir)
    return list_instruction_templates({**payload, "configPath": str(config_path)})


def sync_instruction_template(payload):
    """把一个模板复制到另一个模板目录，不启用它。"""
    payload = payload or {}
    source_dir = _template_dir(payload)
    target_dir = Path(payload.get("targetTemplateDir") or "")
    if not target_dir:
        raise ValueError("目标模板目录不能为空")
    template = _find_template(str(payload.get("id") or "").strip(), source_dir)
    source = _template_path(template["filename"], source_dir)
    if not source.exists():
        raise FileNotFoundError("模板文件不存在")
    _write_text_atomic(_template_path(template["filename"], target_dir), source.read_text(encoding="utf-8"))
    templates = [item for item in _load_index(target_dir) if item["id"] != template["id"]]
    templates.append(template)
    _save_index(templates, target_dir)
    return {"id": template["id"], "filename": template["filename"]}


def enable_instruction_template(payload):
    """启用指定模板，写入当前 Codex 目录并更新 config.toml。"""
    payload = payload or {}
    template_dir = _template_dir(payload)
    template = _find_template(str(payload.get("id") or "").strip(), template_dir)
    source = _template_path(template["filename"], template_dir)
    if not source.exists():
        raise FileNotFoundError("模板文件不存在")
    codex_home = Path(payload.get("codexHome") or get_active_codex_dir())
    config_path = Path(payload.get("configPath") or get_active_config_path())
    target = codex_home / template["filename"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    _set_instruction_file(f"./{template['filename']}", config_path)
    return list_instruction_templates({**payload, "configPath": str(config_path)})


def disable_instruction_template(_payload=None):
    """禁用指令模板，只移除配置字段，不删除用户模板。"""
    payload = _payload or {}
    config_path = Path(payload.get("configPath") or get_active_config_path())
    _set_instruction_file("", config_path)
    return list_instruction_templates({**payload, "configPath": str(config_path)})


def _template_dir(payload=None):
    return Path((payload or {}).get("templateDir") or DEFAULT_TEMPLATE_DIR)


def _load_index(template_dir=None):
    """读取模板索引。"""
    data = db.load_instruction_templates(_template_scope(template_dir))
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


def _save_index(templates, template_dir=None):
    """保存模板索引。"""
    template_dir = Path(template_dir or DEFAULT_TEMPLATE_DIR)
    template_dir.mkdir(parents=True, exist_ok=True)
    db.save_instruction_templates(_template_scope(template_dir), templates)


def _template_scope(template_dir=None):
    return str(Path(template_dir or DEFAULT_TEMPLATE_DIR).resolve())


def _find_template(template_id, template_dir=None):
    """按编号查找模板。"""
    for template in _load_index(template_dir):
        if template["id"] == template_id:
            return template
    raise ValueError("模板不存在")


def _template_path(filename, template_dir=None):
    """返回模板文件路径。"""
    return Path(template_dir or DEFAULT_TEMPLATE_DIR) / _safe_filename(filename)


def _safe_filename(value):
    """把用户输入转换成安全的 Markdown 文件名。"""
    name = re.sub(r"[^0-9A-Za-z._-]+", "-", str(value or "").strip()).strip(".-")
    if not name:
        name = "instruction"
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    return name[:80]


def _get_current_instruction_file(config_path=None):
    """读取当前配置中的 model_instructions_file 文件名。"""
    config_path = Path(config_path or get_active_config_path())
    if not config_path.exists():
        return ""
    text = config_path.read_text(encoding="utf-8")
    match = re.search(r'(?m)^\s*model_instructions_file\s*=\s*"([^"]*)"', text)
    if not match:
        return ""
    return Path(match.group(1).replace("\\", "/")).name


def _set_instruction_file(relative_path, config_path=None):
    """更新当前 config.toml 的 model_instructions_file 字段。"""
    config_path = Path(config_path or get_active_config_path())
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
