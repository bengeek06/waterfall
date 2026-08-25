import re
from collections.abc import Set
from pathlib import Path
from typing import Any, cast

import yaml

from waterfall.main import app

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
        if method in {"get", "post", "patch", "delete"}
    } == {
        (_normalize_path(path), method)
        for path in runtime_paths
        for method in runtime_paths[path]
        if method in {"get", "post", "patch", "delete"}
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
            if method not in {"get", "post", "patch", "delete"}:
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
