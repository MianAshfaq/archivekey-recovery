from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


RELEASES_API_URL = (
    "https://api.github.com/repos/MianAshfaq/archivekey-recovery/releases?per_page=10"
)
MAX_RELEASE_METADATA_BYTES = 1024 * 1024
MAX_INSTALLER_BYTES = 64 * 1024 * 1024
MAX_SIGNATURE_BYTES = 4096
ALLOWED_DOWNLOAD_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
SHA256_PATTERN = re.compile(r"^sha256:([0-9a-fA-F]{64})$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    title: str
    notes: str
    page_url: str
    installer_name: str
    installer_url: str
    installer_size: int
    installer_digest: str | None
    signature_url: str | None
    signature_size: int | None
    prerelease: bool = False

    @property
    def supports_automatic_install(self) -> bool:
        return bool(
            self.installer_digest and self.signature_url and self.signature_size
        )


def parse_version(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid semantic version: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _safe_https_url(value: str, hosts: set[str] = ALLOWED_DOWNLOAD_HOSTS) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in hosts:
        raise UpdateError("GitHub returned an untrusted update URL.")
    return value


def _asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return {}
    return {
        str(asset.get("name")): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("name")
    }


def select_newer_release(payload: object, current_version: str) -> ReleaseInfo | None:
    if not isinstance(payload, list):
        raise UpdateError("GitHub returned invalid release metadata.")
    current = parse_version(current_version)
    candidates: list[tuple[tuple[int, int, int], ReleaseInfo]] = []

    for raw_release in payload:
        if not isinstance(raw_release, dict) or raw_release.get("draft"):
            continue
        tag = str(raw_release.get("tag_name", ""))
        try:
            version_tuple = parse_version(tag)
        except ValueError:
            continue
        if version_tuple <= current:
            continue

        version = ".".join(str(part) for part in version_tuple)
        installer_name = f"ArchiveKey-{version}-x64.msi"
        signature_name = installer_name + ".sig"
        assets = _asset_map(raw_release)
        installer = assets.get(installer_name)
        if not installer:
            continue

        try:
            installer_size = int(installer.get("size", 0))
        except (TypeError, ValueError):
            continue
        if not 0 < installer_size <= MAX_INSTALLER_BYTES:
            continue
        installer_url = _safe_https_url(str(installer.get("browser_download_url", "")))

        digest = installer.get("digest")
        installer_digest = str(digest) if digest else None
        if installer_digest and not SHA256_PATTERN.fullmatch(installer_digest):
            continue

        signature = assets.get(signature_name)
        signature_url: str | None = None
        signature_size: int | None = None
        if signature:
            try:
                possible_size = int(signature.get("size", 0))
                possible_url = _safe_https_url(
                    str(signature.get("browser_download_url", ""))
                )
            except (TypeError, ValueError, UpdateError):
                possible_size = 0
                possible_url = ""
            if 0 < possible_size <= MAX_SIGNATURE_BYTES and possible_url:
                signature_size = possible_size
                signature_url = possible_url

        page_url = _safe_https_url(
            str(raw_release.get("html_url", "")), {"github.com"}
        )
        candidates.append(
            (
                version_tuple,
                ReleaseInfo(
                    version=version,
                    title=str(raw_release.get("name") or f"ArchiveKey {version}"),
                    notes=str(raw_release.get("body") or ""),
                    page_url=page_url,
                    installer_name=installer_name,
                    installer_url=installer_url,
                    installer_size=installer_size,
                    installer_digest=installer_digest,
                    signature_url=signature_url,
                    signature_size=signature_size,
                    prerelease=bool(raw_release.get("prerelease")),
                ),
            )
        )

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def fetch_newer_release(current_version: str, timeout: int = 15) -> ReleaseInfo | None:
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ArchiveKey/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        _safe_https_url(response.geturl(), {"api.github.com"})
        data = response.read(MAX_RELEASE_METADATA_BYTES + 1)
    if len(data) > MAX_RELEASE_METADATA_BYTES:
        raise UpdateError("GitHub release metadata exceeded the safe size limit.")
    try:
        payload = json.loads(data.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise UpdateError("GitHub returned unreadable release metadata.") from exc
    return select_newer_release(payload, current_version)


def _download(
    url: str,
    destination: Path,
    maximum_bytes: int,
    expected_size: int | None,
    timeout: int,
) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ArchiveKey-Updater"},
    )
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(request, timeout=timeout) as response:
        _safe_https_url(response.geturl())
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                announced_size = int(content_length)
            except ValueError as exc:
                raise UpdateError("The update server returned an invalid size.") from exc
            if announced_size > maximum_bytes:
                raise UpdateError("The update download exceeds the safe size limit.")
        with destination.open("wb") as stream:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > maximum_bytes:
                    raise UpdateError("The update download exceeds the safe size limit.")
                digest.update(chunk)
                stream.write(chunk)
    if expected_size is not None and received != expected_size:
        raise UpdateError("The downloaded update size does not match the GitHub release.")
    return received, digest.hexdigest()


def verify_ed25519_signature(
    installer: Path, signature_text: bytes, public_key_pem: bytes
) -> None:
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise UpdateError("The packaged signature verifier is unavailable.") from exc

    try:
        signature = base64.b64decode(signature_text.strip(), validate=True)
        public_key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("Unexpected update-key type.")
        public_key.verify(signature, installer.read_bytes())
    except InvalidSignature as exc:
        raise UpdateError("The installer signature is invalid. Installation was blocked.") from exc
    except (TypeError, ValueError) as exc:
        raise UpdateError("The installer signature could not be validated.") from exc


def download_verified_installer(
    release: ReleaseInfo,
    update_directory: Path,
    public_key_path: Path,
    timeout: int = 60,
) -> Path:
    if not release.supports_automatic_install:
        raise UpdateError("This release has no ArchiveKey update signature.")
    update_directory.mkdir(parents=True, exist_ok=True)
    destination = update_directory / release.installer_name
    signature_destination = destination.with_suffix(destination.suffix + ".sig")
    partial = destination.with_suffix(destination.suffix + ".part")
    signature_partial = destination.with_suffix(destination.suffix + ".sig.part")
    for stale in (partial, signature_partial):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
    try:
        _received, sha256 = _download(
            release.installer_url,
            partial,
            MAX_INSTALLER_BYTES,
            release.installer_size,
            timeout,
        )
        if release.installer_digest:
            match = SHA256_PATTERN.fullmatch(release.installer_digest)
            if not match or sha256.casefold() != match.group(1).casefold():
                raise UpdateError("The installer SHA-256 does not match GitHub's digest.")
        _download(
            release.signature_url or "",
            signature_partial,
            MAX_SIGNATURE_BYTES,
            release.signature_size,
            timeout,
        )
        verify_ed25519_signature(
            partial,
            signature_partial.read_bytes(),
            public_key_path.read_bytes(),
        )
        os.replace(partial, destination)
        os.replace(signature_partial, signature_destination)
        return destination
    except Exception:
        for stale in (partial, signature_partial):
            try:
                stale.unlink()
            except OSError:
                pass
        raise
    finally:
        try:
            signature_partial.unlink()
        except OSError:
            pass


def load_settings(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def should_check_automatically(
    settings: dict[str, Any], now: float | None = None, interval_hours: int = 24
) -> bool:
    if settings.get("automatic_update_checks") is not True:
        return False
    timestamp = settings.get("last_update_check")
    if not isinstance(timestamp, (int, float)):
        return True
    return (now if now is not None else time.time()) - float(timestamp) >= interval_hours * 3600


def wait_for_process_exit(pid: int, timeout_seconds: int = 120) -> bool:
    if os.name != "nt" or pid <= 0:
        return True
    import ctypes

    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True
    try:
        result = ctypes.windll.kernel32.WaitForSingleObject(
            handle, max(0, timeout_seconds) * 1000
        )
        return result == 0
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def run_update_helper(
    parent_pid: int,
    installer: Path,
    launch_executable: Path,
    version: str,
    state_directory: Path,
    public_key_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    launcher: Callable[..., Any] = subprocess.Popen,
    waiter: Callable[[int, int], bool] = wait_for_process_exit,
) -> int:
    state_directory.mkdir(parents=True, exist_ok=True)
    if not waiter(parent_pid, 120):
        return 2
    if not installer.is_file() or installer.suffix.casefold() != ".msi":
        return 3

    signature_path = installer.with_suffix(installer.suffix + ".sig")
    try:
        verify_ed25519_signature(
            installer,
            signature_path.read_bytes(),
            public_key_path.read_bytes(),
        )
    except (OSError, UpdateError):
        marker = state_directory / "update-error.json"
        save_settings(
            marker,
            {
                "version": version,
                "installer": installer.name,
                "exit_code": "signature-verification-failed",
            },
        )
        if launch_executable.is_file():
            launcher([str(launch_executable)], close_fds=True)
        return 5

    completed = runner(
        [
            "msiexec.exe",
            "/i",
            str(installer),
            "/passive",
            "/norestart",
        ],
        check=False,
        timeout=900,
    )
    success = completed.returncode in {0, 3010}
    marker = state_directory / ("update-complete.json" if success else "update-error.json")
    save_settings(
        marker,
        {
            "version": version,
            "installer": installer.name,
            "exit_code": completed.returncode,
        },
    )
    if launch_executable.is_file():
        launcher([str(launch_executable)], close_fds=True)
    return 0 if success else int(completed.returncode or 1)
