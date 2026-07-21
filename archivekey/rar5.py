from __future__ import annotations

import hashlib
import hmac
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
RAR5_HASH = re.compile(
    r"\$rar5\$16\$([0-9a-fA-F]{32})\$(\d+)\$([0-9a-fA-F]{32})\$8\$([0-9a-fA-F]{16})"
)


class Rar5FormatError(RuntimeError):
    pass


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise Rar5FormatError("Unexpected end of RAR archive.")
    return data


def _read_vint_from_stream(stream: BinaryIO) -> tuple[int, bytes]:
    value = 0
    encoded = bytearray()
    for index in range(10):
        current = _read_exact(stream, 1)[0]
        encoded.append(current)
        value |= (current & 0x7F) << (index * 7)
        if current & 0x80 == 0:
            return value, bytes(encoded)
    raise Rar5FormatError("Invalid RAR variable-length integer.")


def _read_vint(data: bytes, offset: int, limit: int | None = None) -> tuple[int, int]:
    end = len(data) if limit is None else min(limit, len(data))
    value = 0
    for index in range(10):
        if offset >= end:
            raise Rar5FormatError("Truncated RAR variable-length integer.")
        current = data[offset]
        offset += 1
        value |= (current & 0x7F) << (index * 7)
        if current & 0x80 == 0:
            return value, offset
    raise Rar5FormatError("Invalid RAR variable-length integer.")


def _fold_password_check(value: bytes) -> bytes:
    if len(value) != 32:
        raise ValueError("RAR 5 password-check input must be 32 bytes.")
    return bytes(value[i] ^ value[i + 8] ^ value[i + 16] ^ value[i + 24] for i in range(8))


@dataclass(frozen=True)
class Rar5Target:
    salt: bytes
    lg2_count: int
    password_check: bytes

    @property
    def iterations(self) -> int:
        return 1 << self.lg2_count

    @classmethod
    def from_hash(cls, value: str) -> "Rar5Target":
        match = RAR5_HASH.search(value)
        if not match:
            raise Rar5FormatError("Not a supported RAR 5 password-check hash.")
        salt_hex, lg2_text, _unused_check, password_check_hex = match.groups()
        return cls(bytes.fromhex(salt_hex), int(lg2_text), bytes.fromhex(password_check_hex))

    @classmethod
    def from_archive(cls, archive: str | Path) -> "Rar5Target":
        path = Path(archive)
        with path.open("rb") as stream:
            signature_window = stream.read(1024 * 1024 + len(RAR5_SIGNATURE))
            signature_offset = signature_window.find(RAR5_SIGNATURE)
            if signature_offset < 0:
                raise Rar5FormatError("RAR 5 signature was not found.")
            stream.seek(signature_offset + len(RAR5_SIGNATURE))

            while stream.tell() < path.stat().st_size:
                stored_crc = struct.unpack("<I", _read_exact(stream, 4))[0]
                header_size, encoded_header_size = _read_vint_from_stream(stream)
                if header_size > 2 * 1024 * 1024:
                    raise Rar5FormatError("RAR header exceeds the supported size.")
                header = _read_exact(stream, header_size)
                if zlib.crc32(encoded_header_size + header) & 0xFFFFFFFF != stored_crc:
                    raise Rar5FormatError("RAR header checksum is invalid.")

                offset = 0
                header_type, offset = _read_vint(header, offset)
                header_flags, offset = _read_vint(header, offset)
                extra_size = 0
                data_size = 0
                if header_flags & 0x0001:
                    extra_size, offset = _read_vint(header, offset)
                if header_flags & 0x0002:
                    data_size, offset = _read_vint(header, offset)

                if header_type == 4:  # Archive encryption header.
                    target = cls._parse_encryption_record(header, offset, len(header), has_iv=False)
                    if target:
                        return target

                if extra_size:
                    if extra_size > len(header):
                        raise Rar5FormatError("Invalid RAR extra-area size.")
                    extra_offset = len(header) - extra_size
                    target = cls._parse_extra_area(header, extra_offset, len(header))
                    if target:
                        return target

                if data_size:
                    stream.seek(data_size, 1)

        raise Rar5FormatError("No RAR 5 password-check record was found.")

    @classmethod
    def _parse_extra_area(cls, data: bytes, offset: int, end: int) -> "Rar5Target | None":
        while offset < end:
            record_size, offset = _read_vint(data, offset, end)
            record_end = offset + record_size
            if record_end > end:
                raise Rar5FormatError("RAR extra record exceeds its header.")
            record_type, payload_offset = _read_vint(data, offset, record_end)
            if record_type == 1:  # File encryption record.
                target = cls._parse_encryption_record(data, payload_offset, record_end, has_iv=True)
                if target:
                    return target
            offset = record_end
        return None

    @classmethod
    def _parse_encryption_record(
        cls, data: bytes, offset: int, end: int, *, has_iv: bool
    ) -> "Rar5Target | None":
        version, offset = _read_vint(data, offset, end)
        flags, offset = _read_vint(data, offset, end)
        if version != 0 or flags & 0x0001 == 0:
            return None
        if offset >= end:
            raise Rar5FormatError("Truncated RAR encryption record.")
        lg2_count = data[offset]
        offset += 1
        required = 16 + (16 if has_iv else 0) + 12
        if offset + required > end:
            raise Rar5FormatError("Truncated RAR password-check record.")
        salt = data[offset : offset + 16]
        offset += 16
        if has_iv:
            offset += 16
        password_check = data[offset : offset + 8]
        return cls(salt, lg2_count, password_check)

    def derive_password_check(self, password: str) -> bytes:
        # RAR 5 derives the key at N iterations, then continues the same PBKDF2
        # chain for 32 rounds. Standard PBKDF2 at N+32 yields that final value.
        value = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), self.salt, self.iterations + 32, dklen=32
        )
        return _fold_password_check(value)

    def matches(self, password: str) -> bool:
        return hmac.compare_digest(self.derive_password_check(password), self.password_check)
