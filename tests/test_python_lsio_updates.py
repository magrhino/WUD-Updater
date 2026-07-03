from __future__ import annotations

import pytest

from wudup.lsio_updates import classify_lsio_update, parse_lsio_tag


@pytest.mark.parametrize(
    ("tag", "kind", "arch", "branch", "upstream_version", "build_suffix"),
    [
        ("2.6.0-ls224", "build", "", "", "2.6.0", "ls224"),
        ("nightly-4.7.2.7675-ls481", "build", "", "nightly", "4.7.2.7675", "ls481"),
        (
            "amd64-nightly-4.7.2.7675-ls481",
            "build",
            "amd64",
            "nightly",
            "4.7.2.7675",
            "ls481",
        ),
        ("version-2.6.0", "version", "", "", "2.6.0", ""),
        (
            "arm64v8-nightly-version-4.7.2.7675",
            "version",
            "arm64v8",
            "nightly",
            "4.7.2.7675",
            "",
        ),
        ("latest", "branch", "", "latest", "", ""),
        ("2.6.0", "pseudo_semver", "", "", "2.6.0", ""),
    ],
)
def test_parse_lsio_tag_extracts_known_shapes(
    tag: str,
    kind: str,
    arch: str,
    branch: str,
    upstream_version: str,
    build_suffix: str,
) -> None:
    parts = parse_lsio_tag(tag)

    assert parts.raw == tag
    assert parts.kind == kind
    assert parts.arch == arch
    assert parts.branch == branch
    assert parts.upstream_version == upstream_version
    assert parts.build_suffix == build_suffix


@pytest.mark.parametrize(
    ("current_tag", "target_tag"),
    [
        ("2.6.0-ls224", "2.6.0-ls225"),
        ("nightly-4.7.2.7675-ls481", "nightly-4.7.2.7675-ls482"),
        (
            "amd64-nightly-4.7.2.7675-ls481",
            "amd64-nightly-4.7.2.7675-ls482",
        ),
        ("version-2.6.0", "version-2.6.0"),
        ("version-5.2.2_v2.0.13", "5.2.2_v2.0.13-ls464"),
        (
            "libtorrentv1-version-5.2.2_v1.2.20",
            "libtorrentv1-5.2.2_v1.2.20-ls122",
        ),
    ],
)
def test_classify_lsio_update_detects_image_rebuild(
    current_tag: str,
    target_tag: str,
) -> None:
    classification = classify_lsio_update(
        image_repo="linuxserver/docker-swag",
        current_tag=current_tag,
        target_tag=target_tag,
    )

    assert classification.change_type == "image_rebuild"


@pytest.mark.parametrize(
    ("current_tag", "target_tag"),
    [
        ("2.6.0-ls224", "2.7.0-ls1"),
        ("nightly-4.7.2.7675-ls481", "nightly-4.8.0.1-ls1"),
        ("version-2.6.0", "version-2.7.0"),
        ("5.21.1", "5.22.4"),
        ("version-5.2.1_v2.0.13", "5.2.2_v2.0.13-ls464"),
    ],
)
def test_classify_lsio_update_detects_upstream_update(
    current_tag: str,
    target_tag: str,
) -> None:
    classification = classify_lsio_update(
        image_repo="linuxserver/docker-swag",
        current_tag=current_tag,
        target_tag=target_tag,
    )

    assert classification.change_type == "upstream_update"


@pytest.mark.parametrize(
    ("image_repo", "current_tag", "target_tag"),
    [
        ("acme/app", "2.6.0-ls224", "2.6.0-ls225"),
        ("acme/app", "2.6.0", "2.7.0"),
        ("linuxserver/docker-swag", "latest", ""),
        ("linuxserver/docker-swag", "latest", "latest"),
        ("linuxserver/docker-swag", "nightly-2.6.0-ls224", "develop-2.6.0-ls225"),
        ("linuxserver/docker-swag", "amd64-2.6.0-ls224", "arm64v8-2.6.0-ls225"),
    ],
)
def test_classify_lsio_update_fails_closed_for_ambiguous_inputs(
    image_repo: str,
    current_tag: str,
    target_tag: str,
) -> None:
    classification = classify_lsio_update(
        image_repo=image_repo,
        current_tag=current_tag,
        target_tag=target_tag,
    )

    assert classification.change_type == "unknown"


def test_classify_lsio_update_uses_explicit_upstream_version_metadata() -> None:
    classification = classify_lsio_update(
        image_repo="linuxserver/docker-swag",
        current_tag="2.6.0-ls224",
        target_tag="2.7.0",
        upstream_version="v2.7.0",
    )

    assert classification.change_type == "upstream_update"
