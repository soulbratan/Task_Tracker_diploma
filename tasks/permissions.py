from django.db import models
from rest_framework import permissions

from organization.models import Position

from .models import Task


class IsManagerOrAdmin(permissions.BasePermission):
    """
    Разрешение для руководителей и администраторов
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи всегда имеют доступ
        if request.user.is_superuser:
            return True

        # Проверяем наличие должности руководителя или администратора
        has_manager_position = Position.objects.filter(
            employee=request.user, level__in=["manager", "admin"], is_active=True
        ).exists()

        return has_manager_position


class IsTaskAssignee(permissions.BasePermission):
    """
    Разрешение для исполнителя задачи
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Проверяем, является ли пользователь исполнителем задачи
        return obj.assignee and obj.assignee.employee == request.user


class IsTaskOwner(permissions.BasePermission):
    """
    Разрешение для владельца задачи
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Проверяем, является ли пользователь владельцем задачи
        return obj.owner and obj.owner.employee == request.user


class CanCreateSubtask(permissions.BasePermission):
    """
    Разрешение на создание подзадач
    Проверяет глубину вложенности (максимум 3 уровня)
    """

    def has_permission(self, request, view):
        if request.method != "POST":
            return True

        # Проверяем parent_id из запроса
        parent_id = request.data.get("parent")
        if not parent_id:
            return True

        # Получаем задачу из БД
        try:
            parent_task = Task.objects.get(id=parent_id)
        except Task.DoesNotExist:
            return True

        # Проверяем глубину вложенности (максимум 3 уровня)
        if parent_task.get_depth() >= 2:
            return False

        return True


class CanReassignTask(permissions.BasePermission):
    """
    Разрешение на переназначение задачи
    Только руководители и администраторы
    """

    def has_permission(self, request, view):
        return IsManagerOrAdmin().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class CanChangeTaskStatus(permissions.BasePermission):
    """
    Разрешение на изменение статуса задачи
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи и руководители могут менять любые статусы
        if IsManagerOrAdmin().has_permission(request, view):
            return True

        # Исполнитель может менять статус своей задачи
        if obj.assignee and obj.assignee.employee == request.user:
            return True

        # Владелец может менять статус своей задачи
        if obj.owner and obj.owner.employee == request.user:
            return True

        return False


class CanViewTaskDetails(permissions.BasePermission):
    """
    Разрешение на просмотр деталей задачи
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи видят все
        if request.user.is_superuser:
            return True

        # Руководители отдела видят задачи своего отдела
        if IsManagerOrAdmin().has_permission(request, view):
            user_positions = Position.objects.filter(
                employee=request.user, level__in=["manager", "admin"], is_active=True
            )
            user_departments = user_positions.values_list("department", flat=True)

            if obj.owner and obj.owner.department_id in user_departments:
                return True

        # Исполнитель видит свою задачу
        if obj.assignee and obj.assignee.employee == request.user:
            return True

        # Владелец видит свою задачу
        if obj.owner and obj.owner.employee == request.user:
            return True

        # Создатель видит свою задачу
        if obj.created_by == request.user:
            return True

        # Авторы комментариев к задаче видят задачу
        if obj.comments.filter(author=request.user).exists():
            return True

        return False


class CanViewTaskList(permissions.BasePermission):
    """
    Разрешение на просмотр списка задач
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Все авторизованные пользователи могут видеть списки задач
        return True


class CanDeleteTask(permissions.BasePermission):
    """
    Разрешение на удаление задачи
    Только руководители, администраторы и создатель (если задача не назначена)
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Суперпользователи и руководители могут удалять
        if IsManagerOrAdmin().has_permission(request, view):
            return True

        # Создатель может удалить задачу, если она не назначена и не в работе
        if obj.created_by == request.user:
            return not obj.assignee and obj.status in [Task.TaskStatus.CREATED, Task.TaskStatus.CANCELLED]

        return False


class CanUpdateTaskFields(permissions.BasePermission):
    """
    Разрешение на обновление определенных полей задачи
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Поля, которые может менять только руководитель
        manager_only_fields = {"title", "description", "deadline", "priority", "owner", "assignee"}

        # Поля, которые может менять исполнитель
        assignee_fields = {"status"}

        # Определяем, какие поля пытаются обновить
        update_fields = set(request.data.keys())

        # Проверяем, есть ли поля только для руководителей
        if update_fields.intersection(manager_only_fields):
            return IsManagerOrAdmin().has_permission(request, view)

        # Проверяем, есть ли поля для исполнителя
        if update_fields.intersection(assignee_fields):
            return obj.assignee and obj.assignee.employee == request.user

        return False


class CanViewBusyEmployees(permissions.BasePermission):
    """
    Разрешение на просмотр списка занятых сотрудников
    Только руководители и администраторы
    """

    def has_permission(self, request, view):
        return IsManagerOrAdmin().has_permission(request, view)


class CanViewImportantTasks(permissions.BasePermission):
    """
    Разрешение на просмотр важных (блокирующих) задач
    Только руководители и администраторы
    """

    def has_permission(self, request, view):
        return IsManagerOrAdmin().has_permission(request, view)


class CanViewEmployeeSuggestions(permissions.BasePermission):
    """
    Разрешение на просмотр предложений по сотрудникам для задачи
    Только руководители и администраторы
    """

    def has_permission(self, request, view):
        return IsManagerOrAdmin().has_permission(request, view)


# ========== РАЗРЕШЕНИЯ ==========


class TaskCRUDPermissions(permissions.BasePermission):
    """
    Композитное разрешение для CRUD операций с задачами
    """

    def has_permission(self, request, view):
        # Определяем действие
        action = getattr(view, "action", None)

        if action == "create":
            return IsManagerOrAdmin().has_permission(request, view)
        elif action in ["update", "partial_update", "destroy"]:
            # Разрешение проверяется на уровне объекта
            return True
        else:  # list, retrieve
            return CanViewTaskList().has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        action = getattr(view, "action", None)

        if action in ["retrieve", "list", "tree", "progress"]:
            return CanViewTaskDetails().has_object_permission(request, view, obj)
        elif action in ["update", "partial_update"]:
            return CanUpdateTaskFields().has_object_permission(request, view, obj)
        elif action == "destroy":
            return CanDeleteTask().has_object_permission(request, view, obj)

        return False


class CanDeleteComment(permissions.BasePermission):
    """
    Разрешение на удаление комментария.
    Удалять может автор комментария или администратор.
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Суперпользователь может удалять
        if request.user.is_superuser:
            return True

        # Автор комментария может удалять
        if obj.author == request.user:
            return True

        is_admin = Position.objects.filter(employee=request.user, level="admin", is_active=True).exists()

        return is_admin


class CommentCRUDPermissions(permissions.BasePermission):
    """
    Композитное разрешение для операций с комментариями.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        # Проверяем доступ к задаче
        task_id = view.kwargs.get("task_pk")
        if not task_id:
            return True  # Для списка всех комментариев

        try:
            task = Task.objects.get(id=task_id)
            return CanViewTaskDetails().has_object_permission(request, view, task)
        except Task.DoesNotExist:
            return False

    def has_object_permission(self, request, view, obj):
        if view.action in ["retrieve", "list"]:
            # Чтение комментария - доступно всем, кто видит задачу
            return CanViewTaskDetails().has_object_permission(request, view, obj.task)
        elif view.action == "destroy":
            # Удаление - только автор или администратор
            return CanDeleteComment().has_object_permission(request, view, obj)
        # PUT, PATCH - запрещены (возвращаем False)
        return False


# ========== ФУНКЦИИ ДЛЯ ПРОВЕРКИ ПРАВ ==========


def check_task_permission(user, task, permission_type="view"):
    """
    Утилитная функция для проверки прав доступа к задаче
    """
    if not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    if permission_type == "view":
        return any(
            [
                task.assignee and task.assignee.employee == user,
                task.owner and task.owner.employee == user,
                task.created_by == user,
                # Руководитель отдела
                Position.objects.filter(
                    employee=user,
                    level__in=["manager", "admin"],
                    is_active=True,
                    department=task.owner.department if task.owner else None,
                ).exists(),
            ]
        )

    elif permission_type == "edit":
        return any(
            [
                IsManagerOrAdmin().has_permission(None, None, user),
                task.owner and task.owner.employee == user,
            ]
        )

    elif permission_type == "delete":
        return any(
            [
                IsManagerOrAdmin().has_permission(None, None, user),
                task.created_by == user
                and not task.assignee
                and task.status in [Task.TaskStatus.CREATED, Task.TaskStatus.CANCELLED],
            ]
        )

    return False


def get_accessible_tasks(user):
    """
    Получение QuerySet задач, доступных пользователю
    """
    if not user.is_authenticated:
        return Task.objects.none()

    if user.is_superuser:
        return Task.objects.all()

    # Базовый запрос
    queryset = Task.objects.all()

    # Получаем должности пользователя
    user_positions = Position.objects.filter(employee=user, is_active=True)
    position_ids = user_positions.values_list("id", flat=True)

    # Базовые условия: задачи где пользователь исполнитель или владелец
    base_conditions = (
        models.Q(assignee_id__in=position_ids) | models.Q(owner_id__in=position_ids) | models.Q(created_by=user)
    )

    # Задачи, где пользователь оставлял комментарии
    base_conditions |= models.Q(comments__author=user)

    # Если пользователь руководитель, добавляем задачи его отдела
    is_manager = user_positions.filter(level__in=["manager", "admin"]).exists()
    if is_manager:
        manager_departments = user_positions.filter(level__in=["manager", "admin"]).values_list(
            "department", flat=True
        )

        base_conditions |= models.Q(owner__department_id__in=manager_departments)

    return queryset.filter(base_conditions).distinct()
