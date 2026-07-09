from __future__ import annotations

import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest


def load_script():
    script = Path(__file__).resolve().parents[1] / "scripts" / (
        "update-lsio-upstreams.py"
    )
    spec = importlib.util.spec_from_file_location("update_lsio_upstreams", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lsio = load_script()


def write_metadata(root: Path, repo: str, filename: str, project_url: str) -> None:
    repo_dir = root / repo
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / filename).write_text(
        f'---\nproject_url: "{project_url}"\n',
        encoding="utf-8",
    )


def write_jenkins_ext(root: Path, repo: str, user: str, name: str) -> None:
    repo_dir = root / repo
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "jenkins-vars.yml").write_text(
        f"---\nrepo_vars:\n  - EXT_USER = '{user}'\n  - EXT_REPO = '{name}'\n",
        encoding="utf-8",
    )


def test_source_dir_reads_readme_vars_then_jenkins_and_github_only(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    write_metadata(source, "docker-radarr", "readme-vars.yml", "https://github.com/Radarr/Radarr/")
    write_metadata(
        source,
        "docker-fallback",
        "jenkins-vars.yml",
        "https://github.com/example/fallback",
    )
    no_project_dir = source / "docker-no-project"
    no_project_dir.mkdir()
    (no_project_dir / "readme-vars.yml").write_text(
        "---\nproject_name: no-project\n",
        encoding="utf-8",
    )
    write_metadata(
        source,
        "docker-no-project",
        "jenkins-vars.yml",
        "https://github.com/example/no-project",
    )
    write_metadata(source, "docker-web", "readme-vars.yml", "https://example.com/app")

    scan = lsio.source_entries_from_dir(source)

    assert scan.entries == {
        "linuxserver/docker-fallback": "example/fallback",
        "linuxserver/docker-no-project": "example/no-project",
        "linuxserver/docker-radarr": "Radarr/Radarr",
    }
    assert "linuxserver/docker-web" in scan.seen


def test_source_dir_falls_back_to_jenkins_ext_after_homepage_url(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    write_metadata(source, "docker-bazarr", "readme-vars.yml", "https://www.bazarr.media/")
    write_jenkins_ext(source, "docker-bazarr", "morpheus65535", "bazarr")

    assert lsio.source_entries_from_dir(source).entries == {
        "linuxserver/docker-bazarr": "morpheus65535/bazarr",
    }


def test_source_dir_accepts_single_repo_checkout(tmp_path: Path):
    source = tmp_path / "source"
    write_metadata(source, "docker-radarr", "readme-vars.yml", "https://github.com/Radarr/Radarr/")

    assert lsio.source_entries_from_dir(source / "docker-radarr").entries == {
        "linuxserver/docker-radarr": "Radarr/Radarr",
    }


def test_render_preserves_commented_overrides_and_sorts(tmp_path: Path):
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text(
        """# old header

linuxserver/docker-zed: old/zed
# Manual override.
linuxserver/docker-emby: MediaBrowser/Emby.Releases
linuxserver/docker-old: old/removed
""",
        encoding="utf-8",
    )
    current = lsio.read_map(map_path)
    source = {
        "linuxserver/docker-alpha": "alpha/app",
        "linuxserver/docker-emby": "plain/emby",
        "linuxserver/docker-zed": "new/zed",
    }

    scan = lsio.SourceScan(set(source), source)

    assert lsio.render_map(lsio.build_output_entries(current, scan)) == """# /wud/upstreams.txt
# Format: linuxserver/docker-<image>: <Owner>/<Repo>
# Keep entries sorted by the linuxserver/docker-* key.

linuxserver/docker-alpha: alpha/app
# Manual override.
linuxserver/docker-emby: MediaBrowser/Emby.Releases
linuxserver/docker-zed: new/zed
"""


def test_read_map_preserves_leading_override_comment(tmp_path: Path):
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text(
        """# Leading override.
linuxserver/docker-first: example/first

# Cleared comment.

linuxserver/docker-second: example/second
""",
        encoding="utf-8",
    )

    entries = lsio.read_map(map_path)

    assert entries["linuxserver/docker-first"].comments == ("# Leading override.",)
    assert entries["linuxserver/docker-second"].comments == ()


def test_check_reports_missing_changed_and_removed_without_overrides(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    write_metadata(source, "docker-alpha", "readme-vars.yml", "https://github.com/new/alpha")
    write_metadata(source, "docker-beta", "readme-vars.yml", "https://github.com/new/beta")
    write_metadata(
        source,
        "docker-override",
        "readme-vars.yml",
        "https://github.com/new/override",
    )
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text(
        """linuxserver/docker-alpha: old/alpha
# Manual override.
linuxserver/docker-override: old/override
linuxserver/docker-removed: old/removed
""",
        encoding="utf-8",
    )

    assert lsio.main(["--map", str(map_path), "--source-dir", str(source)]) == 1

    output = capsys.readouterr().out
    assert "missing: linuxserver/docker-beta: new/beta" in output
    assert "changed: linuxserver/docker-alpha: old/alpha -> new/alpha" in output
    assert "removed: linuxserver/docker-removed: old/removed" in output
    assert "docker-override" not in output
    assert "Regenerate with: scripts/update-lsio-upstreams.py --write --map" in output


def test_write_updates_map_deterministically(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    write_metadata(source, "docker-zed", "readme-vars.yml", "https://github.com/zed/app")
    write_metadata(source, "docker-alpha", "readme-vars.yml", "https://github.com/alpha/app")
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text("", encoding="utf-8")

    assert lsio.main(
        ["--write", "--map", str(map_path), "--source-dir", str(source)]
    ) == 0

    assert map_path.read_text(encoding="utf-8") == """# /wud/upstreams.txt
# Format: linuxserver/docker-<image>: <Owner>/<Repo>
# Keep entries sorted by the linuxserver/docker-* key.

linuxserver/docker-alpha: alpha/app
linuxserver/docker-zed: zed/app
"""


def test_write_preserves_seen_unmapped_existing_entry(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    write_metadata(source, "docker-sonarr", "readme-vars.yml", "https://sonarr.tv/")
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text("linuxserver/docker-sonarr: Sonarr/Sonarr\n", encoding="utf-8")

    assert lsio.main(
        ["--write", "--map", str(map_path), "--source-dir", str(source)]
    ) == 0

    assert "linuxserver/docker-sonarr: Sonarr/Sonarr\n" in map_path.read_text(
        encoding="utf-8"
    )


def test_github_mode_checks_jenkins_after_homepage_project_url(monkeypatch):
    def fake_github_file(_repo: str, _branch: str, filename: str) -> str | None:
        if filename == "readme-vars.yml":
            return '---\nproject_url: "https://www.bazarr.media/"\n'
        if filename == "jenkins-vars.yml":
            return "---\nrepo_vars:\n  - EXT_USER = 'morpheus65535'\n  - EXT_REPO = 'bazarr'\n"
        return None

    monkeypatch.setattr(lsio, "github_file", fake_github_file)

    assert lsio.source_entry_from_github_repo("docker-bazarr", "master") == (
        "linuxserver/docker-bazarr",
        "morpheus65535/bazarr",
    )


def test_default_github_mode_requires_token(tmp_path: Path, monkeypatch, capsys):
    def fail_network():
        raise AssertionError("network should not run")

    monkeypatch.chdir(tmp_path)
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text("", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(lsio, "source_entries_from_github", fail_network)

    assert lsio.main(["--map", str(map_path)]) == 2

    assert "requires GITHUB_TOKEN or GH_TOKEN" in capsys.readouterr().err


@pytest.mark.parametrize("status,message", [(403, "Forbidden"), (429, "Too Many Requests")])
def test_github_mode_reports_throttling_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
    status: int,
    message: str,
):
    def throttled(_request, *, timeout: float):
        raise urllib.error.HTTPError("https://api.github.com/test", status, message, {}, None)

    monkeypatch.chdir(tmp_path)
    map_path = tmp_path / "upstreams.txt"
    map_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(lsio.urllib.request, "urlopen", throttled)

    assert lsio.main(["--map", str(map_path)]) == 2

    captured = capsys.readouterr()
    assert f"HTTP {status} ({message})" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "network_exc",
    [
        urllib.error.URLError("temporary failure in name resolution"),
        TimeoutError("timed out"),
    ],
)
def test_github_json_wraps_network_failures(monkeypatch, network_exc: OSError):
    def failed(_request, *, timeout: float):
        raise network_exc

    monkeypatch.setattr(lsio.urllib.request, "urlopen", failed)

    with pytest.raises(lsio.GitHubRequestError) as exc_info:
        lsio.github_json("https://api.github.com/test")

    assert exc_info.value.__cause__ is network_exc
    assert "network error" in str(exc_info.value)
    assert "retry later" in str(exc_info.value)


def test_github_json_reraises_non_throttling_http_errors(monkeypatch):
    http_error = urllib.error.HTTPError(
        "https://api.github.com/test",
        500,
        "Server Error",
        {},
        None,
    )

    def failed(_request, *, timeout: float):
        raise http_error

    monkeypatch.setattr(lsio.urllib.request, "urlopen", failed)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        lsio.github_json("https://api.github.com/test")

    assert exc_info.value is http_error


def test_map_path_must_stay_inside_repo_or_cwd(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside_upstreams = tmp_path.parent / "outside-upstreams.txt"

    with pytest.raises(SystemExit) as exc_info:
        lsio.parse_args(["--map", str(outside_upstreams)])

    assert exc_info.value.code == 2
