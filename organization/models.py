from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction


class Department(models.Model):
    """
    Модель отдела компании.
    Поддерживает иерархическую структуру.
    """

    name = models.CharField(max_length=255, unique=True, verbose_name="Название отдела")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="children",
        null=True,
        blank=True,
        verbose_name="Родительский отдел",
    )
    description = models.TextField(blank=True, null=True, verbose_name="Описание отдела")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Отдел"
        verbose_name_plural = "Отделы"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        """Валидация отдела"""
        super().clean()

        # Проверка на циклические ссылки
        if self.parent:
            if self.parent == self:
                raise ValidationError("Отдел не может быть родителем самому себе")

            # Проверяем всю цепочку родителей
            parent = self.parent
            while parent:
                if parent == self:
                    raise ValidationError("Обнаружена циклическая ссылка в иерархии отделов")
                parent = parent.parent

    def get_full_path(self):
        """Возвращает полный путь отдела в иерархии"""
        path = []
        current = self
        while current:
            path.insert(0, current.name)
            current = current.parent
        return " → ".join(path)

    @property
    def level(self):
        """Уровень вложенности отдела"""
        level = 0
        current = self.parent
        while current:
            level += 1
            current = current.parent
        return level


class Position(models.Model):
    """
    Модель должности в отделе.
    """

    class PositionLevel(models.TextChoices):
        ADMIN = "admin", "Администратор"
        MANAGER = "manager", "Руководитель"
        EMPLOYEE = "employee", "Сотрудник"

    name = models.CharField(max_length=255, verbose_name="Название должности")
    level = models.CharField(max_length=20, choices=PositionLevel.choices, verbose_name="Уровень должности")
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="positions", verbose_name="Отдел"
    )
    employee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="positions",
        null=True,
        blank=True,
        verbose_name="Сотрудник",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    is_active = models.BooleanField(default=True, verbose_name="Активная должность")

    class Meta:
        verbose_name = "Должность"
        verbose_name_plural = "Должности"
        ordering = ["department", "level", "name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "department"], name="unique_position_name_in_department")
        ]
        indexes = [
            models.Index(fields=["is_active", "employee"]),
            models.Index(fields=["level", "is_active"]),
            models.Index(fields=["department", "is_active"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["employee"]),
        ]

    def __str__(self):
        department_name = self.department.name if self.department else "Без отдела"
        employee_name = self.employee.get_full_name() if self.employee else "Вакантно"
        return f"{self.name} ({department_name}) - {employee_name}"

    def get_level_display(self):
        """Получение читаемого названия уровня должности"""
        return dict(self.PositionLevel.choices).get(self.level, self.level)

    def clean(self):
        """Валидация должности (неатомарная часть)"""
        super().clean()

        errors = {}

        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs):
        """
        Атомарное сохранение с проверкой бизнес-правил.
        Использует блокировки для предотвращения race condition.
        """
        # Определяем, новая ли это запись или обновление
        is_new = self.pk is None

        if is_new:
            # Для новой записи - обычная валидация
            self.full_clean()
            return super().save(*args, **kwargs)

        # Для существующей записи - атомарная проверка
        try:
            with transaction.atomic():
                # Блокируем нужные строки для проверки
                self._lock_relevant_rows()

                # Выполняем атомарные проверки
                self._atomic_validation()

                # Если проверки прошли - сохраняем
                result = super().save(*args, **kwargs)

                # Обновляем пользователя (это тоже в транзакции)
                self._update_user_in_transaction()

                return result

        except ValidationError as e:
            raise e
        except Exception as e:
            # Логируем ошибку
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка при сохранении должности {self.id if self.id else 'new'}: {e}")
            raise

    def _lock_relevant_rows(self):
        """
        Блокировка строк для атомарных проверок.
        select_for_update() блокирует строки до конца транзакции.
        """

        # Блокируем строки для проверки "не более 2 руководителей в отделе"
        if self.level == self.PositionLevel.MANAGER and self.is_active:
            Position.objects.filter(
                department=self.department, level=self.PositionLevel.MANAGER, is_active=True
            ).select_for_update()

        # Блокируем строки для проверки "не более 4 администраторов"
        if self.level == self.PositionLevel.ADMIN and self.is_active:
            Position.objects.filter(level=self.PositionLevel.ADMIN, is_active=True).select_for_update()

        # Блокируем строки для проверки "один сотрудник - одна должность"
        if self.employee and self.is_active:
            Position.objects.filter(employee=self.employee, is_active=True).select_for_update()

    def _atomic_validation(self):
        """
        Атомарные проверки бизнес-правил.
        Выполняется после блокировки строк, поэтому безопасно.
        """
        errors = {}

        # 1. Проверка: не более 2 руководителей в отделе
        if self.level == self.PositionLevel.MANAGER and self.is_active:
            manager_count = (
                Position.objects.filter(department=self.department, level=self.PositionLevel.MANAGER, is_active=True)
                .exclude(id=self.id)
                .count()
            )

            if manager_count >= 2:
                errors["level"] = "В отделе не может быть больше 2 руководителей"

        # 2. Проверка: не более 4 администраторов всего
        if self.level == self.PositionLevel.ADMIN and self.is_active:
            admin_count = (
                Position.objects.filter(level=self.PositionLevel.ADMIN, is_active=True).exclude(id=self.id).count()
            )

            if admin_count >= 4:
                errors["level"] = "Всего не может быть больше 4 администраторов"

        # 3. Проверка: сотрудник может занимать только одну активную должность
        if self.employee and self.is_active:
            employee_positions = Position.objects.filter(employee=self.employee, is_active=True).exclude(id=self.id)

            if employee_positions.exists():
                errors["employee"] = "Сотрудник уже занимает другую должность"

        if errors:
            raise ValidationError(errors)

    def _update_user_in_transaction(self):
        """
        Обновление связанного пользователя в той же транзакции.
        """
        if self.employee and self.is_active:
            # Обновляем поля пользователя
            self.employee.department = self.department.name if self.department else None
            self.employee.position = self.name

            # Обновляем is_staff для администраторов
            if self.level == self.PositionLevel.ADMIN:
                self.employee.is_staff = True
            elif self.employee.is_staff:
                # Проверяем, есть ли у сотрудника другие должности ADMIN
                has_other_admin = (
                    Position.objects.filter(employee=self.employee, level=self.PositionLevel.ADMIN, is_active=True)
                    .exclude(id=self.id)
                    .exists()
                )

                if not has_other_admin:
                    self.employee.is_staff = False

            self.employee.save(update_fields=["department", "position", "is_staff"])

    def delete(self, *args, **kwargs):
        """
        Атомарное удаление должности.
        """
        with transaction.atomic():
            # Сохраняем информацию о сотруднике перед удалением
            old_employee = self.employee

            # Удаляем должность
            result = super().delete(*args, **kwargs)

            # Если был сотрудник - обновляем его данные
            if old_employee:
                # Сбрасываем поля у сотрудника
                old_employee.department = None
                old_employee.position = None

                # Проверяем is_staff если удаляется должность администратора
                if self.level == self.PositionLevel.ADMIN:
                    has_other_admin = Position.objects.filter(
                        employee=old_employee, level=self.PositionLevel.ADMIN, is_active=True
                    ).exists()

                    if not has_other_admin:
                        old_employee.is_staff = False

                old_employee.save(update_fields=["department", "position", "is_staff"])

            return result
