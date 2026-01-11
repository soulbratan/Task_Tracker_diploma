from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver


@receiver(pre_save, sender="organization.Position")
def handle_position_pre_save(sender, instance, **kwargs):
    """
    Обработка перед сохранением: сохраняем старые данные.
    """
    if instance.pk:
        try:
            Position = sender  # sender уже является моделью Position
            old_position = Position.objects.get(pk=instance.pk)
            instance._old_employee = old_position.employee
            instance._old_level = old_position.level
            instance._old_department = old_position.department
        except Position.DoesNotExist:
            instance._old_employee = None
            instance._old_level = None
            instance._old_department = None
    else:
        instance._old_employee = None
        instance._old_level = None
        instance._old_department = None


@receiver(post_save, sender="organization.Position")
def handle_position_post_save(sender, instance, created, **kwargs):
    """
    Основная логика обновления пользователя после сохранения должности.
    """
    with transaction.atomic():
        User = instance.employee._meta.model if instance.employee else None  # noqa

        # 1. Обработка СТАРОГО сотрудника (если сменился или снят)
        old_employee = getattr(instance, "_old_employee", None)

        if old_employee and old_employee != instance.employee:
            # Сбрасываем поля у старого сотрудника
            old_employee.department = None
            old_employee.position = None

            # Проверяем is_staff
            old_level = getattr(instance, "_old_level", None)
            if old_level == "admin":  # ← Используем строку вместо Position.PositionLevel.ADMIN
                # Проверяем другие должности ADMIN
                Position = sender  # Используем sender как модель
                has_other_admin = (
                    Position.objects.filter(employee=old_employee, level="admin", is_active=True)
                    .exclude(id=instance.pk)
                    .exists()
                )

                if not has_other_admin:
                    old_employee.is_staff = False

            old_employee.save(update_fields=["department", "position", "is_staff"])
            print(f"Сброшены данные у старого сотрудника {old_employee.email}")

        # 2. Обработка НОВОГО сотрудника
        if instance.employee and instance.is_active:
            Position = sender  # Ленивая загрузка

            # Обновляем поля пользователя
            if instance.department:
                instance.employee.department = instance.department.name
            else:
                instance.employee.department = None
            instance.employee.position = instance.name

            # Обновляем is_staff
            if instance.level == "admin":  # Строковое сравнение
                instance.employee.is_staff = True
            elif instance.employee.is_staff:
                # Проверяем, есть ли другие должности ADMIN
                has_other_admin = (
                    Position.objects.filter(employee=instance.employee, level="admin", is_active=True)
                    .exclude(id=instance.pk)
                    .exists()
                )

                if not has_other_admin:
                    instance.employee.is_staff = False

            instance.employee.save(update_fields=["department", "position", "is_staff"])
            print(f"Обновлен {instance.employee.email}")

        # 3. Обработка снятия сотрудника
        elif old_employee and not instance.employee:
            old_employee.department = None
            old_employee.position = None

            old_level = getattr(instance, "_old_level", None)
            if old_level == "admin":
                Position = sender
                has_other_admin = (
                    Position.objects.filter(employee=old_employee, level="admin", is_active=True)
                    .exclude(id=instance.pk)
                    .exists()
                )

                if not has_other_admin:
                    old_employee.is_staff = False

            old_employee.save(update_fields=["department", "position", "is_staff"])
            print(f"Снят сотрудник {old_employee.email} с должности")


@receiver(pre_delete, sender="organization.Position")
def handle_position_pre_delete(sender, instance, **kwargs):
    """
    Очистка данных пользователя при удалении должности.
    """
    if instance.employee:
        with transaction.atomic():
            employee = instance.employee
            Position = sender  # Ленивая загрузка

            # Сбрасываем поля
            employee.department = None
            employee.position = None

            # Проверяем is_staff
            if instance.level == "admin":
                has_other_admin = (
                    Position.objects.filter(employee=employee, level="admin", is_active=True)
                    .exclude(id=instance.pk)
                    .exists()
                )

                if not has_other_admin:
                    employee.is_staff = False

            employee.save(update_fields=["department", "position", "is_staff"])
            print(f"Удалена должность, сброшены данные у {employee.email}")


@receiver(pre_save, sender=settings.AUTH_USER_MODEL)
def prevent_manual_position_update(sender, instance, **kwargs):
    """
    ДОПОЛНИТЕЛЬНО: Защита от ручного обновления position/department.
    Эти поля должны обновляться только через назначение на должность.
    """
    if not instance.pk:
        return  # Новая запись

    try:
        User = sender
        old_user = User.objects.get(pk=instance.pk)

        # Если кто-то пытается вручную изменить position или department
        if old_user.position != instance.position or old_user.department != instance.department:
            print(f"ВНИМАНИЕ: Ручное изменение position/department у {instance.email}")

            from django.apps import apps

            Position = apps.get_model("organization", "Position")

            # Проверяем, есть ли активная должность у пользователя
            has_active_position = Position.objects.filter(employee=instance, is_active=True).exists()

            if has_active_position:
                # Восстанавливаем значения из активной должности
                active_position = Position.objects.filter(employee=instance, is_active=True).first()

                if active_position:
                    instance.position = active_position.name
                    instance.department = active_position.department.name if active_position.department else None
                    print("Восстановлено из активной должности")
            else:
                # Если нет активной должности, сбрасываем поля
                instance.position = None
                instance.department = None
                print("Сброшено, так как нет активной должности")

    except User.DoesNotExist:
        pass
