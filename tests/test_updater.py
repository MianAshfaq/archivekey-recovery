import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from archivekey.updater import (
    ReleaseInfo,
    UpdateError,
    download_verified_installer,
    parse_version,
    run_update_helper,
    select_newer_release,
    should_check_automatically,
    verify_ed25519_signature,
)


def release(version: str, *, signed: bool = True, draft: bool = False):
    name = f"ArchiveKey-{version}-x64.msi"
    assets = [
        {
            "name": name,
            "size": 12_000_000,
            "digest": "sha256:" + "a" * 64,
            "browser_download_url": (
                f"https://github.com/MianAshfaq/archivekey-recovery/releases/"
                f"download/v{version}/{name}"
            ),
        }
    ]
    if signed:
        assets.append(
            {
                "name": name + ".sig",
                "size": 89,
                "browser_download_url": (
                    f"https://github.com/MianAshfaq/archivekey-recovery/releases/"
                    f"download/v{version}/{name}.sig"
                ),
            }
        )
    return {
        "tag_name": f"v{version}",
        "name": f"ArchiveKey {version}",
        "body": "Synthetic release notes.",
        "html_url": (
            f"https://github.com/MianAshfaq/archivekey-recovery/releases/tag/v{version}"
        ),
        "draft": draft,
        "prerelease": True,
        "assets": assets,
    }


class UpdaterTests(unittest.TestCase):
    def test_semantic_version_comparison(self):
        self.assertEqual(parse_version("v1.12.3"), (1, 12, 3))
        self.assertGreater(parse_version("0.10.0"), parse_version("0.9.9"))

    def test_selects_newest_release_with_exact_installer(self):
        selected = select_newer_release(
            [release("0.8.0"), release("0.7.2"), release("0.9.0", draft=True)],
            "0.7.0",
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.version, "0.8.0")
        self.assertTrue(selected.supports_automatic_install)

    def test_unsigned_release_is_announced_but_not_auto_installed(self):
        selected = select_newer_release([release("0.8.0", signed=False)], "0.7.0")
        self.assertIsNotNone(selected)
        self.assertFalse(selected.supports_automatic_install)

    def test_release_without_github_digest_is_not_auto_installed(self):
        payload = release("0.8.0")
        payload["assets"][0]["digest"] = None
        selected = select_newer_release([payload], "0.7.0")
        self.assertIsNotNone(selected)
        self.assertFalse(selected.supports_automatic_install)

    def test_rejects_untrusted_asset_host(self):
        payload = release("0.8.0")
        payload["assets"][0]["browser_download_url"] = "https://example.com/update.msi"
        with self.assertRaises(UpdateError):
            select_newer_release([payload], "0.7.0")

    def test_ed25519_signature_accepts_original_and_rejects_tamper(self):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / "ArchiveKey-test.msi"
            installer.write_bytes(b"synthetic installer bytes")
            signature = base64.b64encode(private_key.sign(installer.read_bytes()))
            verify_ed25519_signature(installer, signature, public_key)
            installer.write_bytes(b"tampered installer bytes")
            with self.assertRaises(UpdateError):
                verify_ed25519_signature(installer, signature, public_key)

    def test_automatic_check_interval(self):
        self.assertFalse(should_check_automatically({}))
        self.assertTrue(
            should_check_automatically(
                {"automatic_update_checks": True, "last_update_check": 0}, now=90_000
            )
        )
        self.assertFalse(
            should_check_automatically(
                {"automatic_update_checks": True, "last_update_check": 89_000},
                now=90_000,
            )
        )

    def test_update_helper_writes_completion_marker_and_relaunches(self):
        launched = []

        def runner(*_args, **_kwargs):
            return SimpleNamespace(returncode=0)

        def launcher(args, **_kwargs):
            launched.append(args)
            return SimpleNamespace()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = root / "ArchiveKey-0.8.0-x64.msi"
            signature = root / "ArchiveKey-0.8.0-x64.msi.sig"
            executable = root / "ArchiveKey.exe"
            installer.write_bytes(b"msi")
            executable.write_bytes(b"exe")
            private_key = Ed25519PrivateKey.generate()
            signature.write_bytes(base64.b64encode(private_key.sign(installer.read_bytes())))
            public_key = root / "update-public.pem"
            public_key.write_bytes(
                private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            code = run_update_helper(
                123,
                installer,
                executable,
                "0.8.0",
                root,
                public_key,
                runner=runner,
                launcher=launcher,
                waiter=lambda _pid, _timeout: True,
            )
            self.assertEqual(code, 0)
            self.assertTrue((root / "update-complete.json").is_file())
            self.assertEqual(launched, [[str(executable)]])

    def test_verified_download_retains_signature_for_install_helper(self):
        installer_bytes = b"synthetic signed msi"
        private_key = Ed25519PrivateKey.generate()
        signature_bytes = base64.b64encode(private_key.sign(installer_bytes))
        release_info = ReleaseInfo(
            version="0.8.0",
            title="ArchiveKey 0.8.0",
            notes="Synthetic release notes.",
            page_url="https://github.com/MianAshfaq/archivekey-recovery/releases/tag/v0.8.0",
            installer_name="ArchiveKey-0.8.0-x64.msi",
            installer_url="https://github.com/example/ArchiveKey-0.8.0-x64.msi",
            installer_size=len(installer_bytes),
            installer_digest="sha256:" + hashlib.sha256(installer_bytes).hexdigest(),
            signature_url="https://github.com/example/ArchiveKey-0.8.0-x64.msi.sig",
            signature_size=len(signature_bytes),
        )

        def fake_download(url, destination, *_args):
            content = signature_bytes if url.endswith(".sig") else installer_bytes
            destination.write_bytes(content)
            return len(content), hashlib.sha256(content).hexdigest()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public_key = root / "update-public.pem"
            public_key.write_bytes(
                private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            with patch("archivekey.updater._download", side_effect=fake_download):
                installer = download_verified_installer(
                    release_info,
                    root / "updates",
                    public_key,
                )

            self.assertEqual(installer.read_bytes(), installer_bytes)
            self.assertEqual(
                installer.with_suffix(installer.suffix + ".sig").read_bytes(),
                signature_bytes,
            )

    def test_update_helper_blocks_a_replaced_installer(self):
        runner_called = False

        def runner(*_args, **_kwargs):
            nonlocal runner_called
            runner_called = True
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            installer = root / "ArchiveKey-0.8.0-x64.msi"
            signature = root / "ArchiveKey-0.8.0-x64.msi.sig"
            public_key = root / "update-public.pem"
            private_key = Ed25519PrivateKey.generate()
            installer.write_bytes(b"original")
            signature.write_bytes(base64.b64encode(private_key.sign(installer.read_bytes())))
            public_key.write_bytes(
                private_key.public_key().public_bytes(
                    serialization.Encoding.PEM,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            installer.write_bytes(b"replaced after initial verification")

            code = run_update_helper(
                123,
                installer,
                root / "missing.exe",
                "0.8.0",
                root,
                public_key,
                runner=runner,
                waiter=lambda _pid, _timeout: True,
            )

            self.assertEqual(code, 5)
            self.assertFalse(runner_called)
            self.assertTrue((root / "update-error.json").is_file())


if __name__ == "__main__":
    unittest.main()
