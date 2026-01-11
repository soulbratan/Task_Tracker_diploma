from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from organization.models import Department, Position
from tasks.models import Comment, Task

User = get_user_model()


class Command(BaseCommand):
    help = "Создает тестовые данные для приложений: users, organization, tasks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Очистить все существующие данные перед созданием новых",
        )

    def handle(self, *args, **options):
        clear_data = options["clear"]

        if clear_data:
            self.clear_existing_data()

        self.stdout.write(self.style.SUCCESS("Начинаем создание тестовых данных..."))

        # 1. Создаем пользователей
        users = self.create_users()

        # 2. Создаем отделы
        departments = self.create_departments()

        # 3. Создаем должности
        positions = self.create_positions(users, departments)

        # 4. Создаем задачи
        tasks = self.create_tasks(users, positions)

        # 5. Создаем комментарии
        self.create_comments(users, tasks)

        self.stdout.write(self.style.SUCCESS("Тестовые данные успешно созданы!"))
        self.print_summary(users, departments, positions, tasks)

    def clear_existing_data(self):
        """Очистка всех существующих данных"""
        self.stdout.write(self.style.WARNING("Очищаем существующие данные..."))

        # Порядок удаления важен из-за foreign key constraints
        deleted_counts = {}

        # 1. Комментарии (зависит от задач и пользователей)
        deleted_counts["comments"] = Comment.objects.all().delete()[0]

        # 2. Задачи (зависит от должностей и пользователей)
        deleted_counts["tasks"] = Task.objects.all().delete()[0]

        # 3. Должности (зависит от отделов и пользователей)
        deleted_counts["positions"] = Position.objects.all().delete()[0]

        # 4. Отделы
        deleted_counts["departments"] = Department.objects.all().delete()[0]

        # 5. Пользователи (кроме суперпользователя, если он есть)
        try:
            # Сохраняем суперпользователя если он существует
            superusers = User.objects.filter(is_superuser=True)
            superuser_emails = [user.email for user in superusers]

            deleted_counts["users"] = User.objects.filter(is_superuser=False).delete()[0]

            if superusers.exists():
                self.stdout.write(self.style.WARNING(f'Сохранены суперпользователи: {", ".join(superuser_emails)}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Ошибка при удалении пользователей: {e}"))
            deleted_counts["users"] = 0

        self.stdout.write(self.style.SUCCESS("Данные очищены:"))
        for model, count in deleted_counts.items():
            if count > 0:
                self.stdout.write(f"{model}: {count} записей удалено")

    def create_users(self):
        """Создание тестовых пользователей"""
        self.stdout.write("Создаем пользователей...")

        users_data = [
            {
                "email": "admin@company.com",
                "password": "Admin123!@#",
                "last_name": "Админов",
                "first_name": "Админ",
                "middle_name": "Админович",
                "phone": "+79991234567",
                "telegram_id": "@admin_user",
                "organization": "ТехноКорп",
                "is_staff": True,
                "is_superuser": True,
            },
            {
                "email": "ivanov@company.com",
                "password": "Ivanov123!@#",
                "last_name": "Иванов",
                "first_name": "Иван",
                "middle_name": "Иванович",
                "phone": "+79992345678",
                "telegram_id": "@ivanov_ii",
                "organization": "ТехноКорп",
                "is_staff": False,
                "is_superuser": False,
            },
            {
                "email": "petrov@company.com",
                "password": "Petrov123!@#",
                "last_name": "Петров",
                "first_name": "Петр",
                "middle_name": "Петрович",
                "phone": "+79993456789",
                "telegram_id": "@petrov_pp",
                "organization": "ТехноКорп",
                "is_staff": False,
                "is_superuser": False,
            },
            {
                "email": "sidorova@company.com",
                "password": "Sidorova123!@#",
                "last_name": "Сидорова",
                "first_name": "Анна",
                "middle_name": "Сергеевна",
                "phone": "+79994567890",
                "telegram_id": "@sidorova_as",
                "organization": "ТехноКорп",
                "is_staff": False,
                "is_superuser": False,
            },
            {
                "email": "smirnov@company.com",
                "password": "Smirnov123!@#",
                "last_name": "Смирнов",
                "first_name": "Алексей",
                "middle_name": "Владимирович",
                "phone": "+79995678901",
                "telegram_id": "@smirnov_av",
                "organization": "ТехноКорп",
                "is_staff": False,
                "is_superuser": False,
            },
        ]

        created_users = {}

        for user_data in users_data:
            email = user_data["email"]
            password = user_data.pop("password")

            # Удаляем email из user_data, т.к. передаем его отдельно
            user_data.pop("email")

            if User.objects.filter(email=email).exists():
                self.stdout.write(f"⚠️  Пользователь {email} уже существует")
                user = User.objects.get(email=email)
            else:
                user = User.objects.create_user(email=email, password=password, **user_data)
                self.stdout.write(self.style.SUCCESS(f"Создан: {user.email} ({user.get_full_name()})"))

            created_users[email] = user

        return created_users

    def create_departments(self):
        """Создание отделов"""
        self.stdout.write("Создаем отделы...")

        departments_data = [
            {"name": "Администрация", "parent": None, "description": "Высшее руководство"},
            {"name": "IT отдел", "parent": None, "description": "Отдел информационных технологий"},
            {"name": "Разработка", "parent": "IT отдел", "description": "Подразделение разработки ПО"},
            {"name": "Тестирование", "parent": "IT отдел", "description": "QA подразделение"},
            {"name": "Отдел маркетинга", "parent": None, "description": "Маркетинг и реклама"},
            {"name": "Отдел продаж", "parent": None, "description": "Отдел прямых продаж"},
        ]

        created_departments = {}

        # Сначала создаем корневые отделы
        for data in departments_data:
            if data["parent"] is None:
                dept = Department.objects.create(name=data["name"], description=data["description"])
                created_departments[data["name"]] = dept
                self.stdout.write(self.style.SUCCESS(f"Отдел: {dept.name}"))

        # Затем подотделы
        for data in departments_data:
            if data["parent"] and data["parent"] in created_departments:
                dept = Department.objects.create(
                    name=data["name"], parent=created_departments[data["parent"]], description=data["description"]
                )
                created_departments[data["name"]] = dept
                self.stdout.write(self.style.SUCCESS(f'Подотдел: {dept.name} → {data["parent"]}'))

        return created_departments

    def create_positions(self, users, departments):
        """Создание должностей"""
        self.stdout.write("💼 Создаем должности...")

        positions_data = [
            {
                "name": "Главный администратор",
                "level": "admin",
                "department": "Администрация",
                "employee": "admin@company.com",
            },
            {
                "name": "Руководитель IT",
                "level": "manager",
                "department": "IT отдел",
                "employee": "ivanov@company.com",
            },
            {
                "name": "Senior разработчик",
                "level": "employee",
                "department": "Разработка",
                "employee": "petrov@company.com",
            },
            {"name": "Младший разработчик", "level": "employee", "department": "Разработка", "employee": None},
            {"name": "Тестировщик", "level": "employee", "department": "Тестирование", "employee": None},
            {
                "name": "Ведущий маркетолог",
                "level": "manager",
                "department": "Отдел маркетинга",
                "employee": "sidorova@company.com",
            },
            {
                "name": "Менеджер по продажам",
                "level": "employee",
                "department": "Отдел продаж",
                "employee": "smirnov@company.com",
            },
            {"name": "Администратор БД", "level": "admin", "department": "IT отдел", "employee": None},
        ]

        created_positions = {}

        for data in positions_data:
            department = departments.get(data["department"])
            employee = users.get(data["employee"]) if data["employee"] else None

            if not department:
                self.stdout.write(self.style.ERROR(f'❌ Отдел не найден: {data["department"]}'))
                continue

            position = Position.objects.create(
                name=data["name"], level=data["level"], department=department, employee=employee, is_active=True
            )

            created_positions[data["name"]] = position

            if employee:
                self.stdout.write(self.style.SUCCESS(f"Должность: {position.name} → {employee.get_full_name()}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Вакансия: {position.name}"))

        return created_positions

    def create_tasks(self, users, positions):
        """Создание задач"""
        self.stdout.write("Создаем задачи...")

        now = timezone.now()

        tasks_data = [
            # Проект 1: Веб-сайт (с блокирующими задачами)
            {
                "title": "Запуск нового веб-сайта",
                "description": "Полный цикл разработки и запуска корпоративного сайта",
                "parent": None,
                "assignee": "Руководитель IT",
                "owner": "Руководитель IT",
                "deadline": now + timedelta(days=180),
                "status": "in_progress",
                "priority": "high",
                "created_by": "ivanov@company.com",
            },
            {
                "title": "Разработка фронтенда",
                "description": "Верстка и клиентская часть сайта",
                "parent": "Запуск нового веб-сайта",
                "assignee": None,
                "owner": "Руководитель IT",
                "deadline": now + timedelta(days=90),
                "status": "in_progress",
                "priority": "high",
                "created_by": "ivanov@company.com",
            },
            {
                "title": "Разработка бэкенда",
                "description": "Серверная часть и API",
                "parent": "Запуск нового веб-сайта",
                "assignee": None,  # ← БЛОКИРУЮЩАЯ (нет исполнителя)
                "owner": "Руководитель IT",
                "deadline": now + timedelta(days=100),
                "status": "created",
                "priority": "critical",
                "created_by": "ivanov@company.com",
            },
            {
                "title": "Верстка главной страницы",
                "description": "Адаптивная верстка главной страницы",
                "parent": "Разработка фронтенда",
                "assignee": None,
                "owner": "Руководитель IT",
                "deadline": now + timedelta(days=30),
                "status": "assigned",
                "priority": "medium",
                "created_by": "ivanov@company.com",
            },
            {
                "title": "Разработка API для продуктов",
                "description": "REST API для каталога продуктов",
                "parent": "Разработка бэкенда",
                "assignee": None,  # ← БЛОКИРУЮЩАЯ (нет исполнителя)
                "owner": "Руководитель IT",
                "deadline": now + timedelta(days=50),
                "status": "created",
                "priority": "critical",
                "created_by": "ivanov@company.com",
            },
            # Проект 2: Маркетинг
            {
                "title": "Кампания по продвижению продукта X",
                "description": "Маркетинговая кампания для нового продукта",
                "parent": None,
                "assignee": None,
                "owner": "Ведущий маркетолог",
                "deadline": now + timedelta(days=120),
                "status": "in_progress",
                "priority": "high",
                "created_by": "sidorova@company.com",
            },
            {
                "title": "Разработка рекламных материалов",
                "description": "Баннеры, презентации, буклеты",
                "parent": "Кампания по продвижению продукта X",
                "assignee": None,
                "owner": "Ведущий маркетолог",
                "deadline": now + timedelta(days=60),
                "status": "in_progress",
                "priority": "medium",
                "created_by": "sidorova@company.com",
            },
            {
                "title": "Анализ конкурентов",
                "description": "Исследование рынка и конкурентов",
                "parent": "Кампания по продвижению продукта X",
                "assignee": None,  # ← БЛОКИРУЮЩАЯ (нет исполнителя)
                "owner": "Ведущий маркетолог",
                "deadline": now + timedelta(days=20),
                "status": "created",
                "priority": "low",
                "created_by": "sidorova@company.com",
            },
            # Проект 3: Продажи
            {
                "title": "Квартальный отчет по продажам",
                "description": "Подготовка отчета за 2 квартал 2024",
                "parent": None,
                "assignee": "Менеджер по продажам",
                "owner": "Менеджер по продажам",
                "deadline": now + timedelta(days=15),
                "status": "assigned",
                "priority": "medium",
                "created_by": "smirnov@company.com",
            },
            {
                "title": "Сбор данных по клиентам",
                "description": "Анализ клиентской базы и покупок",
                "parent": "Квартальный отчет по продажам",
                "assignee": None,
                "owner": "Менеджер по продажам",
                "deadline": now - timedelta(days=5),  # ← ПРОСРОЧЕННАЯ
                "status": "completed",
                "priority": "low",
                "created_by": "smirnov@company.com",
            },
        ]

        created_tasks = {}

        # Сначала создаем задачи без родителей
        for data in tasks_data:
            if data["parent"] is None:
                task = self._create_task_instance(data, users, positions, created_tasks)
                created_tasks[data["title"]] = task

        # Затем задачи с родителями
        for data in tasks_data:
            if data["parent"] and data["parent"] in created_tasks:
                task = self._create_task_instance(data, users, positions, created_tasks)
                created_tasks[data["title"]] = task

        return created_tasks

    def _create_task_instance(self, data, users, positions, created_tasks):
        """Создание экземпляра задачи"""
        assignee = positions.get(data["assignee"]) if data["assignee"] else None
        owner = positions.get(data["owner"]) if data["owner"] else None
        parent = created_tasks.get(data["parent"]) if data["parent"] else None
        created_by = users.get(data["created_by"]) if data["created_by"] else None

        task = Task.objects.create(
            title=data["title"],
            description=data["description"],
            parent=parent,
            assignee=assignee,
            owner=owner,
            deadline=data["deadline"],
            status=data["status"],
            priority=data["priority"],
            created_by=created_by,
        )

        # Устанавливаем completed_at для завершенных задач
        if data["status"] == "completed":
            task.completed_at = timezone.now()
            task.save()

        status_display = task.get_status_display()
        self.stdout.write(self.style.SUCCESS(f"Задача: {task.title} ({status_display})"))

        return task

    def print_summary(self, users, departments, positions, tasks):
        """Вывод сводки"""
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("СВОДКА СОЗДАННЫХ ДАННЫХ:"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Пользователи: {len(users)}")
        self.stdout.write(f"Отделы: {len(departments)}")
        self.stdout.write(f"Должности: {len(positions)}")
        self.stdout.write(f"Задачи: {len(tasks)}")

        # Статистика по задачам
        task_statuses = {}
        for task in tasks.values():
            status = task.get_status_display()
            task_statuses[status] = task_statuses.get(status, 0) + 1

        self.stdout.write("\nСтатусы задач:")
        for status, count in task_statuses.items():
            self.stdout.write(f"  {status}: {count}")

        # Блокирующие задачи
        blocking_tasks = [
            t
            for t in tasks.values()
            if t.status in ["created", "assigned"] and t.parent and t.parent.status == "in_progress"
        ]
        self.stdout.write(f"\n⚠Блокирующие задачи: {len(blocking_tasks)}")

        # Логины для тестирования
        self.stdout.write("\nДЛЯ ТЕСТИРОВАНИЯ:")
        self.stdout.write("=" * 50)
        for email, user in users.items():
            if user.is_superuser:
                self.stdout.write(self.style.WARNING(f"Админ: {email} / Admin123!@#"))
            elif user.is_staff:
                self.stdout.write(self.style.WARNING(f"Руководитель: {email} / {user.last_name}123!@#"))
            else:
                self.stdout.write(f"Сотрудник: {email} / {user.last_name}123!@#")

        self.stdout.write("\nAPI для тестирования:")
        self.stdout.write("=" * 50)
        self.stdout.write("1. Занятые сотрудники:")
        self.stdout.write("   GET /api/tasks/employees/busy/")
        self.stdout.write("\n2. Важные (блокирующие) задачи:")
        self.stdout.write("   GET /api/tasks/important-tasks/blocking/")
        self.stdout.write("\n3. Поиск сотрудников для задачи:")
        self.stdout.write("   GET /api/tasks/important-tasks/3/suggestions/")
        self.stdout.write("\n4. Задачи с назначениями:")
        self.stdout.write("   GET /api/tasks/important-tasks/with-assignments/")

        # Примеры запросов с curl
        self.stdout.write("\nПримеры curl запросов:")
        self.stdout.write("=" * 50)
        self.stdout.write("1. Получить JWT токен:")
        self.stdout.write("   curl -X POST http://localhost:8000/api/users/login/ \\")
        self.stdout.write('   -H "Content-Type: application/json" \\')
        self.stdout.write('   -d \'{"email": "ivanov@company.com", "password": "Ivanov123!@#"}\'')

        self.stdout.write("\n2. Занятые сотрудники (с токеном):")
        self.stdout.write("   curl -X GET http://localhost:8000/api/tasks/employees/busy/ \\")
        self.stdout.write('   -H "Authorization: Bearer YOUR_JWT_TOKEN"')
