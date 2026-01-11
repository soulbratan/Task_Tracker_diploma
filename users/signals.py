import logging

from django.apps import apps
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import User

logger = logging.getLogger(__name__)


@receiver(pre_delete, sender=User)
def handle_user_delete(sender, instance, **kwargs):
    """
    Обработка удаления пользователя.
    Освобождает все должности, на которые был назначен пользователь.
    """
    try:
        Position = apps.get_model("organization", "Position")

        # Получаем все должности пользователя
        positions = Position.objects.filter(employee=instance)

        if positions.exists():
            # Освобождаем должности (устанавливаем employee=None)
            positions.update(employee=None)

            # Логируем действие
            logger.info(f"Пользователь {instance.email} удален.")

    except Exception as e:
        logger.error(f"Ошибка при обработке удаления пользователя {instance.email}: {e}")
