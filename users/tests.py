import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


def create_test_image():
    """Создает временное тестовое изображение"""
    image = Image.new("RGB", (100, 100), color="red")
    tmp_file = tempfile.NamedTemporaryFile(suffix=".jpg")
    image.save(tmp_file, "JPEG")
    tmp_file.seek(0)
    return tmp_file


class UserModelTests(TestCase):
    """Тесты модели User"""

    def setUp(self):
        self.user_data = {
            "email": "test@example.com",
            "password": "TestPass123!",
            "last_name": "Иванов",
            "first_name": "Иван",
            "middle_name": "Иванович",
            "phone": "+79161234567",
            "telegram_id": "@testuser",
            "organization": "ООО Тест",
            "position": "Тестировщик",
        }

    def test_create_user(self):
        """Тест создания обычного пользователя"""
        user = User.objects.create_user(**self.user_data)

        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.last_name, "Иванов")
        self.assertEqual(user.first_name, "Иван")
        self.assertTrue(user.check_password("TestPass123!"))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_superuser(self):
        """Тест создания суперпользователя"""
        superuser = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!", last_name="Админов", first_name="Админ"
        )

        self.assertEqual(superuser.email, "admin@example.com")
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)
        self.assertTrue(superuser.is_active)

    def test_user_str(self):
        """Тест строкового представления пользователя"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(str(user), "test@example.com")

    def test_get_full_name(self):
        """Тест получения полного имени"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_full_name(), "Иванов Иван Иванович")

        # Без отчества
        user2 = User.objects.create_user(
            email="test2@example.com", password="TestPass123!", last_name="Петров", first_name="Петр"
        )
        self.assertEqual(user2.get_full_name(), "Петров Петр")

    def test_get_short_name(self):
        """Тест получения короткого имени"""
        user = User.objects.create_user(**self.user_data)
        self.assertEqual(user.get_short_name(), "Иван")

    def test_password_validation(self):
        """Тест валидации пароля"""
        from .validators import validate_password_complexity

        # Валидные пароли
        valid_passwords = [
            "ValidPass123!",
            "Another1@Pass",
            "Test#123Password",
        ]

        for password in valid_passwords:
            try:
                validate_password_complexity(password)
            except Exception as e:
                self.fail(f"Пароль {password} должен быть валидным: {e}")

        # Невалидные пароли
        invalid_cases = [
            ("short", "Пароль должен содержать минимум 8 символов"),
            ("noupper123!", "Пароль должен содержать хотя бы одну заглавную букву"),
            ("NOLOWER123!", "Пароль должен содержать хотя бы одну строчную букву"),
            ("NoDigits!", "Пароль должен содержать хотя бы одну цифру"),
            ("NoSpecial123", "Пароль должен содержать хотя бы один специальный символ"),
        ]

        for password, expected_error in invalid_cases:
            with self.assertRaises(Exception) as context:
                validate_password_complexity(password)
            self.assertIn(expected_error, str(context.exception))


class UserAPITests(APITestCase):
    """Тесты API пользователей"""

    def setUp(self):
        self.client = APIClient()

        # Данные для регистрации
        self.register_data = {
            "email": "newuser@example.com",
            "password": "NewPass123!",
            "confirm_password": "NewPass123!",
            "last_name": "Новиков",
            "first_name": "Новый",
            "middle_name": "Тестович",
            "phone": "+79169876543",
            "telegram_id": "@newuser",
            "organization": "Новая Организация",
            "position": "Новая Должность",
        }

        # Данные для логина
        self.login_data = {"email": "test@example.com", "password": "TestPass123!"}

        # Создаем тестового пользователя
        self.user = User.objects.create_user(
            email="test@example.com",
            password="TestPass123!",
            last_name="Тестов",
            first_name="Тест",
            phone="+79161234567",
        )

        # Создаем второго пользователя
        self.user2 = User.objects.create_user(
            email="user2@example.com", password="User2Pass123!", last_name="Второй", first_name="Пользователь"
        )

        # Создаем админа
        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!", last_name="Админов", first_name="Админ"
        )

    def get_token_for_user(self, user):
        """Получение JWT токена для пользователя"""
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    # ========== ТЕСТЫ БЕЗ АУТЕНТИФИКАЦИИ ==========

    def test_user_registration(self):
        """Тест регистрации нового пользователя"""
        url = reverse("user-list")
        response = self.client.post(url, self.register_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["email"], "newuser@example.com")
        self.assertEqual(response.data["last_name"], "Новиков")
        self.assertEqual(response.data["first_name"], "Новый")
        self.assertNotIn("password", response.data)
        self.assertNotIn("confirm_password", response.data)

        # Проверяем что пользователь создан в БД
        user = User.objects.get(email="newuser@example.com")
        self.assertTrue(user.check_password("NewPass123!"))
        self.assertTrue(user.is_active)

    def test_user_registration_password_mismatch(self):
        """Тест регистрации с несовпадающими паролями"""
        data = self.register_data.copy()
        data["confirm_password"] = "WrongPass123!"

        url = reverse("user-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)
        self.assertEqual(response.data["confirm_password"][0], "Пароли не совпадают")

    def test_user_registration_weak_password(self):
        """Тест регистрации со слабым паролем"""
        data = self.register_data.copy()
        data["password"] = "weak"
        data["confirm_password"] = "weak"

        url = reverse("user-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    def test_user_registration_duplicate_email(self):
        """Тест регистрации с уже существующим email"""
        data = self.register_data.copy()
        data["email"] = "test@example.com"  # Email уже существует

        url = reverse("user-list")
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_user_login(self):
        """Тест входа в систему"""
        url = reverse("user-login")
        response = self.client.post(url, self.login_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["email"], "test@example.com")

    def test_user_login_wrong_credentials(self):
        """Тест входа с неверными учетными данными"""
        url = reverse("user-login")
        data = {"email": "wrong@example.com", "password": "wrong"}
        response = self.client.post(url, data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)

    def test_user_login_inactive_user(self):
        """Тест входа неактивного пользователя"""
        # Деактивируем пользователя
        self.user.is_active = False
        self.user.save()

        url = reverse("user-login")
        response = self.client.post(url, self.login_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)

        # Активируем обратно для других тестов
        self.user.is_active = True
        self.user.save()

    # ========== ТЕСТЫ С АУТЕНТИФИКАЦИЕЙ ==========
    def test_get_user_list_unauthenticated(self):
        """Тест получения списка пользователей без аутентификации"""
        url = reverse("user-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_own_profile(self):
        """Тест получения своего профиля"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "test@example.com")
        self.assertEqual(response.data["last_name"], "Тестов")
        self.assertEqual(response.data["first_name"], "Тест")

    def test_get_other_user_profile_as_user(self):
        """Тест получения чужого профиля обычным пользователем"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user2.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_other_user_profile_as_admin(self):
        """Тест получения чужого профиля администратором"""
        token = self.get_token_for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "test@example.com")

    def test_get_current_user_via_me(self):
        """Тест получения текущего пользователя через /me/"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-me")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "test@example.com")
        self.assertEqual(response.data["last_name"], "Тестов")

    def test_update_own_profile(self):
        """Тест обновления своего профиля"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        update_data = {
            "last_name": "Обновленный",
            "first_name": "Тест",
            "phone": "+79161111111",
            "organization": "Обновленная Организация",
        }

        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["last_name"], "Обновленный")
        self.assertEqual(response.data["phone"], "+79161111111")
        self.assertEqual(response.data["organization"], "Обновленная Организация")

        # Проверяем в БД
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "Обновленный")

    def test_update_own_profile_email_readonly(self):
        """Тест что email нельзя изменить"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        update_data = {"email": "newemail@example.com"}

        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Email не должен измениться
        self.assertEqual(response.data["email"], "test@example.com")

    def test_update_other_user_profile_as_user(self):
        """Тест обновления чужого профиля обычным пользователем"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user2.id})
        update_data = {"last_name": "Взломанный"}

        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_other_user_profile_as_admin(self):
        """Тест обновления чужого профиля администратором"""
        token = self.get_token_for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        update_data = {"last_name": "Обновленный Админом"}

        response = self.client.patch(url, update_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["last_name"], "Обновленный Админом")

    def test_delete_own_profile(self):
        """Тест удаления своего профиля (soft delete)"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Проверяем что пользователь деактивирован
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_delete_other_user_profile_as_user(self):
        """Тест удаления чужого профиля обычным пользователем"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user2.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Проверяем что пользователь НЕ деактивирован
        self.user2.refresh_from_db()
        self.assertTrue(self.user2.is_active)

    def test_delete_user_profile_as_admin(self):
        """Тест удаления профиля администратором"""
        token = self.get_token_for_user(self.admin)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})
        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Проверяем что пользователь деактивирован
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

    def test_upload_profile_photo(self):
        """Тест загрузки фотографии профиля"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user.id})

        # Создаем тестовое изображение
        with create_test_image() as image:
            data = {"photo": image}
            response = self.client.patch(url, data, format="multipart")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(response.data["photo"])
        self.assertTrue("user_photos" in response.data["photo"])

    # ========== ТЕСТЫ JWT ТОКЕНОВ ==========

    def test_token_refresh(self):
        """Тест обновления JWT токена"""
        # Сначала получаем refresh токен через логин
        login_url = reverse("user-login")
        login_response = self.client.post(login_url, self.login_data, format="json")
        refresh_token = login_response.data["refresh"]

        # Обновляем токен
        refresh_url = reverse("token_refresh")
        refresh_data = {"refresh": refresh_token}
        response = self.client.post(refresh_url, refresh_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_token_verify(self):
        """Тест проверки JWT токена"""
        token = self.get_token_for_user(self.user)

        verify_url = reverse("token_verify")
        verify_data = {"token": token}
        response = self.client.post(verify_url, verify_data, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ========== ТЕСТЫ ДЛЯ ФОТО URL ==========

    def test_photo_url_in_response(self):
        """Тест что photo_url присутствует в ответе"""
        token = self.get_token_for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        # Загружаем фото
        url = reverse("user-detail", kwargs={"pk": self.user.id})
        with create_test_image() as image:
            data = {"photo": image}
            self.client.patch(url, data, format="multipart")

        # Получаем профиль
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("photo_url", response.data)
        self.assertIsNotNone(response.data["photo_url"])

    def test_photo_url_without_photo(self):
        """Тест photo_url когда фото нет"""
        token = self.get_token_for_user(self.user2)  # У user2 нет фото
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

        url = reverse("user-detail", kwargs={"pk": self.user2.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("photo_url", response.data)
        self.assertIsNone(response.data["photo_url"])


class UserAdminTests(TestCase):
    """Тесты админки пользователей"""

    def setUp(self):
        self.admin_user = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!", last_name="Админов", first_name="Админ"
        )

        self.regular_user = User.objects.create_user(
            email="user@example.com", password="UserPass123!", last_name="Пользователь", first_name="Обычный"
        )

    def test_admin_user_is_staff(self):
        """Тест что админ имеет флаг is_staff"""
        self.assertTrue(self.admin_user.is_staff)
        self.assertTrue(self.admin_user.is_superuser)

    def test_regular_user_not_staff(self):
        """Тест что обычный пользователь не имеет флага is_staff"""
        self.assertFalse(self.regular_user.is_staff)
        self.assertFalse(self.regular_user.is_superuser)

    def test_user_admin_display(self):
        """Тест отображения пользователей в админке"""
        self.assertEqual(str(self.admin_user), "admin@example.com")
        self.assertEqual(str(self.regular_user), "user@example.com")

        self.assertEqual(self.admin_user.get_full_name(), "Админов Админ")
        self.assertEqual(self.regular_user.get_full_name(), "Пользователь Обычный")


class UserPermissionsTests(APITestCase):
    """Тесты permissions"""

    def setUp(self):
        self.user = User.objects.create_user(
            email="user1@example.com", password="Pass123!", last_name="Первый", first_name="Пользователь"
        )

        self.user2 = User.objects.create_user(
            email="user2@example.com", password="Pass123!", last_name="Второй", first_name="Пользователь"
        )

        self.admin = User.objects.create_superuser(
            email="admin@example.com", password="AdminPass123!", last_name="Админ", first_name="Администратор"
        )

    def get_token_for_user(self, user):
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)

    def test_is_self_or_admin_permission_self(self):
        """Тест permission IsSelfOrAdmin для своего профиля"""
        from .permissions import IsSelfOrAdmin

        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.user})()

        self.assertTrue(permission.has_object_permission(request, None, self.user))

    def test_is_self_or_admin_permission_other_user(self):
        """Тест permission IsSelfOrAdmin для чужого профиля"""
        from .permissions import IsSelfOrAdmin

        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.user})()

        self.assertFalse(permission.has_object_permission(request, None, self.user2))

    def test_is_self_or_admin_permission_admin(self):
        """Тест permission IsSelfOrAdmin для администратора"""
        from .permissions import IsSelfOrAdmin

        permission = IsSelfOrAdmin()
        request = type("Request", (), {"user": self.admin})()

        self.assertTrue(permission.has_object_permission(request, None, self.user))
        self.assertTrue(permission.has_object_permission(request, None, self.user2))
        self.assertTrue(permission.has_object_permission(request, None, self.admin))
