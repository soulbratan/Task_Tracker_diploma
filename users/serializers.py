from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import User
from .validators import validate_password_complexity


class UserSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), message="Пользователь с таким email уже существует")],
    )

    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password_complexity],
        style={"input_type": "password"},
        label="Пароль",
    )

    confirm_password = serializers.CharField(
        write_only=True, required=True, style={"input_type": "password"}, label="Подтверждение пароля"
    )

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "password",
            "confirm_password",
            "last_name",
            "first_name",
            "middle_name",
            "phone",
            "telegram_id",
            "photo",
            "organization",
            "position",
            "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]

    def validate(self, data):
        if data.get("password") != data.get("confirm_password"):
            raise serializers.ValidationError({"confirm_password": "Пароли не совпадают"})
        return data

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        password = validated_data.pop("password")

        user = User(**validated_data)
        user.set_password(password)
        user.save()

        return user


class UserUpdateSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = [
            "email",
            "last_name",
            "first_name",
            "middle_name",
            "phone",
            "telegram_id",
            "photo",
            "organization",
        ]
        read_only_fields = ["email", "is_staff", "department", "position"]


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, style={"input_type": "password"})

    def validate(self, data):
        email = data.get("email")
        password = data.get("password")

        if email and password:
            user = authenticate(username=email, password=password)

            if not user:
                raise serializers.ValidationError("Неверный email или пароль")

            if not user.is_active:
                raise serializers.ValidationError("Аккаунт неактивен")

            data["user"] = user
            return data

        raise serializers.ValidationError("Требуется email и пароль")


class ProfileSerializer(serializers.ModelSerializer):
    """Сериализатор для профиля пользователей"""

    photo_url = serializers.SerializerMethodField()
    position_info = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "last_name",
            "first_name",
            "middle_name",
            "phone",
            "telegram_id",
            "photo",
            "photo_url",
            "organization",
            "department",  # ← CharField
            "position",  # ← CharField
            "position_info",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "date_joined"]

    def get_photo_url(self, obj):
        if obj.photo:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.photo.url)
            return obj.photo.url
        return None

    def get_position_info(self, obj):
        """Получение информации о должности"""
        if obj.department and obj.position:
            return {
                "department": obj.department,
                "position": obj.position,
            }
        return None


class UserListSerializer(serializers.ModelSerializer):
    """Сериализатор для списка пользователей (ограниченные поля)"""

    photo_url = serializers.SerializerMethodField()
    position_info = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "last_name",
            "first_name",
            "middle_name",
            "phone",
            "photo",
            "photo_url",
            "organization",
            "position",
            "position_info",
        ]

    def get_photo_url(self, obj):
        if obj.photo:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.photo.url)
            return obj.photo.url
        return None

    def get_position_info(self, obj):
        """Получение информации о должности"""
        return obj.get_position_info()
