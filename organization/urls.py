from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DepartmentViewSet, EmployeeListView, OrganizationView, PositionViewSet

router = DefaultRouter()
router.register(r"departments", DepartmentViewSet, basename="department")
router.register(r"positions", PositionViewSet, basename="position")

urlpatterns = [
    path("", include(router.urls)),
    path("organization/chart/", OrganizationView.as_view(), name="organization-chart"),
    path("employees/", EmployeeListView.as_view(), name="employee-list"),
]
