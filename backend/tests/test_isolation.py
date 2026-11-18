"""US-60: every route, user B against user A's ids, must fail and leave A's data untouched."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import ColumnElement, Table, bindparam, select
from sqlalchemy.orm import Session

from app.api.deps import PUBLIC_ROUTES, CurrentUser, Db
from app.db import Base
from app.models import (
    Application,
    EmailThread,
    FollowUpTask,
    Sequence,
    User,
)
from app.repositories import followups as followups_repo
from app.repositories import sequences as sequences_repo
from tests.routes import PARAM, all_routes
from tests.test_applications_api import login, make_app
from tests.test_sessions import Env, env  # noqa: F401

DENIED = {403, 404}


@dataclass
class World:
    user: User
    application: Application
    thread: EmailThread
    sequence: Sequence
    task: FollowUpTask
    company: str
    role: str
    subject: str
    snippet: str

    def strings(self) -> list[str]:
        ids = [self.application.id, self.thread.id, self.sequence.id, self.task.id, self.user.id]
        return [*map(str, ids), self.company, self.role, self.subject, self.snippet]


def build_world(env: Env, tag: str) -> World:  # noqa: F811
    user = env.user()
    company, role = f"Company{tag}", f"Role{tag}"
    subject, snippet = f"Subject{tag}", f"Snippet{tag}"
    application = make_app(
        env, user, company=company, role=role, subject=subject, snippet=snippet, from_user=True
    )
    thread = env.db.get(EmailThread, application.source_thread_id)
    assert thread is not None
    sequence = sequences_repo.get_or_create_default(env.db, user.id)
    due = env.clock.now + timedelta(days=7)
    followups_repo.insert_if_absent(env.db, application.id, sequence.id, 0, due, env.clock.now)
    task = env.db.scalars(
        select(FollowUpTask).where(FollowUpTask.application_id == application.id)
    ).one()
    return World(user, application, thread, sequence, task, company, role, subject, snippet)


# Path template -> {path parameter name: attribute of A's World holding the id to substitute}.
# A parameterized route missing here fails the suite: add every new route.
PARAM_MAP: dict[str, dict[str, str]] = {
    "/applications/{application_id}": {"application_id": "application"},
    "/applications/{application_id}/events": {"application_id": "application"},
    "/follow-ups/{task_id}/skip": {"task_id": "task"},
    "/follow-ups/{task_id}/delay": {"task_id": "task"},
    "/sequences/{sequence_id}": {"sequence_id": "sequence"},
}
# Bodies for state-changing routes (the route must reject on ownership, not on validation).
BODIES: dict[tuple[str, str], dict[str, object]] = {
    ("PATCH", "/applications/{application_id}"): {"status": "rejected", "company": "Hacked"},
    ("POST", "/follow-ups/{task_id}/delay"): {"days": 3},
    ("PATCH", "/sequences/{sequence_id}"): {"name": "Hacked"},
}


def attack_path(template: str, world: World, mapping: dict[str, dict[str, str]]) -> str:
    if template not in mapping:
        raise AssertionError(f"route {template} has parameters but no PARAM_MAP entry")
    params = mapping[template]

    def pick(match: Any) -> str:
        name = match.group(1)
        if name not in params:
            raise AssertionError(f"route {template}: parameter {name} is not mapped")
        return str(getattr(world, params[name]).id)

    return PARAM.sub(pick, template)


# Tables with no per-user rows: nothing to snapshot or leak.
GLOBAL_TABLES = frozenset({"invite_codes", "alembic_version", "rate_limits"})


def user_scope(table: Table) -> ColumnElement[bool] | None:
    """WHERE clause limiting a table to user A's rows, via user_id or one FK hop; else None."""
    if "user_id" in table.c:
        return table.c.user_id == bindparam("uid")
    for fk in table.foreign_keys:
        parent = fk.column.table
        if parent is not table and "user_id" in parent.c:
            return table.c[fk.parent.name].in_(
                select(parent.c[fk.column.name]).where(parent.c.user_id == bindparam("uid"))
            )
    return None


def covered_tables() -> dict[str, Table]:
    return {
        name: table
        for name, table in Base.metadata.tables.items()
        if name != "users" and user_scope(table) is not None
    }


def snapshot(db: Session, world: World) -> dict[str, list[tuple[Any, ...]]]:
    """Every row of every user-owned table for user A, to compare before and after."""
    db.flush()
    db.expire_all()
    result: dict[str, list[tuple[Any, ...]]] = {}
    users = Base.metadata.tables["users"]
    result["users"] = sorted(
        map(tuple, db.execute(select(users).where(users.c.id == world.user.id)))
    )
    for name, table in covered_tables().items():
        scope = user_scope(table)
        assert scope is not None
        stmt = select(table).where(scope)
        rows = db.execute(stmt, {"uid": world.user.id}).all()
        result[name] = sorted((tuple(r) for r in rows), key=repr)
    return result


def test_ac5_every_table_is_snapshotted_or_explicitly_global() -> None:
    uncovered = set(Base.metadata.tables) - {"users"} - set(covered_tables()) - GLOBAL_TABLES
    assert not uncovered, f"snapshot cannot scope {sorted(uncovered)}: add user_id/FK or allowlist"
    assert not GLOBAL_TABLES & set(covered_tables())
    assert {"applications", "status_events", "follow_up_tasks", "classifications"} <= set(
        covered_tables()
    )


def assert_denied(
    client: TestClient,
    db: Session,
    world: World,
    method: str,
    template: str,
    mapping: dict[str, dict[str, str]],
    bodies: dict[tuple[str, str], dict[str, object]],
) -> None:
    path = attack_path(template, world, mapping)
    before = snapshot(db, world)
    kwargs: dict[str, Any] = {}
    if method in {"POST", "PUT", "PATCH"}:
        kwargs["json"] = bodies.get((method, template), {})
    response = client.request(method, path, **kwargs)
    assert response.status_code in DENIED, f"{method} {template} gave {response.status_code}"
    assert snapshot(db, world) == before, f"{method} {template} changed the owner's data"


def assert_list_leaks_nothing(client: TestClient, path: str, world: World) -> None:
    response = client.get(path)
    assert response.status_code == 200, path
    for secret in world.strings():
        assert secret not in response.text, f"{path} leaked {secret}"


@pytest.fixture
def two_users(env: Env) -> tuple[World, World, TestClient]:  # noqa: F811
    a, b = build_world(env, "Alpha"), build_world(env, "Bravo")
    return a, b, login(env, b.user)


PARAM_ROUTES = [(m, p) for m, p in all_routes() if PARAM.search(p)]
# The Gmail OAuth callback is a browser redirect bound to the user's own flow cookie; it returns
# no data, and tests/test_gmail_connect.py covers a flow cookie from another user's session.
REDIRECT_ONLY = {("GET", "/gmail/callback")}
LIST_ROUTES = [
    p
    for m, p in all_routes()
    if m == "GET"
    and not PARAM.search(p)
    and (m, p) not in PUBLIC_ROUTES  # token-authorized
    and (m, p) not in REDIRECT_ONLY
]


def test_ac5_world_has_a_row_of_every_owned_kind(
    two_users: tuple[World, World, TestClient],
) -> None:
    a, _, _ = two_users
    assert a.application.id and a.sequence.id and a.task.id and a.thread.id


@pytest.mark.parametrize(("method", "template"), PARAM_ROUTES)
def test_ac5_user_b_cannot_touch_user_a_through_route(
    env: Env,  # noqa: F811
    two_users: tuple[World, World, TestClient],
    method: str,
    template: str,
) -> None:
    a, _, client_b = two_users
    assert_denied(client_b, env.db, a, method, template, PARAM_MAP, BODIES)


@pytest.mark.parametrize("path", LIST_ROUTES)
def test_ac5_list_route_for_user_b_contains_nothing_of_user_a(
    two_users: tuple[World, World, TestClient], path: str
) -> None:
    a, _, client_b = two_users
    assert_list_leaks_nothing(client_b, path, a)


def test_ac5_owner_still_reaches_own_data_through_mapped_routes(
    env: Env,  # noqa: F811
    two_users: tuple[World, World, TestClient],
) -> None:
    """Guards against the suite passing only because every request 404s for everyone."""
    a, _, _ = two_users
    owner = login(env, a.user)
    for template in {p for m, p in PARAM_ROUTES if m == "GET"}:
        assert owner.get(attack_path(template, a, PARAM_MAP)).status_code == 200
    assert a.company in owner.get("/applications").text


def test_ac5_every_parameterized_route_is_mapped() -> None:
    assert PARAM_ROUTES, "no parameterized routes found: the walker is broken"
    for _, template in PARAM_ROUTES:
        assert template in PARAM_MAP, f"add {template} to PARAM_MAP"


def test_ac5_unmapped_parameterized_route_fails_the_suite(
    env: Env,  # noqa: F811
    two_users: tuple[World, World, TestClient],
) -> None:
    a, _, client_b = two_users
    router = APIRouter()

    @router.get("/widgets/{widget_id}")
    def widget(widget_id: uuid.UUID, user: CurrentUser) -> dict[str, str]:
        return {}

    assert isinstance(client_b.app, FastAPI)
    client_b.app.include_router(router)
    unmapped = [(m, p) for m, p in all_routes(client_b.app) if p == "/widgets/{widget_id}"]
    assert unmapped
    with pytest.raises(AssertionError, match="no PARAM_MAP entry"):
        assert_denied(client_b, env.db, a, "GET", "/widgets/{widget_id}", PARAM_MAP, BODIES)
    with pytest.raises(AssertionError, match="not mapped"):
        assert_denied(
            client_b, env.db, a, "GET", "/widgets/{widget_id}", {"/widgets/{widget_id}": {}}, BODIES
        )


def leaky_router() -> APIRouter:
    """Deliberately unscoped: looks rows up by id (and lists them) without filtering by user."""
    router = APIRouter()

    @router.get("/leaky/{application_id}")
    def one(application_id: uuid.UUID, user: CurrentUser, db: Db) -> dict[str, str | None]:
        row = db.get(Application, application_id)  # no user_id filter
        return {"company": row.company if row else None}

    @router.patch("/leaky/{application_id}")
    def change(application_id: uuid.UUID, user: CurrentUser, db: Db) -> dict[str, bool]:
        row = db.get(Application, application_id)  # no user_id filter
        if row is not None:
            row.company = "Hacked"
            db.commit()
        return {"ok": row is not None}

    @router.get("/leaky")
    def everything(user: CurrentUser, db: Db) -> list[dict[str, str | None]]:
        return [{"company": r.company} for r in db.scalars(select(Application))]

    return router


def test_ac5_negative_control_suite_detects_unscoped_routes(
    env: Env,  # noqa: F811
    two_users: tuple[World, World, TestClient],
) -> None:
    a, _, client_b = two_users
    assert isinstance(client_b.app, FastAPI)
    client_b.app.include_router(leaky_router())
    mapping = {"/leaky/{application_id}": {"application_id": "application"}}
    bodies: dict[tuple[str, str], dict[str, object]] = {}
    with pytest.raises(AssertionError, match="leaked"):
        assert_list_leaks_nothing(client_b, "/leaky", a)
    with pytest.raises(AssertionError, match="gave 200"):
        assert_denied(client_b, env.db, a, "GET", "/leaky/{application_id}", mapping, bodies)
    with pytest.raises(AssertionError, match="gave 200"):
        assert_denied(client_b, env.db, a, "PATCH", "/leaky/{application_id}", mapping, bodies)
