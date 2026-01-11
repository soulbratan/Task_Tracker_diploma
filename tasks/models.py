from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Task(models.Model):
    """Модель задачи"""

    class TaskStatus(models.TextChoices):
        CREATED = "created", "Создана"
        ASSIGNED = "assigned", "Назначена"
        IN_PROGRESS = "in_progress", "Выполняется"
        COMPLETED = "completed", "Выполнена"
        CANCELLED = "cancelled", "Отменена"
        ON_HOLD = "on_hold", "На паузе"

    class TaskPriority(models.TextChoices):
        LOW = "low", "Низкий"
        MEDIUM = "medium", "Средний"
        HIGH = "high", "Высокий"
        CRITICAL = "critical", "Критический"

    # Константы для приоритетов
    class PriorityLevels:
        @staticmethod
        def get_priority_value(priority):
            priority_values = {
                "low": 1,
                "medium": 2,
                "high": 3,
                "critical": 4,
            }
            return priority_values.get(priority, 1)

    title = models.CharField(max_length=255, verbose_name="Название задачи")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")

    # Иерархия задач
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="subtasks",
        null=True,
        blank=True,
        verbose_name="Родительская задача",
    )

    # Исполнитель и владелец
    assignee = models.ForeignKey(
        "organization.Position",
        on_delete=models.SET_NULL,
        related_name="assigned_tasks",
        null=True,
        blank=True,
        verbose_name="Исполнитель",
    )

    owner = models.ForeignKey(
        "organization.Position",
        on_delete=models.SET_NULL,
        related_name="owned_tasks",
        null=True,
        verbose_name="Владелец задачи",
    )

    # Сроки
    deadline = models.DateTimeField(null=True, blank=True, verbose_name="Срок выполнения")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата выполнения")

    # Статус и приоритет
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.CREATED, verbose_name="Статус"
    )

    priority = models.CharField(
        max_length=20, choices=TaskPriority.choices, default=TaskPriority.MEDIUM, verbose_name="Приоритет"
    )

    # Мета-данные
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
        verbose_name="Создатель",
    )

    class Meta:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["priority"]),
            models.Index(fields=["deadline"]),
            models.Index(fields=["assignee", "status"]),
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["parent"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def clean(self):
        """Валидация задачи"""
        errors = {}

        # 1. Срок не раньше даты создания
        if self.deadline and self.deadline < timezone.now():
            errors["deadline"] = "Срок выполнения не может быть в прошлом"

        # 2. Проверка циклических ссылок в иерархии
        if self.parent:
            if self.parent == self:
                errors["parent"] = "Задача не может быть родителем самой себе"
            else:
                # Проверяем всю цепочку родителей на циклы
                parent = self.parent
                while parent:
                    if parent == self:
                        errors["parent"] = "Обнаружена циклическая ссылка в иерархии задач"
                        break
                    parent = parent.parent

        # 3. Проверка глубины вложенности (не более 3 уровней)
        if self.get_depth() > 3:
            errors["parent"] = "Максимальная глубина вложенности задач - 3 уровня"

        # 4. Валидация назначения исполнителя
        if self.assignee and self.owner:
            # Проверка: задача назначается либо сотруднику своего отдела,
            # либо руководителю нижестоящего отдела
            if not self._is_valid_assignment():
                errors["assignee"] = (
                    "Задача может быть назначена только сотруднику своего отдела "
                    "или руководителю нижестоящего отдела"
                )

        # 5. Автоматическая установка статуса "Назначена" при наличии исполнителя
        if self.assignee and self.status == self.TaskStatus.CREATED:
            self.status = self.TaskStatus.ASSIGNED

        if errors:
            raise ValidationError(errors)

    def get_depth(self):
        """Получение уровня вложенности задачи"""
        depth = 0
        parent = self.parent
        while parent:
            depth += 1
            parent = parent.parent
        return depth

    def _is_valid_assignment(self):
        """Проверка валидности назначения исполнителя"""
        if not self.assignee or not self.owner:
            return True

        # Если исполнитель и владелец в одном отделе - разрешено
        if self.assignee.department == self.owner.department:
            return True

        # Если исполнитель - руководитель нижестоящего отдела
        if self.assignee.level == "manager":
            # Проверяем, является ли отдел исполнителя дочерним для отдела владельца

            def is_child_department(child, parent):
                """Рекурсивная проверка, является ли child дочерним для parent"""
                current = child
                while current:
                    if current == parent:
                        return True
                    current = current.parent
                return False

            if is_child_department(self.assignee.department, self.owner.department):
                return True

        return False

    def save(self, *args, **kwargs):
        """Переопределение save для валидации и автоматического управления статусом"""
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        """Проверка просроченности задачи"""
        if self.deadline and self.status not in [self.TaskStatus.COMPLETED, self.TaskStatus.CANCELLED]:
            return timezone.now() > self.deadline
        return False

    @property
    def progress(self):
        """Прогресс выполнения задачи (0-100%)"""
        if self.status == self.TaskStatus.COMPLETED:
            return 100
        elif self.status == self.TaskStatus.CANCELLED:
            return 0

        # Если есть подзадачи, считаем по их прогрессу
        subtasks = self.subtasks.all()
        if subtasks:
            completed = subtasks.filter(status=self.TaskStatus.COMPLETED).count()
            total = subtasks.count()
            return int((completed / total) * 100) if total > 0 else 0

        # Без подзадач - оцениваем по статусу
        status_progress = {
            self.TaskStatus.CREATED: 0,
            self.TaskStatus.ASSIGNED: 20,
            self.TaskStatus.IN_PROGRESS: 50,
            self.TaskStatus.ON_HOLD: 30,
        }
        return status_progress.get(self.status, 0)

    def get_dependent_tasks_in_progress(self):
        """Получение зависимых задач, которые находятся в работе"""
        return self.subtasks.filter(status=self.TaskStatus.IN_PROGRESS)

    def is_blocking_other_tasks(self):
        """Проверка, блокирует ли задача другие задачи"""
        if self.status in [self.TaskStatus.CREATED, self.TaskStatus.ASSIGNED]:
            return self.subtasks.filter(status=self.TaskStatus.IN_PROGRESS).exists()
        return False

    def get_blocking_severity(self):
        """Получение уровня серьезности блокировки"""
        if not self.is_blocking_other_tasks():
            return None

        in_progress_count = self.get_dependent_tasks_in_progress().count()
        total_dependents = self.subtasks.count()

        if total_dependents == 0:
            return 0

        severity = (in_progress_count / total_dependents) * 100

        # Учет приоритета
        priority_multipliers = {
            self.TaskPriority.LOW: 1,
            self.TaskPriority.MEDIUM: 1.5,
            self.TaskPriority.HIGH: 2,
            self.TaskPriority.CRITICAL: 3,
        }

        severity *= priority_multipliers.get(self.priority, 1)

        return min(severity, 100)


class Comment(models.Model):
    """Модель комментария к задаче"""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments", verbose_name="Задача")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments", verbose_name="Автор"
    )
    content = models.TextField(verbose_name="Текст комментария")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Комментарий"
        verbose_name_plural = "Комментарии"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Комментарий от {self.author.email} к задаче #{self.task.id}"
