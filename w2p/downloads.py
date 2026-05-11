from __future__ import annotations

import io
import re
import zipfile

from .models import GeneratedFile


def terraform_zip_bytes(files: list[GeneratedFile]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(files, key=lambda item: item.path):
            if not file.path.startswith("terraform/"):
                continue
            archive.writestr(file.path, file.content)
    return buffer.getvalue()


def terraform_file_count(files: list[GeneratedFile]) -> int:
    return sum(1 for file in files if file.path.startswith("terraform/"))


def safe_archive_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9-]+", "-", name).strip("-").lower()
    return f"{slug or 'w2p'}-terraform.zip"

