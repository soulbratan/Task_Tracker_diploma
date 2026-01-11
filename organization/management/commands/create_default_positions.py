from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from organization.models import Department, Position


class Command(BaseCommand):
    help = "Создает дефолтные данные для организации"

    def handle(self, *args, **options):
        User = get_user_model()

        # Создаем корневой отдел если его нет
        root_department, created = Department.objects.get_or_create(
            name="Главный офис", defaults={"description": "Корневой отдел компании"}
        )

        if created:
            self.stdout.write(self.style.SUCCESS("Создан корневой отдел: Главный офис"))

        # Создаем дефолтную должность администратора
        admin_position, created = Position.objects.get_or_create(
            name="Администратор",
            level=Position.PositionLevel.ADMIN,
            department=root_department,
            defaults={"is_active": True},
        )

        if created:
            self.stdout.write(self.style.SUCCESS("Создана дефолтная должность: Администратор"))
        else:
            self.stdout.write(self.style.WARNING("!!!Должность Администратор уже существует!!!"))

        # Назначаем суперпользователя на должность администратора если он есть
        try:
            superuser = User.objects.filter(is_superuser=True).first()
            if superuser and not admin_position.employee:
                admin_position.employee = superuser
                admin_position.save()
                self.stdout.write(
                    self.style.SUCCESS(f"Назначен суперпользователь {superuser.email} на должность Администратор")
                )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка назначения суперпользователя: {e}"))
