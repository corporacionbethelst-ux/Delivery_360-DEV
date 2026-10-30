"""Portable public-route and dependency inventory, without inspecting runtime secrets."""

import hashlib
import inspect
import json
from enum import Enum
from fastapi.routing import APIRoute, APIWebSocketRoute


def callable_name(value):
    if inspect.isfunction(value) or inspect.ismethod(value):
        return value.__module__ + "." + value.__qualname__
    return type(value).__module__ + "." + type(value).__qualname__


def dependency_contract(dependant, definitions):
    result = {
        "call": callable_name(dependant.call),
        "name": dependant.name,
        "use_cache": dependant.use_cache,
        "security_scopes": dependant.security_scopes or [],
    }
    # Only the public role allowlist is inspected, not arbitrary closure state.
    call = dependant.call
    if inspect.isfunction(call) and call.__closure__:
        for name, cell in zip(call.__code__.co_freevars, call.__closure__):
            if name == "roles":
                values = cell.cell_contents
                if isinstance(values, tuple) and all(
                    isinstance(item, Enum) for item in values
                ):
                    result["roles"] = [item.value for item in values]
    result["dependencies"] = [
        dependency_contract(child, definitions) for child in dependant.dependencies
    ]
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    identifier = hashlib.sha256(canonical.encode()).hexdigest()
    definitions[identifier] = result
    return identifier


def api_surface(app):
    routes = []
    definitions = {}
    for route in app.routes:
        row = {
            "path": route.path,
            "name": route.name,
            "route_class": type(route).__name__,
            "methods": sorted(getattr(route, "methods", ()) or ()),
        }
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            row["dependency_contract"] = dependency_contract(
                route.dependant, definitions
            )
        if isinstance(route, APIRoute):
            row.update(
                status_code=route.status_code,
                tags=route.tags,
                include_in_schema=route.include_in_schema,
            )
        routes.append(row)
    schema = json.dumps(
        app.openapi(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "routes": routes,
        "dependencies": definitions,
        "openapi_sha256": hashlib.sha256(schema.encode()).hexdigest(),
    }
