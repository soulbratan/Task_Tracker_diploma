from django.contrib.auth import get_user_model
from django.db.models import Prefetch, Q
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Department, Position
from .permissions import CanAssignEmployee, IsAdminOrSuperUser, IsPositionAssignedEmployee
from .serializers import (DepartmentSerializer, DepartmentStructureSerializer, EmployeeProfileSerializer,
                          PositionAssignSerializer, PositionSerializer, PositionUpdateSerializer)

User = get_user_model()


class DepartmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления отделами.
    """

    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

    def get_permissions(self):
        """
        Настройка прав доступа:
        - Список и детали: доступны всем авторизованным с должностью
        - Создание: только администраторам и суперпользователям
        - Обновление/Удаление: только администраторам и суперпользователям
        """
        if self.action in ["list", "retrieve", "tree", "structure"]:
            permission_classes = [IsAuthenticated, IsPositionAssignedEmployee]
        else:  # create, update, partial_update, destroy
            permission_classes = [IsAuthenticated, IsAdminOrSuperUser]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        """
        Фильтрация отделов.
        """
        queryset = super().get_queryset()

        # Фильтр по родительскому отделу
        parent_id = self.request.query_params.get("parent")
        if parent_id:
            queryset = queryset.filter(parent_id=parent_id)

        # Фильтр по названию
        name = self.request.query_params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        # Фильтр по уровню (корневые отделы)
        root_only = self.request.query_params.get("root_only")
        if root_only and root_only.lower() == "true":
            queryset = queryset.filter(parent__isnull=True)

        return queryset.select_related("parent")

    def destroy(self, request, *args, **kwargs):
        """
        Двухэтапное удаление отдела:

        Этап 1: Если в отделе есть должности с сотрудниками:
                - Освобождаем все должности (employee=None)
                - Возвращаем сообщение о необходимости повторного запроса

        Этап 2: Если все должности вакантны:
                - Проверяем есть ли дочерние отделы
                - Если есть: запрещаем удаление
                - Если нет: удаляем отдел и все его должности
        """
        instance = self.get_object()

        # Проверяем права
        self.check_object_permissions(self.request, instance)

        # Получаем все должности отдела
        department_positions = instance.positions.all()
        positions_with_employees = department_positions.filter(employee__isnull=False)

        # ПЕРВЫЙ ЭТАП: Есть должности с сотрудниками
        if positions_with_employees.exists():
            # Освобождаем все должности от сотрудников
            employees_freed = []

            for position in positions_with_employees:
                if position.employee:
                    # Сохраняем информацию о сотруднике
                    employees_freed.append(
                        {
                            "position_id": position.id,
                            "position_name": position.name,
                            "employee_id": position.employee.id,
                            "employee_name": position.employee.get_full_name(),
                            "employee_email": position.employee.email,
                        }
                    )

                    # Логируем
                    print(
                        f"Сотрудник {position.employee.email} снят с должности {position.name} "
                        f"при удалении отдела {instance.name}"
                    )

                    # Освобождаем должность
                    position.employee = None
                    position.save()

            # Формируем ответ
            response_data = {
                "detail": "Все сотрудники сняты с должностей отдела.",
                "message": "Для удаления отдела отправьте DELETE запрос повторно.",
                "department": {
                    "id": instance.id,
                    "name": instance.name,
                    "positions_count": department_positions.count(),
                    "employees_freed_count": len(employees_freed),
                    "employees_freed": employees_freed,
                    "has_children": instance.children.exists(),
                },
                "next_step": "Повторный DELETE запрос проверит наличие дочерних отделов и выполнит удаление.",
            }

            return Response(response_data, status=status.HTTP_200_OK)

        # ВТОРОЙ ЭТАП: Все должности вакантны
        else:
            # Проверяем наличие дочерних отделов
            child_departments = instance.children.all()

            if child_departments.exists():
                # Запрещаем удаление - есть дочерние отделы
                child_departments_list = [
                    {
                        "id": child.id,
                        "name": child.name,
                        "positions_count": child.positions.count(),
                        "employees_count": child.positions.filter(employee__isnull=False).count(),
                    }
                    for child in child_departments
                ]

                return Response(
                    {
                        "detail": "Нельзя удалить отдел с дочерними подотделами.",
                        "message": "Сначала удалите или переместите все дочерние отделы.",
                        "department": {
                            "id": instance.id,
                            "name": instance.name,
                            "positions_count": department_positions.count(),
                            "vacant_positions": department_positions.filter(employee__isnull=True).count(),
                        },
                        "child_departments": {
                            "count": child_departments.count(),
                            "departments": child_departments_list,
                        },
                        "action_required": "Удалите дочерние отделы или измените их родительский отдел.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # ВТОРОЙ ЭТАП: Удаляем отдел (все должности вакантны, дочерних отделов нет)

            # Сохраняем информацию об удаляемых должностях
            deleted_positions_info = [
                {
                    "id": position.id,
                    "name": position.name,
                    "level": position.level,
                    "level_display": position.get_level_display(),
                }
                for position in department_positions
            ]

            # Сохраняем информацию об отделе для ответа
            department_info = {
                "id": instance.id,
                "name": instance.name,
                "description": instance.description,
                "parent": instance.parent.name if instance.parent else None,
                "positions_deleted": len(deleted_positions_info),
            }

            # Удаляем отдел (должности удалятся каскадно благодаря on_delete=CASCADE)
            instance.delete()

            return Response(
                {
                    "detail": f'Отдел "{instance.name}" и все его должности удалены.',
                    "deleted_department": department_info,
                    "deleted_positions": deleted_positions_info,
                    "warning": "Все должности отдела были удалены каскадно.",
                },
                status=status.HTTP_200_OK,
            )

    @action(detail=False, methods=["get"])
    def tree(self, request):
        """
        Получение иерархического дерева отделов.
        """
        root_departments = Department.objects.filter(parent__isnull=True)
        serializer = DepartmentStructureSerializer(root_departments, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def structure(self, request, pk=None):
        """
        Получение структуры конкретного отдела с подотделами.
        """
        department = self.get_object()
        serializer = DepartmentStructureSerializer(department, context={"request": request})
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def positions(self, request, pk=None):
        """
        Получение всех должностей в отделе.
        """
        department = self.get_object()
        positions = department.positions.filter(is_active=True)
        serializer = PositionSerializer(positions, many=True, context={"request": request})
        return Response(serializer.data)


class PositionViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления должностями.
    """

    queryset = Position.objects.filter(is_active=True)
    serializer_class = PositionSerializer

    def get_permissions(self):
        """
        Настройка прав доступа:
        - Список и детали: доступны всем авторизованным с должностью
        - Создание/Обновление/Удаление: только администраторам и суперпользователям
        - Назначение сотрудника: только администраторам и суперпользователям
        """
        if self.action in ["list", "retrieve", "my_position"]:
            permission_classes = [IsAuthenticated, IsPositionAssignedEmployee]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAuthenticated, IsAdminOrSuperUser]
        elif self.action in ["assign", "unassign"]:
            permission_classes = [IsAuthenticated, CanAssignEmployee]
        else:
            permission_classes = [IsAuthenticated]
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        """
        Выбор сериализатора в зависимости от действия.
        """
        if self.action in ["update", "partial_update"]:
            return PositionUpdateSerializer
        elif self.action in ["assign"]:
            return PositionAssignSerializer
        return super().get_serializer_class()

    def get_queryset(self):
        """
        Фильтрация должностей.
        По умолчанию показываем только активные должности.
        """
        queryset = Position.objects.all().select_related("department", "employee")

        # Для большинства эндпоинтов показываем только активные
        if self.action in ["list", "retrieve", "my_position", "vacancies", "by_level"]:
            queryset = queryset.filter(is_active=True)

        # Фильтр по отделу
        department_id = self.request.query_params.get("department")
        if department_id:
            queryset = queryset.filter(department_id=department_id)

        # Фильтр по уровню должности
        level = self.request.query_params.get("level")
        if level:
            queryset = queryset.filter(level=level)

        # Фильтр по статусу занятости
        vacant = self.request.query_params.get("vacant")
        if vacant and vacant.lower() == "true":
            queryset = queryset.filter(employee__isnull=True)

        # Фильтр по сотруднику
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        # Фильтр по названию
        name = self.request.query_params.get("name")
        if name:
            queryset = queryset.filter(name__icontains=name)

        return queryset

    def destroy(self, request, *args, **kwargs):
        """
        Двухэтапное удаление должности:
        1. Если должность активна ИЛИ есть сотрудник:
           - Деактивируем (is_active=False)
           - Снимаем сотрудника (employee=None)
           - Возвращаем сообщение
        2. Если должность неактивна И нет сотрудника:
           - Полностью удаляем из БД
        """
        instance = self.get_object()

        # Проверяем права
        self.check_object_permissions(self.request, instance)

        # Проверяем условия
        needs_deactivation = instance.is_active or instance.employee

        if needs_deactivation:
            # ПЕРВЫЙ ЭТАП: Деактивация и освобождение
            previous_employee = None

            if instance.employee:
                # Сохраняем информацию о сотруднике для ответа
                previous_employee = {
                    "id": instance.employee.id,
                    "name": instance.employee.get_full_name(),
                    "email": instance.employee.email,
                }

                # Логируем снятие сотрудника
                print(f"Сотрудник {instance.employee.email} снят с должности {instance.name}")

                # Снимаем сотрудника
                instance.employee = None

            # Деактивируем должность
            was_active = instance.is_active
            instance.is_active = False
            instance.save()

            # Формируем ответ
            response_data = {
                "detail": "Должность деактивирована и освобождена.",
                "message": "Для полного удаления отправьте DELETE запрос повторно.",
                "position": {
                    "id": instance.id,
                    "name": instance.name,
                    "department": instance.department.name if instance.department else None,
                    "previous_status": {
                        "was_active": was_active,
                        "had_employee": previous_employee is not None,
                        "employee": previous_employee,
                    },
                    "current_status": {"is_active": instance.is_active, "has_employee": bool(instance.employee)},
                    "can_be_deleted": not instance.is_active and not instance.employee,
                },
            }

            return Response(response_data, status=status.HTTP_200_OK)

        else:
            # ВТОРОЙ ЭТАП: Полное удаление
            # Должность уже неактивна и вакантна

            # Сохраняем информацию для ответа
            position_info = {
                "id": instance.id,
                "name": instance.name,
                "department": instance.department.name if instance.department else None,
                "level": instance.level,
                "level_display": instance.get_level_display(),
            }

            # Удаляем из БД
            instance.delete()

            return Response(
                {"detail": "Должность полностью удалена из базы данных.", "deleted_position": position_info},
                status=status.HTTP_200_OK,
            )

    @action(detail=False, methods=["get"])
    def my_position(self, request):
        """
        Получение текущей должности авторизованного пользователя.
        """
        position = Position.objects.filter(employee=request.user, is_active=True).first()

        if not position:
            return Response({"detail": "У вас нет назначенной должности"}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(position)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        """
        Назначение сотрудника на должность с гарантией обновления.
        """
        from django.db import transaction

        with transaction.atomic():
            position = self.get_object()
            serializer = self.get_serializer(position, data=request.data, partial=True)

            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            # Сохраняем через serializer (вызовет сигналы)
            serializer.save()

            # Перезагружаем объект для проверки
            position.refresh_from_db()

            return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def unassign(self, request, pk=None):
        """
        Снятие сотрудника с должности.
        """
        position = self.get_object()

        if not position.employee:
            return Response({"detail": "Должность уже вакантна"}, status=status.HTTP_400_BAD_REQUEST)

        # Логирование снятия
        print(f"Сотрудник {position.employee.email} снят с должности {position.name}")

        position.employee = None
        position.save()

        serializer = self.get_serializer(position)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def vacancies(self, request):
        """
        Получение списка вакантных должностей.
        """
        vacancies = self.get_queryset().filter(employee__isnull=True)
        serializer = self.get_serializer(vacancies, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_level(self, request):
        """
        Группировка должностей по уровням.
        """
        levels = Position.PositionLevel.choices
        result = {}

        for level_code, level_name in levels:
            positions = self.get_queryset().filter(level=level_code)
            serializer = self.get_serializer(positions, many=True)
            result[level_name] = {"count": positions.count(), "positions": serializer.data}

        return Response(result)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsAdminOrSuperUser])
    def inactive(self, request):
        """
        Получение списка неактивных должностей.
        """
        inactive_positions = Position.objects.filter(is_active=False).select_related("department", "employee")

        # Фильтрация по отделу
        department_id = self.request.query_params.get("department")
        if department_id:
            inactive_positions = inactive_positions.filter(department_id=department_id)

        # Фильтрация по наличию сотрудника
        with_employee = self.request.query_params.get("with_employee")
        if with_employee:
            if with_employee.lower() == "true":
                inactive_positions = inactive_positions.filter(employee__isnull=False)
            elif with_employee.lower() == "false":
                inactive_positions = inactive_positions.filter(employee__isnull=True)

        serializer = self.get_serializer(inactive_positions, many=True)
        return Response(serializer.data)


class OrganizationView(APIView):
    """
    View для работы с организационной структурой.
    """

    permission_classes = [IsAuthenticated, IsPositionAssignedEmployee]

    def get(self, request):
        """
        Получение полной организационной диаграммы.
        """
        # Получаем все отделы с их детьми и должностями
        all_departments = Department.objects.all().prefetch_related(
            Prefetch("children", queryset=Department.objects.all().prefetch_related("positions")),
            Prefetch("positions", queryset=Position.objects.filter(is_active=True).select_related("employee")),
        )

        # Строим иерархию
        def build_tree(parent_id=None):
            """Рекурсивно строим дерево отделов"""
            departments = [dept for dept in all_departments if dept.parent_id == parent_id]

            result = []
            for dept in departments:
                # Получаем позиции отдела
                positions_data = []
                for position in dept.positions.filter(is_active=True):
                    position_data = {
                        "id": position.id,
                        "name": position.name,
                        "level": position.level,
                        "level_display": position.get_level_display(),
                        "is_active": position.is_active,
                    }

                    # Добавляем информацию о сотруднике, если есть
                    if position.employee:
                        position_data["employee"] = {
                            "id": position.employee.id,
                            "full_name": position.employee.get_full_name(),
                            "email": position.employee.email,
                        }
                    else:
                        position_data["employee"] = None

                    positions_data.append(position_data)

                # Рекурсивно получаем детей
                children = build_tree(dept.id)

                result.append(
                    {
                        "id": dept.id,
                        "name": dept.name,
                        "description": dept.description,
                        "positions": positions_data,
                        "children": children,
                    }
                )

            return result

        # Получаем дерево (корневые отделы имеют parent_id=None)
        departments_tree = build_tree(None)

        # Статистика
        total_departments = Department.objects.count()
        total_positions = Position.objects.filter(is_active=True).count()
        total_employees = Position.objects.filter(is_active=True, employee__isnull=False).count()
        vacant_positions = Position.objects.filter(is_active=True, employee__isnull=True).count()

        data = {
            "departments": departments_tree,
            "total_departments": total_departments,
            "total_positions": total_positions,
            "total_employees": total_employees,
            "vacant_positions": vacant_positions,
        }

        return Response(data)


class EmployeeListView(generics.ListAPIView):
    """
    View для получения списка сотрудников с их должностями.
    """

    serializer_class = EmployeeProfileSerializer
    permission_classes = [IsAuthenticated, IsPositionAssignedEmployee]

    def get_queryset(self):
        """
        Получение только пользователей с назначенными должностями.
        """
        # Получаем ID пользователей с активными должностями
        employee_ids = (
            Position.objects.filter(is_active=True, employee__isnull=False)
            .values_list("employee_id", flat=True)
            .distinct()
        )

        return User.objects.filter(id__in=employee_ids).select_related()

    def get(self, request, *args, **kwargs):
        """
        Получение списка сотрудников с фильтрацией.
        """
        queryset = self.get_queryset()

        # Фильтрация по отделу
        department_id = self.request.query_params.get("department")
        if department_id:
            # Получаем ID сотрудников в указанном отделе
            employee_ids = Position.objects.filter(
                department_id=department_id, is_active=True, employee__isnull=False
            ).values_list("employee_id", flat=True)
            queryset = queryset.filter(id__in=employee_ids)

        # Фильтрация по уровню должности
        level = self.request.query_params.get("level")
        if level:
            employee_ids = Position.objects.filter(level=level, is_active=True, employee__isnull=False).values_list(
                "employee_id", flat=True
            )
            queryset = queryset.filter(id__in=employee_ids)

        # Фильтрация по имени
        name = self.request.query_params.get("name")
        if name:
            queryset = queryset.filter(
                Q(first_name__icontains=name)
                | Q(last_name__icontains=name)
                | Q(middle_name__icontains=name)
                | Q(email__icontains=name)
            )

        # Пагинация
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
