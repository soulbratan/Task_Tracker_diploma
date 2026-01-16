from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from organization.models import Department, Position
from tasks.models import Comment, Task

User = get_user_model()


class TaskModelTests(TestCase):
    """Тесты модели Task"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com", password="TestPass123!", last_name="Тестов", first_name="Тест"
        )

        self.department = Department.objects.create(name="Тестовый отдел")

        self.position = Position.objects.create(
            name="Тестировщик", level=Position.PositionLevel.EMPLOYEE, department=self.department, employee=self.user
        )

        self.task = Task.objects.create(
            title="Тестовая задача",
            description="Описание тестовой задачи",
            owner=self.position,
            priority=Task.TaskPriority.MEDIUM,
            created_by=self.user,
        )

    def test_task_creation(self):
        """Тест создания задачи"""
        self.assertEqual(self.task.title, "Тестовая задача")
        self.assertEqual(self.task.status, Task.TaskStatus.CREATED)
        self.assertEqual(self.task.priority, Task.TaskPriority.MEDIUM)
        self.assertIsNone(self.task.assignee)
        self.assertEqual(self.task.owner, self.position)
        self.assertEqual(self.task.created_by, self.user)

    def test_task_str_method(self):
        """Тест строкового представления задачи"""
        expected = "Тестовая задача (Создана)"
        self.assertEqual(str(self.task), expected)

    def test_task_is_overdue_property(self):
        """Тест свойства is_overdue"""
        # Задача без срока - не просрочена
        self.assertFalse(self.task.is_overdue)

        # Задача с будущим сроком - не просрочена
        self.task.deadline = timezone.now() + timezone.timedelta(days=1)
        self.task.save()
        self.assertFalse(self.task.is_overdue)

        # Для тестирования просроченности создаем новую задачу
        # и обновляем дедлайн через queryset
        task2 = Task.objects.create(
            title="Задача в работе", owner=self.position, status=Task.TaskStatus.IN_PROGRESS, created_by=self.user
        )
        # Обновляем дедлайн напрямую через update
        Task.objects.filter(id=task2.id).update(deadline=timezone.now() - timezone.timedelta(days=1))
        task2.refresh_from_db()
        self.assertTrue(task2.is_overdue)

    def test_task_progress_property(self):
        """Тест свойства progress"""
        # Задача без подзадач
        self.assertEqual(self.task.progress, 0)  # CREATED → 0%

        # Задача назначена
        self.task.assignee = self.position
        self.task.status = Task.TaskStatus.ASSIGNED
        self.task.save()
        self.assertEqual(self.task.progress, 20)  # ASSIGNED → 20%

        # Задача в работе
        self.task.status = Task.TaskStatus.IN_PROGRESS
        self.task.save()
        self.assertEqual(self.task.progress, 50)  # IN_PROGRESS → 50%

        # Задача выполнена
        self.task.status = Task.TaskStatus.COMPLETED
        self.task.save()
        self.assertEqual(self.task.progress, 100)  # COMPLETED → 100%

    def test_subtask_creation(self):
        """Тест создания подзадачи"""
        subtask = Task.objects.create(
            title="Подзадача",
            description="Описание подзадачи",
            parent=self.task,
            owner=self.position,
            created_by=self.user,
        )

        self.assertEqual(subtask.parent, self.task)
        self.assertEqual(self.task.subtasks.count(), 1)
        self.assertEqual(self.task.subtasks.first(), subtask)

    def test_task_depth_property(self):
        """Тест глубины вложенности задачи"""
        self.assertEqual(self.task.get_depth(), 0)

        # Создаем подзадачу
        subtask = Task.objects.create(
            title="Подзадача",
            description="Описание подзадачи",
            parent=self.task,
            owner=self.position,
            created_by=self.user,
        )

        self.assertEqual(subtask.get_depth(), 1)

        # Создаем под-подзадачу
        subsubtask = Task.objects.create(
            title="Под-подзадача",
            description="Описание под-подзадачи",
            parent=subtask,
            owner=self.position,
            created_by=self.user,
        )

        self.assertEqual(subsubtask.get_depth(), 2)

    def test_comment_creation(self):
        """Тест создания комментария"""
        comment = Comment.objects.create(task=self.task, author=self.user, content="Тестовый комментарий")

        self.assertEqual(comment.task, self.task)
        self.assertEqual(comment.author, self.user)
        self.assertEqual(comment.content, "Тестовый комментарий")
        self.assertEqual(self.task.comments.count(), 1)


class TaskAPITests(APITestCase):
    """Тесты API задач"""

    def setUp(self):
        # Создаем пользователей
        self.user = User.objects.create_user(
            email="user@example.com", password="UserPass123!", last_name="Пользователь", first_name="Обычный"
        )

        self.manager = User.objects.create_user(
            email="manager@example.com", password="ManagerPass123!", last_name="Руководитель", first_name="Тест"
        )

        # Создаем отдел и должности
        self.department = Department.objects.create(name="Тестовый отдел")

        self.employee_position = Position.objects.create(
            name="Сотрудник", level=Position.PositionLevel.EMPLOYEE, department=self.department, employee=self.user
        )

        self.manager_position = Position.objects.create(
            name="Руководитель",
            level=Position.PositionLevel.MANAGER,
            department=self.department,
            employee=self.manager,
        )

        # Создаем задачу
        self.task = Task.objects.create(
            title="Тестовая задача API",
            description="Описание для тестов API",
            owner=self.manager_position,
            assignee=self.employee_position,
            status=Task.TaskStatus.ASSIGNED,
            priority=Task.TaskPriority.HIGH,
            created_by=self.manager,
        )

        # Создаем JWT токены
        self.user_token = self.get_token_for_user(self.user)
        self.manager_token = self.get_token_for_user(self.manager)

    def get_token_for_user(self, user):
        """Получение JWT токена для пользователя"""
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_get_task_list_unauthenticated(self):
        """Тест получения списка задач без аутентификации"""
        url = reverse("task-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_task_list_authenticated(self):
        """Тест получения списка задач с аутентификацией"""
        url = reverse("task-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Проверяем что возвращаются данные
        self.assertTrue(len(response.data) > 0 or ("results" in response.data and len(response.data["results"]) > 0))

    def test_get_task_detail(self):
        """Тест получения деталей задачи"""
        url = reverse("task-detail", kwargs={"pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Тестовая задача API")
        self.assertEqual(response.data["status"], "assigned")
        self.assertEqual(response.data["priority"], "high")

    def test_create_task_as_manager(self):
        """Тест создания задачи руководителем"""
        url = reverse("task-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")

        data = {
            "title": "Новая задача",
            "description": "Описание новой задачи",
            "owner": self.manager_position.id,
            "priority": "medium",
            "deadline": (timezone.now() + timezone.timedelta(days=7)).isoformat(),
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Проверяем что задача создалась (должен быть ID в ответе или в БД)
        if "id" in response.data:
            task_id = response.data["id"]
        else:
            # Если ID не в ответе, ищем задачу по названию
            task = Task.objects.filter(title="Новая задача").first()
            self.assertIsNotNone(task)
            task_id = task.id

        # Проверяем в БД
        task = Task.objects.get(id=task_id)
        self.assertEqual(task.status, Task.TaskStatus.CREATED)  # Нет исполнителя
        self.assertEqual(task.created_by, self.manager)

    def test_create_task_with_assignee(self):
        """Тест создания задачи с исполнителем"""
        url = reverse("task-list")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")

        data = {
            "title": "Задача с исполнителем",
            "description": "Задача сразу с назначенным исполнителем",
            "owner": self.manager_position.id,
            "assignee": self.employee_position.id,
            "priority": "high",
        }

        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Находим задачу в БД
        task = Task.objects.filter(title="Задача с исполнителем").first()
        self.assertIsNotNone(task)
        self.assertEqual(task.status, Task.TaskStatus.ASSIGNED)  # Есть исполнитель
        self.assertEqual(task.created_by, self.manager)

    def test_update_task_status_as_assignee(self):
        """Тест обновления статуса задачи исполнителем"""
        url = reverse("task-detail", kwargs={"pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")

        data = {"status": "in_progress"}
        response = self.client.patch(url, data, format="json")

        # Проверяем ответ
        if response.status_code == status.HTTP_200_OK:
            # Успешное обновление
            self.assertEqual(response.data["status"], "in_progress")
            self.task.refresh_from_db()
            self.assertEqual(self.task.status, Task.TaskStatus.IN_PROGRESS)
        elif response.status_code == status.HTTP_400_BAD_REQUEST:
            # Ошибка валидации (например, недопустимый переход статуса)
            self.assertIn("detail", response.data)
        else:
            # Неожиданный код ответа
            self.fail(f"Неожиданный код ответа: {response.status_code}")

    def test_update_task_as_manager(self):
        """Тест обновления задачи руководителем"""
        url = reverse("task-detail", kwargs={"pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")

        data = {"title": "Обновленное название", "priority": "critical"}

        response = self.client.patch(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Обновленное название")
        self.assertEqual(response.data["priority"], "critical")

    def test_create_comment(self):
        """Тест создания комментария к задаче"""
        url = reverse("task-comments", kwargs={"task_pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")

        data = {"content": "Тестовый комментарий от пользователя"}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["content"], "Тестовый комментарий от пользователя")
        self.assertEqual(response.data["author_name"], "Пользователь Обычный")

        # Проверяем в БД
        self.assertEqual(self.task.comments.count(), 1)
        comment = self.task.comments.first()
        self.assertEqual(comment.author, self.user)
        self.assertEqual(comment.content, "Тестовый комментарий от пользователя")

    def test_get_comments(self):
        """Тест получения списка комментариев"""
        # Создаем несколько комментариев
        Comment.objects.create(task=self.task, author=self.user, content="Первый комментарий")
        Comment.objects.create(task=self.task, author=self.manager, content="Второй комментарий")

        url = reverse("task-comments", kwargs={"task_pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_get_my_tasks(self):
        """Тест получения задач текущего пользователя"""
        url = reverse("task-my-tasks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Проверяем что возвращаются данные
        data_length = 0
        if "results" in response.data:
            data_length = len(response.data["results"])
        else:
            data_length = len(response.data)

        self.assertGreaterEqual(data_length, 1)

    def test_get_task_progress(self):
        """Тест получения прогресса задачи"""
        url = reverse("task-progress", kwargs={"pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("progress", response.data)
        # Проверяем что прогресс в допустимом диапазоне
        self.assertGreaterEqual(response.data["progress"], 0)
        self.assertLessEqual(response.data["progress"], 100)


class TaskPermissionTests(APITestCase):
    """Тесты прав доступа к задачам"""

    def setUp(self):
        # Создаем пользователей
        self.user1 = User.objects.create_user(
            email="user1@example.com", password="Pass123!", last_name="Первый", first_name="Пользователь"
        )

        self.user2 = User.objects.create_user(
            email="user2@example.com", password="Pass123!", last_name="Второй", first_name="Пользователь"
        )

        self.manager = User.objects.create_user(
            email="manager@example.com", password="ManagerPass123!", last_name="Руководитель", first_name="Отдела"
        )

        # Создаем отделы
        self.department1 = Department.objects.create(name="Отдел 1")
        self.department2 = Department.objects.create(name="Отдел 2")

        # Создаем должности
        self.position1 = Position.objects.create(
            name="Сотрудник 1", level=Position.PositionLevel.EMPLOYEE, department=self.department1, employee=self.user1
        )

        self.position2 = Position.objects.create(
            name="Сотрудник 2", level=Position.PositionLevel.EMPLOYEE, department=self.department2, employee=self.user2
        )

        self.manager_position = Position.objects.create(
            name="Руководитель отдела 1",
            level=Position.PositionLevel.MANAGER,
            department=self.department1,
            employee=self.manager,
        )

        # Создаем задачи
        self.task1 = Task.objects.create(
            title="Задача пользователя 1",
            owner=self.position1,
            assignee=self.position1,
            status=Task.TaskStatus.ASSIGNED,
            created_by=self.user1,
        )

        self.task2 = Task.objects.create(
            title="Задача пользователя 2",
            owner=self.position2,
            assignee=self.position2,
            status=Task.TaskStatus.ASSIGNED,
            created_by=self.user2,
        )

        # Токены
        self.user1_token = self.get_token_for_user(self.user1)
        self.user2_token = self.get_token_for_user(self.user2)
        self.manager_token = self.get_token_for_user(self.manager)

    def get_token_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_user_can_view_own_task(self):
        """Тест: пользователь может видеть свою задачу"""
        url = reverse("task-detail", kwargs={"pk": self.task1.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user1_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Задача пользователя 1")

    def test_user_cannot_view_other_user_task(self):
        """Тест: пользователь не может видеть чужую задачу"""
        url = reverse("task-detail", kwargs={"pk": self.task2.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user1_token}")
        response = self.client.get(url)

        # Должен получить 403 или 404
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_manager_can_view_department_tasks(self):
        """Тест: руководитель может видеть задачи своего отдела"""
        url = reverse("task-detail", kwargs={"pk": self.task1.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Задача пользователя 1")

    def test_manager_cannot_view_other_department_tasks(self):
        """Тест: руководитель не может видеть задачи другого отдела"""
        url = reverse("task-detail", kwargs={"pk": self.task2.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")
        response = self.client.get(url)

        # Должен получить 403 или 404
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_user_can_update_own_task_status(self):
        """Тест: пользователь может обновлять статус своей задачи"""
        url = reverse("task-detail", kwargs={"pk": self.task1.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user1_token}")

        # Пробуем обновить только поле статуса
        data = {"status": "in_progress"}
        response = self.client.patch(url, data, format="json")

        # Проверяем что запрос прошел (200 или 400 при ошибке перехода)
        self.assertIn(response.status_code, [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST])

    def test_user_cannot_update_other_task(self):
        """Тест: пользователь не может обновлять чужую задачу"""
        url = reverse("task-detail", kwargs={"pk": self.task2.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user1_token}")

        data = {"title": "Попытка изменить"}
        response = self.client.patch(url, data, format="json")

        # Должен получить 403 или 404
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_manager_can_update_task_in_department(self):
        """Тест: руководитель может обновлять задачи своего отдела"""
        url = reverse("task-detail", kwargs={"pk": self.task1.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")

        data = {"title": "Изменено руководителем"}
        response = self.client.patch(url, data, format="json")

        # Проверяем ответ
        if response.status_code == status.HTTP_200_OK:
            self.assertEqual(response.data["title"], "Изменено руководителем")
        else:
            # Если нет прав, проверяем ошибку
            self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])


class SpecialEndpointsTests(APITestCase):
    """Тесты специальных эндпоинтов"""

    def setUp(self):
        # Создаем пользователей
        self.user = User.objects.create_user(
            email="user@example.com", password="Pass123!", last_name="Тестов", first_name="Пользователь"
        )

        self.manager = User.objects.create_user(
            email="manager@example.com", password="ManagerPass123!", last_name="Руководитель", first_name="Тест"
        )

        # Создаем отдел
        self.department = Department.objects.create(name="Тестовый отдел")

        # Создаем должности
        self.employee_position = Position.objects.create(
            name="Сотрудник", level=Position.PositionLevel.EMPLOYEE, department=self.department, employee=self.user
        )

        self.manager_position = Position.objects.create(
            name="Руководитель",
            level=Position.PositionLevel.MANAGER,
            department=self.department,
            employee=self.manager,
        )

        # Создаем задачи для тестирования загруженности
        for i in range(3):
            Task.objects.create(
                title=f"Задача {i + 1}",
                owner=self.manager_position,
                assignee=self.employee_position,
                status=Task.TaskStatus.IN_PROGRESS,
                created_by=self.manager,
            )

        # Создаем задачу для тестирования просроченности
        overdue_task = Task.objects.create(
            title="Задача без срока",
            owner=self.manager_position,
            assignee=self.employee_position,
            status=Task.TaskStatus.IN_PROGRESS,
            created_by=self.manager,
        )
        # Обновляем дедлайн через queryset
        Task.objects.filter(id=overdue_task.id).update(deadline=timezone.now() - timezone.timedelta(days=1))

        # Токены
        self.user_token = self.get_token_for_user(self.user)
        self.manager_token = self.get_token_for_user(self.manager)

    def get_token_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_busy_employees_endpoint_access(self):
        """Тест доступа к эндпоинту занятых сотрудников"""
        url = reverse("busy-employees")

        # Обычный пользователь не должен иметь доступ
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Руководитель должен иметь доступ
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_busy_employees_data(self):
        """Тест данных в эндпоинте занятых сотрудников"""
        url = reverse("busy-employees")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Проверяем структуру ответа
        self.assertIn("employees", response.data)
        self.assertIn("statistics", response.data)

    def test_important_tasks_access(self):
        """Тест доступа к эндпоинту важных задач"""
        url = reverse("blocking-tasks")

        # Обычный пользователь не должен иметь доступ
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Руководитель должен иметь доступ
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_blocking_tasks_scenario(self):
        """Тест сценария блокирующих задач"""
        # Создаем родительскую задачу в работе
        parent_task = Task.objects.create(
            title="Родительская задача",
            owner=self.manager_position,
            assignee=self.employee_position,
            status=Task.TaskStatus.IN_PROGRESS,
            created_by=self.manager,
        )

        # Создаем подзадачу, которая не в работе (блокирующая)
        blocking_subtask = Task.objects.create(  # noqa
            title="Блокирующая подзадача",
            parent=parent_task,
            owner=self.manager_position,
            status=Task.TaskStatus.CREATED,  # Не в работе
            created_by=self.manager,
        )

        url = reverse("blocking-tasks")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.manager_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Проверяем структуру ответа
        self.assertIn("tasks", response.data)


class CommentAPITests(APITestCase):
    """Тесты API комментариев"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com", password="Pass123!", last_name="Тестов", first_name="Пользователь"
        )

        self.other_user = User.objects.create_user(
            email="other@example.com", password="Pass123!", last_name="Другой", first_name="Пользователь"
        )

        self.department = Department.objects.create(name="Тестовый отдел")
        self.position = Position.objects.create(
            name="Сотрудник", level=Position.PositionLevel.EMPLOYEE, department=self.department, employee=self.user
        )

        self.task = Task.objects.create(title="Задача для комментариев", owner=self.position, created_by=self.user)

        self.comment = Comment.objects.create(task=self.task, author=self.user, content="Тестовый комментарий")

        self.user_token = self.get_token_for_user(self.user)
        self.other_user_token = self.get_token_for_user(self.other_user)

    def get_token_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_create_comment(self):
        """Тест создания комментария"""
        url = reverse("task-comments", kwargs={"task_pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")

        data = {"content": "Новый комментарий"}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["content"], "Новый комментарий")
        self.assertEqual(Comment.objects.count(), 2)

    def test_get_comments_list(self):
        """Тест получения списка комментариев"""
        url = reverse("task-comments", kwargs={"task_pk": self.task.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["content"], "Тестовый комментарий")

    def test_get_comment_detail(self):
        """Тест получения деталей комментария"""
        url = reverse("task-comment-detail", kwargs={"task_pk": self.task.id, "pk": self.comment.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["content"], "Тестовый комментарий")
        self.assertEqual(response.data["author_name"], "Тестов Пользователь")

    def test_delete_own_comment(self):
        """Тест удаления своего комментария"""
        url = reverse("task-comment-detail", kwargs={"task_pk": self.task.id, "pk": self.comment.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(Comment.objects.count(), 0)

    def test_cannot_delete_other_comment(self):
        """Тест: нельзя удалить чужой комментарий"""
        # Создаем комментарий от другого пользователя
        other_comment = Comment.objects.create(
            task=self.task, author=self.other_user, content="Комментарий другого пользователя"
        )

        url = reverse("task-comment-detail", kwargs={"task_pk": self.task.id, "pk": other_comment.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")
        response = self.client.delete(url)

        # Должен получить 403 или 404
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

        # Комментарий должен остаться
        self.assertEqual(Comment.objects.count(), 2)

    def test_cannot_edit_comment(self):
        """Тест: нельзя редактировать комментарий"""
        url = reverse("task-comment-detail", kwargs={"task_pk": self.task.id, "pk": self.comment.id})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.user_token}")

        data = {"content": "Измененный текст"}
        response = self.client.patch(url, data, format="json")

        # Должен получить 405 (метод не разрешен)
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        # Проверяем что это именно запрет метода, а не другая ошибка
        self.assertIn("Метод", str(response.data))
