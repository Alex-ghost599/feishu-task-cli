from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _release_steps() -> list[dict[str, object]]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["release"]["steps"]


def _checksum_producer_command() -> str:
    build_step = next(
        step for step in _release_steps() if step.get("name") == "Build and validate distributions"
    )
    return next(
        line.strip()
        for line in str(build_step["run"]).splitlines()
        if "sha256sum" in line and "SHA256SUMS" in line
    )


def _fixture(tmp_path: Path) -> tuple[Path, set[str]]:
    packages = tmp_path / "release" / "packages"
    packages.mkdir(parents=True)
    files = {
        "feishu_task_cli-0.1.2-py3-none-any.whl": b"synthetic wheel\n",
        "feishu_task_cli-0.1.2.tar.gz": b"synthetic sdist\n",
    }
    for name, content in files.items():
        (packages / name).write_bytes(content)
    return packages, set(files)


def _verify(cwd: Path, manifest: str = "SHA256SUMS") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sha256sum", "-c", manifest],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_checksum_manifest_is_portable_across_nested_and_flat_layouts(tmp_path: Path) -> None:
    packages, expected_names = _fixture(tmp_path)
    producer_command = _checksum_producer_command()
    assert "sha256sum *.whl *.tar.gz > ../SHA256SUMS" in producer_command
    result = subprocess.run(
        ["bash", "-c", producer_command],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    manifest = packages.parent / "SHA256SUMS"
    entries = [line.split(maxsplit=1)[1] for line in manifest.read_text().splitlines()]
    assert set(entries) == expected_names
    assert len(entries) == 2
    assert all(Path(entry).name == entry for entry in entries)
    assert all(not Path(entry).is_absolute() and ".." not in Path(entry).parts for entry in entries)
    assert _verify(packages, "../SHA256SUMS").returncode == 0

    public_download = tmp_path / "public-download"
    public_download.mkdir()
    shutil.copy2(manifest, public_download / manifest.name)
    for package in packages.iterdir():
        shutil.copy2(package, public_download / package.name)

    public_result = _verify(public_download)
    assert public_result.returncode == 0, public_result.stderr


def test_pypi_artifact_consumer_verifies_nested_layout_without_rebuild(tmp_path: Path) -> None:
    _fixture(tmp_path)
    producer = subprocess.run(
        ["bash", "-c", _checksum_producer_command()],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert producer.returncode == 0, producer.stderr
    consumer_release = tmp_path / "consumer" / "release"
    shutil.copytree(tmp_path / "release", consumer_release)

    consumer_result = _verify(consumer_release / "packages", "../SHA256SUMS")
    assert consumer_result.returncode == 0, consumer_result.stderr

    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    publish_steps = workflow["jobs"]["publish-pypi"]["steps"]
    publish_text = "\n".join(str(step.get("run", "")) for step in publish_steps)

    assert "cd release/packages" in publish_text
    assert "sha256sum -c ../SHA256SUMS" in publish_text
    assert "uv build" not in publish_text
