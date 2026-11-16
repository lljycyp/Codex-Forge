import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.codex_source import resolve_codex_execution_path


class CodexExecutionAliasTest(unittest.TestCase):
    def setUp(self):
        temporary_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_dir.cleanup)
        self.root = Path(temporary_dir.name)
        self.package = self.root / "WindowsApps" / "OpenAI.Codex_26.1111.2228.0_x64__publisher"
        self.source = self.package / "app" / "ChatGPT.exe"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"client")
        self.alias_root = self.root / "Local" / "Microsoft" / "WindowsApps"
        self.alias = self.alias_root / "OpenAI.Codex_publisher" / "chatgpt-desktop.exe"
        self.alias.parent.mkdir(parents=True)
        self.alias.write_bytes(b"alias")
        self.manifest = self.package / "AppxManifest.xml"
        self.manifest.write_text(
            '''<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
                xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
                xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10">
              <Identity Name="OpenAI.Codex" />
              <Applications>
                <Application Id="Helper" Executable="app/resources/helper.exe">
                  <Extensions><uap3:Extension><uap3:AppExecutionAlias>
                    <desktop:ExecutionAlias Alias="helper.exe" />
                  </uap3:AppExecutionAlias></uap3:Extension></Extensions>
                </Application>
                <Application Id="App" Executable="app\\ChatGPT.exe">
                  <Extensions><uap3:Extension><uap3:AppExecutionAlias>
                    <desktop:ExecutionAlias Alias="chatgpt-desktop.exe" />
                  </uap3:AppExecutionAlias></uap3:Extension></Extensions>
                </Application>
              </Applications>
            </Package>''',
            encoding="utf-8",
        )
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "Local")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_uses_alias_for_matching_package_and_application(self):
        (self.alias_root / "chatgpt-desktop.exe").write_bytes(b"other-package")
        (self.alias.parent / "helper.exe").write_bytes(b"helper")

        self.assertEqual(resolve_codex_execution_path(self.source), self.alias)

    def test_does_not_use_global_alias_when_package_alias_is_missing(self):
        self.alias.unlink()
        (self.alias_root / "chatgpt-desktop.exe").write_bytes(b"other-package")

        self.assertEqual(resolve_codex_execution_path(self.source), self.source)

    def test_preserves_existing_launch_path_when_manifest_is_unavailable(self):
        self.manifest.unlink()
        self.assertEqual(resolve_codex_execution_path(self.source), self.source)
        self.manifest.write_text("invalid XML", encoding="utf-8")
        self.assertEqual(resolve_codex_execution_path(self.source), self.source)

    def test_custom_client_is_not_redirected_to_installed_store_app(self):
        source = self.root / "CustomCodex" / "ChatGPT.exe"
        self.assertEqual(resolve_codex_execution_path(source), source)


if __name__ == "__main__":
    unittest.main()
