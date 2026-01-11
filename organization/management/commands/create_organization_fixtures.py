from django.core.management.base import BaseCommand
from django.db.models import Count

from organization.models import Department, Position


class Command(BaseCommand):
    help = "Создание тестовых данных для организации"

    def handle(self, *args, **options):
        self.stdout.write("Создание тестовой организационной структуры...")

        # Создаем отделы
        main_office, _ = Department.objects.get_or_create(
            name="Главный офис", defaults={"description": "Центральное управление компании"}
        )

        it_department, _ = Department.objects.get_or_create(
            name="IT отдел", parent=main_office, defaults={"description": "Разработка и поддержка IT систем"}
        )

        hr_department, _ = Department.objects.get_or_create(
            name="HR отдел", parent=main_office, defaults={"description": "Управление персоналом"}
        )

        sales_department, _ = Department.objects.get_or_create(
            name="Отдел продаж", parent=main_office, defaults={"description": "Продажи и работа с клиентами"}
        )

        # Подотделы
        frontend_team, _ = Department.objects.get_or_create(
            name="Frontend команда", parent=it_department, defaults={"description": "Разработка интерфейсов"}
        )

        backend_team, _ = Department.objects.get_or_create(
            name="Backend команда", parent=it_department, defaults={"description": "Разработка серверной части"}
        )

        self.stdout.write(self.style.SUCCESS(f"Создано {Department.objects.count()} отделов"))

        # Создаем дефолтные должности
        default_positions = [
            # Главный офис
            ("Генеральный директор", Position.PositionLevel.ADMIN, main_office),
            ("Финансовый директор", Position.PositionLevel.MANAGER, main_office),
            ("Офис-менеджер", Position.PositionLevel.EMPLOYEE, main_office),
            # IT отдел
            ("IT директор", Position.PositionLevel.MANAGER, it_department),
            ("Системный администратор", Position.PositionLevel.MANAGER, it_department),
            # Frontend команда
            ("Senior Frontend Developer", Position.PositionLevel.EMPLOYEE, frontend_team),
            ("Middle Frontend Developer", Position.PositionLevel.EMPLOYEE, frontend_team),
            ("Junior Frontend Developer", Position.PositionLevel.EMPLOYEE, frontend_team),
            # Backend команда
            ("Team Lead Backend", Position.PositionLevel.MANAGER, backend_team),
            ("Senior Backend Developer", Position.PositionLevel.EMPLOYEE, backend_team),
            ("Middle Backend Developer", Position.PositionLevel.EMPLOYEE, backend_team),
            # HR отдел
            ("HR менеджер", Position.PositionLevel.MANAGER, hr_department),
            ("Рекрутер", Position.PositionLevel.EMPLOYEE, hr_department),
            # Отдел продаж
            ("Руководитель отдела продаж", Position.PositionLevel.MANAGER, sales_department),
            ("Менеджер по продажам", Position.PositionLevel.EMPLOYEE, sales_department),
        ]

        created_count = 0
        for name, level, department in default_positions:
            position, created = Position.objects.get_or_create(
                name=name, level=level, department=department, defaults={"is_active": True}
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Создано {created_count} должностей"))
        self.stdout.write(self.style.SUCCESS("Тестовые данные созданы успешно!"))

        # Выводим статистику
        self.stdout.write("\n📊 Статистика:")
        self.stdout.write(f"  Всего отделов: {Department.objects.count()}")
        self.stdout.write(f"  Всего должностей: {Position.objects.count()}")

        # Исправленная строка: используем Count из django.db.models
        level_stats = Position.objects.values("level").annotate(count=Count("id"))
        for stat in level_stats:
            level_display = dict(Position.PositionLevel.choices).get(stat["level"], stat["level"])
            self.stdout.write(f'  {level_display}: {stat["count"]}')
