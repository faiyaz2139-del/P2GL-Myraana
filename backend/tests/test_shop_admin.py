"""Invite sign-in, user removal, archived jobs, and build identity. No Mongo client."""
import asyncio
import json
from pathlib import Path

from p2g.account_access import exclude_archived, removal_denial
from p2g.build_metadata import resolve_build_metadata
from p2g.membership import end_user_sessions, save_session, user_for_session
from p2g.tenancy import TenantDatabase, clear_shop, reset_shop, shop_scope
from test_tenancy import MemoryDB


ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-10-22T12:00:00+00:00"
LATER = "2026-10-22T18:00:00+00:00"
STALE_COMMIT = "989b95bc4b635aefd72b815198df3bbfbf5e5655"


def test_removal_refuses_self_and_the_last_admin():
    admin = {"id": "admin-1", "role": "admin"}
    other = {"id": "admin-2", "role": "admin"}
    operator = {"id": "op-1", "role": "operator"}
    assert removal_denial("admin-1", admin, 2) == "You can't remove your own account."
    assert removal_denial("admin-1", other, 1) == "The shop needs at least one administrator."
    assert removal_denial("admin-1", other, 2) is None
    assert removal_denial("admin-1", operator, 1) is None
    assert removal_denial("admin-1", None, 2) == "That person is not in this shop."
    removed = {"id": "op-1", "role": "operator", "active": False}
    assert removal_denial("admin-1", removed, 2) == "That person is not in this shop."


def test_invite_session_signs_the_user_into_their_shop():
    asyncio.run(_invite_session_signs_the_user_into_their_shop())


async def _invite_session_signs_the_user_into_their_shop():
    tokens = clear_shop()
    try:
        database = TenantDatabase(MemoryDB())
        await database.shops.insert_one({"_id": "shop-a", "status": "active", "name": "North"})
        await database.shops.insert_one({"_id": "shop-b", "status": "active", "name": "South"})
        with shop_scope("shop-a"):
            await database.users.insert_one({
                "id": "user-a",
                "name": "Ada",
                "email": "ada@shop.test",
                "role": "operator",
                "shop_id": "shop-a",
            })
            await database.jobs.insert_one({"_id": "job-a", "id": "job-a", "customer": "Ada", "state": "active"})
        with shop_scope("shop-b"):
            await database.jobs.insert_one({"_id": "job-b", "id": "job-b", "customer": "Bea", "state": "active"})
        await save_session(
            database,
            token="invite-session-token",
            user_id="user-a",
            shop_id="shop-a",
            session_id="sess-1",
            expires=LATER,
        )
        user = await user_for_session(database, "invite-session-token", NOW)
        assert user["id"] == "user-a"
        assert user["email"] == "ada@shop.test"
        assert user["role"] == "operator"
        assert user["shop_id"] == "shop-a"
        assert user["shop_status"] == "active"
        assert "password" not in user
        listed = await database.jobs.find(exclude_archived(), {"_id": 0}).to_list(10)
        assert [row["id"] for row in listed] == ["job-a"]
        assert await database.jobs.find_one({"_id": "job-b"}) is None
        await end_user_sessions(database, "user-a")
        assert await user_for_session(database, "invite-session-token", NOW) is None
    finally:
        reset_shop(tokens)


def test_removed_account_session_does_not_resolve():
    asyncio.run(_removed_account_session_does_not_resolve())


async def _removed_account_session_does_not_resolve():
    tokens = clear_shop()
    try:
        database = TenantDatabase(MemoryDB())
        await database.shops.insert_one({"_id": "shop-a", "status": "active"})
        with shop_scope("shop-a"):
            await database.users.insert_one({
                "id": "user-a",
                "role": "operator",
                "shop_id": "shop-a",
                "active": False,
            })
        await save_session(
            database,
            token="removed-user-token",
            user_id="user-a",
            shop_id="shop-a",
            session_id="sess-removed",
            expires=LATER,
        )
        assert await user_for_session(database, "removed-user-token", NOW) is None
    finally:
        reset_shop(tokens)


def test_archived_jobs_stay_off_the_default_list():
    asyncio.run(_archived_jobs_stay_off_the_default_list())


async def _archived_jobs_stay_off_the_default_list():
    tokens = clear_shop()
    try:
        database = TenantDatabase(MemoryDB())
        with shop_scope("shop-a"):
            await database.jobs.insert_one({"_id": "open", "id": "open", "customer": "Open", "state": "active"})
            await database.jobs.insert_one({
                "_id": "old",
                "id": "old",
                "customer": "Old",
                "state": "active",
                "archived": True,
            })
            found = await database.jobs.find(exclude_archived(), {"_id": 0}).to_list(10)
            assert [row["id"] for row in found] == ["open"]
            direct = await database.jobs.find_one({"_id": "old"})
            assert direct["customer"] == "Old"
            assert direct["archived"] is True
    finally:
        reset_shop(tokens)


def test_build_info_uses_the_live_commit_not_a_stale_file():
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        path = Path(folder) / "build_metadata.json"
        path.write_text(json.dumps({
            "commit": STALE_COMMIT,
            "builtAt": "2026-10-11T09:15:33+00:00",
        }), encoding="utf-8")
        live = resolve_build_metadata(
            environ={"GIT_COMMIT": "5e1c048abc", "BUILD_TIMESTAMP": "2026-10-22T12:00:00+00:00"},
            path=path,
            git_commit=lambda: "ignored",
        )
        assert live == {"commit": "5e1c048abc", "builtAt": "2026-10-22T12:00:00+00:00"}
        from_git = resolve_build_metadata(environ={}, path=path, git_commit=lambda: "abcdef123456")
        assert from_git["commit"] == "abcdef123456"
        assert from_git["commit"] != STALE_COMMIT
        missing = resolve_build_metadata(
            environ={},
            path=Path(folder) / "missing.json",
            git_commit=lambda: "",
        )
        assert missing == {"commit": "unavailable", "builtAt": "unavailable"}
        assert missing["commit"] != STALE_COMMIT


def test_litellm_requirement_has_no_hash_fragment():
    for relative in ("backend/requirements.txt", "frontend/requirements.txt"):
        lines = [
            line for line in (ROOT / relative).read_text(encoding="utf-8").splitlines()
            if line.startswith("litellm")
        ]
        assert lines, relative
        assert "#sha256=" not in lines[0]
        assert "litellm-1.80.0-py3-none-any.whl" in lines[0]


def test_accept_and_login_issue_the_same_session():
    text = (ROOT / "backend/server.py").read_text(encoding="utf-8")
    login = text.split("async def auth_login", 1)[1].split("async def auth_logout", 1)[0]
    accept = text.split("async def accept_operator_invite", 1)[1].split('@api.get("/jobs")', 1)[0]
    assert "issue_session(request, user)" in login
    assert "issue_session(request, user)" in accept
    assert "set_cookie(**cookie)" in login
    assert "set_cookie(**cookie)" in accept
