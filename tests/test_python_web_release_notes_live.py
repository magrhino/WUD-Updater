from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from tests.web_test_helpers import _client

from wudup.release_notes import OCI_SOURCE_LABEL

pytestmark = pytest.mark.skipif(
    os.environ.get("WUD_LIVE_DOCKER_TESTS") != "1",
    reason="set WUD_LIVE_DOCKER_TESTS=1 to run live Docker release-note tests",
)


SOURCE_IMAGE = "ghcr.io/magrhino/wudup:latest"
LOCAL_IMAGE = "wudup-issue259:live"
LOCAL_REPO = "wudup-issue259"
SOURCE_LABEL = "https://github.com/magrhino/wudup"


def test_live_release_notes_resolve_digest_pinned_image_labels(tmp_path: Path) -> None:
    _docker("pull", SOURCE_IMAGE, timeout=300)
    source_label = _image_label(SOURCE_IMAGE, OCI_SOURCE_LABEL)
    assert source_label == SOURCE_LABEL
    digest = _image_digest(SOURCE_IMAGE)
    local_digest_image = f"{LOCAL_IMAGE}@{digest}"
    bare_digest_image = f"{LOCAL_REPO}@{digest}"
    container_name = f"wudup-issue259-{os.getpid()}"

    _docker("tag", SOURCE_IMAGE, LOCAL_IMAGE)
    try:
        direct = _docker("image", "inspect", local_digest_image, check=False)
        if direct.returncode == 0:
            pytest.skip(
                "Docker can inspect tag+digest refs directly in this environment"
            )

        client = _client(
            tmp_path,
            {
                "WUD_WEB_DEV_NO_AUTH": "true",
                "WUD_API_BASE_URL": "http://127.0.0.1:1",
            },
        )
        wud_file = tmp_path / "state" / "images.todo"
        wud_file.write_text(f"{local_digest_image}\n", encoding="utf-8")

        response = client.get("/api/v1/release-notes")
        assert response.status_code == 200
        item = response.json()["items"][0]
        assert item["provider"] == "github"
        assert item["upstream_repo"] == "magrhino/wudup"

        _docker("run", "-d", "--name", container_name, LOCAL_IMAGE, "sleep", "60")
        try:
            wud_file.write_text(f"{bare_digest_image}\n", encoding="utf-8")

            response = client.get("/api/v1/release-notes")
            assert response.status_code == 200
            item = response.json()["items"][0]
            assert item["provider"] == "github"
            assert item["upstream_repo"] == "magrhino/wudup"
        finally:
            _docker("rm", "-f", container_name, check=False)
    finally:
        _docker("rmi", LOCAL_IMAGE, check=False)


def _image_label(image: str, label: str) -> str:
    result = _docker(
        "image",
        "inspect",
        "--format",
        f'{{{{ index .Config.Labels "{label}" }}}}',
        image,
    )
    return result.stdout.strip()


def _image_digest(image: str) -> str:
    result = _docker(
        "image",
        "inspect",
        "--format",
        "{{range .RepoDigests}}{{println .}}{{end}}",
        image,
    )
    for line in result.stdout.splitlines():
        if "@sha256:" in line:
            return line.rsplit("@", 1)[1]
    pytest.fail(f"no RepoDigests sha256 value found for {image}")


def _docker(
    *args: str,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ("docker", *args),
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        pytest.skip("docker command is not available")
    if check and result.returncode != 0:
        pytest.fail(
            "docker command failed: "
            f"docker {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n"
            f"{result.stderr}"
        )
    return result
