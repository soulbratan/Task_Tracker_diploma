from django.apps import AppConfig


class UsersConfig(AppConfig):
    name = "users"

    def ready(self):
        """Инициализация приложения"""

        import users.signals  # noqa
