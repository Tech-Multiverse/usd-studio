import re
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath

USD_EXTENSIONS = {".usd", ".usda", ".usdc", ".usdz"}


def safe_relative_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    invalid_part = any(part in {"", ".", ".."} for part in path.parts)
    if not normalized or normalized.startswith("/") or path.is_absolute() or invalid_part:
        raise ValueError(f"Unsafe package path: {value}")
    if any(":" in part for part in path.parts):
        raise ValueError(f"Unsafe package path: {value}")
    return Path(*path.parts)


def create_package_directory(uploads_dir: Path, name: str) -> Path:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip(".-") or "scene"
    destination = uploads_dir / f"{stem}-{uuid.uuid4().hex[:8]}"
    destination.mkdir(parents=True, exist_ok=False)
    return destination


def find_scene_files(directory: Path) -> list[Path]:
    return sorted(
        (
            path.resolve()
            for path in directory.rglob("*")
            if path.is_file()
            and path.suffix.lower() in USD_EXTENSIONS
            and "__MACOSX" not in path.parts
        ),
        key=lambda path: (len(path.relative_to(directory.resolve()).parts), str(path).lower()),
    )


def choose_root_scene(scenes: list[Path], preferred_name: str = "") -> Path:
    if not scenes:
        raise ValueError("The package does not contain a USD scene")
    preferred_stem = Path(preferred_name).stem.lower()
    common_names = {"main", "scene", "root", "stage", "world"}

    def rank(path: Path) -> tuple[int, int, str]:
        stem = path.stem.lower()
        if preferred_stem and stem == preferred_stem:
            name_rank = 0
        elif stem in common_names:
            name_rank = 1
        elif "scene" in stem or "stage" in stem:
            name_rank = 2
        else:
            name_rank = 3
        return name_rank, len(path.parts), str(path).lower()

    return min(scenes, key=rank)


def extract_zip_package(
    archive_path: Path,
    destination: Path,
    max_files: int,
    max_uncompressed_bytes: int,
) -> None:
    destination = destination.resolve()
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise ValueError("The uploaded file is not a valid ZIP archive") from exc
    with archive:
        members = [member for member in archive.infolist() if not member.is_dir()]
        if len(members) > max_files:
            raise ValueError(f"Package contains more than {max_files} files")
        total_size = sum(member.file_size for member in members)
        if total_size > max_uncompressed_bytes:
            raise ValueError("Expanded package exceeds the configured size limit")
        destinations: set[Path] = set()
        for member in members:
            if member.flag_bits & 0x1:
                raise ValueError(f"Package contains an encrypted file: {member.filename}")
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError(f"Package contains a symbolic link: {member.filename}")
            relative_path = safe_relative_path(member.filename)
            output_path = (destination / relative_path).resolve()
            if destination not in output_path.parents or output_path in destinations:
                raise ValueError(f"Unsafe or duplicate package path: {member.filename}")
            destinations.add(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
