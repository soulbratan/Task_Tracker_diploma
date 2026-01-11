from datetime import timedelta

from django.db import models
from django.db.models import Count, Q
from django.utils import timezone

from organization.models import Department, Position

from .models import Task


class TaskDependencyService:
    """Сервис для работы с зависимостями задач"""

    @staticmethod
    def get_blocking_tasks(department_id=None, min_blocking_level=0):
        """
        Получение ПОДЗАДАЧ, которые не взяты в работу,
        но от которых зависят РОДИТЕЛЬСКИЕ задачи, взятые в работу
        """
        # ПОДЗАДАЧИ, которые не в работе (статус: Создана или Назначена)
        not_in_progress_statuses = [Task.TaskStatus.CREATED, Task.TaskStatus.ASSIGNED]

        # Ищем ПОДЗАДАЧИ, которые блокируют родительские задачи в работе
        blocking_tasks = Task.objects.filter(
            status__in=not_in_progress_statuses,  # ПОДЗАДАЧА не в работе
            parent__status=Task.TaskStatus.IN_PROGRESS,  # РОДИТЕЛЬСКАЯ задача В работе
            parent__isnull=False,  # есть родительская задача
        ).distinct()

        # Фильтрация по отделу
        if department_id:
            blocking_tasks = blocking_tasks.filter(
                Q(owner__department_id=department_id) | Q(parent__owner__department_id=department_id)
            )

        # Оптимизация запросов
        blocking_tasks = blocking_tasks.select_related(
            "assignee",
            "assignee__employee",
            "assignee__department",
            "owner",
            "owner__employee",
            "owner__department",
            "parent",
            "parent__owner",
            "parent__owner__employee",
            "parent__owner__department",
            "created_by",
        ).prefetch_related("subtasks", "comments")

        # Фильтрация по минимальному уровню блокировки
        if min_blocking_level > 0:
            blocking_tasks = [
                task
                for task in blocking_tasks
                if TaskDependencyService._calculate_blocking_level(task) >= min_blocking_level
            ]

        return blocking_tasks

    @staticmethod
    def find_suitable_employees_for_task(task, department_id=None):
        """
        Поиск подходящих сотрудников для задачи

        Алгоритм:
        1. Найти наименее загруженных сотрудников в отделе
        2. Если есть сотрудник, выполняющий родительскую задачу,
           и у него не более чем на 2 задачи больше, чем у наименее загруженного
        3. Возвращаем список подходящих сотрудников
        """
        # Определяем отдел для поиска сотрудников
        target_department_id = department_id or (task.owner.department_id if task.owner else None)

        if not target_department_id:
            return []

        # Получаем активных сотрудников отдела с подсчетом их задач
        employees_positions = (
            Position.objects.filter(
                department_id=target_department_id, is_active=True, employee__isnull=False, employee__is_active=True
            )
            .annotate(
                active_tasks_count=Count(
                    "assigned_tasks",
                    filter=Q(
                        assigned_tasks__status__in=[
                            Task.TaskStatus.ASSIGNED,
                            Task.TaskStatus.IN_PROGRESS,
                            Task.TaskStatus.ON_HOLD,
                        ]
                    ),
                ),
                total_tasks_count=Count("assigned_tasks"),
                overdue_tasks_count=Count(
                    "assigned_tasks",
                    filter=Q(
                        assigned_tasks__deadline__lt=timezone.now(),
                        assigned_tasks__status__in=[Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS],
                    ),
                ),
            )
            .filter(
                # Фильтруем только сотрудников, которые могут взять задачу
                Q(level__in=["employee", "manager"])  # Исключаем администраторов
            )
            .order_by(
                "active_tasks_count",  # Сначала наименее загруженные
                "overdue_tasks_count",  # Затем по количеству просроченных
                "employee__last_name",  # Для стабильной сортировки
            )
            .select_related("employee", "department")
        )

        if not employees_positions:
            return []

        # Находим минимальную нагрузку
        min_load = employees_positions.first().active_tasks_count

        # Определяем порог для "немного больше нагрузки"
        threshold = min_load + 2

        # 1. Наименее загруженные сотрудники
        least_busy_employees = [pos for pos in employees_positions if pos.active_tasks_count == min_load]

        # 2. Сотрудник, выполняющий родительскую задачу (если есть)
        parent_task_employee = None
        if task.parent and task.parent.assignee and task.parent.assignee.employee:
            parent_employee_position = task.parent.assignee

            # Проверяем, входит ли этот сотрудник в наш список
            for pos in employees_positions:
                if pos.id == parent_employee_position.id:
                    parent_task_employee = pos
                    break

        suitable_employees = []

        # Добавляем наименее загруженных сотрудников
        for position in least_busy_employees:
            suitable_employees.append(
                {
                    "position": position,
                    "reason": "least_busy",
                    "active_tasks": position.active_tasks_count,
                    "overdue_tasks": position.overdue_tasks_count,
                    "total_tasks": position.total_tasks_count,
                }
            )

        # Проверяем сотрудника с родительской задачей
        if parent_task_employee:
            # Проверяем условие "не более чем на 2 задачи больше"
            if parent_task_employee.active_tasks_count <= threshold:
                # Проверяем, что его еще нет в списке
                if not any(emp["position"].id == parent_task_employee.id for emp in suitable_employees):
                    suitable_employees.append(
                        {
                            "position": parent_task_employee,
                            "reason": "parent_task_assignee",
                            "active_tasks": parent_task_employee.active_tasks_count,
                            "overdue_tasks": parent_task_employee.overdue_tasks_count,
                            "total_tasks": parent_task_employee.total_tasks_count,
                        }
                    )

        return suitable_employees

    @staticmethod
    def analyze_task_dependencies(department_id=None):
        """
        Анализ всех блокирующих ПОДЗАДАЧ и поиск подходящих сотрудников
        """
        blocking_subtasks = TaskDependencyService.get_blocking_tasks(department_id)

        result = []

        for subtask in blocking_subtasks:
            # Получаем информацию о подзадаче
            subtask_info = {
                "subtask": subtask,
                "blocking_level": TaskDependencyService._calculate_blocking_level(subtask),
            }

            # Информация о родительской задаче
            parent_info = None
            if subtask.parent:
                parent_info = {
                    "id": subtask.parent.id,
                    "title": subtask.parent.title,
                    "status": subtask.parent.status,
                    "status_display": subtask.parent.get_status_display(),
                    "priority": subtask.parent.priority,
                    "priority_display": subtask.parent.get_priority_display(),
                }

            # Ищем подходящих сотрудников для ПОДЗАДАЧИ
            suitable_employees = TaskDependencyService.find_suitable_employees_for_task(subtask, department_id)

            # Формируем список информации о сотрудниках
            employee_info = []
            for emp in suitable_employees:
                position = emp["position"]
                employee_info.append(
                    {
                        "id": position.employee.id,
                        "full_name": position.employee.get_full_name(),
                        "position": position.name,
                        "level": position.level,
                        "active_tasks": emp["active_tasks"],
                        "overdue_tasks": emp["overdue_tasks"],
                        "total_tasks": emp["total_tasks"],
                        "reason": emp["reason"],
                    }
                )

            result.append(
                {
                    "blocking_subtask": {
                        "id": subtask.id,
                        "title": subtask.title,
                        "status": subtask.status,
                        "status_display": subtask.get_status_display(),
                        "priority": subtask.priority,
                        "priority_display": subtask.get_priority_display(),
                        "blocking_level": subtask_info["blocking_level"],
                        "description": subtask.description,
                    },
                    "parent_task": parent_info,
                    "deadline": subtask.deadline,
                    "suitable_employees": employee_info,
                    "department": (
                        subtask.owner.department.name if subtask.owner and subtask.owner.department else None
                    ),
                    "department_id": subtask.owner.department_id if subtask.owner else None,
                    "owner": (
                        subtask.owner.employee.get_full_name() if subtask.owner and subtask.owner.employee else None
                    ),
                    "owner_id": subtask.owner.employee_id if subtask.owner else None,
                }
            )

        # Сортируем по уровню блокировки, приоритету и сроку
        result.sort(
            key=lambda x: (
                -x["blocking_subtask"]["blocking_level"],
                -Task.TaskPriorityLevels.get_priority_value(x["blocking_subtask"]["priority"]),
                x["deadline"] if x["deadline"] else timezone.now() + timedelta(days=365),
            )
        )

        return result

    @staticmethod
    def _calculate_blocking_level(task):
        """
        Расчет уровня блокировки ПОДЗАДАЧИ.
        Теперь считаем, насколько подзадача критична для родительской задачи.
        """
        # У подзадачи может не быть своих подзадач, так что логика меняется

        # Основные факторы:
        # 1. Приоритет подзадачи
        # 2. Приоритет родительской задачи
        # 3. Сроки выполнения
        # 4. Статус подзадачи

        # Базовый уровень блокировки
        blocking_level = 0

        # Фактор 1: Приоритет подзадачи
        priority_multiplier = {
            "low": 0.5,
            "medium": 1.0,
            "high": 1.5,
            "critical": 2.0,
        }.get(task.priority, 1.0)

        # Фактор 2: Приоритет родительской задачи
        if task.parent:
            parent_priority_multiplier = {
                "low": 1.0,
                "medium": 1.2,
                "high": 1.5,
                "critical": 2.0,
            }.get(task.parent.priority, 1.0)
        else:
            parent_priority_multiplier = 1.0

        # Фактор 3: Время до дедлайна
        time_factor = 1.0
        if task.deadline:
            time_until_deadline = task.deadline - timezone.now()
            if time_until_deadline.total_seconds() > 0:
                # Чем меньше времени осталось, тем выше блокировка
                days_until_deadline = time_until_deadline.days
                if days_until_deadline <= 1:
                    time_factor = 3.0  # Меньше дня - критично
                elif days_until_deadline <= 3:
                    time_factor = 2.0  # Меньше 3 дней - высокий приоритет
                elif days_until_deadline <= 7:
                    time_factor = 1.5  # Меньше недели - повышенный
                elif days_until_deadline <= 14:
                    time_factor = 1.2  # Меньше 2 недель - немного повышенный

        # Фактор 4: Статус
        status_factor = {
            Task.TaskStatus.CREATED: 1.0,  # Создана - нормальный приоритет
            Task.TaskStatus.ASSIGNED: 0.8,  # Назначена - уже лучше
        }.get(task.status, 1.0)

        # Рассчитываем итоговый уровень блокировки
        blocking_level = 50 * priority_multiplier * parent_priority_multiplier * time_factor * status_factor

        # Ограничиваем 0-100
        return min(max(blocking_level, 0), 100)


class TaskStatisticsService:
    """Сервис для статистики по задачам"""

    @staticmethod
    def get_busy_employees_statistics(department_id=None, min_tasks=1, limit=None):
        """
        Получение статистики по занятым сотрудникам
        """
        # Базовый запрос для сотрудников с должностями
        employees_query = Position.objects.filter(employee__isnull=False, is_active=True)

        # Фильтрация по отделу
        if department_id:
            employees_query = employees_query.filter(department_id=department_id)

        # Аннотируем статистику задач
        employees = (
            employees_query.annotate(
                total_tasks=Count("assigned_tasks", filter=Q(assigned_tasks__assignee_id=models.F("id"))),
                active_tasks=Count(
                    "assigned_tasks",
                    filter=Q(
                        assigned_tasks__assignee_id=models.F("id"),
                        assigned_tasks__status__in=[
                            Task.TaskStatus.ASSIGNED,
                            Task.TaskStatus.IN_PROGRESS,
                            Task.TaskStatus.ON_HOLD,
                        ],
                    ),
                ),
                overdue_tasks=Count(
                    "assigned_tasks",
                    filter=Q(
                        assigned_tasks__assignee_id=models.F("id"),
                        assigned_tasks__status__in=[Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS],
                        assigned_tasks__deadline__lt=timezone.now(),
                    ),
                ),
            )
            .filter(
                # Фильтруем по минимальному количеству задач
                active_tasks__gte=min_tasks
            )
            .order_by(
                # Сортируем по загрузке
                "-active_tasks",
                "-overdue_tasks",
                "-total_tasks",
            )
            .select_related("employee", "department")
        )

        # Ограничение количества
        if limit:
            employees = employees[:limit]

        # Формируем результат
        employees_data = []
        for position in employees:
            if position.employee:
                employees_data.append(
                    {
                        "position": position,
                        "employee": position.employee,
                        "statistics": {
                            "active_tasks": position.active_tasks,
                            "overdue_tasks": position.overdue_tasks,
                            "total_tasks": position.total_tasks,
                        },
                    }
                )

        # Общая статистика
        total_employees = len(employees_data)
        total_active_tasks = sum(emp["statistics"]["active_tasks"] for emp in employees_data)
        total_overdue_tasks = sum(emp["statistics"]["overdue_tasks"] for emp in employees_data)

        return {
            "total_employees": total_employees,
            "total_active_tasks": total_active_tasks,
            "total_overdue_tasks": total_overdue_tasks,
            "average_tasks_per_employee": round(total_active_tasks / total_employees, 2) if total_employees > 0 else 0,
            "employees": employees_data,
        }

    @staticmethod
    def get_department_statistics(department_id=None, period_days=30):
        """
        Получение статистики по отделам
        """
        departments_query = Department.objects.all()

        if department_id:
            departments_query = departments_query.filter(id=department_id)

        departments_stats = []

        for department in departments_query:
            # Сотрудники отдела
            positions = Position.objects.filter(department=department, is_active=True, employee__isnull=False)

            # Задачи отдела за период
            end_date = timezone.now()
            start_date = end_date - timedelta(days=period_days)

            department_tasks = Task.objects.filter(owner__department=department, created_at__gte=start_date)

            total_tasks = department_tasks.count()
            completed_tasks = department_tasks.filter(status=Task.TaskStatus.COMPLETED).count()

            overdue_tasks = department_tasks.filter(
                deadline__lt=end_date, status__in=[Task.TaskStatus.ASSIGNED, Task.TaskStatus.IN_PROGRESS]
            ).count()

            departments_stats.append(
                {
                    "department": {
                        "id": department.id,
                        "name": department.name,
                        "employees_count": positions.count(),
                    },
                    "tasks_statistics": {
                        "total_tasks": total_tasks,
                        "completed_tasks": completed_tasks,
                        "overdue_tasks": overdue_tasks,
                        "completion_rate": round(completed_tasks / total_tasks * 100, 2) if total_tasks > 0 else 0,
                    },
                }
            )

        return departments_stats


class TaskAssignmentOptimizer:
    """Оптимизатор назначения задач"""

    @staticmethod
    def find_best_assignee_for_task(task, candidates=None):
        """
        Поиск лучшего исполнителя для задачи
        """
        if not candidates:
            candidates = TaskDependencyService.find_suitable_employees_for_task(task)

        if not candidates:
            return None

        # Сортируем кандидатов по количеству активных задач
        candidates.sort(key=lambda x: x["active_tasks"])

        # Лучший кандидат (наименее загруженный)
        best_candidate = candidates[0]

        return {
            "position": best_candidate["position"],
            "employee": best_candidate["position"].employee,
            "reason": best_candidate["reason"],
            "active_tasks": best_candidate["active_tasks"],
            "overdue_tasks": best_candidate["overdue_tasks"],
        }
