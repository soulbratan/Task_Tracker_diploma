from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from users.tasks import send_task_assignment_email

from .models import Comment, Task


@receiver(pre_save, sender=Task)
def update_completion_date(sender, instance, **kwargs):
    """
    Обновление даты выполнения при изменении статуса на COMPLETED
    """
    if instance.pk:
        try:
            old_instance = Task.objects.get(pk=instance.pk)
            if old_instance.status != Task.TaskStatus.COMPLETED and instance.status == Task.TaskStatus.COMPLETED:
                instance.completed_at = timezone.now()
            elif old_instance.status == Task.TaskStatus.COMPLETED and instance.status != Task.TaskStatus.COMPLETED:
                instance.completed_at = None
        except Task.DoesNotExist:
            pass


@receiver(pre_save, sender=Task)
def auto_update_task_status(sender, instance, **kwargs):
    """
    Автоматическое обновление статуса задачи при изменении исполнителя
    """
    if instance.pk:
        try:
            old_instance = Task.objects.get(pk=instance.pk)

            # Если назначили исполнителя
            if not old_instance.assignee and instance.assignee:
                if instance.status == Task.TaskStatus.CREATED:
                    instance.status = Task.TaskStatus.ASSIGNED

            # Если сняли исполнителя
            elif old_instance.assignee and not instance.assignee:
                if instance.status == Task.TaskStatus.ASSIGNED:
                    instance.status = Task.TaskStatus.CREATED

        except Task.DoesNotExist:
            pass
    else:
        # Новая задача: если есть исполнитель, статус "Назначена"
        if instance.assignee and instance.status == Task.TaskStatus.CREATED:
            instance.status = Task.TaskStatus.ASSIGNED


@receiver(post_save, sender=Task)
def update_parent_task_progress(sender, instance, created, **kwargs):
    """
    Обновление прогресса родительской задачи при изменении подзадач
    """
    if instance.parent:
        # Пересчитываем прогресс родительской задачи
        instance.parent.save()


@receiver(post_save, sender=Comment)
def update_task_updated_at(sender, instance, created, **kwargs):
    """
    Обновление поля updated_at задачи при добавлении комментария
    """
    if created:
        instance.task.updated_at = timezone.now()
        instance.task.save(update_fields=["updated_at"])


@receiver(pre_save, sender=Task)
def track_old_assignee(sender, instance, **kwargs):
    """
    Сохраняем старого исполнителя ДО сохранения
    """
    if instance.pk:
        try:
            # Получаем только нужное поле
            result = Task.objects.filter(pk=instance.pk).values("assignee_id").first()
            instance._old_assignee_id = result["assignee_id"] if result else None
        except Exception:
            instance._old_assignee_id = None
    else:
        instance._old_assignee_id = None


@receiver(post_save, sender=Task)
def send_task_assignment_notification(sender, instance, created, **kwargs):
    """
    Отправка уведомления при назначении задачи
    """
    # Проверяем, есть ли исполнитель с email
    if instance.assignee and instance.assignee.employee:
        if created:
            # Новая задача с исполнителем - отправляем уведомление
            send_task_assignment_email.delay(task_id=instance.id, assignee_email=instance.assignee.employee.email)
        else:
            # Существующая задача - проверяем, изменился ли исполнитель по ID
            old_assignee_id = getattr(instance, "_old_assignee_id", None)
            new_assignee_id = instance.assignee.id if instance.assignee else None

            if old_assignee_id != new_assignee_id:
                send_task_assignment_email.delay(task_id=instance.id, assignee_email=instance.assignee.employee.email)
