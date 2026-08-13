from __future__ import annotations

from fastapi.routing import APIRoute
from typing import get_type_hints

from app.api.career_process import router
from app.schemas.job_description_snapshot import JobDescriptionSnapshotFromProductUI


SNAPSHOT_PATH = "/career-process/opportunities/{opportunity_id}/jd-snapshots"


def test_job_description_snapshot_read_and_typed_write_routes_are_registered() -> None:
    routes = [
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == SNAPSHOT_PATH
    ]

    assert any("GET" in route.methods for route in routes)
    assert any("POST" in route.methods for route in routes)


def test_snapshot_write_route_uses_typed_product_ui_command() -> None:
    post_route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute)
        and route.path == SNAPSHOT_PATH
        and "POST" in route.methods
    )
    assert post_route.body_field is not None
    assert (
        get_type_hints(post_route.endpoint)["command"]
        is JobDescriptionSnapshotFromProductUI
    )
