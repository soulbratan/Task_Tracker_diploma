from django.apps import apps
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField


class UserManager(BaseUserManager):
    """
    Кастомный менеджер пользователей для модели User.
    """

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email обязателен")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Модель пользователя (email, пароль, имя и фамилия)"""

    email = models.EmailField(unique=True, verbose_name="Email адрес")
    last_name = models.CharField(max_length=150, verbose_name="Фамилия")
    first_name = models.CharField(max_length=150, verbose_name="Имя")
    middle_name = models.CharField(max_length=150, blank=True, null=True, verbose_name="Отчество")
    phone = PhoneNumberField(blank=True, null=True, verbose_name="Телефон", region="RU")
    telegram_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Telegram ID")
    photo = models.ImageField(upload_to="user_photos/", blank=True, null=True, verbose_name="Фотография")
    organization = models.CharField(max_length=255, blank=True, null=True, verbose_name="Организация")
    department = models.CharField(max_length=255, blank=True, null=True, verbose_name="Отдел")
    position = models.CharField(max_length=255, blank=True, null=True, verbose_name="Должность")
    is_active = models.BooleanField(default=True, verbose_name="Активный")
    is_staff = models.BooleanField(default=False, verbose_name="Персонал")
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name="Дата регистрации")

    # TODO: Будет реализовано позже
    # email_verified = models.BooleanField(default=False, verbose_name="Email подтвержден")
    # email_verification_token = models.CharField(max_length=100, blank=True, null=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["last_name", "first_name"]

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["department"]),
            models.Index(fields=["position"]),
        ]

    def __str__(self):
        return self.email

    def get_full_name(self):
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return " ".join(parts)

    def get_short_name(self):
        return self.first_name

    def get_position_info(self):
        """Получение информации о текущей должности"""
        if self.department and self.position:
            return {
                "department": self.department,
                "position": self.position,
            }
        return None

    def update_from_position(self, position_instance):
        """
        Обновляет поля пользователя из назначенной должности.
        Использует ленивую загрузку модели Position для избежания циклических импортов.
        """
        Position = apps.get_model("organization", "Position")

        if position_instance:
            # Проверяем, что position_instance действительно является экземпляром Position
            if not isinstance(position_instance, Position):
                raise ValueError("position_instance должен быть экземпляром Position")

            # Берем название отдела из связанного Department
            self.department = position_instance.department.name if position_instance.department else None
            self.position = position_instance.name

            # Обновляем is_staff для администраторов
            if position_instance.level == Position.PositionLevel.ADMIN:
                self.is_staff = True
            elif self.is_staff and position_instance.level != Position.PositionLevel.ADMIN:
                # Проверяем другие должности ADMIN
                has_other_admin = (
                    Position.objects.filter(employee=self, level=Position.PositionLevel.ADMIN, is_active=True)
                    .exclude(id=position_instance.id)
                    .exists()
                )
                if not has_other_admin:
                    self.is_staff = False
        else:
            # Сброс полей при снятии с должности
            self.department = None
            self.position = None

            # Сбрасываем is_staff если нет других должностей ADMIN
            Position = apps.get_model("organization", "Position")
            has_other_admin = Position.objects.filter(
                employee=self, level=Position.PositionLevel.ADMIN, is_active=True
            ).exists()
            if not has_other_admin:
                self.is_staff = False

        self.save(update_fields=["department", "position", "is_staff"])

    def clean(self):
        """Валидация модели пользователя"""
        super().clean()

        # Валидация email
        if self.email:
            self.email = self.email.lower().strip()

        # Валидация ФИО
        if self.last_name:
            self.last_name = self.last_name.strip()
        if self.first_name:
            self.first_name = self.first_name.strip()
        if self.middle_name:
            self.middle_name = self.middle_name.strip()

    def save(self, *args, **kwargs):
        """Переопределяем save для предварительной очистки"""
        self.full_clean()
        return super().save(*args, **kwargs)
