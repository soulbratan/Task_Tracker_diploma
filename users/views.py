from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .permissions import IsSelfOrAdmin
from .serializers import LoginSerializer, ProfileSerializer, UserListSerializer, UserSerializer, UserUpdateSerializer
from .tasks import send_welcome_email


class UserViewSet(viewsets.ModelViewSet):
    """Вьюсет для пользователя"""

    queryset = User.objects.filter(is_active=True)
    serializer_class = UserSerializer

    def get_permissions(self):
        if self.action in ["create", "login"]:
            permission_classes = [AllowAny]
        elif self.action in ["retrieve", "update", "partial_update", "destroy"]:
            permission_classes = [IsAuthenticated, IsSelfOrAdmin]
        else:
            permission_classes = [IsAuthenticated]  # Для list тоже требуется аутентификация
        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list":
            return UserListSerializer
        elif self.action == "create":
            return UserSerializer
        elif self.action in ["update", "partial_update"]:
            return UserUpdateSerializer
        elif self.action == "retrieve":
            return ProfileSerializer
        return super().get_serializer_class()

    def perform_create(self, serializer):
        """Создание пользователя и отправка приветственного письма"""
        user = serializer.save()

        # Отправляем приветственное письмо асинхронно через Celery
        send_welcome_email.delay(user.id)

        return user

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save()

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def login(self, request):
        """
        Вход в систему.
        Параметры: {"email": "user@example.com", "password": "password"}
        """
        serializer = LoginSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user = serializer.validated_data["user"]

        # Генерация JWT токенов
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
                "user": ProfileSerializer(user, context={"request": request}).data,
            }
        )

    @action(detail=False, methods=["get"], permission_classes=[IsAuthenticated])
    def me(self, request):
        """
        Получение профиля текущего пользователя.
        Требуется аутентификация.
        """
        serializer = ProfileSerializer(request.user, context={"request": request})
        return Response(serializer.data)
