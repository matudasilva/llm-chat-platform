"""Offline-only preparation and validation for the synthetic worker create request.

This module does not contact Docker. A prepared request is a draft; it is not
evidence that an Engine accepted the request or that the worker is ready.
"""

import hashlib
import json
import re
from copy import deepcopy


IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
ID_RE = re.compile(r"[0-9a-f]{64}\Z")
RUN_RE = re.compile(r"[0-9]{12}\Z")
API_RE = re.compile(r"[0-9]+\.[0-9]+\Z")

WORKER_IMAGE = "sha256:775d925078229f173fc48a4b95d5ca1620cb518b46433ead60cec3440029b852"
WORKER_ENTRYPOINT = ["/usr/local/bin/python3", "-I", "-B"]
WORKER_CMD = [
    "/orq41-synthetic/synthetic_worker.py",
    "/orq41-synthetic/plan.json",
    "/g6run",
]
RESOURCE_HOST_CONFIG = {
    "CgroupParent": "orq41bench.slice",
    "CpusetCpus": "0,2",
    "NanoCpus": 2_000_000_000,
    "Memory": 2_147_483_648,
    "MemorySwap": 2_147_483_648,
    "RestartPolicy": {"Name": "no"},
    "Privileged": False,
    "CapAdd": [],
    "PortBindings": {},
}
LEGACY_PROOF_SCHEMA = "orq41-worker-create-proof-v1"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _mounts(run_id):
    return [
        {
            "Source": f"/var/lib/orq41-cpuset/{run_id}/synthetic",
            "Target": "/orq41-synthetic",
            "ReadOnly": True,
        },
        {
            "Source": f"/var/lib/orq41-cpuset/{run_id}/receipts",
            "Target": "/g6run",
            "ReadOnly": False,
        },
        {
            "Source": f"/run/orq41-lifecycle/{run_id}",
            "Target": "/orq41-lifecycle",
            "ReadOnly": True,
        },
    ]


def _expected_body(run_id, image_ref, postgres_id, variant):
    host = deepcopy(RESOURCE_HOST_CONFIG)
    host["NetworkMode"] = f"container:{postgres_id}"
    mounts = _mounts(run_id)
    if variant == "strict_mounts":
        host["Mounts"] = [
            {
                "Type": "bind",
                "Source": mount["Source"],
                "Target": mount["Target"],
                "ReadOnly": mount["ReadOnly"],
                "BindOptions": {"CreateMountpoint": False},
            }
            for mount in mounts
        ]
    else:
        host["Binds"] = [
            f'{mount["Source"]}:{mount["Target"]}:{"ro" if mount["ReadOnly"] else "rw"}'
            for mount in mounts
        ]
    return {
        "Image": image_ref,
        "User": "1000:1000",
        "Entrypoint": list(WORKER_ENTRYPOINT),
        "Cmd": list(WORKER_CMD),
        "HostConfig": host,
    }


def _projection_from_body(name, body, variant):
    host = body["HostConfig"]
    mounts = _mounts_from_body(body, variant)
    return {
        "Name": "/" + name,
        "Image": body["Image"],
        "Entrypoint": list(body["Entrypoint"]),
        "Cmd": list(body["Cmd"]),
        "User": body["User"],
        "Resources": {
            key: deepcopy(host[key])
            for key in (
                "CgroupParent", "CpusetCpus", "NanoCpus", "Memory", "MemorySwap",
                "RestartPolicy", "Privileged", "CapAdd", "PortBindings", "NetworkMode",
            )
        },
        "Mounts": mounts,
    }


def _mounts_from_body(body, variant):
    if variant == "strict_mounts":
        raw_mounts = body["HostConfig"]["Mounts"]
        return [
            {"Source": item["Source"], "Destination": item["Target"], "RW": not item["ReadOnly"]}
            for item in raw_mounts
        ]
    result = []
    for bind in body["HostConfig"]["Binds"]:
        source, target, mode = bind.rsplit(":", 2)
        result.append({"Source": source, "Destination": target, "RW": mode == "rw"})
    return result


def _canonical_digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _check_legacy_proof(proof, expected_proof_sha256, daemon_id, run_id,
                        api_version, image_ref, name, body):
    _require(type(proof) is dict, "legacy Binds requires a hash-bound metadata-only proof")
    _require(type(expected_proof_sha256) is str and ID_RE.fullmatch(expected_proof_sha256),
             "legacy Binds requires a separately supplied proof SHA-256")
    required = {
        "schema", "kind", "run_id", "daemon_id", "api_version", "image_ref", "create_name",
        "create_http_status", "create_id", "create_warnings", "source_absent_before",
        "source_absent_after", "worker_started", "inspect_projection", "proof_sha256",
    }
    _require(set(proof) == required, "legacy proof has missing or unknown fields")
    unsigned = {key: value for key, value in proof.items() if key != "proof_sha256"}
    _require(proof["proof_sha256"] == _canonical_digest(unsigned), "legacy proof hash mismatch")
    _require(proof["proof_sha256"] == expected_proof_sha256,
             "legacy proof does not match the separately supplied SHA-256")
    _require(proof["schema"] == LEGACY_PROOF_SCHEMA, "unsupported legacy proof schema")
    _require(proof["kind"] == "metadata_only_no_early_create", "legacy proof is not metadata-only")
    _require(proof["run_id"] == run_id, "legacy proof run mismatch")
    _require(proof["daemon_id"] == daemon_id, "legacy proof daemon identity mismatch")
    _require(proof["api_version"] == api_version, "legacy proof API version mismatch")
    _require(proof["image_ref"] == image_ref, "legacy proof image mismatch")
    _require(proof["create_name"] == name, "legacy proof create name mismatch")
    _require(proof["create_http_status"] == 201, "legacy proof create did not return HTTP 201")
    _require(type(proof["create_id"]) is str and ID_RE.fullmatch(proof["create_id"]),
             "legacy proof create ID is invalid")
    _require(proof["create_warnings"] == [], "legacy proof contains warnings")
    _require(proof["source_absent_before"] is True and proof["source_absent_after"] is True,
             "legacy proof does not establish source absence before and after create")
    _require(proof["worker_started"] is False, "legacy proof includes a worker start")
    expected = _projection_from_body(name, body, "conditional_legacy_binds")
    expected["Id"] = proof["create_id"]
    _require(proof["inspect_projection"] == expected, "legacy proof inspect projection mismatch")


def prepare_create_request(run_id, image_ref, postgres_id, api_version, daemon_id, *,
                           variant="strict_mounts", legacy_proof=None,
                           expected_legacy_proof_sha256=None):
    """Return an exact offline Engine request draft for the supplied identities.

    `api_version` is mandatory because it must be bound to the daemon by the
    caller at a separately authorized implementation time. No transport is
    opened and this function never sends the returned POST.
    """
    _require(type(run_id) is str and RUN_RE.fullmatch(run_id), "run_id must be 12 decimal digits")
    _require(type(image_ref) is str and IMAGE_RE.fullmatch(image_ref), "image_ref must be an immutable sha256 digest")
    _require(image_ref == WORKER_IMAGE, "image_ref differs from the reviewed worker image")
    _require(type(postgres_id) is str and ID_RE.fullmatch(postgres_id), "postgres_id must be a full lowercase Engine ID")
    _require(type(api_version) is str and API_RE.fullmatch(api_version), "api_version must be supplied as major.minor")
    _require(type(daemon_id) is str and ID_RE.fullmatch(daemon_id), "daemon_id must be a full lowercase Engine ID")
    _require(variant in ("strict_mounts", "conditional_legacy_binds"), "unknown create variant")

    name = f"orq41-blocked-{run_id}-synthetic-worker-b0"
    body = _expected_body(run_id, image_ref, postgres_id, variant)
    if variant == "conditional_legacy_binds":
        _check_legacy_proof(legacy_proof, expected_legacy_proof_sha256, daemon_id,
                            run_id, api_version, image_ref, name, body)
    else:
        _require(legacy_proof is None and expected_legacy_proof_sha256 is None,
                 "legacy proof is only valid for the legacy Binds variant")
    request = {
        "transport": "unix:///var/run/docker.sock",
        "method": "POST",
        "path": f"/v{api_version}/containers/create?name={name}",
        "body": body,
        "variant": variant,
        "run_id": run_id,
        "image_ref": image_ref,
        "postgres_id": postgres_id,
        "daemon_id": daemon_id,
        "api_version": api_version,
        "readiness": "PREPARATION_ONLY_NOT_RUNTIME_READINESS",
        "request_sent": False,
        "selected": False,
        "executable": False,
    }
    request["draft_sha256"] = _canonical_digest(request)
    return request


def validate_create_response(http_status, payload):
    """Validate one already-observed response; never retries or resends."""
    _require(type(http_status) is int and http_status == 201, "create response must be HTTP 201")
    if type(payload) is bytes:
        _require(len(payload) <= 65_536, "create response body exceeds the 64 KiB limit")

        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                _require(key not in value, "create response contains duplicate JSON keys")
                value[key] = item
            return value

        try:
            decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("create response is not valid UTF-8 JSON") from error
        _require(payload == json.dumps(decoded, sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=True).encode("ascii"),
                 "create response JSON is not canonical")
        payload = decoded
    _require(type(payload) is dict and set(payload) == {"Id", "Warnings"},
             "create response has missing or unknown fields")
    _require(type(payload["Id"]) is str and ID_RE.fullmatch(payload["Id"]),
             "create response ID must be 64 lowercase hexadecimal characters")
    _require(type(payload["Warnings"]) is list and payload["Warnings"] == [],
             "create response contains warnings")
    return payload["Id"]


def validate_inspect(inspect, request, worker_id):
    """Check a returned inspect document against the frozen request projection."""
    _require(type(request) is dict and request.get("method") == "POST", "invalid prepared request")
    _require(request.get("request_sent") is False, "request draft must remain offline")
    _require(set(request) == {"transport", "method", "path", "body", "variant", "readiness",
                              "request_sent", "selected", "executable", "run_id",
                              "image_ref", "postgres_id", "daemon_id", "api_version",
                              "draft_sha256"},
             "prepared request has missing or unknown fields")
    _require(request["transport"] == "unix:///var/run/docker.sock",
             "prepared request transport differs from the local Engine socket")
    _require(request["selected"] is False and request["executable"] is False,
             "prepared request cannot be selected or executable")
    _require(request["readiness"] == "PREPARATION_ONLY_NOT_RUNTIME_READINESS",
             "prepared request cannot claim runtime readiness")
    unsigned_request = {key: value for key, value in request.items() if key != "draft_sha256"}
    _require(request["draft_sha256"] == _canonical_digest(unsigned_request),
             "prepared request draft hash mismatch")
    body = request.get("body")
    variant = request.get("variant")
    _require(type(body) is dict and variant in ("strict_mounts", "conditional_legacy_binds"),
             "invalid prepared request body or variant")
    _require(type(request["run_id"]) is str and RUN_RE.fullmatch(request["run_id"]), "invalid draft run_id")
    _require(type(request["image_ref"]) is str and IMAGE_RE.fullmatch(request["image_ref"])
             and request["image_ref"] == WORKER_IMAGE, "invalid draft image_ref")
    _require(type(request["postgres_id"]) is str and ID_RE.fullmatch(request["postgres_id"]),
             "invalid draft postgres_id")
    _require(type(request["daemon_id"]) is str and ID_RE.fullmatch(request["daemon_id"]),
             "invalid draft daemon_id")
    _require(type(request["api_version"]) is str and API_RE.fullmatch(request["api_version"]),
             "invalid draft API version")
    name = f"orq41-blocked-{request['run_id']}-synthetic-worker-b0"
    _require(request["path"] == f"/v{request['api_version']}/containers/create?name={name}",
             "prepared request path differs from its bound identities")
    expected_body = _expected_body(request["run_id"], request["image_ref"],
                                   request["postgres_id"], variant)
    _require(body == expected_body, "prepared request body differs from the reviewed worker shape")
    expected = _projection_from_body(name, body, variant)
    _require(type(inspect) is dict, "inspect result must be an object")
    _require(type(worker_id) is str and ID_RE.fullmatch(worker_id),
             "worker_id must be the full lowercase ID returned by create")
    _require(inspect.get("Id") == worker_id, "inspect ID differs from the create response ID")
    config = inspect.get("Config")
    host = inspect.get("HostConfig")
    mounts = inspect.get("Mounts")
    _require(type(config) is dict and type(host) is dict and type(mounts) is list,
             "inspect result is missing Config, HostConfig, or Mounts")
    observed = {
        "Name": inspect.get("Name"),
        "Image": config.get("Image"),
        "Entrypoint": config.get("Entrypoint"),
        "Cmd": config.get("Cmd"),
        "User": config.get("User"),
        "Resources": {
            "CgroupParent": host.get("CgroupParent"),
            "CpusetCpus": host.get("CpusetCpus"),
            "NanoCpus": host.get("NanoCpus"),
            "Memory": host.get("Memory"),
            "MemorySwap": host.get("MemorySwap"),
            "RestartPolicy": host.get("RestartPolicy"),
            "Privileged": host.get("Privileged"),
            "CapAdd": host.get("CapAdd"),
            "PortBindings": host.get("PortBindings"),
            "NetworkMode": host.get("NetworkMode"),
        },
        "Mounts": [
            {"Source": item.get("Source"), "Destination": item.get("Destination"), "RW": item.get("RW")}
            if type(item) is dict else item
            for item in mounts
        ],
    }
    _require(observed == expected, "inspect projection differs from the prepared create request")
    return True
