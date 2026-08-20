import re
from collections.abc import Set
from pathlib import Path
from typing import Any, cast

import yaml

from waterfall.main import app

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "openapi" / "waterfall_v1.yaml"
PATH_PARAMETER = re.compile(r"\{[^}]+\}")
DOCUMENTATION_PATHS = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}


def _normalize_path(path: str) -> str:
    return PATH_PARAMETER.sub("{}", path)


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
