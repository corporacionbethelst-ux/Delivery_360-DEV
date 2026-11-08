"""Portable public-route and dependency inventory, without inspecting runtime secrets."""

import hashlib
import inspect
import json
from enum import Enum
from fastapi.routing import APIRoute, APIWebSocketRoute

try:
    from fastapi.routing import iter_route_contexts
except ImportError:  # Read historical surfaces under the previous framework too.
    iter_route_contexts = None


def callable_name(value):
    if inspect.isfunction(value) or inspect.ismethod(value):
        return value.__module__ + "." + value.__qualname__
    return type(value).__module__ + "." + type(value).__qualname__


def dependency_contract(dependant, definitions):
    result = {
        "call": callable_name(dependant.call),
        "name": dependant.name,
        "use_cache": dependant.use_cache,
        "security_scopes": (
            getattr(dependant, "security_scopes", None)
            or list(
                dict.fromkeys(
                    (getattr(dependant, "parent_oauth_scopes", None) or [])
                    + (getattr(dependant, "own_oauth_scopes", None) or [])
                )
            )
        ),
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
    contexts = iter_route_contexts(app.routes) if iter_route_contexts else app.routes
    for context in contexts:
        route = getattr(context, "original_route", context)
        row = {
            "path": context.path,
            "name": context.name,
            "route_class": type(route).__name__,
            "methods": sorted(getattr(context, "methods", ()) or ()),
        }
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            row["dependency_contract"] = dependency_contract(
                context.dependant, definitions
            )
        if isinstance(route, APIRoute):
            row.update(
                status_code=context.status_code,
                tags=context.tags,
                include_in_schema=context.include_in_schema,
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


def effective_routes(app):
    """Inspect prefixed routes through the framework's public route contexts."""
    return list(iter_route_contexts(app.routes)) if iter_route_contexts else app.routes
