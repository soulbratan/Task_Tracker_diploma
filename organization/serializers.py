from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import Department, Position

User = get_user_model()


class UserSimpleSerializer(serializers.ModelSerializer):
    """Упрощенный сериализатор для пользователей"""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "last_name", "first_name", "middle_name"]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.get_full_name()


class DepartmentSerializer(serializers.ModelSerializer):
    """Сериализатор для отделов"""

    parent_name = serializers.CharField(source="parent.name", read_only=True)
    full_path = serializers.CharField(source="get_full_path", read_only=True)
    level = serializers.IntegerField(read_only=True)
    children_count = serializers.SerializerMethodField()
    positions_count = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "parent",
            "parent_name",
            "description",
            "full_path",
            "level",
            "children_count",
            "positions_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_children_count(self, obj):
        return obj.children.count()

    def get_positions_count(self, obj):
        return obj.positions.filter(is_active=True).count()

    def validate_parent(self, value):
        """Валидация родительского отдела"""
        if value and self.instance and value == self.instance:
            raise serializers.ValidationError("Отдел не может быть родителем самому себе")
        return value

    def create(self, validated_data):
        # Проверяем права на создание подотдела
        request = self.context.get("request")
        parent = validated_data.get("parent")

        if parent and request:
            # Проверяем, что пользователь имеет право создавать подотделы
            if not (request.user.is_superuser or request.user.is_staff):
                raise serializers.ValidationError(
                    "Только администратор или суперпользователь могут создавать подотделы"
                )

        return super().create(validated_data)


class PositionSerializer(serializers.ModelSerializer):
    """Сериализатор для должностей"""

    department_name = serializers.CharField(source="department.name", read_only=True)
    employee_details = UserSimpleSerializer(source="employee", read_only=True)
    level_display = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "id",
            "name",
            "level",
            "level_display",
            "department",
            "department_name",
            "employee",
            "employee_details",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_level_display(self, obj):
        """Получение читаемого названия уровня должности"""
        return obj.get_level_display()

    def validate(self, data):
        """Валидация данных должности"""
        errors = {}

        # Получаем инстанс если он есть (для обновления)
        instance = getattr(self, "instance", None)

        # Проверка: не более 2 руководителей в отделе
        if data.get("level") == Position.PositionLevel.MANAGER:
            department = data.get("department") or (instance.department if instance else None)

            if department:
                manager_count = (
                    Position.objects.filter(
                        department=department, level=Position.PositionLevel.MANAGER, is_active=True
                    )
                    .exclude(id=instance.id if instance else None)
                    .count()
                )

                if manager_count >= 2:
                    errors["level"] = "В отделе не может быть больше 2 руководителей"

        # Проверка: не более 4 администраторов всего
        if data.get("level") == Position.PositionLevel.ADMIN:
            admin_count = (
                Position.objects.filter(level=Position.PositionLevel.ADMIN, is_active=True)
                .exclude(id=instance.id if instance else None)
                .count()
            )

            if admin_count >= 4:
                errors["level"] = "Всего не может быть больше 4 администраторов"

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        """Создание должности с проверкой прав"""
        request = self.context.get("request")

        if request and not (request.user.is_superuser or request.user.is_staff):
            raise serializers.ValidationError("Только администратор или суперпользователь могут создавать должности")

        return super().create(validated_data)


class PositionUpdateSerializer(serializers.ModelSerializer):
    """Сериализатор для обновления должностей (особенно назначения сотрудника)"""

    department_name = serializers.CharField(source="department.name", read_only=True)
    employee_details = UserSimpleSerializer(source="employee", read_only=True)
    level_display = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "id",
            "name",
            "level",
            "level_display",
            "department",
            "department_name",
            "employee",
            "employee_details",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["name", "level", "department", "created_at", "updated_at"]

    def get_level_display(self, obj):
        """Получение читаемого названия уровня должности"""
        return obj.get_level_display()

    def validate_employee(self, value):
        """Валидация назначения сотрудника"""
        instance = self.instance

        # Проверяем, что сотрудник не занят на другой должности
        if value:
            existing_position = (
                Position.objects.filter(employee=value, is_active=True)
                .exclude(id=instance.id if instance else None)
                .first()
            )

            if existing_position:
                raise serializers.ValidationError(
                    f'Сотрудник уже занимает должность "{existing_position.name}" '
                    f'в отделе "{existing_position.department.name}"'
                )

        return value


class PositionAssignSerializer(serializers.ModelSerializer):
    """Сериализатор только для назначения сотрудника на должность"""

    class Meta:
        model = Position
        fields = ["employee"]

    def validate_employee(self, value):
        """Валидация назначения сотрудника"""
        instance = self.instance

        if value:
            # Проверяем, что сотрудник не занят на другой должности
            existing_position = Position.objects.filter(employee=value, is_active=True).exclude(id=instance.id).first()

            if existing_position:
                raise serializers.ValidationError(
                    f'Сотрудник уже занимает должность "{existing_position.name}" '
                    f'в отделе "{existing_position.department.name}"'
                )

        return value

    def update(self, instance, validated_data):
        """
        Обновляем должность.
        is_staff обновится автоматически через метод save() модели Position.
        """
        return super().update(instance, validated_data)


class DepartmentStructureSerializer(serializers.ModelSerializer):
    """Сериализатор для иерархической структуры отделов"""

    children = serializers.SerializerMethodField()
    positions = serializers.SerializerMethodField()

    class Meta:
        model = Department
        fields = ["id", "name", "description", "children", "positions"]

    def get_children(self, obj):
        """Рекурсивно получаем дочерние отделы"""

        # Проверяем, что obj - это экземпляр модели Department, а не словарь
        if isinstance(obj, dict):
            # Если это словарь (уже сериализованные данные), возвращаем пустой список
            return []

        children = obj.children.all()
        serializer = DepartmentStructureSerializer(children, many=True)
        return serializer.data

    def get_positions(self, obj):
        """Получаем должности отдела"""

        if isinstance(obj, dict):
            return []

        positions = obj.positions.filter(is_active=True)
        return PositionSerializer(positions, many=True, context=self.context).data


class EmployeeProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для профиля сотрудника с должностью"""

    position = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "last_name",
            "first_name",
            "middle_name",
            "phone",
            "photo",
            "organization",
            "position",
            "department",
        ]

    def get_position(self, obj):
        """Получаем текущую должность сотрудника"""
        position = obj.positions.filter(is_active=True).first()
        if position:
            return {
                "id": position.id,
                "name": position.name,
                "level": position.level,
                "level_display": position.get_level_display(),
            }
        return None

    def get_department(self, obj):
        """Получаем отдел сотрудника"""
        position = obj.positions.filter(is_active=True).first()
        if position and position.department:
            return {"id": position.department.id, "name": position.department.name}
        return None
