from __future__ import annotations

import io
import zipfile

from w2p.downloads import safe_archive_name, terraform_file_count, terraform_zip_bytes
from w2p.models import GeneratedFile


def test_terraform_zip_contains_only_terraform_folder() -> None:
    files = [
        GeneratedFile(path="terraform/main.tf", content="resource x"),
        GeneratedFile(path="terraform/variables.tf", content="variable x"),
        GeneratedFile(path="backend/app/main.py", content="print('skip')"),
    ]

    payload = terraform_zip_bytes(files)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == ["terraform/main.tf", "terraform/variables.tf"]
        assert archive.read("terraform/main.tf").decode() == "resource x"

    assert terraform_file_count(files) == 2
    assert safe_archive_name("Checkout Platform!") == "checkout-platform-terraform.zip"

