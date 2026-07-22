from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import os
from ctypes import wintypes
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


DEFAULT_PROTECTED_KEY = (
    Path.home() / ".archivekey-release-signing" / "update-private.dpapi"
)


class DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def unprotect_with_dpapi(protected: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("The local protected release key is available only on Windows.")
    input_buffer = ctypes.create_string_buffer(protected)
    input_blob = DataBlob(
        len(protected), ctypes.cast(input_buffer, ctypes.POINTER(ctypes.c_byte))
    )
    output_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)


def load_private_key(path: Path | None) -> Ed25519PrivateKey:
    encoded = os.environ.get("ARCHIVEKEY_UPDATE_SIGNING_KEY_B64")
    if encoded:
        pem = base64.b64decode(encoded, validate=True)
    elif path:
        pem = path.read_bytes()
    else:
        pem = unprotect_with_dpapi(DEFAULT_PROTECTED_KEY.read_bytes())
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("The ArchiveKey release key is not Ed25519.")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign an ArchiveKey MSI update asset.")
    parser.add_argument("installer", type=Path)
    parser.add_argument("--private-key", type=Path)
    args = parser.parse_args()

    installer = args.installer.resolve()
    if not installer.is_file() or installer.suffix.casefold() != ".msi":
        raise SystemExit("Installer must be an existing MSI file.")
    data = installer.read_bytes()
    signature = load_private_key(args.private_key).sign(data)
    signature_path = installer.with_suffix(installer.suffix + ".sig")
    signature_path.write_bytes(base64.b64encode(signature) + b"\n")
    print(signature_path)
    print(f"sha256:{hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
