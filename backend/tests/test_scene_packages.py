import zipfile
from pathlib import Path

import pytest

from usd_studio.scene_packages import (
    choose_root_scene,
    extract_zip_package,
    find_scene_files,
    safe_relative_path,
)


def test_safe_relative_path_rejects_traversal_and_absolute_paths():
    for value in ("../scene.usda", "folder/../../scene.usda", "/scene.usda", "C:/scene.usda"):
        with pytest.raises(ValueError):
            safe_relative_path(value)


def test_extract_zip_preserves_package_and_discovers_preferred_scene(tmp_path: Path):
    archive_path = tmp_path / "show.zip"
    destination = tmp_path / "package"
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("show.usda", "#usda 1.0")
        archive.writestr("assets/model.usdc", b"model")
        archive.writestr("textures/albedo.png", b"image")

    extract_zip_package(archive_path, destination, max_files=10, max_uncompressed_bytes=1024)
    scenes = find_scene_files(destination)

    assert (destination / "textures" / "albedo.png").read_bytes() == b"image"
    assert choose_root_scene(scenes, "show.zip") == (destination / "show.usda").resolve()


def test_extract_zip_rejects_path_traversal(tmp_path: Path):
    archive_path = tmp_path / "unsafe.zip"
    destination = tmp_path / "package"
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.usda", "#usda 1.0")

    with pytest.raises(ValueError, match="Unsafe package path"):
        extract_zip_package(archive_path, destination, max_files=10, max_uncompressed_bytes=1024)

    assert not (tmp_path / "outside.usda").exists()


def test_extract_zip_enforces_expanded_size_limit(tmp_path: Path):
    archive_path = tmp_path / "large.zip"
    destination = tmp_path / "package"
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("scene.usda", "x" * 2048)

    with pytest.raises(ValueError, match="Expanded package"):
        extract_zip_package(archive_path, destination, max_files=10, max_uncompressed_bytes=1024)
