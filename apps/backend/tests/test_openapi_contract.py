import re
from collections.abc import Set
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
import yaml
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from waterfall.api.revision_errors import REVISION_IMMUTABLE
from waterfall.api.routes import estimates
from waterfall.main import app
from waterfall.services import (
    PlanningTreeCascadeConfirmationRequiredError,
    PlanningTreeTaskReferencedError,
)

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "waterfall_v1.yaml"
GENERATED_CLIENT_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "api-client-ts"
    / "src"
    / "generated"
    / "api-types.ts"
)
PATH_PARAMETER = re.compile(r"\{[^}]+\}")
DOCUMENTATION_PATHS = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
PUBLIC_OPERATIONS = {
    ("/health", "get"),
    ("/health/ready", "get"),
    ("/metrics", "get"),
    ("/auth/register", "post"),
    ("/auth/token", "post"),
    ("/auth/refresh", "post"),
    ("/auth/logout", "post"),
}


def _normalize_path(path: str) -> str:
    return PATH_PARAMETER.sub("{}", path)


def _normalize_parameter_name(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _parameter_signature(
    operation: dict[str, Any], document: dict[str, Any] | None = None
) -> set[tuple[str, str, bool]]:
    parameters = operation.get("parameters", [])
    if document is not None:
        parameter_components = document.get("components", {}).get("parameters", {})
        parameters = [
            parameter_components.get(parameter["$ref"].rsplit("/", 1)[-1], parameter)
            if "$ref" in parameter
            else parameter
            for parameter in parameters
        ]
    return {
        (
            parameter["in"],
            (
                f"path:{index}"
                if parameter["in"] == "path"
                else _normalize_parameter_name(parameter["name"])
            ),
            parameter.get("required", False),
        )
        for index, parameter in enumerate(parameters)
    }


def _direct_response_refs(operation: dict[str, Any]) -> dict[str, str | None]:
    refs: dict[str, str | None] = {}
    for code in ("200", "201"):
        response = operation.get("responses", {}).get(code, {})
        schema = response.get("content", {}).get("application/json", {}).get("schema", {})
        refs[code] = schema.get("$ref")
    return refs


def _schema_property_names(schema: dict[str, Any], components: dict[str, Any]) -> set[str]:
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _schema_property_names(components[name], components)
    names = set(schema.get("properties", {}))
    for item in schema.get("allOf", []):
        names.update(_schema_property_names(item, components))
    return names


def _runtime_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    pending_routes: list[Any] = list(app.routes)
    while pending_routes:
        route = pending_routes.pop()
        nested_routes = getattr(route, "routes", None)
        if isinstance(nested_routes, list):
            pending_routes.extend(cast(list[Any], nested_routes))
        original_router = getattr(route, "original_router", None)
        original_routes = getattr(original_router, "routes", None)
        if isinstance(original_routes, list):
            pending_routes.extend(cast(list[Any], original_routes))

        route_path = getattr(route, "path", None)
        route_methods = getattr(route, "methods", None)
        if (
            not isinstance(route_path, str)
            or not isinstance(route_methods, Set)
            or route_path in DOCUMENTATION_PATHS
        ):
            continue
        typed_methods = cast(Set[str], route_methods)
        for method in typed_methods:
            if method not in {"HEAD", "OPTIONS"}:
                operations.add((_normalize_path(route_path), method.lower()))
    return operations


def test_static_openapi_matches_runtime_routes() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_document, dict):
        raise AssertionError("OpenAPI document must be an object")

    static_document = cast(dict[str, Any], raw_document)
    static_paths = cast(dict[str, dict[str, Any]], static_document["paths"])
    static_operations: set[tuple[str, str]] = set()
    for path, path_operations in static_paths.items():
        for method in path_operations:
            if method in {"get", "post", "put", "patch", "delete"}:
                static_operations.add((_normalize_path(path), method))

    assert static_operations == _runtime_operations()


def test_static_openapi_uses_31_nullability_syntax() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    def find_nullable_paths(value: object, path: str = "$") -> list[str]:
        if isinstance(value, dict):
            paths = [f"{path}/nullable"] if "nullable" in value else []
            for key, child in cast(dict[object, object], value).items():
                paths.extend(find_nullable_paths(child, f"{path}/{key}"))
            return paths
        if isinstance(value, list):
            paths = []
            for index, child in enumerate(cast(list[object], value)):
                paths.extend(find_nullable_paths(child, f"{path}/{index}"))
            return paths
        return []

    assert find_nullable_paths(raw_document) == []


def test_nullable_enums_include_null_member() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))

    def find_invalid_enum_paths(value: object, path: str = "$") -> list[str]:
        if isinstance(value, dict):
            schema = cast(dict[object, object], value)
            type_value = schema.get("type")
            enum_value = schema.get("enum")
            paths = (
                [path]
                if isinstance(type_value, list)
                and "null" in type_value
                and isinstance(enum_value, list)
                and None not in enum_value
                else []
            )
            for key, child in schema.items():
                paths.extend(find_invalid_enum_paths(child, f"{path}/{key}"))
            return paths
        if isinstance(value, list):
            paths = []
            for index, child in enumerate(cast(list[object], value)):
                paths.extend(find_invalid_enum_paths(child, f"{path}/{index}"))
            return paths
        return []

    assert find_invalid_enum_paths(raw_document) == []


def test_static_openapi_declares_repository_license() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_document, dict):
        raise AssertionError("OpenAPI document must be an object")

    assert raw_document["info"]["license"] == {
        "name": "GNU Affero General Public License v3.0 only",
        "identifier": "AGPL-3.0-only",
    }


def test_public_operations_explicitly_disable_security() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_document, dict):
        raise AssertionError("OpenAPI document must be an object")

    paths = cast(dict[str, dict[str, Any]], raw_document["paths"])
    unauthenticated_operations = {
        (path, method)
        for path, operations in paths.items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and operation.get("security") == []
    }
    assert unauthenticated_operations == PUBLIC_OPERATIONS


def _enums_by_path(schema: object, path: str = "$") -> dict[str, list[object]]:
    """Every ``enum`` under ``schema``, keyed by where it sits.

    Keyed by path, so a static spec that moved an enumeration to another property (or
    lost the surrounding ``anyOf`` a nullable field generates) fails just as loudly as
    one whose members drifted.
    """
    if isinstance(schema, dict):
        node = cast(dict[str, Any], schema)
        members = node.get("enum")
        found = {path: cast(list[object], members)} if isinstance(members, list) else {}
        for key, child in node.items():
            found.update(_enums_by_path(child, f"{path}/{key}"))
        return found
    if isinstance(schema, list):
        found: dict[str, list[object]] = {}
        for index, child in enumerate(cast(list[object], schema)):
            found.update(_enums_by_path(child, f"{path}/{index}"))
        return found
    return {}


def test_static_openapi_matches_runtime_operation_ids_and_components() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw_document, dict):
        raise AssertionError("OpenAPI document must be an object")

    static_document = cast(dict[str, Any], raw_document)
    runtime_document = app.openapi()
    static_components = cast(dict[str, Any], static_document["components"])["schemas"]
    runtime_components = cast(dict[str, Any], runtime_document["components"])["schemas"]
    assert static_components["PlanningCreate"].get("required") == runtime_components[
        "PlanningCreate"
    ].get("required")
    for schema_name in (
        "ProjectRead",
        "ProjectStatusUpdate",
        "PlanningRead",
        "PlanningCreate",
        "PlanningLinkRead",
        "ReconciliationPlanRead",
        # E14-05 (#331): the revision tree replaces the planning-snapshot read and
        # its whole mutation family, so it is anchored here in their place.
        "RevisionTreeRead",
        "RevisionNodeRead",
        "RevisionPlanFacetUpdate",
    ):
        assert schema_name in runtime_components
        assert schema_name in static_components
        static_schema = cast(dict[str, Any], static_components[schema_name])
        runtime_schema = cast(dict[str, Any], runtime_components[schema_name])
        assert set(static_schema.get("properties", {})) == set(runtime_schema["properties"])

    # Enumerations, hand-copied into the static spec value by value, compared by the
    # path they sit at rather than by schema (#331 review, B5). The properties compared
    # above are a set of *names*: an enumeration losing a member -- which is what M1
    # was, on the MSPDI `LagFormat` -- changes nothing in that set while publishing to
    # every client a narrower domain than the API accepts, or a wider one than it does.
    for schema_name in ("RevisionPlanFacetUpdate", "RevisionPredecessorWrite"):
        static_schema = cast(dict[str, Any], static_components[schema_name])
        runtime_schema = cast(dict[str, Any], runtime_components[schema_name])
        static_enums = _enums_by_path(static_schema)
        assert static_enums, f"{schema_name} is anchored here for its enums and has none"
        assert static_enums == _enums_by_path(runtime_schema)

    static_move = cast(dict[str, Any], static_components["RevisionNodeMove"])
    runtime_move = cast(dict[str, Any], runtime_components["RevisionNodeMove"])
    assert (
        static_move["properties"]["node_ids"]["minItems"]
        == runtime_move["properties"]["node_ids"]["minItems"]
    )
    assert (
        static_move["properties"]["node_ids"]["items"]["exclusiveMinimum"]
        == runtime_move["properties"]["node_ids"]["items"]["exclusiveMinimum"]
    )

    static_plan = cast(dict[str, Any], static_components["ReconciliationPlanRead"])
    runtime_plan = cast(dict[str, Any], runtime_components["ReconciliationPlanRead"])
    for field_name in (
        "tasks_to_delete",
        "labor_to_update",
        "labor_to_delete",
        "non_labor_to_update",
        "non_labor_to_delete",
    ):
        assert (
            static_plan["properties"][field_name]["items"]["minimum"]
            == runtime_plan["properties"][field_name]["items"]["minimum"]
        )

    static_operation_ids = {
        operation["operationId"]
        for path_operations in cast(dict[str, dict[str, Any]], static_document["paths"]).values()
        for method, operation in path_operations.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert len(static_operation_ids) == sum(
        method in {"get", "post", "put", "patch", "delete"}
        for path_operations in cast(dict[str, dict[str, Any]], static_document["paths"]).values()
        for method in path_operations
    )


def test_planning_contract_matches_runtime_shapes() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_paths = cast(dict[str, dict[str, Any]], static_document["paths"])
    runtime_paths = cast(dict[str, dict[str, Any]], app.openapi()["paths"])
    relevant = {
        path
        for path in static_paths
        if "/plannings" in path
        or "/revisions/" in path
        or path.endswith("/export.xml")
        or "/estimates" in path
    }
    assert {
        (_normalize_path(path), method)
        for path in relevant
        for method in static_paths[path]
        if method in {"get", "post", "put", "patch", "delete"}
    } == {
        (_normalize_path(path), method)
        for path in runtime_paths
        for method in runtime_paths[path]
        if method in {"get", "post", "put", "patch", "delete"}
        and (
            "/plannings" in path
            or "/revisions/" in path
            or path.endswith("/export.xml")
            or "/estimates" in path
        )
    }
    for path in relevant:
        runtime_path = next(
            candidate
            for candidate in runtime_paths
            if _normalize_path(candidate) == _normalize_path(path)
        )
        for method in static_paths[path]:
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            static_operation = cast(dict[str, Any], static_paths[path][method])
            runtime_operation = cast(dict[str, Any], runtime_paths[runtime_path][method])
            assert _parameter_signature(static_operation, static_document) == _parameter_signature(
                runtime_operation
            )
            assert _direct_response_refs(static_operation) == _direct_response_refs(
                runtime_operation
            )

    relevant_schemas = (
        "PlanningRead",
        "PlanningDetailRead",
        "RevisionNodeMove",
        "RevisionTreeRead",
        "TaskRead",
        "PlanningLinkRead",
        "ProjectEstimateRead",
    )
    static_schemas = cast(dict[str, Any], static_document["components"])["schemas"]
    runtime_schemas = cast(dict[str, Any], app.openapi()["components"])["schemas"]
    for schema_name in relevant_schemas:
        assert _schema_property_names(static_schemas[schema_name], static_schemas) == (
            _schema_property_names(runtime_schemas[schema_name], runtime_schemas)
        )


def test_resource_calendar_contract_matches_runtime_shapes() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_schemas = cast(dict[str, Any], static_document["components"])["schemas"]
    runtime_schemas = cast(dict[str, Any], app.openapi()["components"])["schemas"]
    for schema_name in (
        "CalendarCreate",
        "CalendarUpdate",
        "CalendarRead",
        "CalendarWeekdayCreate",
        "CalendarWeekdayRead",
        "ResourceRoleCreate",
        "ResourceRoleUpdate",
        "ResourceRoleRead",
    ):
        assert schema_name in static_schemas
        assert schema_name in runtime_schemas
        assert _schema_property_names(static_schemas[schema_name], static_schemas) == (
            _schema_property_names(runtime_schemas[schema_name], runtime_schemas)
        )

    # ResourceRole no longer has a `code` field (issue #46): accounting_code is derived
    # from cost_category.accounting_code instead, never from a role-owned code proxy.
    for schema_name in ("ResourceRoleCreate", "ResourceRoleRead"):
        assert "code" not in _schema_property_names(static_schemas[schema_name], static_schemas)
        assert "code" not in _schema_property_names(runtime_schemas[schema_name], runtime_schemas)


def test_revision_endpoints_document_their_structured_error_responses() -> None:
    """E14-05 (#331), in place of the move/delete-family contract checks it removed.

    Every refusal of the revision API is a structured ``{"detail": {"code": ...}}``
    body, not the generic ``FastAPIErrorResponse`` (``str | object | array``) the
    endpoints it replaces documented -- a TS client could not type ``error.detail``
    off that one. Pinned here on all six operations at once, with the INV-03 code
    E14-07 (#333) has to reuse verbatim.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_paths = cast(dict[str, Any], static_document["paths"])
    static_components = cast(dict[str, Any], static_document["components"])

    revision_paths = [path for path in static_paths if "/revisions/" in path]
    assert len(revision_paths) == 6
    for path in revision_paths:
        for method, operation in cast(dict[str, Any], static_paths[path]).items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            assert operation["responses"]["404"]["$ref"] == (
                "#/components/responses/RevisionNotFound"
            ), (path, method)
            assert operation["responses"]["409"]["$ref"] == (
                "#/components/responses/RevisionConflict"
            ), (path, method)

    for response_name, schema_name in (
        ("RevisionNotFound", "RevisionErrorResponse"),
        ("RevisionBadRequest", "RevisionErrorResponse"),
        ("RevisionConflict", "RevisionLockConflict"),
    ):
        response = static_components["responses"][response_name]
        assert response["content"]["application/json"]["schema"]["$ref"] == (
            f"#/components/schemas/{schema_name}"
        )

    # The lock conflict carries what a client needs to resynchronise, not just a code.
    conflict_detail = static_components["schemas"]["RevisionLockConflict"]["properties"]["detail"]
    assert conflict_detail["required"] == ["code"]
    assert set(conflict_detail["properties"]) == {
        "code",
        "revision_id",
        "expected_lock_version",
        "current_lock_version",
    }
    # INV-03's code is published, because #333 has to answer exactly this one.
    assert REVISION_IMMUTABLE == "REVISION_IMMUTABLE"
    assert REVISION_IMMUTABLE in static_components["responses"]["RevisionConflict"]["description"]

    # Unchanged, and checked here because this is where it used to be checked: the
    # generic error body every *other* route still answers with.
    error_schema = static_components["schemas"]["FastAPIErrorResponse"]
    assert error_schema["properties"]["detail"]["anyOf"] == [
        {"type": "string"},
        {"type": "object", "additionalProperties": True},
        {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    ]


def test_the_contract_no_longer_names_a_planning_task_snapshot_schema() -> None:
    """Acceptance criterion of #331, pinned rather than checked by hand once.

    `wf_planning_task_snapshot` is the twin table the revision node replaces, and no
    *schema* of the published contract -- nor of the TypeScript client generated from
    it -- may be named after it any more. Prose still mentioning the table is fine and
    deliberately not matched: ``PATCH /projects/{id}/tasks/{uid}`` still writes it, and
    says so.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    schemas = cast(dict[str, Any], static_document["components"])["schemas"]

    assert [name for name in schemas if "PlanningTaskSnapshot" in name] == []
    generated_client = GENERATED_CLIENT_PATH.read_text(encoding="utf-8")
    assert re.findall(r"\b\w*PlanningTaskSnapshot\w*\s*:", generated_client) == []


def test_generic_error_responses_document_fastapi_error_shape() -> None:
    """Issue #223: these shared/generic response components are used by routes that all
    raise `HTTPException`, which always serializes through `_generic_http_exception_handler`
    into `{"detail": ...}` (see test_error_handler.py) -- never the unrelated `{error,
    message}` shape of `ErrorResponse`. Guards against a future edit silently repointing one
    of these back to `ErrorResponse` (e.g. by copy-pasting the pattern from an inline response
    that hasn't been migrated yet)."""
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_responses = cast(dict[str, Any], static_document["components"])["responses"]

    for response_name in (
        "BadRequest",
        "Conflict",
        "Unauthorized",
        "Forbidden",
        "BatchNotFound",
        "EstimateNotFound",
        "PlanningNotFound",
        "ProjectNotFound",
        "ProjectPlanningTaskNotFound",
        "ResourceNotFound",
        "TaskNotFound",
        "UserNotFound",
    ):
        schema_ref = static_responses[response_name]["content"]["application/json"]["schema"][
            "$ref"
        ]
        assert schema_ref == "#/components/schemas/FastAPIErrorResponse", response_name


def test_inline_error_responses_document_fastapi_error_shape_and_error_response_is_gone() -> None:
    """Issue #232: the 5 remaining inline (not shared-component) responses that still
    referenced `ErrorResponse` after #223 -- upload-time 413/415, run-time 409 on the imports
    batch endpoints, and login-time 423/429 on /auth/token -- all originate from routes that
    raise `HTTPException` (`imports.py`, `auth.py`), except 415 which is documented but never
    actually raised by any route today (a pre-existing orphan, tracked separately). Every one
    of these serializes the same `{"detail": ...}` shape as every other error response in this
    API. With these fixed, `ErrorResponse` has no remaining usage anywhere in the spec (nor in
    the `responses={"model": ...}` metadata of any FastAPI route decorator, which independently
    feeds `app.openapi()`/`/docs` and is not derived from the static spec at all) and was
    removed entirely -- schema file, `components.schemas` registration, and the orphaned
    `ErrorResponse` Pydantic model in `schemas/imports.py` -- rather than left as a dead,
    misleading document fixture."""
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_paths = cast(dict[str, Any], static_document["paths"])
    static_components = cast(dict[str, Any], static_document["components"])

    for path, method, status_code in (
        ("/imports/v1/batches/{batchId}/xml", "post", "413"),
        ("/imports/v1/batches/{batchId}/xml", "post", "415"),
        ("/imports/v1/batches/{batchId}/run", "post", "409"),
        ("/auth/token", "post", "423"),
        ("/auth/token", "post", "429"),
        # Added by E13-01: the fail-closed 503 raised when the login rate limiter's
        # Redis backend is unreachable. Same inline shape, anchored here by the same
        # convention.
        ("/auth/token", "post", "503"),
        # Added by E13-02: import sources live in S3-compatible object storage (Garage),
        # so every endpoint that stores or reads one can fail on that backend. Same
        # inline shape again -- these all raise HTTPException from imports.py.
        ("/imports/v1/batches/{batchId}/xml", "post", "503"),
        ("/imports/v1/batches/{batchId}/run", "post", "503"),
        ("/imports/v1/batches/{batchId}/diff", "get", "503"),
    ):
        schema_ref = static_paths[path][method]["responses"][status_code]["content"][
            "application/json"
        ]["schema"]["$ref"]
        assert schema_ref == "#/components/schemas/FastAPIErrorResponse", (
            path,
            method,
            status_code,
        )

    assert "ErrorResponse" not in static_components["schemas"]

    # The static bundle isn't the only place this could regress: FastAPI route decorators
    # declare their own `responses={status: {"model": ...}}` metadata independently, which
    # feeds the *runtime* `app.openapi()` (and therefore `/docs`, `/openapi.json`) without ever
    # touching the committed YAML. `imports.py`'s decorators referenced a distinct `ErrorResponse`
    # Pydantic model (schemas/imports.py) that this same issue's fix also removed -- check the
    # live schema, not just the static one, so this class of drift can't come back silently.
    runtime_schemas = cast(dict[str, Any], app.openapi()["components"])["schemas"]
    assert "ErrorResponse" not in runtime_schemas


def test_readiness_contract_documents_the_dependency_checks_and_its_503() -> None:
    """Issue #300 (E13-03): `/health/ready` really probes Postgres, Redis and the object
    store, and answers 503 when any of them is unreachable.

    Deliberately *not* added to the inline-error list above: unlike every other error
    response in this API, this 503 is not an `HTTPException` and therefore not a
    `FastAPIErrorResponse` -- the route sets the status code on the response and returns
    the exact same `ReadinessStatus` body as the 200, because a caller that gets a 503
    needs the per-dependency breakdown even more than one that gets a 200. Anchoring the
    two `$ref`s equal is what keeps a future edit from "harmonizing" this into the generic
    `{"detail": ...}` shape and silently dropping the diagnosis Docker's healthcheck (and
    E13-04's gauge) depend on.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_operation = cast(dict[str, Any], static_document["paths"]["/health/ready"])["get"]
    runtime_document = app.openapi()
    runtime_operation = cast(dict[str, Any], runtime_document["paths"]["/health/ready"])["get"]

    for operation in (static_operation, runtime_operation):
        for status_code in ("200", "503"):
            assert (
                operation["responses"][status_code]["content"]["application/json"]["schema"]["$ref"]
                == "#/components/schemas/ReadinessStatus"
            ), status_code

    static_schemas = cast(dict[str, Any], static_document["components"])["schemas"]
    runtime_schemas = cast(dict[str, Any], runtime_document["components"])["schemas"]
    for schema_name in ("ReadinessStatus", "ReadinessChecks"):
        assert set(static_schemas[schema_name]["properties"]) == set(
            runtime_schemas[schema_name]["properties"]
        )
        assert set(static_schemas[schema_name]["required"]) == set(
            runtime_schemas[schema_name]["required"]
        )
    # The three dependency keys are the published contract (and E13-04's `dependency`
    # label values), so pin the names and their two possible states.
    assert set(static_schemas["ReadinessChecks"]["properties"]) == {"database", "redis", "storage"}
    for dependency in ("database", "redis", "storage"):
        assert static_schemas["ReadinessChecks"]["properties"][dependency]["enum"] == [
            "ok",
            "unavailable",
        ]

    # Liveness stays a dependency-free `{"status": "ok"}`: E13-03 keeps it that way on
    # purpose (a failing liveness probe restarts the container).
    assert set(cast(dict[str, Any], static_document["paths"]["/health"])["get"]["responses"]) == {
        "200"
    }


def test_generated_client_contains_every_static_operation() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_operation_ids = {
        operation["operationId"]
        for path_operations in cast(dict[str, dict[str, Any]], static_document["paths"]).values()
        for method, operation in path_operations.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    generated_client = GENERATED_CLIENT_PATH.read_text(encoding="utf-8")
    generated_operation_ids = set(re.findall(r'operations\["([^\"]+)"\]', generated_client))
    assert static_operation_ids <= generated_operation_ids


def test_import_and_estimate_contracts_match_runtime_nullability_and_aliases() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_schemas = cast(dict[str, Any], static_document["components"])["schemas"]
    runtime_schemas = cast(dict[str, Any], app.openapi()["components"])["schemas"]

    for schema_name in ("ImportRunRequest", "EstimateTaskRowRead"):
        assert set(static_schemas[schema_name]["properties"]) == set(
            runtime_schemas[schema_name]["properties"]
        )
        assert set(static_schemas[schema_name].get("required", [])) == set(
            runtime_schemas[schema_name].get("required", [])
        )
    assert "dryRun" in runtime_schemas["ImportRunRequest"]["properties"]
    assert "task_id" not in runtime_schemas["EstimateTaskRowRead"].get("required", [])
    assert runtime_schemas["EstimateTaskRowRead"]["properties"]["task_id"]["anyOf"] == [
        {"type": "integer"},
        {"type": "null"},
    ]

    # #291 review finding Moyenne #2: EstimateCostLineRead/EstimateRoleAssignmentRead
    # (E12-09) declare every nullable field as `X | None` with no `= None` default
    # (see their own class docstrings in schemas/projects.py) -- unlike
    # EstimateTaskRowRead above, FastAPI/Pydantic therefore marks *every* field
    # required at runtime for these two (the JSON key is always present in the
    # response, only its value may be null). The static spec keeps its own,
    # narrower, pre-existing convention here instead, listing only the fields
    # actually chosen as non-nullable -- so `required` is expected to diverge
    # between static and runtime for this schema shape, while `properties` still
    # has to match exactly, same as every other schema checked in this test.
    for schema_name in ("EstimateCostLineRead", "EstimateRoleAssignmentRead"):
        assert set(static_schemas[schema_name]["properties"]) == set(
            runtime_schemas[schema_name]["properties"]
        )
        assert set(runtime_schemas[schema_name].get("required", [])) == set(
            runtime_schemas[schema_name]["properties"]
        )
    assert set(static_schemas["EstimateCostLineRead"].get("required", [])) == {
        "id",
        "estimate_id",
        "cost_type_id",
        "cost_category_id",
        "cost_type_code",
        "accounting_code",
        "label",
        "quantity",
        "unit_cost",
        "purchase_cost",
        "uid",
        "position",
        "row_number",
    }
    assert set(static_schemas["EstimateRoleAssignmentRead"].get("required", [])) == {
        "id",
        "estimate_id",
        "task_id",
        "role_id",
        "role_code",
        "role_name",
        "cost_category_id",
        "accounting_code",
        "quantity",
        "hours",
        "created_at",
        "updated_at",
        "uid",
        "position",
        "row_number",
    }
    # `parent_uid` (E12-09/#291) is nullable and, per the narrower static
    # convention pinned above, deliberately excluded from the static spec's
    # `required` (it is still present in runtime `required`, like every other
    # field of these two schemas -- checked in the loop above). Spot-check its
    # anyOf/null shape the same way the EstimateTaskRowRead.task_id check does.
    for schema_name in ("EstimateCostLineRead", "EstimateRoleAssignmentRead"):
        assert "parent_uid" not in static_schemas[schema_name].get("required", [])
        assert runtime_schemas[schema_name]["properties"]["parent_uid"]["anyOf"] == [
            {"type": "integer"},
            {"type": "null"},
        ]


def _auth_headers(client: TestClient) -> dict[str, str]:
    email = f"openapi.contract.{uuid4().hex}@example.com"
    password = "SuperSecret123!"
    assert (
        client.post("/auth/register", json={"email": email, "password": password}).status_code
        == 201
    )
    token = client.post("/auth/token", data={"username": email, "password": password})
    assert token.status_code == 200
    return {"Authorization": f"Bearer {token.json()['access_token']}"}


def _create_project(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post("/projects", json={"name": "OpenAPI contract fixture"}, headers=headers)
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def test_planning_task_delete_conflict_schema_keeps_its_shape_for_the_devis() -> None:
    """The dedicated 409 body the devis reconciliation still answers with.

    E14-05 (#331) removed ``POST .../plannings/{id}/tasks/delete`` and its response
    component, but **not** this schema: ``EstimateReconciliationConfirmConflict``
    still references it (see the test further down), because
    ``services.delete_planning_tasks`` still serves the reconciliation import. What
    is pinned here is the shape a generated client types ``error.detail`` off --
    the finding that produced this schema in the first place.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_components = cast(dict[str, Any], static_document["components"])

    conflict_schema = static_components["schemas"]["PlanningTaskDeleteConflict"]
    detail_schema = conflict_schema["properties"]["detail"]
    assert detail_schema["type"] == "object"
    assert detail_schema["required"] == ["code"]
    assert detail_schema["properties"]["code"]["enum"] == [
        "CASCADE_CONFIRMATION_REQUIRED",
        "TASK_REFERENCED",
    ]
    assert detail_schema["properties"]["descendant_uids"]["items"]["type"] == "integer"
    assert detail_schema["properties"]["task_uids"]["items"]["type"] == "integer"

    runtime_schemas = cast(dict[str, Any], app.openapi()["components"])["schemas"]
    runtime_detail_ref = runtime_schemas["PlanningTaskDeleteConflict"]["properties"]["detail"]
    runtime_detail_schema = runtime_schemas[runtime_detail_ref["$ref"].rsplit("/", 1)[-1]]
    assert set(runtime_detail_schema["properties"]) == set(detail_schema["properties"])
    assert (
        runtime_detail_schema["properties"]["code"]["enum"]
        == detail_schema["properties"]["code"]["enum"]
    )


_RECONCILIATION_XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _generate_structure(client: TestClient, headers: dict[str, str], project_id: int) -> None:
    """Minimal structure -- just enough to get a draft displayed planning (E6-09)."""
    response = client.post(
        f"/projects/{project_id}/planning-structure",
        json={
            "posts": [
                {
                    "key": "design",
                    "name": "Design",
                    "lots": [
                        {
                            "key": "specification",
                            "name": "Specification",
                            "deliverables": [{"key": "requirements", "name": "Requirements"}],
                        }
                    ],
                }
            ]
        },
        headers=headers,
    )
    assert response.status_code == 201


def _create_estimate(client: TestClient, headers: dict[str, str], project_id: int) -> int:
    response = client.post(
        f"/projects/{project_id}/estimates",
        json={"kind": "initial", "currency_code": "EUR"},
        headers=headers,
    )
    assert response.status_code == 201
    return cast(int, response.json()["id"])


def _create_standalone_task(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int, name: str
) -> None:
    """A root task with no children and no MO/Non-MO reference (E6-06/#67's own endpoint) --
    a deletion candidate ``_precheck_task_deletions`` never blocks on, so a reconciliation
    import removing it always reaches ``_apply_task_deletes``/``delete_planning_tasks``.
    """
    response = client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/tasks",
        json={"name": name, "is_milestone": False},
        headers=headers,
    )
    assert response.status_code == 201


def _export_reconciliation_workbook(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int
) -> bytes:
    response = client.get(
        f"/projects/{project_id}/estimates/{estimate_id}/export-reconciliation.xlsx",
        headers=headers,
    )
    assert response.status_code == 200
    return response.content


def _delete_task_row_by_name(content: bytes, task_name: str) -> bytes:
    """Remove one row from the exported ``Tâches`` sheet, staging it for deletion."""
    workbook = load_workbook(BytesIO(content))
    sheet = workbook["Tâches"]
    header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
    name_index = header_row.index("task_name")
    for row in sheet.iter_rows(min_row=2):
        if row[name_index].value == task_name:
            row_number = row[name_index].row
            assert row_number is not None
            sheet.delete_rows(row_number, 1)
            break
    else:
        raise AssertionError(f"No task row named {task_name!r}")
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _confirm_reconciliation_import(
    client: TestClient, headers: dict[str, str], project_id: int, estimate_id: int, content: bytes
) -> Any:
    return client.post(
        f"/projects/{project_id}/estimates/{estimate_id}/import-reconciliation/confirm",
        files={"file": ("reconciliation.xlsx", content, _RECONCILIATION_XLSX_CONTENT_TYPE)},
        headers=headers,
    )


def _seed_reconciliation_task_deletion_fixture(
    client: TestClient, headers: dict[str, str]
) -> tuple[int, int, bytes]:
    """Project + draft devis with one standalone task, exported and staged for deletion --
    a file ``_run_reconciliation``'s own read-only precheck always finds zero blocking issues
    for (see ``_create_standalone_task``), so ``confirm``'s locked, real ``apply=True`` pass
    is always reached and calls ``delete_planning_tasks`` for real.
    """
    project_id = _create_project(client, headers)
    _generate_structure(client, headers, project_id)
    estimate_id = _create_estimate(client, headers, project_id)
    _create_standalone_task(client, headers, project_id, estimate_id, "Doomed task")
    content = _export_reconciliation_workbook(client, headers, project_id, estimate_id)
    edited = _delete_task_row_by_name(content, "Doomed task")
    return project_id, estimate_id, edited


def test_confirm_estimate_reconciliation_import_conflict_response_declares_dedicated_schema() -> (
    None
):
    """Finding Moyenne #2 (E6-09 round 2 review): confirm's 409 is not always a bare
    ``ReconciliationPlanRead`` -- a write racing between the unlocked precheck and the
    locked apply can still let a ``PlanningTreeCascadeConfirmationRequiredError``/
    ``PlanningTreeTaskReferencedError`` escape (see ``confirm_estimate_reconciliation_import``'s
    own docstring), surfaced exactly like the direct ``.../tasks/delete`` route already
    documents it: a ``PlanningTaskDeleteConflict`` body, not the usual devis diagnostic.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_components = cast(dict[str, Any], static_document["components"])
    confirm_operation = static_document["paths"][
        "/projects/{projectId}/estimates/{estimateId}/import-reconciliation/confirm"
    ]["post"]
    conflict_response = static_components["responses"]["EstimateReconciliationConfirmConflict"]
    conflict_schema_refs = {
        member["$ref"]
        for member in conflict_response["content"]["application/json"]["schema"]["oneOf"]
    }
    assert conflict_schema_refs == {
        "#/components/schemas/ReconciliationPlanRead",
        "#/components/schemas/PlanningTaskDeleteConflict",
    }
    assert confirm_operation["responses"]["409"]["$ref"] == (
        "#/components/responses/EstimateReconciliationConfirmConflict"
    )

    runtime_operation = cast(dict[str, Any], app.openapi()["paths"])[
        "/projects/{project_id}/estimates/{estimate_id}/import-reconciliation/confirm"
    ]["post"]
    runtime_conflict_schema = runtime_operation["responses"]["409"]["content"]["application/json"][
        "schema"
    ]
    runtime_conflict_refs = {member["$ref"] for member in runtime_conflict_schema["anyOf"]}
    assert runtime_conflict_refs == conflict_schema_refs


def test_confirm_reconciliation_import_cascade_confirmation_conflict_matches_declared_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    detail_properties = static_document["components"]["schemas"]["PlanningTaskDeleteConflict"][
        "properties"
    ]["detail"]["properties"]

    def _raise_cascade_confirmation_required(*args: Any, **kwargs: Any) -> None:
        raise PlanningTreeCascadeConfirmationRequiredError([99])

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, estimate_id, edited = _seed_reconciliation_task_deletion_fixture(
            client, headers
        )

        monkeypatch.setattr(
            estimates, "delete_planning_tasks", _raise_cascade_confirmation_required
        )
        response = _confirm_reconciliation_import(client, headers, project_id, estimate_id, edited)

    assert response.status_code == 409
    detail = cast(dict[str, Any], response.json())["detail"]
    assert set(detail) <= set(detail_properties)
    assert detail["code"] == "CASCADE_CONFIRMATION_REQUIRED"
    assert detail["descendant_uids"] == [99]


def test_confirm_reconciliation_import_task_referenced_conflict_matches_declared_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    detail_properties = static_document["components"]["schemas"]["PlanningTaskDeleteConflict"][
        "properties"
    ]["detail"]["properties"]

    def _raise_task_referenced(*args: Any, **kwargs: Any) -> None:
        raise PlanningTreeTaskReferencedError([99])

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id, estimate_id, edited = _seed_reconciliation_task_deletion_fixture(
            client, headers
        )

        monkeypatch.setattr(estimates, "delete_planning_tasks", _raise_task_referenced)
        response = _confirm_reconciliation_import(client, headers, project_id, estimate_id, edited)

    assert response.status_code == 409
    detail = cast(dict[str, Any], response.json())["detail"]
    assert set(detail) <= set(detail_properties)
    assert detail["code"] == "TASK_REFERENCED"
    assert detail["task_uids"] == [99]
