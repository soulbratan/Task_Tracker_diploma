from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tasks"
    verbose_name = "Управление задачами"

    def ready(self):
        """
        Инициализация приложения
        """
        # Регистрируем сигналы
        try:
            import tasks.signals  # noqa
        except ImportError:
            pass
