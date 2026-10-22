#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import ssl
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROJECT_NUMBER = "1049039378581"
POOL_ID = "finals-archive"
PROVIDER_ID = "oci-instance"
AUDIENCE = (
    f"//iam.googleapis.com/projects/{PROJECT_NUMBER}/locations/global/"
    f"workloadIdentityPools/{POOL_ID}/providers/{PROVIDER_ID}"
)
BUCKETS = {
    "database": "finals-database-1049039378581",
    "gitea": "finals-gitea-1049039378581",
    "pcaps": "finals-pcaps-1049039378581",
    "scores": "finals-scores-1049039378581",
}
UPLOADS = {
    "platform": {"database": Path("/srv/anvil/backups"), "scores": Path("/srv/anvil/backups")},
    "repository": {"gitea": Path("/srv/gitea/backups")},
    "gateway": {"pcaps": Path("/srv/captures")},
}
RESTORE_ROOT = Path("/srv/finals-archive/restore")
RECEIPT_ROOT = Path("/var/lib/finals-archive/receipts")
IMDS = "http://169.254.169.254/opc/v2"
MAXIMUM_FILE_BYTES = 8 * 1024 * 1024 * 1024
DIGEST = re.compile(r"^[0-9a-f]{64}$")


class ArchiveError(Exception):
    pass


def request(url, *, method="GET", headers=None, data=None, context=None, timeout=120):
    try:
        return urllib.request.urlopen(
            urllib.request.Request(url, method=method, headers=headers or {}, data=data),
            context=context,
            timeout=timeout,
        )
    except (OSError, urllib.error.URLError) as error:
        raise ArchiveError(f"request failed: {urllib.parse.urlsplit(url).hostname}") from error


def request_json(url, *, method="GET", headers=None, data=None, context=None):
    with request(url, method=method, headers=headers, data=data, context=context) as response:
        if response.status not in {200, 201}:
            raise ArchiveError(f"unexpected HTTP status: {response.status}")
        try:
            value = json.load(response)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ArchiveError("remote response is not valid JSON") from error
    if not isinstance(value, dict):
        raise ArchiveError("remote response is not a JSON object")
    return value


def host_role():
    platform = Path("/etc/finals-platform/role")
    router = Path("/etc/event-router/role")
    if platform.exists() == router.exists():
        raise ArchiveError("host has no unique fixed role")
    if platform.exists():
        try:
            value = json.loads(platform.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ArchiveError("platform role is invalid") from error
        if value not in ({"role": "platform"}, {"role": "operations"}, {"role": "repository"}):
            raise ArchiveError("platform role is not archive-eligible")
        return value["role"]
    try:
        value = router.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise ArchiveError("gateway role is invalid") from error
    if value != "active\n":
        raise ArchiveError("only the active gateway can archive captures")
    return "gateway"


def authorize(role, action, purpose):
    if purpose not in BUCKETS:
        raise ArchiveError("unknown archive purpose")
    marker = Path("/run/finals-archive/egress-enabled")
    if not marker.is_file() or marker.read_text(encoding="ascii") != "enabled\n":
        raise ArchiveError("post-event archive egress is not enabled")
    if action == "upload":
        if purpose not in UPLOADS.get(role, {}):
            raise ArchiveError("host role cannot upload this archive purpose")
    elif action in {"verify", "download"}:
        if role != "operations":
            raise ArchiveError("only operations can verify or download archives")
    else:
        raise ArchiveError("unknown archive action")


def source_file(role, purpose, name, roots=UPLOADS, owner_uid=0):
    path = Path(name)
    if path.is_symlink():
        raise ArchiveError("archive source must not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(roots[role][purpose].resolve(strict=True))
        info = resolved.stat()
    except (OSError, KeyError, ValueError) as error:
        raise ArchiveError("archive source is outside its fixed durable root") from error
    if not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o022:
        raise ArchiveError("archive source must be a root-owned regular file not writable by group or other")
    if info.st_size < 1 or info.st_size > MAXIMUM_FILE_BYTES:
        raise ArchiveError("archive source must be between 1 byte and 8 GiB")
    return resolved, info


def file_identity(path):
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    with path.open("rb", buffering=1024 * 1024) as source:
        while chunk := source.read(1024 * 1024):
            sha256.update(chunk)
            md5.update(chunk)
    return sha256.hexdigest(), base64.b64encode(md5.digest()).decode("ascii")


def same_file(before, after):
    names = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(before, name) == getattr(after, name) for name in names)


def object_name(digest):
    if not DIGEST.fullmatch(digest):
        raise ArchiveError("SHA-256 must be 64 lowercase hexadecimal characters")
    return f"finals-2026/sha256/{digest}"


def metadata_url(purpose, digest, *, media=False, generation=None):
    name = urllib.parse.quote(object_name(digest), safe="")
    query = {"alt": "media" if media else "json"}
    if generation is not None:
        query["generation"] = generation
    prefix = "download/storage/v1" if media else "storage/v1"
    return f"https://storage.googleapis.com/{prefix}/b/{BUCKETS[purpose]}/o/{name}?{urllib.parse.urlencode(query)}"


def validate_metadata(document, purpose, digest, *, size=None, md5=None):
    expected_name = object_name(digest)
    remote_metadata = document.get("metadata")
    if (
        document.get("bucket") != BUCKETS[purpose]
        or document.get("name") != expected_name
        or not isinstance(remote_metadata, dict)
        or remote_metadata.get("sha256") != digest
        or not isinstance(document.get("generation"), str)
        or not document["generation"].isdigit()
        or not isinstance(document.get("size"), str)
        or not document["size"].isdigit()
        or not isinstance(document.get("md5Hash"), str)
    ):
        raise ArchiveError("remote object metadata does not match its immutable identity")
    if size is not None and document["size"] != str(size):
        raise ArchiveError("remote object size does not match the source")
    if md5 is not None and document["md5Hash"] != md5:
        raise ArchiveError("remote object checksum does not match the source")
    return document


def imds(path):
    with request(f"{IMDS}/{path}", headers={"Authorization": "Bearer Oracle"}, timeout=10) as response:
        value = response.read(1024 * 1024 + 1)
    if not value or len(value) > 1024 * 1024:
        raise ArchiveError("OCI instance identity response has an invalid size")
    return value


def identity_context(directory):
    instance_id = imds("instance/id").decode("ascii").strip()
    if not re.fullmatch(r"ocid1\.instance\.oc1\.ap-hyderabad-1\.[a-z0-9]+", instance_id):
        raise ArchiveError("OCI instance identity is invalid")
    files = {
        "cert.pem": imds("identity/cert.pem"),
        "intermediate.pem": imds("identity/intermediate.pem"),
        "key.pem": imds("identity/key.pem"),
    }
    for name, value in files.items():
        path = directory / name
        path.write_bytes(value)
        path.chmod(0o600)
    commands = (
        ["openssl", "x509", "-in", str(directory / "cert.pem"), "-noout", "-checkend", "300"],
        ["openssl", "x509", "-in", str(directory / "cert.pem"), "-noout", "-checkhost", instance_id],
        ["openssl", "pkey", "-in", str(directory / "key.pem"), "-check", "-noout"],
    )
    try:
        for command in commands:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        certificate_key = subprocess.run(
            ["openssl", "x509", "-in", str(directory / "cert.pem"), "-pubkey", "-noout"],
            check=True,
            capture_output=True,
        ).stdout
        private_key = subprocess.run(
            ["openssl", "pkey", "-in", str(directory / "key.pem"), "-pubout"],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise ArchiveError("OCI instance certificate validation failed") from error
    if not certificate_key or certificate_key != private_key:
        raise ArchiveError("OCI instance certificate and private key do not match")
    chain = directory / "chain.pem"
    chain.write_bytes(files["cert.pem"].rstrip() + b"\n" + files["intermediate.pem"].rstrip() + b"\n")
    chain.chmod(0o600)
    context = ssl.create_default_context()
    context.load_cert_chain(str(chain), str(directory / "key.pem"))
    certificates = []
    for value in (files["cert.pem"], files["intermediate.pem"]):
        try:
            certificates.append(base64.b64encode(ssl.PEM_cert_to_DER_cert(value.decode("ascii"))).decode("ascii"))
        except (UnicodeError, ValueError) as error:
            raise ArchiveError("OCI instance certificate is not valid PEM") from error
    return instance_id, context, json.dumps(certificates, separators=(",", ":"))


def access_token(directory):
    _, context, subject_token = identity_context(directory)
    payload = json.dumps(
        {
            "subject_token_type": "urn:ietf:params:oauth:token-type:mtls",
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "audience": AUDIENCE,
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "subject_token": subject_token,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    response = request_json(
        "https://sts.mtls.googleapis.com/v1/token",
        method="POST",
        headers={"Content-Type": "application/json"},
        data=payload,
        context=context,
    )
    token = response.get("access_token")
    if (
        response.get("token_type") != "Bearer"
        or not isinstance(response.get("expires_in"), int)
        or response["expires_in"] < 300
        or not isinstance(token, str)
        or not 32 <= len(token) <= 8192
        or any(character.isspace() for character in token)
    ):
        raise ArchiveError("Google STS returned an invalid access token")
    return token


def authorization(token):
    return {"Authorization": f"Bearer {token}"}


def remote_metadata(token, purpose, digest):
    return validate_metadata(request_json(metadata_url(purpose, digest), headers=authorization(token)), purpose, digest)


def upload(token, role, purpose, source_name):
    source, before = source_file(role, purpose, source_name)
    digest, md5 = file_identity(source)
    name = object_name(digest)
    query = urllib.parse.urlencode({"uploadType": "resumable", "ifGenerationMatch": "0"})
    metadata = json.dumps({"name": name, "metadata": {"sha256": digest}}, separators=(",", ":")).encode()
    initiate = urllib.request.Request(
        f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKETS[purpose]}/o?{query}",
        method="POST",
        headers={
            **authorization(token),
            "Content-Type": "application/json; charset=UTF-8",
            "Content-Length": str(len(metadata)),
            "X-Upload-Content-Type": "application/octet-stream",
            "X-Upload-Content-Length": str(before.st_size),
        },
        data=metadata,
    )
    try:
        with urllib.request.urlopen(initiate, timeout=120) as response:
            location = response.headers.get("Location")
    except urllib.error.HTTPError as error:
        if error.code != 412:
            raise ArchiveError("Cloud Storage rejected the immutable upload") from error
        existing = remote_metadata(token, purpose, digest)
        return validate_metadata(existing, purpose, digest, size=before.st_size, md5=md5)
    except (OSError, urllib.error.URLError) as error:
        raise ArchiveError("cannot initiate Cloud Storage upload") from error
    if not isinstance(location, str) or urllib.parse.urlsplit(location).hostname != "storage.googleapis.com":
        raise ArchiveError("Cloud Storage returned an invalid resumable upload location")
    try:
        with source.open("rb", buffering=1024 * 1024) as content:
            result = request_json(
                location,
                method="PUT",
                headers={
                    **authorization(token),
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(before.st_size),
                    "X-Goog-Hash": f"md5={md5}",
                },
                data=content,
            )
    except ArchiveError:
        raise
    if not same_file(before, source.stat()):
        raise ArchiveError("archive source changed during upload")
    return validate_metadata(result, purpose, digest, size=before.st_size, md5=md5)


def write_receipt(purpose, digest, metadata, root=RECEIPT_ROOT):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    receipt = {
        "schema_version": 1,
        "bucket": BUCKETS[purpose],
        "object": object_name(digest),
        "generation": metadata["generation"],
        "size": int(metadata["size"]),
        "md5": metadata["md5Hash"],
        "sha256": digest,
    }
    path = root / f"{purpose}-{digest}.json"
    encoded = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path.exists():
        if path.is_symlink() or path.read_bytes() != encoded:
            raise ArchiveError("existing archive receipt conflicts with remote metadata")
        return path
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=root)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path


def restore_path(name, root=RESTORE_ROOT):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    destination = Path(name)
    try:
        destination.parent.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise ArchiveError("restore destination is outside the fixed restore root") from error
    if destination.exists() or destination.is_symlink():
        raise ArchiveError("restore destination already exists")
    return destination


def download(token, purpose, digest, destination_name):
    metadata = remote_metadata(token, purpose, digest)
    destination = restore_path(destination_name)
    descriptor, temporary = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    try:
        os.fchmod(descriptor, 0o600)
        url = metadata_url(purpose, digest, media=True, generation=metadata["generation"])
        with request(url, headers=authorization(token)) as response, os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            while chunk := response.read(1024 * 1024):
                sha256.update(chunk)
                md5.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if (
            sha256.hexdigest() != digest
            or base64.b64encode(md5.digest()).decode("ascii") != metadata["md5Hash"]
            or os.stat(temporary).st_size != int(metadata["size"])
        ):
            raise ArchiveError("downloaded archive failed checksum verification")
        os.link(temporary, destination)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return destination


def main():
    if os.geteuid() != 0 or len(sys.argv) not in {4, 5}:
        print("usage: finals-archive {upload PURPOSE FILE|verify PURPOSE SHA256|download PURPOSE SHA256 DESTINATION}", file=sys.stderr)
        return 2
    action, purpose = sys.argv[1:3]
    expected = {"upload": 4, "verify": 4, "download": 5}.get(action)
    if expected is None or len(sys.argv) != expected:
        print("invalid archive command", file=sys.stderr)
        return 2
    try:
        role = host_role()
        authorize(role, action, purpose)
        with tempfile.TemporaryDirectory(prefix="finals-archive-", dir="/run") as temporary:
            token = access_token(Path(temporary))
            if action == "upload":
                metadata = upload(token, role, purpose, sys.argv[3])
                digest = metadata["metadata"]["sha256"]
                receipt = write_receipt(purpose, digest, metadata)
                print(receipt)
            elif action == "verify":
                digest = sys.argv[3]
                metadata = remote_metadata(token, purpose, digest)
                print(json.dumps({key: metadata[key] for key in ("bucket", "name", "generation", "size", "md5Hash")}, sort_keys=True))
            else:
                digest, destination = sys.argv[3:5]
                print(download(token, purpose, digest, destination))
    except (ArchiveError, OSError, UnicodeError) as error:
        print(f"archive failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
