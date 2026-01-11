from rest_framework import permissions


class IsSelfOrAdmin(permissions.BasePermission):
    """
    Разрешение, позволяющее пользователям работать только со своим профилем
    """

    def has_object_permission(self, request, view, obj):
        # Разрешаем администраторам все действия
        if request.user.is_staff:
            return True

        # Разрешаем пользователям работать только со своим профилем
        return obj == request.user
