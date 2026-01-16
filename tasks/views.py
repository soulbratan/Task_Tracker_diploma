from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organization.models import Position

from .models import Comment, Task
from .permissions import (CanChangeTaskStatus, CanReassignTask, CanViewBusyEmployees, CanViewEmployeeSuggestions,
                          CanViewImportantTasks, CommentCRUDPermissions, IsManagerOrAdmin, TaskCRUDPermissions,
                          get_accessible_tasks)
from .serializers import (BusyEmployeeSerializer, CommentSerializer, TaskAssigneeUpdateSerializer,
                          TaskCreateSerializer, TaskDetailSerializer, TaskListSerializer, TaskProgressSerializer,
                          TaskReassignSerializer, TaskTreeSerializer, TaskUpdateSerializer)
from .services import TaskDependencyService, TaskStatisticsService

User = get_user_model()


# ========== БАЗОВЫЕ VIEWSETS ==========


class TaskViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления задачами
    """

    serializer_class = TaskDetailSerializer
    permission_classes = [IsAuthenticated, TaskCRUDPermissions]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["status", "priority", "owner", "assignee"]
    search_fields = ["title", "description"]
    ordering_fields = ["created_at", "deadline", "priority", "status", "title"]
    ordering = ["-created_at"]

    def get_queryset(self):
        """
        Фильтрация задач в зависимости от роли пользователя
        """
        user = self.request.user

        # Получаем задачи, доступные пользователю
        queryset = get_accessible_tasks(user)

        # Оптимизация запросов
        queryset = queryset.select_related(
            "assignee",
            "assignee__employee",
            "assignee__department",
            "owner",
            "owner__employee",
            "owner__department",
            "parent",
            "created_by",
        ).prefetch_related("comments", "comments__author", "subtasks")

        # Применяем фильтры из запроса
        queryset = self._apply_filters(queryset)

        return queryset

    def _apply_filters(self, queryset):
        """
        Применение фильтров из параметров запроса
        """
        request = self.request

        # Фильтр по статусу
        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Фильтр по приоритету
        priority_filter = request.query_params.get("priority")
        if priority_filter:
            queryset = queryset.filter(priority=priority_filter)

        # Фильтр по отделу
        department_id = request.query_params.get("department")
        if department_id:
            queryset = queryset.filter(owner__department_id=department_id)

        # Фильтр "мои задачи"
        my_tasks = request.query_params.get("my_tasks")
        if my_tasks and my_tasks.lower() == "true":
            user_positions = Position.objects.filter(employee=self.request.user, is_active=True)
            position_ids = user_positions.values_list("id", flat=True)
            queryset = queryset.filter(
                Q(assignee_id__in=position_ids) | Q(owner_id__in=position_ids) | Q(created_by=self.request.user)
            )

        # Фильтр "просроченные"
        overdue = request.query_params.get("overdue")
        if overdue and overdue.lower() == "true":
            queryset = queryset.filter(
                deadline__lt=timezone.now(),
                status__in=[Task.TaskStatus.CREATED, Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS],
            )

        # Фильтр "без исполнителя"
        unassigned = request.query_params.get("unassigned")
        if unassigned and unassigned.lower() == "true":
            queryset = queryset.filter(assignee__isnull=True)

        return queryset

    def get_serializer_class(self):
        """
        Выбор сериализатора в зависимости от действия
        """
        if self.action == "list":
            return TaskListSerializer
        elif self.action == "create":
            return TaskCreateSerializer
        elif self.action in ["update", "partial_update"]:
            # Определяем, кто обновляет задачу
            if hasattr(self, "get_object"):
                try:
                    task = self.get_object()
                    if task.assignee and task.assignee.employee == self.request.user:
                        return TaskAssigneeUpdateSerializer
                    else:
                        return TaskUpdateSerializer
                except:  # noqa
                    return TaskUpdateSerializer
            return TaskUpdateSerializer
        elif self.action == "reassign":
            return TaskReassignSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer):
        """
        Создание задачи с указанием создателя
        """
        # Находим активную должность пользователя как владельца (если не указан)
        if not serializer.validated_data.get("owner"):
            user_position = Position.objects.filter(employee=self.request.user, is_active=True).first()

            if user_position:
                serializer.validated_data["owner"] = user_position

        # Автоматически устанавливаем статус "Назначена" если есть исполнитель
        if serializer.validated_data.get("assignee"):
            serializer.validated_data["status"] = Task.TaskStatus.ASSIGNED

        # Сохраняем задачу
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, CanReassignTask])
    def reassign(self, request, pk=None):
        """
        Переназначение задачи на другого исполнителя
        """
        task = self.get_object()
        serializer = self.get_serializer(task, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, CanChangeTaskStatus])
    def change_status(self, request, pk=None):
        """
        Изменение статуса задачи
        """
        task = self.get_object()
        new_status = request.data.get("status")

        if not new_status:
            return Response({"detail": "Не указан статус"}, status=status.HTTP_400_BAD_REQUEST)

        # Проверяем допустимость перехода статуса
        valid_transitions = {
            Task.TaskStatus.CREATED: [Task.TaskStatus.ASSIGNED, Task.TaskStatus.CANCELLED],
            Task.TaskStatus.ASSIGNED: [Task.TaskStatus.IN_PROGRESS, Task.TaskStatus.CANCELLED],
            Task.TaskStatus.IN_PROGRESS: [Task.TaskStatus.COMPLETED, Task.TaskStatus.ON_HOLD],
            Task.TaskStatus.ON_HOLD: [Task.TaskStatus.IN_PROGRESS, Task.TaskStatus.CANCELLED],
        }

        current_status = task.status
        if new_status not in valid_transitions.get(current_status, []):
            return Response(
                {
                    "detail": f'Недопустимый переход из "{task.get_status_display()}" в '
                    f'"{dict(Task.TaskStatus.choices).get(new_status, new_status)}"'
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Обновляем статус
        old_status = task.status
        task.status = new_status

        # Если задача выполнена, устанавливаем дату выполнения
        if new_status == Task.TaskStatus.COMPLETED:
            task.completed_at = timezone.now()
        elif old_status == Task.TaskStatus.COMPLETED and new_status != Task.TaskStatus.COMPLETED:
            task.completed_at = None

        task.save()

        serializer = self.get_serializer(task)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None):
        """
        Получение прогресса задачи
        """
        task = self.get_object()
        serializer = TaskProgressSerializer(task)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def tree(self, request, pk=None):
        """
        Получение иерархического дерева задачи
        """
        task = self.get_object()
        serializer = TaskTreeSerializer(task)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def my_tasks(self, request):
        """
        Получение задач текущего пользователя
        """
        user = request.user

        # Получаем должности пользователя
        user_positions = Position.objects.filter(employee=user, is_active=True)
        position_ids = user_positions.values_list("id", flat=True)

        # Задачи, где пользователь исполнитель, владелец или создатель
        tasks = (
            get_accessible_tasks(user)
            .filter(Q(assignee_id__in=position_ids) | Q(owner_id__in=position_ids) | Q(created_by=user))
            .distinct()
        )

        # Применяем фильтры
        tasks = self._apply_filters(tasks)

        page = self.paginate_queryset(tasks)
        if page is not None:
            serializer = TaskListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = TaskListSerializer(tasks, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def overdue(self, request):
        """
        Просроченные задачи
        """
        tasks = (
            get_accessible_tasks(request.user)
            .filter(
                deadline__lt=timezone.now(),
                status__in=[Task.TaskStatus.CREATED, Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS],
            )
            .order_by("deadline")
        )

        page = self.paginate_queryset(tasks)
        if page is not None:
            serializer = TaskListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)

        serializer = TaskListSerializer(tasks, many=True, context={"request": request})
        return Response(serializer.data)

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated, IsManagerOrAdmin])
    def statistics(self, request):
        """
        Статистика по задачам
        """
        user = request.user

        # Фильтруем задачи, доступные пользователю
        queryset = get_accessible_tasks(user)

        # Общая статистика
        total = queryset.count()
        by_status = dict(queryset.values_list("status").annotate(count=Count("id")).order_by("status"))
        by_priority = dict(queryset.values_list("priority").annotate(count=Count("id")).order_by("priority"))

        overdue = queryset.filter(
            deadline__lt=timezone.now(),
            status__in=[Task.TaskStatus.CREATED, Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS],
        ).count()

        completed_this_month = queryset.filter(
            status=Task.TaskStatus.COMPLETED,
            completed_at__month=timezone.now().month,
            completed_at__year=timezone.now().year,
        ).count()

        # Статистика по исполнителям
        top_assignees = (
            Position.objects.filter(assigned_tasks__in=queryset)
            .annotate(
                task_count=Count("assigned_tasks"),
                completed_count=Count("assigned_tasks", filter=Q(assigned_tasks__status=Task.TaskStatus.COMPLETED)),
            )
            .order_by("-task_count")[:5]
        )

        assignee_stats = [
            {
                "employee_id": pos.employee.id if pos.employee else None,
                "employee_name": pos.employee.get_full_name() if pos.employee else "Не назначено",
                "position": pos.name,
                "total_tasks": pos.task_count,
                "completed_tasks": pos.completed_count,
                "completion_rate": round((pos.completed_count / pos.task_count * 100), 2) if pos.task_count > 0 else 0,
            }
            for pos in top_assignees
        ]

        stats = {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "overdue": overdue,
            "completed_this_month": completed_this_month,
            "completion_rate": (
                round((by_status.get(Task.TaskStatus.COMPLETED, 0) / total * 100), 2) if total > 0 else 0
            ),
            "top_assignees": assignee_stats,
            "department_distribution": self._get_department_distribution(queryset),
        }

        return Response(stats)

    def _get_department_distribution(self, queryset):
        """
        Распределение задач по отделам
        """

        distribution = (
            queryset.filter(owner__department__isnull=False)
            .values("owner__department__id", "owner__department__name")
            .annotate(count=Count("id"), completed=Count("id", filter=Q(status=Task.TaskStatus.COMPLETED)))
            .order_by("-count")
        )

        return [
            {
                "department_id": item["owner__department__id"],
                "department_name": item["owner__department__name"],
                "total_tasks": item["count"],
                "completed_tasks": item["completed"],
                "completion_rate": round((item["completed"] / item["count"] * 100), 2) if item["count"] > 0 else 0,
            }
            for item in distribution
        ]


class CommentViewSet(viewsets.ModelViewSet):
    """
    ViewSet для управления комментариями.
    РЕДАКТИРОВАНИЕ ЗАПРЕЩЕНО!
    """

    serializer_class = CommentSerializer
    permission_classes = [IsAuthenticated, CommentCRUDPermissions]

    def get_queryset(self):
        """Фильтрация комментариев по задаче"""
        task_id = self.kwargs.get("task_pk")
        return Comment.objects.filter(task_id=task_id).select_related("author").order_by("-created_at")

    def perform_create(self, serializer):
        """Создание комментария с указанием автора и задачи"""
        task_id = self.kwargs.get("task_pk")
        serializer.save(task_id=task_id, author=self.request.user)

    # ЗАПРЕЩАЕМ update и partial_update
    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Редактирование комментариев запрещено. Вы можете удалить и создать новый."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        return Response(
            {"detail": "Редактирование комментариев запрещено. Вы можете удалить и создать новый."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


# ========== СПЕЦИАЛЬНЫЕ ЭНДПОИНТЫ (ТРЕБОВАНИЯ) ==========


class BusyEmployeesView(APIView):
    """
    Эндпоинт 1: Занятые сотрудники
    Запрашивает из БД список сотрудников и их задачи,
    отсортированный по количеству активных задач.
    """

    permission_classes = [IsAuthenticated, CanViewBusyEmployees]

    def get(self, request):
        """
        Получение списка занятых сотрудников

        Параметры запроса:
        - department_id: ID отдела для фильтрации (опционально)
        - min_tasks: минимальное количество задач для включения в список (по умолчанию 1)
        - limit: ограничение количества результатов (опционально)
        """
        # Получаем параметры запроса
        department_id = request.query_params.get("department_id")
        min_tasks = int(request.query_params.get("min_tasks", 1))
        limit = request.query_params.get("limit")

        # Получаем статистику через сервис
        stats = TaskStatisticsService.get_busy_employees_statistics(
            department_id=department_id, min_tasks=min_tasks, limit=int(limit) if limit else None
        )

        if not stats["employees"]:
            return Response({"count": 0, "statistics": stats, "employees": []})

        # Формируем данные для сериализации
        employees_data = []
        for emp_data in stats["employees"]:
            employee = emp_data["employee"]
            position = emp_data["position"]
            statistics = emp_data["statistics"]

            employee_dict = {
                "employee_id": employee.id,
                "full_name": employee.get_full_name(),
                "email": employee.email,
                "position_name": position.name,
                "department_name": position.department.name if position.department else "Без отдела",
                "active_tasks_count": statistics["active_tasks"],
                "overdue_tasks_count": statistics["overdue_tasks"],
                "total_tasks_count": statistics["total_tasks"],
            }
            employees_data.append(employee_dict)

        # Сериализуем данные
        serializer = BusyEmployeeSerializer(employees_data, many=True)

        response_data = {
            "count": stats["total_employees"],
            "statistics": {
                "total_active_tasks": stats["total_active_tasks"],
                "total_overdue_tasks": stats["total_overdue_tasks"],
                "average_tasks_per_employee": stats["average_tasks_per_employee"],
            },
            "employees": serializer.data,
        }

        return Response(response_data)


class ImportantTasksView(APIView):
    """
    Эндпоинт 2.1: Важные задачи (БЛОКИРУЮЩИЕ ПОДЗАДАЧИ)
    Запрашивает из БД ПОДЗАДАЧИ, которые не взяты в работу,
    но от которых зависят РОДИТЕЛЬСКИЕ задачи, взятые в работу.
    """

    permission_classes = [IsAuthenticated, CanViewImportantTasks]

    def get(self, request):
        """
        Получение списка блокирующих ПОДЗАДАЧ

        Параметры запроса:
        - department_id: фильтрация по отделу
        - min_blocking_level: минимальный уровень блокировки (0-100)
        - limit: ограничение количества результатов
        """
        department_id = request.query_params.get("department_id")
        min_blocking_level = int(request.query_params.get("min_blocking_level", 0))
        limit = request.query_params.get("limit")

        # Получаем БЛОКИРУЮЩИЕ ПОДЗАДАЧИ через сервис
        blocking_subtasks = TaskDependencyService.get_blocking_tasks(
            department_id=department_id, min_blocking_level=min_blocking_level
        )

        # Ограничение количества
        if limit:
            blocking_subtasks = blocking_subtasks[: int(limit)]

        result = []

        for subtask in blocking_subtasks:
            # Получаем подходящих сотрудников для ЭТОЙ ПОДЗАДАЧИ
            suitable_employees = TaskDependencyService.find_suitable_employees_for_task(subtask, department_id)

            # Формируем список ФИО сотрудников
            employee_names = [emp["position"].employee.get_full_name() for emp in suitable_employees]

            # Информация о родительской задаче
            parent_info = None
            if subtask.parent:
                parent_info = {
                    "id": subtask.parent.id,
                    "title": subtask.parent.title,
                    "status": subtask.parent.status,
                    "status_display": subtask.parent.get_status_display(),
                }

            result.append(
                {
                    "blocking_subtask": {
                        "id": subtask.id,
                        "title": subtask.title,
                        "description": subtask.description,
                        "status": subtask.status,
                        "status_display": subtask.get_status_display(),
                        "priority": subtask.priority,
                        "priority_display": subtask.get_priority_display(),
                        "blocking_level": TaskDependencyService._calculate_blocking_level(subtask),
                    },
                    "parent_task": parent_info,  # ← Добавляем информацию о родительской задаче
                    "deadline": subtask.deadline,
                    "suitable_employees": employee_names,
                }
            )

        # Сортировка по уровню блокировки (по убыванию) и сроку (по возрастанию)
        result.sort(
            key=lambda x: (
                -x["blocking_subtask"]["blocking_level"],
                x["deadline"] if x["deadline"] else timezone.now() + timedelta(days=365),
            )
        )

        # Статистика
        total_tasks = len(result)
        high_blocking_tasks = len([t for t in result if t["blocking_subtask"]["blocking_level"] > 50])
        critical_blocking_tasks = len([t for t in result if t["blocking_subtask"]["blocking_level"] > 75])

        response_data = {
            "count": total_tasks,
            "statistics": {
                "total_blocking_tasks": total_tasks,
                "high_blocking_tasks": high_blocking_tasks,
                "critical_blocking_tasks": critical_blocking_tasks,
            },
            "tasks": result,
        }

        return Response(response_data)


class EmployeeSuggestionView(APIView):
    """
    Эндпоинт 2.2: Поиск сотрудников для важных задач
    Реализует поиск по сотрудникам, которые могут взять такие задачи.
    Алгоритм: наименее загруженный сотрудник или сотрудник, выполняющий
    родительскую задачу, если ему назначено максимум на 2 задачи больше.
    """

    permission_classes = [IsAuthenticated, CanViewEmployeeSuggestions]

    def get(self, request, task_id):
        """
        Поиск сотрудников, которые могут взять блокирующую задачу
        """
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return Response({"detail": "Задача не найдена"}, status=status.HTTP_404_NOT_FOUND)

        # Проверяем, что задача является блокирующей
        if task.status not in [Task.TaskStatus.CREATED, Task.TaskStatus.ASSIGNED]:
            return Response({"detail": "Задача уже в работе или завершена"}, status=status.HTTP_400_BAD_REQUEST)

        # Получаем подходящих сотрудников
        department_id = request.query_params.get("department_id")
        suitable_employees = TaskDependencyService.find_suitable_employees_for_task(task, department_id)

        if not suitable_employees:
            return Response({"detail": "Нет подходящих сотрудников для этой задачи"}, status=status.HTTP_404_NOT_FOUND)

        # Формируем информацию о сотрудниках
        employees_data = []

        for emp in suitable_employees:
            position = emp["position"]

            employees_data.append(
                {
                    "employee_id": position.employee.id,
                    "full_name": position.employee.get_full_name(),
                    "position": position.name,
                    "active_tasks": emp["active_tasks"],
                    "overdue_tasks": emp["overdue_tasks"],
                    "reason": emp["reason"],
                    "department": position.department.name if position.department else None,
                    "email": position.employee.email,
                }
            )

        # Сортируем по количеству активных задач
        employees_data.sort(key=lambda x: x["active_tasks"])

        # Информация о задаче
        task_info = {
            "id": task.id,
            "title": task.title,
            "priority": task.priority,
            "priority_display": task.get_priority_display(),
            "deadline": task.deadline,
            "owner": task.owner.employee.get_full_name() if task.owner and task.owner.employee else None,
            "department": task.owner.department.name if task.owner and task.owner.department else None,
            "blocking_level": TaskDependencyService._calculate_blocking_level(task),
        }

        response_data = {
            "task": task_info,
            "suggested_employees": employees_data,
            "search_criteria": {
                "algorithm": "least_busy_or_parent_assignee_within_2_tasks",
                "department_filter": department_id,
            },
        }

        return Response(response_data)


class BlockingTasksWithAssignmentsView(APIView):
    """
    Эндпоинт 3: Полный анализ блокирующих задач с предложениями
    Возвращает список объектов в формате:
    {Важная задача, Срок, [ФИО сотрудника]}
    """

    permission_classes = [IsAuthenticated, CanViewImportantTasks]

    def get(self, request):
        """
        Полный анализ всех блокирующих задач с предложениями по назначению
        """
        # Используем уже готовый ImportantTasksView для получения данных
        important_view = ImportantTasksView()
        important_view.request = request
        important_view.format_kwarg = None

        # Получаем данные от ImportantTasksView
        response = important_view.get(request)

        if response.status_code != 200:
            return response

        data = response.data

        # Форматируем данные в требуемый формат
        formatted_tasks = []

        for task_item in data.get("tasks", []):
            # Берем данные из ответа ImportantTasksView
            task_data = task_item.get("blocking_subtask", {})

            # Форматируем название задачи
            task_title = task_data.get("title", "Без названия")
            if len(task_title) > 100:
                task_title = task_title[:97] + "..."

            # Добавляем информацию о родительской задаче
            parent_info = ""
            if task_item.get("parent_task"):
                parent_title = task_item["parent_task"].get("title", "")
                if parent_title:
                    if len(parent_title) > 50:
                        parent_title = parent_title[:47] + "..."
                    parent_info = f" (Блокирует: {parent_title})"
                    task_title = f"{task_title}{parent_info}"

            # Форматируем срок
            deadline_str = "Не установлен"
            deadline = task_item.get("deadline")
            if deadline:
                try:
                    # Пробуем разные форматы даты
                    if isinstance(deadline, str):
                        deadline_dt = timezone.datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                    else:
                        deadline_dt = deadline
                    deadline_str = deadline_dt.strftime("%d.%m.%Y")
                except:  # noqa
                    deadline_str = str(deadline)

            # Получаем список ФИО сотрудников
            employee_names = task_item.get("suitable_employees", [])

            formatted_tasks.append(
                {
                    "important_task": task_title,
                    "deadline": deadline_str,
                    "suitable_employees": employee_names,
                }
            )

        return Response(
            {
                "count": len(formatted_tasks),
                "tasks": formatted_tasks,
            }
        )


# ========== ДОПОЛНИТЕЛЬНЫЕ ЭНДПОИНТЫ ==========


class DepartmentStatisticsView(APIView):
    """
    Статистика по отделам
    """

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        """
        Получение статистики по отделам
        """
        department_id = request.query_params.get("department_id")
        period_days = int(request.query_params.get("period", 30))

        stats = TaskStatisticsService.get_department_statistics(department_id=department_id, period_days=period_days)

        return Response(stats)
