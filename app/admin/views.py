from typing import Any, Dict

from starlette.requests import Request
from starlette_admin import (
    ActionSelection,
    BooleanField,
    DateTimeField,
    IntegerField,
    PasswordField,
    StringField,
    TextAreaField,
    action,
    flash,
)
from starlette_admin.contrib.sqla import ModelView
from starlette_admin.exceptions import ActionFailed, FormValidationError

from app.core.models import AuditLog, RecoveryCode, User
from app.core.security import hash_password
from app.services.audit import log_audit


class UserView(ModelView):
    fields = [
        "id",
        StringField("email", help_text="Login email address."),
        StringField("full_name", required=False),
        PasswordField(
            "password",
            label="Password",
            required=False,
            exclude_from_list=True,
            exclude_from_detail=True,
            help_text="Leave blank when editing to keep the current password.",
        ),
        BooleanField(
            "is_approved",
            label="Approved",
            help_text="Signups must be approved before they can sign in.",
        ),
        BooleanField("is_active"),
        BooleanField("is_superuser", label="Superuser"),
        BooleanField(
            "totp_enabled",
            label="2FA enabled",
            read_only=True,
            help_text="Whether the user has completed TOTP two-factor setup.",
        ),
        IntegerField(
            "token_version",
            help_text="Increment to immediately revoke all tokens issued to this user.",
        ),
        DateTimeField(
            "created_at",
            read_only=True,
            exclude_from_create=True,
            exclude_from_edit=True,
        ),
        DateTimeField(
            "last_login",
            read_only=True,
            exclude_from_create=True,
            exclude_from_edit=True,
        ),
    ]
    searchable_fields = ["email", "full_name"]
    fields_default_sort = [("is_approved", False), ("created_at", True)]
    page_size = 25
    actions = ["approve", "reject", "reset_2fa", "delete"]

    async def before_create(
        self, request: Request, data: Dict[str, Any], obj: Any
    ) -> None:
        password = data.pop("password", None)
        if not password:
            raise FormValidationError({"password": "A password is required."})
        obj.hashed_password = hash_password(password)
        self._normalize_email(data, obj)

    async def before_edit(
        self,
        request: Request,
        data: Dict[str, Any],
        obj: Any,
        pk: Any = None,
        old_data: Any = None,
    ) -> None:
        password = data.pop("password", None)
        if password:
            obj.hashed_password = hash_password(password)
        self._normalize_email(data, obj)

    @staticmethod
    def _normalize_email(data: Dict[str, Any], obj: Any) -> None:
        email = (data.get("email") or "").strip().lower()
        if email:
            data["email"] = email
            obj.email = email

    async def after_create_committed(self, request: Request, obj: Any) -> None:
        log_audit(
            "user_created",
            user=self._actor(request),
            status="success",
            detail=f"target={obj.email}",
            request=request,
        )

    async def after_edit_committed(self, request: Request, obj: Any) -> None:
        log_audit(
            "user_updated",
            user=self._actor(request),
            status="success",
            detail=f"target={obj.email}",
            request=request,
        )

    async def after_delete_committed(self, request: Request, obj: Any) -> None:
        log_audit(
            "user_deleted",
            user=self._actor(request),
            status="success",
            detail=f"target={getattr(obj, 'email', 'unknown')}",
            request=request,
        )

    def _actor(self, request: Request) -> User | None:
        session = request.state.session
        admin_id = request.session.get("admin_user_id")
        if admin_id is None:
            return None
        return session.get(User, admin_id)

    async def delete(self, request: Request, pks: list) -> int | None:
        actor = self._actor(request)
        if actor is not None:
            remaining = [pk for pk in pks if str(pk) != str(actor.id)]
            if not remaining:
                raise ActionFailed("You cannot delete your own account.")
            pks = remaining
        return await super().delete(request, pks)

    @action(
        name="approve",
        text="Approve selected",
        confirmation="Approve the selected user accounts?",
        submit_btn_text="Yes, approve",
        icon_class="fa-solid fa-check",
    )
    async def approve(self, request: Request, selection: ActionSelection) -> None:
        session = request.state.session
        users = await selection.rows()
        actor = self._actor(request)
        for user in users:
            user.is_approved = True
            user.is_active = True
        session.commit()
        for user in users:
            log_audit(
                "user_approved",
                user=actor,
                status="success",
                detail=f"target={user.email}",
                request=request,
            )
        flash(request, f"Approved {len(users)} account(s).", "success")

    @action(
        name="reject",
        text="Reject / disable selected",
        confirmation="Disable the selected accounts?",
        submit_btn_text="Yes, disable",
        icon_class="fa-solid fa-ban",
    )
    async def reject(self, request: Request, selection: ActionSelection) -> None:
        session = request.state.session
        actor = self._actor(request)
        selected = await selection.rows()
        users = [user for user in selected if actor is None or user.id != actor.id]
        for user in users:
            user.is_approved = False
            user.is_active = False
            user.token_version += 1
        session.commit()
        for user in users:
            log_audit(
                "user_rejected",
                user=actor,
                status="success",
                detail=f"target={user.email}",
                request=request,
            )
        skipped = len(selected) - len(users)
        message = f"Disabled {len(users)} account(s)."
        if skipped:
            message += f" Skipped {skipped} (you cannot disable your own account)."
        flash(request, message, "success")

    @action(
        name="reset_2fa",
        text="Reset 2FA",
        confirmation="Reset two-factor authentication for the selected users?",
        submit_btn_text="Yes, reset",
        icon_class="fa-solid fa-key",
    )
    async def reset_2fa(self, request: Request, selection: ActionSelection) -> None:
        session = request.state.session
        users = await selection.rows()
        actor = self._actor(request)
        for user in users:
            user.totp_enabled = False
            user.totp_secret = None
            user.pending_totp_secret = None
            user.token_version += 1
            session.query(RecoveryCode).filter(
                RecoveryCode.user_id == user.id
            ).delete()
        session.commit()
        for user in users:
            log_audit(
                "user_2fa_reset",
                user=actor,
                status="success",
                detail=f"target={user.email}",
                request=request,
            )
        flash(
            request,
            f"Reset 2FA for {len(users)} account(s). They must set it up again.",
            "success",
        )


class AuditLogView(ModelView):
    fields = [
        "id",
        DateTimeField("created_at", read_only=True),
        "user_email",
        "action",
        "filename",
        "status",
        "ip",
        TextAreaField("detail", read_only=True),
    ]
    searchable_fields = ["user_email", "action", "filename", "detail"]
    fields_default_sort = [("created_at", True)]
    page_size = 50

    def can_create(self, request: Request) -> bool:
        return False

    def can_edit(self, request: Request) -> bool:
        return False

    def can_delete(self, request: Request) -> bool:
        return False
