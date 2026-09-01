import re
from collections.abc import Set
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import yaml
from fastapi.testclient import TestClient

from waterfall.db.session import get_session_factory
from waterfall.main import app
from waterfall.models.ms_core import MsTask
from waterfall.models.planning import WfPlanning, WfPlanningTaskSnapshot
from waterfall.models.wf_core import WfChargeLine

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
        "PlanningTaskMove",
        "PlanningLinkRead",
    ):
        assert schema_name in runtime_components
        assert schema_name in static_components
        static_schema = cast(dict[str, Any], static_components[schema_name])
        runtime_schema = cast(dict[str, Any], runtime_components[schema_name])
        assert set(static_schema.get("properties", {})) == set(runtime_schema["properties"])

    static_move = cast(dict[str, Any], static_components["PlanningTaskMove"])
    runtime_move = cast(dict[str, Any], runtime_components["PlanningTaskMove"])
    assert (
        static_move["properties"]["task_uids"]["minItems"]
        == runtime_move["properties"]["task_uids"]["minItems"]
    )
    assert (
        static_move["properties"]["task_uids"]["items"]["minimum"]
        == runtime_move["properties"]["task_uids"]["items"]["minimum"]
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
        or "/planning-tree" in path
        or path.endswith("/tasks")
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
            or "/planning-tree" in path
            or path.endswith("/tasks")
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
        "PlanningTaskMove",
        "PlanningTreeRead",
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


def test_move_planning_tasks_documents_all_not_found_resources() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    move_operation = static_document["paths"][
        "/projects/{projectId}/plannings/{planningId}/tasks/move"
    ]["post"]

    static_components = cast(dict[str, Any], static_document["components"])
    runtime_operation = cast(dict[str, Any], app.openapi()["paths"])[
        "/projects/{project_id}/plannings/{planning_id}/tasks/move"
    ]["post"]

    for status_code, response_name in (
        ("400", "MovePlanningTasksBadRequest"),
        ("404", "MovePlanningTasksNotFound"),
        ("409", "MovePlanningTasksConflict"),
    ):
        assert move_operation["responses"][status_code]["$ref"] == (
            f"#/components/responses/{response_name}"
        )
        static_response = static_components["responses"][response_name]
        assert static_response["content"]["application/json"]["schema"]["$ref"] == (
            "#/components/schemas/FastAPIErrorResponse"
        )
        assert (
            runtime_operation["responses"][status_code]["content"]["application/json"]["schema"][
                "$ref"
            ]
            == "#/components/schemas/FastAPIErrorResponse"
        )

    error_schema = static_components["schemas"]["FastAPIErrorResponse"]
    assert error_schema["properties"]["detail"]["anyOf"] == [
        {"type": "string"},
        {"type": "array", "items": {"type": "object", "additionalProperties": True}},
    ]


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


def _seed_planning_with_parent_and_child(project_id: int) -> int:
    """A minimal draft planning tree: a summary root (uid=1) with one child
    (uid=2) -- just enough to trigger a CASCADE_CONFIRMATION_REQUIRED 409 on
    deleting uid=1, or a TASK_REFERENCED 409 once uid=2 is referenced.
    """
    with get_session_factory()() as session:
        planning = WfPlanning(project_id=project_id, version_number=1, status="draft")
        session.add(planning)
        session.flush()
        session.add_all(
            [
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=1,
                    name="Root",
                    position=1,
                    is_summary=True,
                    is_milestone=False,
                ),
                WfPlanningTaskSnapshot(
                    planning_id=planning.id,
                    uid=2,
                    name="Child",
                    parent_uid=1,
                    position=1,
                    is_summary=False,
                    is_milestone=False,
                ),
            ]
        )
        session.commit()
        return planning.id


def test_delete_planning_tasks_conflict_response_declares_dedicated_schema() -> None:
    """Guards the finding this response used to trigger: a bare ``dict``
    ``HTTPException`` ``detail`` documented as the generic
    ``FastAPIErrorResponse`` (``str | array``), which cannot express
    ``{code, descendant_uids}``/``{code, task_uids}`` and would make a
    TS-generated client type ``error.detail`` incorrectly. Checking the two
    ``$ref``s equal (as ``test_move_planning_tasks_documents_all_not_found_resources``
    does for ``move``) is not enough on its own -- it would pass even if both
    still pointed at the same generic schema -- so this also asserts the
    dedicated schema's actual shape.

    The 409 is documented as a ``oneOf`` of ``PlanningTaskDeleteConflict``
    (the structured cascade/reference conflicts) and ``FastAPIErrorResponse``
    (the plain-string conflicts that ``delete_planning_tasks_route`` also
    raises -- e.g. "Planning is not a draft", or an ``IntegrityError`` on the
    hierarchy) -- see PR #78's Copilot review finding #2: those code paths
    never actually return the structured shape, so documenting it exclusively
    was inaccurate.
    """
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    static_components = cast(dict[str, Any], static_document["components"])
    delete_operation = static_document["paths"][
        "/projects/{projectId}/plannings/{planningId}/tasks/delete"
    ]["post"]
    conflict_response = static_components["responses"]["DeletePlanningTasksConflict"]
    conflict_schema_refs = {
        member["$ref"]
        for member in conflict_response["content"]["application/json"]["schema"]["oneOf"]
    }
    assert conflict_schema_refs == {
        "#/components/schemas/PlanningTaskDeleteConflict",
        "#/components/schemas/FastAPIErrorResponse",
    }
    assert delete_operation["responses"]["409"]["$ref"] == (
        "#/components/responses/DeletePlanningTasksConflict"
    )

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


def test_delete_planning_tasks_cascade_confirmation_conflict_matches_declared_schema() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    detail_properties = static_document["components"]["schemas"]["PlanningTaskDeleteConflict"][
        "properties"
    ]["detail"]["properties"]

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning_with_parent_and_child(project_id)

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [1]},
            headers=headers,
        )

    assert response.status_code == 409
    detail = cast(dict[str, Any], response.json())["detail"]
    assert set(detail) <= set(detail_properties)
    assert detail["code"] == "CASCADE_CONFIRMATION_REQUIRED"
    assert isinstance(detail["descendant_uids"], list)
    assert all(isinstance(uid, int) for uid in detail["descendant_uids"])
    assert detail["descendant_uids"] == [2]


def test_delete_planning_tasks_task_referenced_conflict_matches_declared_schema() -> None:
    raw_document: object = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    static_document = cast(dict[str, Any], raw_document)
    detail_properties = static_document["components"]["schemas"]["PlanningTaskDeleteConflict"][
        "properties"
    ]["detail"]["properties"]

    with TestClient(app) as client:
        headers = _auth_headers(client)
        project_id = _create_project(client, headers)
        planning_id = _seed_planning_with_parent_and_child(project_id)

        with get_session_factory()() as session:
            session.add(MsTask(project_id=project_id, uid=2, name="Legacy bridge"))
            session.flush()
            session.add(WfChargeLine(project_id=project_id, task_uid=2, load_minutes=60))
            session.commit()

        response = client.post(
            f"/projects/{project_id}/plannings/{planning_id}/tasks/delete",
            json={"task_uids": [2]},
            headers=headers,
        )

    assert response.status_code == 409
    detail = cast(dict[str, Any], response.json())["detail"]
    assert set(detail) <= set(detail_properties)
    assert detail["code"] == "TASK_REFERENCED"
    assert isinstance(detail["task_uids"], list)
    assert all(isinstance(uid, int) for uid in detail["task_uids"])
    assert detail["task_uids"] == [2]
