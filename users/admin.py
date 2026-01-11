from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "last_name",
        "first_name",
        "department",
        "position",
        "is_staff",
        "is_active",
        "date_joined",
    )
    list_filter = ("is_staff", "is_active", "date_joined", "department")
    search_fields = ("email", "last_name", "first_name", "phone", "department", "position")
    ordering = ("email",)

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Персональная информация"),
            {"fields": ("last_name", "first_name", "middle_name", "phone", "telegram_id", "photo")},
        ),
        (_("Работа"), {"fields": ("organization", "department", "position")}),
        (_("Права доступа"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Важные даты"), {"fields": ("last_login", "date_joined")}),
    )

    readonly_fields = ("date_joined", "last_login", "department", "position")

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "last_name", "first_name"),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        """
        Поля department и position должны быть только для чтения,
        чтобы избежать рассинхронизации с Position.
        """
        if obj:  # При редактировании существующего пользователя
            return self.readonly_fields + ("department", "position")
        return self.readonly_fields

    def has_change_permission(self, request, obj=None):
        """
        Запрещаем изменение department и position через админку пользователей.
        Эти поля должны обновляться только через назначение на должность.
        """
        return True
