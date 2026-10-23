#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_SPEC = importlib.util.spec_from_file_location("model_a", ROOT / "model_a.py")
MODEL = importlib.util.module_from_spec(MODEL_SPEC)
MODEL_SPEC.loader.exec_module(MODEL)
CONTROL_LOADER = SourceFileLoader(
    "model_a_control", str(ROOT / "rootfs/usr/local/sbin/finals-model-a-control")
)
CONTROL_SPEC = importlib.util.spec_from_loader("model_a_control", CONTROL_LOADER)
CONTROL = importlib.util.module_from_spec(CONTROL_SPEC)
sys.path.insert(0, str(ROOT))
CONTROL_LOADER.exec_module(CONTROL)


def command(arguments, **kwargs):
    return subprocess.run(arguments, check=True, **kwargs)


def output(arguments, **kwargs):
    return command(arguments, capture_output=True, text=True, **kwargs).stdout.strip()


def now():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def refuse_competing_builds():
    processes = output(["ps", "-eo", "pid=,args="])
    own_pid = os.getpid()
    blocked = []
    for line in processes.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_value, _, arguments = stripped.partition(" ")
        if pid_value.isdigit() and int(pid_value) == own_pid:
            continue
        if any(
            marker in arguments
            for marker in (
                "docker build ",
                "docker buildx ",
                "docker-buildx buildx build",
                "docker compose ",
                "patch_gate.py",
                "validation/canary.py",
            )
        ):
            blocked.append(stripped)
    if blocked:
        raise RuntimeError("competing Docker or challenge gate process is active")


def wait_url(url, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise RuntimeError(f"timed out waiting for {url}")


def checker_call(
    url,
    timeout_ms,
    method,
    variant,
    chain,
    round_id,
    flag=None,
    attack_info=None,
    flag_hash=None,
):
    body = {
        "taskId": secrets.randbelow(2**31 - 1) + 1,
        "method": method,
        "address": "model-a-proxy",
        "teamId": 1,
        "teamName": "model-a-smoke",
        "currentRoundId": round_id,
        "relatedRoundId": round_id,
        "variantId": variant,
        "timeout": timeout_ms,
        "roundLength": 120000,
        "taskChainId": chain,
        "flagRegex": r"H7CTF\{[0-9a-f]{32}\}",
    }
    if flag is not None:
        body["flag"] = flag
    if attack_info is not None:
        body["attackInfo"] = attack_info
    if flag_hash is not None:
        body["flagHash"] = flag_hash
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    if result.get("result") != "OK":
        classification = result.get("result", "missing")
        message = str(result.get("message", ""))[:256]
        raise RuntimeError(
            f"{method} store or variant {variant} failed: {classification}: {message}"
        )
    return result


def build_checker(challenge, slug, staging):
    tag = f"finals/checkers/{slug}:{MODEL.SOURCE_COMMIT}"
    override = staging / f"{slug}-checker.json"
    override.write_text(
        json.dumps({"services": {"checker": {"image": tag}}}), encoding="utf-8"
    )
    compose = challenge / "services" / slug / "compose.yaml"
    resolved = json.loads(
        output(
            [
                "docker",
                "compose",
                "-f",
                str(compose),
                "-f",
                str(override),
                "--profile",
                "checker",
                "config",
                "--format",
                "json",
            ]
        )
    )
    if resolved["services"]["checker"]["build"].get("network") != "none":
        raise RuntimeError(f"{slug} checker build network is not none")
    command(
        [
            "docker",
            "compose",
            "-f",
            str(compose),
            "-f",
            str(override),
            "--profile",
            "checker",
            "build",
            "--pull=false",
            "checker",
        ],
        cwd=compose.parent,
    )
    return tag, output(["docker", "image", "inspect", "--format", "{{.Id}}", tag])


def start_service(root, record, service, prefix):
    data = root / "data" / service["slug"]
    data.mkdir(parents=True, mode=0o777, exist_ok=True)
    data.chmod(0o777)
    workspace = root / "work" / service["slug"]
    factory = root / "state" / "factory" / service["slug"]
    document = MODEL.compose_document(service, record["factory_image_id"], str(data))
    document["name"] = f"{prefix}-{service['slug']}"
    document["services"]["service"]["networks"] = {
        "target": {"aliases": [f"target-{service['slug']}"]}
    }
    MODEL.write_json(workspace / "compose.yaml", document)
    MODEL.write_json(factory / "compose.yaml", document)
    environment = dict(os.environ)
    environment["H7_IMAGE"] = record["factory_image_id"]
    command(
        [
            "docker",
            "compose",
            "--project-directory",
            str(workspace),
            "-f",
            str(workspace / "compose.yaml"),
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "120",
            "service",
        ],
        env=environment,
    )
    return data


def seed_instance_secret(data, service, python_image):
    script = "import os,secrets,sys\nname,kind=sys.argv[1],sys.argv[2]\npayload=secrets.token_hex(32).encode() if kind=='hex' else secrets.token_bytes(32)\nfd=os.open('/data/'+name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\nassert os.write(fd,payload)==len(payload)\nos.fsync(fd)\nos.close(fd)"
    command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            f"{service['uid']}:{service['uid']}",
            "--volume",
            f"{data}:/data",
            python_image,
            "python3",
            "-c",
            script,
            service["secret_name"],
            service["secret_format"],
        ],
        stdout=subprocess.DEVNULL,
    )


def main():
    if len(sys.argv) != 4:
        print(
            "usage: local-acceptance.py RELEASE_DIRECTORY CHALLENGE_CHECKOUT EVIDENCE_JSON",
            file=sys.stderr,
        )
        return 2
    release_root = Path(sys.argv[1]).resolve()
    challenge = Path(sys.argv[2]).resolve()
    evidence_path = Path(sys.argv[3]).resolve()
    started = time.monotonic()
    evidence = {
        "schema_version": 1,
        "started_at": now(),
        "source_commit": MODEL.SOURCE_COMMIT,
        "docker_version": output(
            ["docker", "version", "--format", "{{.Server.Version}}"]
        ),
        "buildx_version": output(["docker", "buildx", "version"]),
        "result": "RED",
        "checks": {},
    }
    prefix = f"model-a-smoke-{os.getpid()}"
    containers = []
    projects = []
    network = prefix
    temporary = Path(tempfile.mkdtemp(prefix=f"{prefix}."))
    try:
        refuse_competing_builds()
        release = MODEL.read_json(release_root / "release.json")
        if release.get("source_commit") != MODEL.SOURCE_COMMIT:
            raise RuntimeError("release source commit mismatch")
        for name, record_value in release["archives"].items():
            path = release_root / "archives" / name
            if (
                path.stat().st_size != record_value["bytes"]
                or MODEL.sha256_file(path) != record_value["sha256"]
            ):
                raise RuntimeError(f"archive verification failed for {name}")
        evidence["archives"] = release["archives"]
        command(["docker", "network", "create", network], stdout=subprocess.DEVNULL)
        with tarfile.open(
            release_root / "archives" / "player-bundles.tar", "r"
        ) as archive:
            archive.extractall(temporary, filter="data")
        work = temporary / "work"
        factory_root = temporary / "state" / "factory"
        work.mkdir()
        factory_root.mkdir(parents=True)
        records = {record["slug"]: record for record in release["services"]}
        python_image = next(
            item["reference"]
            for item in release["base_images"]
            if item["reference"].startswith("python@")
        )
        for service in MODEL.SERVICES:
            slug = service["slug"]
            exported = temporary / "services" / slug
            MODEL.verify_player_bundle(exported, slug)
            workspace = work / slug
            factory = factory_root / slug
            shutil.copytree(exported, workspace, copy_function=os.link)
            shutil.copytree(exported, factory, copy_function=os.link)
            data = temporary / "data" / slug
            data.mkdir(parents=True, mode=0o777)
            data.chmod(0o777)
            seed_instance_secret(data, service, python_image)
            data = start_service(temporary, records[slug], service, prefix)
            projects.append((workspace, records[slug]["factory_image_id"]))
            secret_path = data / service["secret_name"]
            if (
                not secret_path.is_file()
                or secret_path.stat().st_uid != service["uid"]
                or secret_path.stat().st_mode & 0o077
            ):
                raise RuntimeError(f"{slug} instance secret owner or mode is invalid")
        evidence["checks"]["all_service_healthchecks"] = "GREEN"
        evidence["checks"]["instance_secret_precreation"] = "GREEN"
        proxy_script = (
            "import asyncio\nports={"
            + ",".join(
                f"{service['port']}:('target-{service['slug']}',{service['port']})"
                for service in MODEL.SERVICES
            )
            + "}\nasync def pipe(r,w):\n try:\n  while data:=await r.read(65536): w.write(data); await w.drain()\n finally: w.close()\nasync def handle(r,w,p):\n rr,rw=await asyncio.open_connection(*ports[p]); await asyncio.gather(pipe(r,rw),pipe(rr,w))\nasync def main():\n servers=[await asyncio.start_server(lambda r,w,p=p: handle(r,w,p),'0.0.0.0',p) for p in ports]\n await asyncio.gather(*(s.serve_forever() for s in servers))\nasyncio.run(main())"
        )
        proxy_name = f"{prefix}-proxy"
        command(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                proxy_name,
                "--network",
                network,
                "--network-alias",
                "model-a-proxy",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "64",
                "--memory",
                "128m",
                python_image,
                "python3",
                "-c",
                proxy_script,
            ],
            stdout=subprocess.DEVNULL,
        )
        containers.append(proxy_name)
        for service in MODEL.SERVICES:
            docker_network = f"{prefix}-{service['slug']}_target"
            command(["docker", "network", "connect", docker_network, proxy_name])
        mongo_name = f"{prefix}-mongo"
        mongo_image = "mongo@sha256:c53852c00c23ca9f23fc39690350ffa9a80e3642fe8f96879726d8da0abe80a7"
        command(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                mongo_name,
                "--network",
                network,
                "--user",
                "999:999",
                "--tmpfs",
                "/data/db:uid=999,gid=999,mode=0700",
                "--tmpfs",
                "/data/configdb:uid=999,gid=999,mode=0700",
                mongo_image,
                "mongod",
                "--bind_ip_all",
                "--quiet",
                "--wiredTigerCacheSizeGB",
                "0.25",
            ],
            stdout=subprocess.DEVNULL,
        )
        containers.append(mongo_name)
        for _ in range(60):
            if (
                subprocess.run(
                    [
                        "docker",
                        "exec",
                        mongo_name,
                        "mongosh",
                        "--quiet",
                        "--eval",
                        "db.runCommand({ping:1}).ok",
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                break
            time.sleep(1)
        else:
            raise RuntimeError("checker database did not become healthy")
        checker_ids = {}
        saved = {}
        for index, service in enumerate(MODEL.SERVICES, start=1):
            slug = service["slug"]
            tag, checker_id = build_checker(challenge, slug, temporary)
            checker_ids[slug] = checker_id
            checker_name = f"{prefix}-checker-{index}"
            checker_port = 18000 + index
            command(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    checker_name,
                    "--network",
                    network,
                    "--publish",
                    f"127.0.0.1:{checker_port}:8000",
                    "--read-only",
                    "--tmpfs",
                    "/tmp:size=32m,mode=1777",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--pids-limit",
                    "96",
                    "--memory",
                    "384m",
                    "--env",
                    f"MONGO_HOST={mongo_name}",
                    "--env",
                    "MONGO_PORT=27017",
                    tag,
                    "gunicorn",
                    "-k",
                    "uvicorn.workers.UvicornWorker",
                    "-w",
                    "2",
                    "-b",
                    "0.0.0.0:8000",
                    "--timeout",
                    "30",
                    "checker:app",
                ],
                stdout=subprocess.DEVNULL,
            )
            containers.append(checker_name)
            base_url = f"http://127.0.0.1:{checker_port}"
            wait_url(base_url + "/service")
            manifest = json.loads(
                (challenge / "services" / slug / "manifest.json").read_text()
            )
            timeout_ms = manifest["checker"]["timeout_ms"]
            rows = []
            for store in range(2):
                flag = f"H7CTF{{{secrets.token_hex(16)}}}"
                chain = secrets.token_hex(16)
                put = checker_call(
                    base_url + "/", timeout_ms, "putflag", store, chain, 1, flag=flag
                )
                checker_call(
                    base_url + "/", timeout_ms, "getflag", store, chain, 1, flag=flag
                )
                rows.append(
                    {
                        "store": store,
                        "flag": flag,
                        "chain": chain,
                        "attack_info": put["attackInfo"],
                    }
                )
            exploit = checker_call(
                base_url + "/",
                timeout_ms,
                "exploit",
                0,
                secrets.token_hex(16),
                1,
                attack_info=rows[0]["attack_info"],
                flag_hash=hashlib.sha256(rows[0]["flag"].encode()).hexdigest(),
            )
            if exploit.get("flag") != rows[0]["flag"]:
                raise RuntimeError(f"{slug} exploit smoke returned the wrong flag")
            saved[slug] = {"url": base_url + "/", "timeout": timeout_ms, "rows": rows}
            evidence["checks"][f"{slug}_checker"] = "GREEN"
            print(f"{slug}: health, both stores, and exploit smoke GREEN", flush=True)
        evidence["checker_image_ids"] = checker_ids
        CONTROL.STATE_ROOT = temporary / "state"
        CONTROL.WORK_ROOT = work
        MODEL.write_json(CONTROL.STATE_ROOT / "release.json", release, 0o600)
        (CONTROL.STATE_ROOT / "active").mkdir()
        for record_value in release["services"]:
            (CONTROL.STATE_ROOT / "active" / record_value["slug"]).write_text(
                record_value["factory_image_id"] + "\n"
            )
        edited = work / "sign-me-in" / "service" / "portal" / "src" / "app.py"
        factory_hash = hashlib.sha256(
            (
                factory_root / "sign-me-in" / "service" / "portal" / "src" / "app.py"
            ).read_bytes()
        ).hexdigest()
        edited_copy = edited.with_name(f".{edited.name}.edited")
        edited_copy.write_bytes(edited.read_bytes() + b"\n")
        os.replace(edited_copy, edited)
        CONTROL.rebuild("sign-me-in")
        for row in saved["sign-me-in"]["rows"]:
            checker_call(
                saved["sign-me-in"]["url"],
                saved["sign-me-in"]["timeout"],
                "getflag",
                row["store"],
                row["chain"],
                1,
                flag=row["flag"],
            )
        evidence["checks"]["edited_rebuild_and_retention"] = "GREEN"
        CONTROL.reset("sign-me-in")
        if hashlib.sha256(edited.read_bytes()).hexdigest() != factory_hash:
            raise RuntimeError("reset did not restore factory source")
        for row in saved["sign-me-in"]["rows"]:
            checker_call(
                saved["sign-me-in"]["url"],
                saved["sign-me-in"]["timeout"],
                "getflag",
                row["store"],
                row["chain"],
                1,
                flag=row["flag"],
            )
        evidence["checks"]["factory_reset_and_data_retention"] = "GREEN"
        evidence["factory_image_ids"] = {
            record_value["slug"]: record_value["factory_image_id"]
            for record_value in release["services"]
        }
        evidence["result"] = "GREEN"
    except Exception as error:
        evidence["error"] = str(error)
        raise
    finally:
        for container in reversed(containers):
            subprocess.run(
                ["docker", "container", "rm", "--force", container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for workspace, image in reversed(projects):
            environment = dict(os.environ)
            environment["H7_IMAGE"] = image
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "--project-directory",
                    str(workspace),
                    "-f",
                    str(workspace / "compose.yaml"),
                    "down",
                    "--remove-orphans",
                ],
                check=False,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        subprocess.run(
            ["docker", "network", "rm", network],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--volume",
                f"{temporary}:/cleanup",
                "alpine@sha256:d406446bc05b82480756ce8f1287964d28768c23955fa9480d2a74a2eae7a654",
                "chmod",
                "-R",
                "a+rwx",
                "/cleanup",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(temporary, ignore_errors=True)
        evidence["ended_at"] = now()
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
        evidence["checks"]["cleanup"] = "GREEN" if not temporary.exists() else "RED"
        if temporary.exists() and evidence["result"] == "GREEN":
            evidence["result"] = "RED"
            evidence["error"] = "local acceptance cleanup failed"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        MODEL.write_json(evidence_path, evidence, 0o600)
    if evidence["result"] != "GREEN":
        return 1
    print(f"Model A local acceptance GREEN; evidence {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
