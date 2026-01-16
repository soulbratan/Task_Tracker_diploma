from rest_framework import permissions

from .models import Position


class IsAdminOrSuperUser(permissions.BasePermission):
    """
    Разрешение для администраторов и суперпользователей.
    Проверяет наличие должности администратора или статус суперпользователя.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи всегда имеют доступ
        if request.user.is_superuser:
            return True

        # Проверяем есть ли у пользователя активная должность администратора
        has_admin_position = Position.objects.filter(
            employee=request.user, level=Position.PositionLevel.ADMIN, is_active=True
        ).exists()

        return has_admin_position


class IsPositionAssignedEmployee(permissions.BasePermission):
    """
    Разрешение для сотрудников, назначенных на любую должность.
    Позволяет просматривать организационную структуру.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи и администраторы всегда имеют доступ
        if IsAdminOrSuperUser().has_permission(request, view):
            return True

        # Проверяем, назначен ли пользователь на какую-либо активную должность
        has_position = Position.objects.filter(employee=request.user, is_active=True).exists()

        return has_position


class CanAssignEmployee(permissions.BasePermission):
    """
    Разрешение для назначения сотрудников на должности.
    """

    def has_permission(self, request, view):
        return IsAdminOrSuperUser().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)
