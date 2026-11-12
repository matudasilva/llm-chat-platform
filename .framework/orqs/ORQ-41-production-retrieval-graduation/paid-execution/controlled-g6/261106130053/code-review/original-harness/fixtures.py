"""Synthetic, independently declared G1/G2/G3 fixtures. No import-time I/O.

Provisioning is deliberately separate from HTTP execution. These functions must
only receive an already provisioned disposable validation database, never C0's
preserved database. No schema, role or grant management belongs here.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from dataclasses import asdict, dataclass
from uuid import UUID, uuid5

from sqlalchemy import text

P3_SHA256 = "0334e3af47edf9c885093a6ad061390f6f85ba62517e56b94450339950599d4f"
P3_FINGERPRINT = "787ae13719ef23c5043449d7d2e84bd489e5896e18d0fe5a035f76e8c6df0999"
P3_CONTENT_SHA256 = "9fa959aeeb5d332882d61f60528eaa72468f110705c51ce05b70e213dd168506"
NAMESPACE = UUID("57398522-e838-48a2-b198-a5e6fceea801")


class HarnessError(ValueError):
    """Invalid/ambiguous evidence, never a passing or skipped gate."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def run_database(run_id, reference):
    if not re.fullmatch(r"[a-z0-9]{8,20}", run_id) or reference not in {"c0", "c1"}:
        raise HarnessError("invalid disposable database identity")
    return f"orq41_g123_{run_id}_{reference}"


@dataclass(frozen=True)
class Fixture:
    run_id: str
    profile: str = "base"

    def __post_init__(self):
        run_database(self.run_id, "c1")
        if self.profile not in {"base", "empty", "equal_text_distinct_ids", "long_history", "source_trim", "cap_exhaustion"}:
            raise HarnessError("unknown synthetic fixture profile")

    def id(self, name):
        return str(uuid5(NAMESPACE, f"{self.run_id}/{name}"))

    def tenant(self, name="own"):
        if name not in {"own", "foreign"}:
            raise HarnessError("unknown fixture tenant")
        return f"g123-{self.run_id}-{name}"

    def rows(self):
        conversations = [dict(id=self.id(name), tenant_id=self.tenant(tenant))
                         for name, tenant in [("current", "own"), ("other", "own"), ("foreign", "foreign")]]
        messages = [dict(id=self.id(f"{name}-{role}"), conversation_id=self.id(name),
                         tenant_id=self.tenant(tenant), role=role,
                         content=f"{name} {role} provenance á 漢字 👩‍💻")
                    for name, tenant in [("current", "own"), ("other", "own"), ("foreign", "foreign")]
                    for role in ("user", "assistant")]
        documents = [dict(id=self.id(f"document-{tenant}"), chunk_id=self.id(f"chunk-{tenant}"),
                          tenant_id=self.tenant(tenant), content=f"{tenant} retrieval provenance á 漢字 👩‍💻")
                     for tenant in ("own", "foreign")]
        if self.profile == "empty":
            messages, documents = [], []
        if self.profile == "equal_text_distinct_ids":
            documents.append({**documents[0], "id": self.id("document-own-equal"), "chunk_id": self.id("chunk-own-equal")})
            messages[1]["content"] = messages[0]["content"]
        if self.profile == "long_history":
            messages += [dict(id=self.id(f"long-{index}-{role}"), conversation_id=self.id("current"),
                              tenant_id=self.tenant(), role=role, content=f"history {index} {role} " + "provenance " * 80)
                         for index in range(60) for role in ("user", "assistant")]
        if self.profile in {"source_trim", "cap_exhaustion"}:
            documents[0]["content"] *= 1000
        if self.profile == "cap_exhaustion":
            messages += [dict(id=self.id(f"cap-{role}"), conversation_id=self.id("current"),
                              tenant_id=self.tenant(), role=role, content="context budget " * 2000)
                         for role in ("user", "assistant")]
        return dict(conversations=conversations, messages=messages, documents=documents)


# These are required families, not assertions inferred from a candidate run.
# Every applicable cell must be expanded into a concrete frozen oracle before
# execution. Missing families prevent a complete-package PASS.
CONTEXT_CASES = (
    "own", "other_conversation", "foreign_conversation", "missing_conversation",
    "foreign_document_poison", "documents_only", "history_only", "combined",
    "episodic_out_of_window", "episodic_no_eligible", "empty", "disabled",
    "equal_text_distinct_ids", "long_history", "source_trim", "cap_exhaustion",
    "oversized_current", "unicode", "serialization_failure", "cancel_before_dispatch",
    "error_after_dispatch", "lost_observation", "duplicate_observation",
    "corrupt_observation", "reordered_observation", "wrong_execution",
    "wrong_attempt", "wrong_purpose", "repeated_request_id",
)
TRANSACTION_CASES = (
    "success_new", "success_existing", "uncommitted_visibility", "provider_error",
    "partial_stream_error", "history_timeout", "history_error", "retrieval_timeout",
    "retrieval_error", "episodic_error", "telemetry_timeout", "telemetry_error",
    "observer_error", "disconnect_before_dispatch", "disconnect_provider_wait",
    "disconnect_after_token", "cancel_before_dispatch", "cancel_provider_wait",
    "cancel_after_user_flush", "cancel_after_token", "flush_rejection",
    "commit_connection_loss", "postcommit_response_loss", "wrapper_control",
)


OBSERVATION_FAULTS = frozenset({"lost_observation", "duplicate_observation", "corrupt_observation",
                              "reordered_observation", "wrong_execution", "wrong_attempt", "wrong_purpose"})
DEPENDENCY_FAULTS = frozenset({"history_error", "history_timeout", "retrieval_error", "retrieval_timeout",
                             "episodic_error", "telemetry_error", "telemetry_timeout", "observer_error"})


def scenario(family, protocol):
    """Approved scenario requirements, independent of operator-supplied oracles."""
    actions = {
        "commit_connection_loss": ("commit_connection_loss", "before_commit"),
        "postcommit_response_loss": ("postcommit_response_loss", "after_commit"),
        "uncommitted_visibility": ("inspect_uncommitted", "primary_provider_wait"),
        "cancel_before_dispatch": ("server_cancel", "before_dispatch"),
        "cancel_provider_wait": ("server_cancel", "primary_provider_wait"),
        "cancel_after_user_flush": ("server_cancel", "after_user_flush"),
        "cancel_after_token": ("server_cancel", "wire_token"),
        "disconnect_before_dispatch": ("disconnect", "before_dispatch"),
        "disconnect_provider_wait": ("disconnect", "primary_provider_wait"),
        "disconnect_after_token": ("disconnect", "wire_token"),
    }
    if family in actions:
        action, barrier = actions[family]
        if family == "disconnect_before_dispatch" and protocol == "sse":
            barrier = "primary_before_dispatch"
        return dict(fault="none" if family == "uncommitted_visibility" else family,
                    action=action, barrier=barrier, marker=None)
    markers = {"serialization_failure": "serialize", "error_after_dispatch": "after_dispatch",
               "provider_error": "before", "partial_stream_error": "after_token", "flush_rejection": "flush_rejection"}
    if family in DEPENDENCY_FAULTS | OBSERVATION_FAULTS:
        markers[family] = family
    return dict(fault=family if family in markers else "none", action=None, barrier="none", marker=markers.get(family))


def minimum_cells():
    """Prospective applicability floor: no caller-supplied matrix can lower it.

    E1-only branches require E1; observer faults require the candidate; wire-token
    faults are SSE-only. Other context rows cover both native adapters and paths.
    OFF compatibility uses both sources. EN/ES applies to positive/Unicode rows.
    """
    cells = set()
    for family in set(CONTEXT_CASES + TRANSACTION_CASES):
        if family == "disabled":
            arms = [("OFF", "c0"), ("OFF", "c1")]
        elif family.startswith("episodic_"):
            arms = [("E1", "c1")]
        elif family in OBSERVATION_FAULTS or family == "observer_error":
            arms = [("C1", "c1")]
        else:
            arms = [("C0", "c0"), ("C1", "c1")]
        protocols = ("sse",) if family in {"partial_stream_error", "cancel_after_token", "disconnect_after_token"} else ("json", "sse")
        adapters = ("bedrock", "openai") if family in CONTEXT_CASES else ("scripted",)
        languages = ("en", "es") if family in {"own", "unicode"} else ("en",)
        for vector, reference in arms:
            for protocol in protocols:
                for adapter in adapters:
                    for language in languages:
                        cells.add((family, vector, reference, protocol, adapter, language))
    return frozenset(cells)


def cell_key(case):
    return (case.family, case.vector, case.reference, case.protocol, case.adapter, case.language)


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    gate: str
    vector: str
    protocol: str
    adapter: str
    language: str
    # Canonical JSON strings prevent later mutation of a frozen dataclass's
    # nested expectations. No default or candidate-generated oracle is allowed.
    request_json: str
    oracle_json: str
    fault: str
    reference: str | None = None

    def __post_init__(self):
        if self.reference is None:
            object.__setattr__(self, "reference", "c0" if self.vector == "C0" else "c1")
        if (not self.case_id or self.gate not in {"G1", "G2", "G3"}
                or self.family not in CONTEXT_CASES + TRANSACTION_CASES
                or self.vector not in {"C0", "C1", "OFF", "E1"}
                or self.protocol not in {"json", "sse"}
                or self.adapter not in {"bedrock", "openai", "scripted"}
                or self.language not in {"en", "es"}):
            raise HarnessError("invalid case identity")
        if self.reference not in {"c0", "c1"} or (self.vector != "OFF" and self.reference != ("c0" if self.vector == "C0" else "c1")):
            raise HarnessError("source/vector mismatch")
        request, oracle = json.loads(self.request_json), json.loads(self.oracle_json)
        required = {"http_status", "terminal", "db_delta", "sources", "forbidden_ids",
                    "capture", "cleanup_s", "barrier", "positive_delivery", "evidence_expected"}
        if not isinstance(request, dict) or not isinstance(oracle, dict) or not required <= oracle.keys():
            raise HarnessError("incomplete independent oracle")
        if request.get("stream", False) != (self.protocol == "sse"):
            raise HarnessError("protocol/request mismatch")
        if not 0 < oracle["cleanup_s"] <= 10:
            raise HarnessError("cleanup bound exceeds approval")
        if self.gate in {"G1", "G2"} and self.adapter == "scripted":
            raise HarnessError("scripted port cannot certify delivery")
        if oracle["evidence_expected"] not in {"valid", "rejected", "baseline"}:
            raise HarnessError("invalid evidence expectation")
        if (self.reference == "c0") != (oracle["evidence_expected"] == "baseline"):
            raise HarnessError("baseline/candidate evidence mismatch")
        if not isinstance(oracle["positive_delivery"], bool):
            raise HarnessError("invalid delivery expectation")
        for table, fields in (("messages", {"role", "content", "tenant_id"}), ("conversations", {"tenant_id"})):
            delta = oracle["db_delta"].get(table, {})
            if not fields <= set(delta.get("fields", [])) or not isinstance(delta.get("rows"), list):
                raise HarnessError("business oracle omits required identity/content fields")
        contract = scenario(self.family, self.protocol)
        if self.fault != contract["fault"] or oracle["barrier"] != contract["barrier"] or oracle.get("action") != contract["action"]:
            raise HarnessError("scenario/fault/action/barrier mismatch")
        if self.family in {"partial_stream_error", "cancel_after_token", "disconnect_after_token"} and self.protocol != "sse":
            raise HarnessError("wire-token scenario requires SSE")
        if self.family in {"commit_connection_loss", "provider_error", "partial_stream_error", "serialization_failure", "error_after_dispatch", "flush_rejection"} or contract["action"] == "server_cancel":
            if oracle["terminal"] in {"success", "done"} or any(oracle["db_delta"][table]["rows"] for table in ("conversations", "messages")):
                raise HarnessError("precommit failure requires no committed business exchange")
        if contract["action"] in {"disconnect", "postcommit_response_loss", "server_cancel"} and oracle.get("client_outcome") != "unresolved":
            raise HarnessError("cancelled client/server requires unresolved client oracle")
        if self.family == "postcommit_response_loss" and len(oracle["db_delta"]["messages"]["rows"]) != 2:
            raise HarnessError("postcommit response loss must preserve exchange")
        if self.family == "uncommitted_visibility" and (oracle["terminal"] not in {"success", "done"} or len(oracle["db_delta"]["messages"]["rows"]) != 2):
            raise HarnessError("visibility control requires a complete final exchange")


async def assert_database(session, database):
    if not re.fullmatch(r"orq41_g123_[a-z0-9]{8,20}_c[01]", database):
        raise HarnessError("refusing non-disposable database")
    actual = (await session.execute(text("SELECT current_database()"))).scalar_one()
    if actual != database:
        raise HarnessError("database identity mismatch")


async def seed(session, fixture, database):
    """Caller owns the real transaction; collisions are errors, never upserts."""
    await assert_database(session, database)
    rows = fixture.rows()
    for row in rows["conversations"]:
        await session.execute(text("INSERT INTO conversations (id,tenant_id) VALUES (CAST(:id AS uuid),:tenant_id)"), row)
    for row in rows["messages"]:
        await session.execute(text("""INSERT INTO messages (id,conversation_id,tenant_id,role,content)
            VALUES (CAST(:id AS uuid),CAST(:conversation_id AS uuid),:tenant_id,CAST(:role AS message_role),:content)"""), row)
    for row in rows["documents"]:
        await session.execute(text("""INSERT INTO documents
            (id,tenant_id,source_path,content_hash,doc_type,indexing_mode)
            VALUES (CAST(:id AS uuid),:tenant_id,:source_path,:content_hash,'text','plain')"""),
            {**row, "source_path": f"synthetic/{row['id']}", "content_hash": hashlib.sha256(row["content"].encode()).hexdigest()})
        await session.execute(text("""INSERT INTO chunks
            (id,document_id,tenant_id,ordinal,text,embedding,search_vector)
            VALUES (CAST(:chunk_id AS uuid),CAST(:id AS uuid),:tenant_id,0,:content,
                    CAST(:embedding AS vector),to_tsvector('simple',:content))"""),
            {**row, "embedding": json.dumps([1.0] + [0.0] * 1535)})


async def readback(session, fixture, database):
    """Independent reader; sequence is observed, never assumed gapless."""
    await assert_database(session, database)
    result = {}
    for table, columns in [("conversations", "id,tenant_id,title,metadata,created_at,updated_at"),
                           ("messages", "id,conversation_id,tenant_id,sequence,role,content,created_at")]:
        rows = (await session.execute(text(f"SELECT {columns} FROM {table} ORDER BY id"))).mappings().all()
        result[table] = [{key: str(value) if isinstance(value, (UUID, datetime)) else value for key, value in row.items()} for row in rows]
    # Ancillary writes are retained separately, never counted as half exchanges.
    # This is a dedicated disposable DB; usage has no tenant column and must
    # not be presented as authoritatively joined through a repeated request_id.
    for table, columns in [("usage_events", "id,request_id,conversation_id,message_id,status,provider,model_version"),
                           ("rag_request_metrics", "id,request_instance_id,request_id,tenant_id,generation_outcome")]:
        rows = (await session.execute(text(f"SELECT {columns} FROM {table} ORDER BY id"))).mappings().all()
        result[table] = [{key: str(value) if isinstance(value, UUID) else value for key, value in row.items()} for row in rows]
    return result


async def cleanup(session, fixture, database):
    """Only run-owned synthetic tenants; never delete/repair the P3 corpus."""
    await assert_database(session, database)
    for table in ("conversations", "documents"):
        await session.execute(text(f"DELETE FROM {table} WHERE tenant_id IN (:own,:foreign)"),
                              dict(own=fixture.tenant(), foreign=fixture.tenant("foreign")))


def conflicting_message(fixture):
    """A real PK collision against a pre-seeded row, not a raised fake error."""
    from app.models.message import Message, MessageRole

    def add(session):
        session.add(Message(id=UUID(fixture.id("current-user")), conversation_id=UUID(fixture.id("current")),
                            tenant_id=fixture.tenant(), role=MessageRole.user, content="controlled real flush conflict"))
    return add


def freeze(cases, identities):
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise HarnessError("empty/duplicate case manifest")
    required = {"run_id", "source", "images", "config", "fixture", "harness", "p3_sha256", "p3_fingerprint"}
    if not required <= identities.keys() or any(not identities[key] for key in required):
        raise HarnessError("missing frozen identities")
    if identities["p3_sha256"] != P3_SHA256 or identities["p3_fingerprint"] != P3_FINGERPRINT:
        raise HarnessError("wrong corpus identity")
    scoped = identities.get("cases")
    if len({(case.vector, case.reference) for case in cases}) > 1 and scoped is None:
        raise HarnessError("mixed vectors require per-case execution identities")
    if scoped is not None:
        if set(scoped) != {case.case_id for case in cases}:
            raise HarnessError("incomplete/extra per-case execution identities")
        for value in scoped.values():
            if set(value) != {"source", "config", "fixture", "harness"} or any(not field for field in value.values()):
                raise HarnessError("invalid per-case execution identity")
    body = dict(version=2, identities=identities, cases=[asdict(case) for case in cases],
                minimum_cells=[list(cell) for cell in sorted(minimum_cells())])
    # Return bytes, not mutable objects; retain before the first request.
    return canonical(dict(body=body, sha256=fingerprint(body)))


def execution_identity(body, case):
    """One frozen packet, distinct source/config/fixture inventories per cell."""
    common = body["identities"]
    return common | common["cases"][case.case_id] if "cases" in common else common


def execution_identity_sha256(body, case):
    selected = execution_identity(body, case)
    return fingerprint({key: selected[key] for key in ("source", "config", "fixture", "harness")})


def expand_cases(declarations):
    """Expand only explicitly supplied independent cell oracles.

    The declaration contains a common family/gate/fault and a nonempty `cells`
    list of concrete vector/protocol/adapter/language/request/oracle dictionaries.
    No implicit Cartesian expansion reuses an oracle across different protocols.
    """
    result = []
    for declaration in declarations:
        cells = declaration["cells"]
        if not cells:
            raise HarnessError("empty case expansion")
        for cell in cells:
            reference = cell.get("reference", "c0" if cell["vector"] == "C0" else "c1")
            name = "/".join([declaration["family"], cell["vector"], reference, cell["protocol"], cell["adapter"], cell["language"]])
            result.append(Case(case_id=name, family=declaration["family"], gate=declaration["gate"],
                               vector=cell["vector"], protocol=cell["protocol"], adapter=cell["adapter"], language=cell["language"],
                               request_json=canonical(cell["request"]).decode(), oracle_json=canonical(cell["oracle"]).decode(), fault=declaration["fault"], reference=reference))
    if len({case.case_id for case in result}) != len(result):
        raise HarnessError("duplicate expanded cell")
    return tuple(result)
