from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from organization.models import Position

from .models import Comment, Task

User = get_user_model()


# ========== БАЗОВЫЕ СЕРИАЛИЗАТОРЫ ==========


class UserSimpleSerializer(serializers.ModelSerializer):
    """Упрощенный сериализатор для пользователей"""

    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "last_name", "first_name", "middle_name"]
        read_only_fields = fields


class PositionSimpleSerializer(serializers.ModelSerializer):
    """Упрощенный сериализатор для должностей"""

    employee_name = serializers.CharField(source="employee.get_full_name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)

    class Meta:
        model = Position
        fields = ["id", "name", "level", "employee", "employee_name", "department", "department_name"]
        read_only_fields = ["employee_name", "department_name"]


class CommentSerializer(serializers.ModelSerializer):
    """Сериализатор для комментариев"""

    author_name = serializers.CharField(source="author.get_full_name", read_only=True)
    author_email = serializers.CharField(source="author.email", read_only=True)
    can_delete = serializers.SerializerMethodField()  # Добавим поле для проверки прав

    class Meta:
        model = Comment
        fields = ["id", "author", "author_name", "author_email", "content", "created_at", "updated_at", "can_delete"]
        read_only_fields = ["author", "author_name", "author_email", "created_at", "updated_at", "can_delete"]

    def get_can_delete(self, obj):
        """Проверка, может ли текущий пользователь удалить комментарий"""
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        # Проверяем права через наше разрешение
        from .permissions import CanDeleteComment

        permission = CanDeleteComment()
        return permission.has_object_permission(request, None, obj)

    def validate(self, data):
        """Валидация данных комментария"""
        # Проверяем, что контент не пустой
        content = data.get("content", "").strip()
        if not content:
            raise serializers.ValidationError({"content": "Комментарий не может быть пустым"})
        return data


# ========== СЕРИАЛИЗАТОРЫ ДЛЯ ЗАДАЧ ==========


class TaskListSerializer(serializers.ModelSerializer):
    """Сериализатор для списка задач (короткая информация)"""

    assignee_name = serializers.CharField(source="assignee.employee.get_full_name", read_only=True)
    owner_name = serializers.CharField(source="owner.employee.get_full_name", read_only=True)
    department = serializers.CharField(source="owner.department.name", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    progress = serializers.IntegerField(read_only=True)
    subtasks_count = serializers.SerializerMethodField()
    parent_title = serializers.CharField(source="parent.title", read_only=True, allow_null=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "status",
            "priority",
            "deadline",
            "assignee",
            "assignee_name",
            "owner",
            "owner_name",
            "department",
            "parent",
            "parent_title",
            "is_overdue",
            "progress",
            "subtasks_count",
            "created_at",
        ]

    def get_subtasks_count(self, obj):
        return obj.subtasks.count()


class TaskDetailSerializer(serializers.ModelSerializer):
    """Сериализатор для детального просмотра задачи (полная информация)"""

    assignee_details = serializers.SerializerMethodField()
    owner_details = serializers.SerializerMethodField()
    parent_title = serializers.CharField(source="parent.title", read_only=True)
    comments = CommentSerializer(many=True, read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    progress = serializers.IntegerField(read_only=True)
    depth = serializers.SerializerMethodField()
    created_by_name = serializers.CharField(source="created_by.get_full_name", read_only=True)

    class Meta:
        model = Task
        fields = [
            "id",
            "title",
            "description",
            "parent",
            "parent_title",
            "assignee",
            "assignee_details",
            "owner",
            "owner_details",
            "deadline",
            "completed_at",
            "status",
            "priority",
            "comments",
            "is_overdue",
            "progress",
            "depth",
            "created_at",
            "updated_at",
            "created_by",
            "created_by_name",
        ]
        read_only_fields = ["created_at", "updated_at", "created_by", "created_by_name"]

    def get_assignee_details(self, obj):
        if obj.assignee and obj.assignee.employee:
            return {
                "id": obj.assignee.employee.id,
                "full_name": obj.assignee.employee.get_full_name(),
                "email": obj.assignee.employee.email,
                "position": obj.assignee.name,
                "department": obj.assignee.department.name if obj.assignee.department else None,
                "level": obj.assignee.level,
            }
        return None

    def get_owner_details(self, obj):
        if obj.owner and obj.owner.employee:
            return {
                "id": obj.owner.employee.id,
                "full_name": obj.owner.employee.get_full_name(),
                "email": obj.owner.employee.email,
                "position": obj.owner.name,
                "department": obj.owner.department.name if obj.owner.department else None,
                "level": obj.owner.level,
            }
        return None

    def get_depth(self, obj):
        return obj.get_depth()


class TaskCreateSerializer(serializers.ModelSerializer):
    """Сериализатор для создания задачи"""

    class Meta:
        model = Task
        fields = ["title", "description", "parent", "assignee", "owner", "deadline", "priority"]

    def validate(self, data):
        """
        Валидация и автоматическое управление статусом:
        - Если есть исполнитель - статус "Назначена"
        - Если нет исполнителя - статус "Создана"
        """
        # Автоматически устанавливаем статус в зависимости от наличия исполнителя
        if data.get("assignee"):
            data["status"] = Task.TaskStatus.ASSIGNED
        else:
            data["status"] = Task.TaskStatus.CREATED

        # Проверка срока выполнения
        if "deadline" in data and data["deadline"]:
            if data["deadline"] < timezone.now():
                raise serializers.ValidationError({"deadline": "Срок выполнения не может быть в прошлом"})

        # Проверка валидности назначения исполнителя
        assignee = data.get("assignee")
        owner = data.get("owner")

        if assignee and owner:
            # Создаем временную задачу для проверки бизнес-правила
            temp_task = Task(assignee=assignee, owner=owner)
            if not temp_task._is_valid_assignment():
                raise serializers.ValidationError(
                    {
                        "assignee": "Задача может быть назначена только сотруднику своего отдела "
                        "или руководителю нижестоящего отдела"
                    }
                )

        return data

    def create(self, validated_data):
        """Создание задачи"""
        return Task.objects.create(**validated_data)


class TaskUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор для обновления задачи (для руководителей)"""

    class Meta:
        model = Task
        fields = ["title", "description", "deadline", "priority", "status"]

    def validate_status(self, value):
        """Валидация изменения статуса"""
        # Руководители могут менять любые статусы
        return value

    def update(self, instance, validated_data):
        """Обновление задачи с автоматическим управлением статусом"""
        # Если меняем исполнителя через этот сериализатор (что маловероятно)
        # лучше использовать специальный сериализатор reassign
        return super().update(instance, validated_data)


class TaskAssigneeUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор для обновления задачи исполнителем (только статус)"""

    class Meta:
        model = Task
        fields = ["status"]

    def validate_status(self, value):
        """Валидация изменения статуса исполнителем"""
        user = self.context["request"].user
        task = self.instance

        # Проверяем, является ли пользователь исполнителем задачи
        if not task.assignee or task.assignee.employee != user:
            raise serializers.ValidationError("Только назначенный исполнитель может менять статус задачи")

        # Проверяем допустимость перехода статуса
        valid_transitions = {
            Task.TaskStatus.CREATED: [Task.TaskStatus.ASSIGNED, Task.TaskStatus.CANCELLED],
            Task.TaskStatus.ASSIGNED: [Task.TaskStatus.IN_PROGRESS, Task.TaskStatus.CANCELLED],
            Task.TaskStatus.IN_PROGRESS: [Task.TaskStatus.COMPLETED, Task.TaskStatus.ON_HOLD],
            Task.TaskStatus.ON_HOLD: [Task.TaskStatus.IN_PROGRESS, Task.TaskStatus.CANCELLED],
        }

        current_status = task.status
        if value not in valid_transitions.get(current_status, []):
            raise serializers.ValidationError(
                f'Недопустимый переход из "{task.get_status_display()}" в '
                f'"{dict(Task.TaskStatus.choices).get(value, value)}"'
            )

        return value


class TaskReassignSerializer(serializers.ModelSerializer):
    """Сериализатор для переназначения задачи (только поле assignee)"""

    class Meta:
        model = Task
        fields = ["assignee"]

    def validate_assignee(self, value):
        """Валидация нового исполнителя"""
        task = self.instance

        # Если назначаем исполнителя, проверяем валидность назначения
        if value and task.owner:
            temp_task = Task(assignee=value, owner=task.owner)
            if not temp_task._is_valid_assignment():
                raise serializers.ValidationError(
                    "Задача может быть назначена только сотруднику своего отдела "
                    "или руководителю нижестоящего отдела"
                )

        return value

    def update(self, instance, validated_data):
        """
        Обновление исполнителя с автоматическим управлением статусом:
        - Назначили исполнителя - статус "Назначена"
        - Сняли исполнителя из статуса "Назначена" - статус "Создана"
        """
        new_assignee = validated_data.get("assignee")

        # Если назначили исполнителя
        if new_assignee:
            instance.assignee = new_assignee
            instance.status = Task.TaskStatus.ASSIGNED
        # Если сняли исполнителя (передали null)
        elif new_assignee is None:
            instance.assignee = None
            # Если задача была "Назначена", возвращаем в "Создана"
            if instance.status == Task.TaskStatus.ASSIGNED:
                instance.status = Task.TaskStatus.CREATED

        instance.save()
        return instance


# ========== СПЕЦИАЛЬНЫЕ СЕРИАЛИЗАТОРЫ ДЛЯ ЭНДПОИНТОВ ==========


class BusyEmployeeSerializer(serializers.Serializer):
    """Сериализатор для эндпоинта "Занятые сотрудников" """

    employee_id = serializers.IntegerField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    position_name = serializers.CharField()
    department_name = serializers.CharField()
    active_tasks_count = serializers.IntegerField()
    overdue_tasks_count = serializers.IntegerField()
    total_tasks_count = serializers.IntegerField()


# ========== УТИЛИТНЫЕ СЕРИАЛИЗАТОРЫ ==========


class TaskProgressSerializer(serializers.ModelSerializer):
    """Сериализатор для отображения прогресса задачи"""

    progress = serializers.IntegerField(read_only=True)
    subtasks_progress = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = ["id", "title", "status", "progress", "subtasks_progress"]

    def get_subtasks_progress(self, obj):
        """Получение прогресса по подзадачам"""
        subtasks = obj.subtasks.all()
        if not subtasks:
            return None

        total = subtasks.count()
        completed = subtasks.filter(status=Task.TaskStatus.COMPLETED).count()
        in_progress = subtasks.filter(status=Task.TaskStatus.IN_PROGRESS).count()

        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "completion_percentage": round((completed / total) * 100, 1) if total > 0 else 0,
        }


class TaskTreeSerializer(serializers.ModelSerializer):
    """Сериализатор для иерархического дерева задач"""

    children = serializers.SerializerMethodField()
    progress = serializers.IntegerField(read_only=True)

    class Meta:
        model = Task
        fields = ["id", "title", "status", "priority", "deadline", "progress", "children"]

    def get_children(self, obj):
        """Рекурсивное получение дочерних задач"""
        children = obj.subtasks.all()
        serializer = TaskTreeSerializer(children, many=True)
        return serializer.data


# ========== СЕРИАЛИЗАТОР ДЛЯ ФИЛЬТРАЦИИ ==========


class TaskFilterSerializer(serializers.Serializer):
    """Сериализатор для фильтрации задач в запросах"""

    status = serializers.CharField(required=False)
    priority = serializers.CharField(required=False)
    assignee = serializers.IntegerField(required=False)
    owner = serializers.IntegerField(required=False)
    department = serializers.IntegerField(required=False)
    overdue = serializers.BooleanField(required=False)
    my_tasks = serializers.BooleanField(required=False)
    search = serializers.CharField(required=False)

    def validate_status(self, value):
        if value and value not in dict(Task.TaskStatus.choices):
            raise serializers.ValidationError(f"Недопустимый статус: {value}")
        return value

    def validate_priority(self, value):
        if value and value not in dict(Task.TaskPriority.choices):
            raise serializers.ValidationError(f"Недопустимый приоритет: {value}")
        return value
