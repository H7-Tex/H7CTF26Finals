import gzip
import hashlib
import io
import json
import os
import re
import sys
import tarfile
import tempfile
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def migration_fingerprint(directory):
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise SystemExit("migration directory contains no SQL migrations")
    content = bytearray()
    for expected, path in enumerate(files, 1):
        match = re.fullmatch(r"([0-9]+)_.+\.sql", path.name)
        if path.is_symlink() or not path.is_file() or match is None or int(match.group(1)) != expected:
            raise SystemExit(f"invalid migration sequence at {path}")
        content.extend(f"{expected}|{path.name}|{digest(path)}\n".encode())
    return len(files), hashlib.sha256(content).hexdigest()


def add(archive, name, source):
    info = tarfile.TarInfo(name)
    info.size = source.stat().st_size
    info.mode = 0o600
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    with source.open("rb") as content:
        archive.addfile(info, content)


def main():
    if len(sys.argv) != 6:
        raise SystemExit(
            "usage: build-anvil-deploy-bundle.py REVISION IMAGES_TAR_GZ GAME_YAML MIGRATIONS_DIR OUTPUT"
        )
    revision, images_name, game_name, migrations_name, output_name = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise SystemExit("revision must be exactly 40 lowercase hexadecimal characters")
    for name in (images_name, game_name, migrations_name):
        if Path(name).is_symlink():
            raise SystemExit(f"input must not be a symbolic link: {name}")
    images = Path(images_name).resolve()
    game = Path(game_name).resolve()
    migrations = Path(migrations_name).resolve()
    output = Path(output_name).resolve()
    deployer = Path(__file__).parents[1] / "terraform/modules/oci-platform/scripts/deploy-anvil-artifact"
    for path in (images, game, deployer):
        if not path.is_file():
            raise SystemExit(f"input is not a regular file: {path}")
    if not migrations.is_dir():
        raise SystemExit(f"input is not a directory: {migrations}")
    if not 0 < images.stat().st_size <= 536870912 or not 0 < game.stat().st_size <= 65536:
        raise SystemExit("deploy input size is outside its fixed bound")

    docker_manifest = None
    with gzip.open(images, "rb") as compressed, tarfile.open(fileobj=compressed, mode="r|") as archive:
        for item in archive:
            if item.name == "manifest.json":
                source = archive.extractfile(item)
                docker_manifest = json.load(source) if source is not None else None
                break
    tags = sorted(tag for item in docker_manifest or [] for tag in item.get("RepoTags", []))
    if len(docker_manifest or []) != 2 or tags != [
        f"anvil-finals-api:{revision}",
        f"anvil-finals-web:{revision}",
    ]:
        raise SystemExit("image archive does not contain exactly the reviewed Anvil tags")
    migration_count, migration_sha256 = migration_fingerprint(migrations)

    manifest = json.dumps(
        {
            "format": "h7ctf-anvil-deploy-v1",
            "revision": revision,
            "images": {"file": "images.tar.gz", "size": images.stat().st_size, "sha256": digest(images)},
            "game": {"file": "game.yaml", "size": game.stat().st_size, "sha256": digest(game)},
            "migrations": {"count": migration_count, "sha256": migration_sha256},
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode() + b"\n"

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as temporary:
        temporary_name = Path(temporary.name)
        with tarfile.open(fileobj=temporary, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            add(archive, "deploy.sh", deployer)
            add(archive, "game.yaml", game)
            add(archive, "images.tar.gz", images)
            info = tarfile.TarInfo("manifest.json")
            info.size = len(manifest)
            info.mode = 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = 0
            archive.addfile(info, io.BytesIO(manifest))
    os.chmod(temporary_name, 0o600)
    os.replace(temporary_name, output)
    print(json.dumps({"path": str(output), "size": output.stat().st_size, "sha256": digest(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
