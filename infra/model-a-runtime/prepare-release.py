#!/usr/bin/env python3
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

from model_a import (
    BASE_IMAGES,
    SERVICES,
    SOURCE_COMMIT,
    ModelAError,
    compose_document,
    run,
    sha256_file,
    verify_player_bundle,
    write_json,
)


def image_id(reference):
    result = run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    if not value.startswith("sha256:") or len(value) != 71:
        raise ModelAError(f"invalid image ID for {reference}")
    return value


def ensure_base_images():
    records = []
    for reference in BASE_IMAGES:
        try:
            identifier = image_id(reference)
        except ModelAError:
            run(["docker", "pull", reference])
            identifier = image_id(reference)
        records.append({"reference": reference, "image_id": identifier})
    return records


def verify_source(source):
    revision = run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True
    ).stdout.strip()
    if revision != SOURCE_COMMIT:
        raise ModelAError(f"challenge checkout must be exact commit {SOURCE_COMMIT}")
    status = run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=source,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ModelAError("challenge checkout must be clean")


def build_service(source, service, staging):
    slug = service["slug"]
    tag = f"finals/model-a/{slug}:{SOURCE_COMMIT}"
    override = staging / f".{slug}.override.json"
    write_json(override, {"services": {"service": {"image": tag}}}, 0o600)
    compose = source / "services" / slug / "compose.yaml"
    resolved = run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "-f",
            str(override),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
    )
    document = json.loads(resolved.stdout)
    build = document["services"]["service"]["build"]
    if build.get("network") != "none":
        raise ModelAError(f"{slug} build network is not none")
    run(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "-f",
            str(override),
            "build",
            "--pull=false",
            "service",
        ],
        cwd=compose.parent,
    )
    override.unlink()
    return tag, image_id(tag)


def deterministic_tar(source, destination):
    with tarfile.open(destination, "w") as archive:
        for path in sorted(
            source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()
        ):
            relative = path.relative_to(source)
            info = archive.gettarinfo(str(path), arcname=relative.as_posix())
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
            else:
                archive.addfile(info)


def prepare(source, output):
    verify_source(source)
    if output.exists():
        raise ModelAError("output path already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        services_root = staging / "payload" / "services"
        services_root.mkdir(parents=True)
        base_records = ensure_base_images()
        service_records = []
        factory_tags = []
        for service in SERVICES:
            slug = service["slug"]
            export = services_root / slug
            run(
                [sys.executable, "tools/export_player_bundle.py", slug, str(export)],
                cwd=source,
            )
            tag, identifier = build_service(source, service, staging)
            factory_tags.append(tag)
            write_json(
                export / "compose.yaml", compose_document(service, identifier), 0o644
            )
            verify_player_bundle(export, slug)
            service_records.append(
                {
                    "slug": slug,
                    "port": service["port"],
                    "uid": service["uid"],
                    "factory_reference": tag,
                    "factory_image_id": identifier,
                    "bundle_sha256": sha256_file(export / "BUNDLE.json"),
                    "storage_bytes": service["storage_bytes"],
                    "storage_inodes": service["storage_inodes"],
                }
            )
        archives = staging / "archives"
        archives.mkdir()
        deterministic_tar(staging / "payload", archives / "player-bundles.tar")
        run(
            [
                "docker",
                "image",
                "save",
                "--output",
                str(archives / "factory-images.tar"),
                *factory_tags,
            ]
        )
        run(
            [
                "docker",
                "image",
                "save",
                "--output",
                str(archives / "base-images.tar"),
                *BASE_IMAGES,
            ]
        )
        archive_records = {
            name: {
                "sha256": sha256_file(archives / name),
                "bytes": (archives / name).stat().st_size,
            }
            for name in ("player-bundles.tar", "factory-images.tar", "base-images.tar")
        }
        release = {
            "schema_version": 1,
            "source_commit": SOURCE_COMMIT,
            "services": service_records,
            "base_images": base_records,
            "archives": archive_records,
        }
        write_json(staging / "release.json", release, 0o644)
        shutil.rmtree(staging / "payload")
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main():
    if len(sys.argv) != 3:
        print("usage: prepare-release.py CHALLENGE_CHECKOUT OUTPUT", file=sys.stderr)
        return 2
    try:
        prepare(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except (ModelAError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Model A release preparation refused: {error}", file=sys.stderr)
        return 1
    print(f"prepared Model A release at {Path(sys.argv[2]).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
