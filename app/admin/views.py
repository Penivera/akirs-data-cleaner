from typing import Any, Dict

from starlette.requests import Request
from starlette_admin import (
    BooleanField,
    DateTimeField,
    IntegerField,
    PasswordField,
    StringField,
    TextAreaField,
)
from starlette_admin.contrib.sqla import ModelView
from starlette_admin.exceptions import FormValidationError

from app.core.models import AuditLog, User
from app.core.security import hash_password


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
        BooleanField("is_active"),
        BooleanField("is_superuser", label="Superuser"),
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
    fields_default_sort = [("created_at", True)]
    page_size = 25

    async def before_create(
        self, request: Request, data: Dict[str, Any], obj: Any
    ) -> None:
        password = data.pop("password", None)
        if not password:
            raise FormValidationError({"password": "A password is required."})
        obj.hashed_password = hash_password(password)

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
    can_create = False
    can_edit = False
    can_delete = False
