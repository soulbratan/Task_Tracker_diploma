from django.contrib import admin
from django.urls import include, path
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

# Простая схема для документации
schema_view = get_schema_view(
    openapi.Info(
        title="User Registration API",
        default_version="v1",
        description="""
                API для управления компанией.

                ## Приложения:
                - **users** - управление пользователями и аутентификация
                - **organization** - организационная структура, отделы и должности
                - **tasks** - задачи, назначения, комментарии

                ## Аутентификация
                Используется JWT токены. Для получения токена:
                1. Зарегистрируйтесь через /api/users/
                2. Войдите через /api/users/login/
                3. Используйте токен в заголовке Authorization: Bearer <ваш_токен>
                """,
    ),
    public=True,  # Документация доступна всем
    permission_classes=(permissions.AllowAny,),  # Разрешаем доступ без авторизации
)

urlpatterns = [
    # Админка
    path("admin/", admin.site.urls),
    # API
    path("api/users/", include("users.urls")),
    # path("api/organization/", include("organization.urls")),
    # path("api/tasks/", include("tasks.urls")),
    # Документация
    path("swagger/", schema_view.with_ui("swagger", cache_timeout=0), name="swagger-ui"),
    path("redoc/", schema_view.with_ui("redoc", cache_timeout=0), name="redoc"),
]
