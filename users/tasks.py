from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail

from tasks.models import Task

from .models import User


@shared_task
def send_welcome_email(user_id):
    """
    Отправка приветственного письма новому пользователю
    """
    try:
        user = User.objects.get(id=user_id)

        subject = "Добро пожаловать в нашу систему!"

        message = f"""
        Здравствуйте, {user.first_name} {user.last_name}!

        Добро пожаловать в систему управления задачами!

        Ваш аккаунт успешно создан.
        Email для входа: {user.email}


        С уважением,
        Команда поддержки
        """

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return f"Письмо успешно отправлено пользователю {user.email}"

    except User.DoesNotExist:
        return f"Пользователь с ID {user_id} не найден"
    except Exception as e:
        return f"Ошибка при отправке письма: {str(e)}"


@shared_task
def send_task_assignment_email(task_id, assignee_email):
    """
    Отправка письма о назначении на задачу
    """
    try:

        # Получаем задачу с связанными данными
        task = Task.objects.select_related("assignee", "assignee__employee", "owner", "owner__employee").get(
            id=task_id
        )

        subject = f"Вам назначена новая задача: {task.title}"

        # Форматируем дату дедлайна
        deadline_str = "Не установлен"
        if task.deadline:
            deadline_str = task.deadline.strftime("%d.%m.%Y %H:%M")

        # Простое текстовое сообщение
        message = f"""
        Здравствуйте!

        Вам назначена новая задача:

        📋 Название: {task.title}
        🏷️ Приоритет: {task.get_priority_display()}
        ⏰ Срок выполнения: {deadline_str}
        📝 Описание: {task.description[:200] if task.description else 'Нет описания'}

        👤 Владелец задачи: {task.owner.employee.get_full_name() if task.owner and task.owner.employee else 'Не указан'}

        Для просмотра и работы с задачей перейдите в систему управления задачами.

        С уважением,
        Система управления задачами
        """

        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[assignee_email],
            fail_silently=False,
        )

        return f"Письмо о назначении задачи отправлено на {assignee_email}"

    except Task.DoesNotExist:
        return f"Задача с ID {task_id} не найдена"
    except Exception as e:
        return f"Ошибка при отправке письма: {str(e)}"
