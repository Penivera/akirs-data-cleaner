import os
import shutil
import tempfile
import time
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from main import app
from app.core import repository as repo
from app.core.config import settings
from app.core.database import AsyncSessionLocal, init_db
from app.core.models import Space, SpaceMember, User
from app.core.security import create_access_token, hash_password
from app.core.state import SpaceFileState, get_space_upload_dir
from app.services import spaces as space_svc
from app.services.cleanup import cleanup_expired_cowork_files
from app.tasks.space_tasks import process_space_files_task


@pytest.fixture(autouse=True)
async def setup_test_db():
    from app.core.database import _prepare_sqlite_directory, normalize_database_url
    _prepare_sqlite_directory(normalize_database_url(settings.database_url))
    await init_db()
    yield


async def _create_test_user(email: str, full_name: str = "Test User") -> User:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(User.email == email))
        user = res.scalars().first()
        if not user:
            user = User(
                email=email,
                full_name=full_name,
                hashed_password=hash_password("TestPassword123!"),
                is_active=True,
                is_approved=True,
                is_superuser=False,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user


@pytest.mark.anyio
async def test_cowork_space_creation_and_membership():
    owner = await _create_test_user("owner@example.com", "Owner User")
    member = await _create_test_user("member@example.com", "Member User")

    # Create space
    space = await space_svc.create_space(owner.id, "Audit Space 1")
    assert space.id is not None
    assert space.owner_id == owner.id
    assert space.share_token is not None

    # Owner lists spaces
    spaces = await space_svc.list_spaces_for_user(owner.id)
    assert any(s.id == space.id for s in spaces)

    # Member is not yet in space
    members = await space_svc.list_members(space.id)
    assert not any(m.id == member.id for m in members)

    # Add member
    added = await space_svc.add_member(space.id, member.id)
    assert added is True
    members = await space_svc.list_members(space.id)
    assert any(m.id == member.id for m in members)

    # Member lists spaces
    m_spaces = await space_svc.list_spaces_for_user(member.id)
    assert any(s.id == space.id for s in m_spaces)


@pytest.mark.anyio
async def test_cowork_invite_by_email_and_username():
    owner = await _create_test_user("inviter@example.com", "Inviter")
    user_email = await _create_test_user("byemail@example.com", "Target One")
    user_name = await _create_test_user("byname@example.com", "Target Two")

    space = await space_svc.create_space(owner.id, "Invite Test Space")

    # Resolve by email
    found_email = await space_svc.find_user_by_email_or_username("byemail@example.com")
    assert found_email is not None
    assert found_email.id == user_email.id

    # Resolve by username / full_name
    found_name = await space_svc.find_user_by_email_or_username("target two")
    assert found_name is not None
    assert found_name.id == user_name.id


@pytest.mark.anyio
async def test_cowork_join_via_token():
    owner = await _create_test_user("spaceowner@example.com", "Space Owner")
    new_member = await _create_test_user("newjoiner@example.com", "New Joiner")
    space = await space_svc.create_space(owner.id, "Share Link Space")

    token = create_access_token(new_member.id, new_member.token_version)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.post(f"/api/cowork/join/{space.share_token}", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["space_id"] == space.id

    # Verify membership
    members = await space_svc.list_members(space.id)
    assert any(m.id == new_member.id for m in members)


@pytest.mark.anyio
async def test_cowork_upload_retention_and_expiration():
    owner = await _create_test_user("retention_owner@example.com", "Retention Owner")
    space = await space_svc.create_space(owner.id, "Retention Space")

    # Upload mock file with 2h TTL
    upload_dir = get_space_upload_dir(space.id)
    mock_file_path = os.path.join(upload_dir, "sample.csv")
    with open(mock_file_path, "w") as f:
        f.write("NUBAN,ACCOUNT_NAME,PHONE\n0123456789,John Doe,08012345678\n")

    state = SpaceFileState()
    state.space_id = space.id
    state.uploaded_by = owner.id
    state.user_id = owner.id
    state.original_filename = "sample.csv"
    state.saved_path = mock_file_path
    state.ttl_hours = 2
    # Set expires_at in the past to test cleanup
    state.uploaded_at = time.time() - 7200
    state.expires_at = time.time() - 3600
    state.status = "Ready"

    await repo.put(repo.KIND_SPACE_FILE, state)

    # Ensure file and state exist
    files = await repo.list_space_files(space.id)
    assert any(f.id == state.id for f in files)
    assert os.path.exists(mock_file_path)

    # Run TTL cleanup
    deleted = await cleanup_expired_cowork_files()
    assert deleted >= 1
    assert not os.path.exists(mock_file_path)

    # Ensure state is removed from database
    files_after = await repo.list_space_files(space.id)
    assert not any(f.id == state.id for f in files_after)


@pytest.mark.anyio
async def test_cowork_live_view_and_download_permissions():
    owner = await _create_test_user("perm_owner@example.com", "Perm Owner")
    member = await _create_test_user("perm_member@example.com", "Perm Member")
    outsider = await _create_test_user("outsider@example.com", "Outsider")
    space = await space_svc.create_space(owner.id, "Permissions Space")
    await space_svc.add_member(space.id, member.id)

    # Create dummy uploaded file
    upload_dir = get_space_upload_dir(space.id)
    file_path = os.path.join(upload_dir, "test_perm.csv")
    with open(file_path, "w") as f:
        f.write("NUBAN,ACCOUNT_NAME,PHONE\n0123456789,Alice Doe,08011111111\n9876543210,Bob Smith,08022222222\n")

    state = SpaceFileState()
    state.space_id = space.id
    state.uploaded_by = owner.id
    state.user_id = owner.id
    state.original_filename = "test_perm.csv"
    state.saved_path = file_path
    state.status = "Ready"
    state.ttl_hours = 24
    state.expires_at = time.time() + 86400
    await repo.put(repo.KIND_SPACE_FILE, state)

    owner_token = create_access_token(owner.id, owner.token_version)
    member_token = create_access_token(member.id, member.token_version)
    outsider_token = create_access_token(outsider.id, outsider.token_version)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        # 1. Live view by member: allowed
        res = await ac.get(
            f"/api/cowork/spaces/{space.id}/view/{state.id}",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert res.status_code == 200
        assert "Alice Doe" in res.text
        assert "Download Restricted" in res.text

        # 2. Live view by outsider: forbidden (404/Not available)
        res_out = await ac.get(
            f"/api/cowork/spaces/{space.id}/view/{state.id}",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert res_out.status_code == 404

        # 3. Download attempt before processing: not available
        res_dl = await ac.get(
            f"/api/cowork/spaces/{space.id}/download/{state.id}",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert res_dl.status_code == 403 or res_dl.status_code == 404

        # Set file as processed by member
        cleaned_file = os.path.join(tempfile.gettempdir(), "test_perm_cleaned.csv")
        with open(cleaned_file, "w") as f:
            f.write("NUBAN,ACCOUNT_NAME\n0123456789,Alice Doe\n")
        state.cleaned_path = cleaned_file
        state.result_filename = "test_perm_cleaned.csv"
        state.processed_by = member.id
        state.status = "Processed (2 rows)"
        await repo.put(repo.KIND_SPACE_FILE, state)

        # 4. Member who processed it CAN download the cleaned result
        res_member_dl = await ac.get(
            f"/api/cowork/spaces/{space.id}/download/{state.id}",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert res_member_dl.status_code == 200
        assert "0123456789,Alice Doe" in res_member_dl.text

        # 5. Owner CAN download the cleaned result
        res_owner_dl = await ac.get(
            f"/api/cowork/spaces/{space.id}/download/{state.id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert res_owner_dl.status_code == 200

        # 6. Outsider CANNOT download
        res_out_dl = await ac.get(
            f"/api/cowork/spaces/{space.id}/download/{state.id}",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert res_out_dl.status_code in (403, 404)

        if os.path.exists(cleaned_file):
            os.remove(cleaned_file)
        if os.path.exists(file_path):
            os.remove(file_path)


@pytest.mark.anyio
async def test_cowork_bulk_processing_task():
    owner = await _create_test_user("bulk_owner@example.com", "Bulk Owner")
    space = await space_svc.create_space(owner.id, "Bulk Process Space")

    upload_dir = get_space_upload_dir(space.id)
    file_path = os.path.join(upload_dir, "bulk_test.csv")
    with open(file_path, "w") as f:
        f.write("NUBAN,ACCOUNT_NAME,PHONE\n0123456789,Bulk User,08099999999\n")

    state = SpaceFileState()
    state.space_id = space.id
    state.uploaded_by = owner.id
    state.user_id = owner.id
    state.original_filename = "bulk_test.csv"
    state.saved_path = file_path
    state.status = "Ready"
    state.mapped_fields = {
        "NUBAN": "NUBAN",
        "ACCOUNT_NAME": "ACCOUNT_NAME",
        "PHONE": "PHONE",
        "TAXPAYER_ID": "",
        "BVN": "",
        "ADDRESS": "",
        "DATE": "",
    }
    state.headers = ["NUBAN", "ACCOUNT_NAME", "PHONE"]
    state.selected_sheets = [""]
    state.header_row_idx = 0
    state.ttl_hours = 24
    state.expires_at = time.time() + 86400
    await repo.put(repo.KIND_SPACE_FILE, state)

    # Run Celery task directly
    task_id = "test_cowork_bulk_123"
    result = process_space_files_task(
        task_id=task_id,
        space_id=space.id,
        file_ids=[state.id],
        runner_user_id=owner.id,
        owner_user_id=owner.id,
        notify_email=False,
    )
    assert result["done"] == 1
    assert result["failed"] == 0

    # Verify state updated
    updated_state = await repo.get(repo.KIND_SPACE_FILE, state.id)
    assert updated_state is not None
    assert "Processed" in updated_state.status
    assert updated_state.cleaned_path is not None
    assert os.path.exists(updated_state.cleaned_path)

    # Clean up
    if os.path.exists(file_path):
        os.remove(file_path)
    if updated_state.cleaned_path and os.path.exists(updated_state.cleaned_path):
        os.remove(updated_state.cleaned_path)
