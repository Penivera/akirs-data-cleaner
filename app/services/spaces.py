"""Persistence helpers for coworking spaces and their members."""
import secrets
from typing import List, Optional

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.models import Space, SpaceMember, User


async def create_space(owner_id: int, name: str) -> Space:
    space = Space(
        id=secrets.token_hex(12),
        owner_id=owner_id,
        name=(name or "Coworking Space").strip()[:255],
        share_token=secrets.token_urlsafe(24),
    )
    async with AsyncSessionLocal() as db:
        db.add(space)
        await db.commit()
    return space


async def get_space(space_id: str) -> Optional[Space]:
    async with AsyncSessionLocal() as db:
        return await db.get(Space, space_id)


async def get_space_by_token(token: str) -> Optional[Space]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Space).where(Space.share_token == token)
        )
        return result.scalars().first()


async def list_spaces_for_user(user_id: int) -> List[Space]:
    """Spaces the user owns or is a member of, newest first."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Space)
            .outerjoin(SpaceMember, SpaceMember.space_id == Space.id)
            .where((Space.owner_id == user_id) | (SpaceMember.user_id == user_id))
            .order_by(Space.created_at.desc())
        )
        return list(result.scalars().all())


async def add_member(space_id: str, user_id: int) -> bool:
    """Add an existing user to a space. Returns False if already a member/owner."""
    async with AsyncSessionLocal() as db:
        space = await db.get(Space, space_id)
        if space is None or space.owner_id == user_id:
            return False
        result = await db.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        if result.scalars().first() is not None:
            return False
        db.add(SpaceMember(space_id=space_id, user_id=user_id))
        await db.commit()
    return True


async def list_members(space_id: str) -> List[User]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User)
            .join(SpaceMember, SpaceMember.user_id == User.id)
            .where(SpaceMember.space_id == space_id)
            .order_by(User.email)
        )
        return list(result.scalars().all())


async def remove_member(space_id: str, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SpaceMember).where(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user_id,
            )
        )
        member = result.scalars().first()
        if member is not None:
            await db.delete(member)
            await db.commit()


async def delete_space(space_id: str) -> None:
    async with AsyncSessionLocal() as db:
        space = await db.get(Space, space_id)
        if space is not None:
            await db.delete(space)
            await db.commit()


async def find_user_by_email_or_username(identifier: str) -> Optional[User]:
    """Resolve an invite target from an email address or a username."""
    value = (identifier or "").strip().lower()
    if not value:
        return None
    async with AsyncSessionLocal() as db:
        if "@" in value:
            result = await db.execute(
                select(User).where(func.lower(User.email) == value)
            )
            return result.scalars().first()
        result = await db.execute(
            select(User).where(
                func.lower(User.full_name) == value,
                User.is_approved.is_(True),
            )
        )
        return result.scalars().first()
