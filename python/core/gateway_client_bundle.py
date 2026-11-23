import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZIP_DEFLATED, ZipFile


def _launcher(restore=False):
    argument = " -Restore" if restore else ""
    return (
        '@echo off\r\n'
        'setlocal\r\n'
        '"%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" '
        '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0forge-lan-config.ps1"'
        f'{argument}\r\n'
        'set "forge_exit=%errorlevel%"\r\n'
        'pause\r\n'
        'exit /b %forge_exit%\r\n'
    )


def export_client_bundle(destination, base_url, certificate, script):
    destination = Path(destination)
    pem = Path(certificate).read_bytes()
    if not pem.startswith(b"-----BEGIN CERTIFICATE-----") or b"PRIVATE KEY" in pem:
        raise ValueError("找不到有效的 Forge 公共证书")
    source = Path(script).read_text(encoding="utf-8-sig")
    with NamedTemporaryFile(dir=destination.parent, suffix=".zip", delete=False) as temporary:
        temp_path = Path(temporary.name)
    try:
        with ZipFile(temp_path, "w", ZIP_DEFLATED) as bundle:
            bundle.writestr("Apply-Forge-Gateway.cmd", _launcher())
            bundle.writestr("Restore-Codex-Settings.cmd", _launcher(restore=True))
            bundle.writestr("forge-lan-config.ps1", source.encode("utf-8-sig"))
            bundle.writestr("forge-gateway-ca.pem", pem)
            bundle.writestr("gateway.json", json.dumps({"baseUrl": base_url}) + "\n")
        temp_path.replace(destination)
    finally:
        temp_path.unlink(missing_ok=True)
