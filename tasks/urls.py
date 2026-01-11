
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BlockingTasksWithAssignmentsView, BusyEmployeesView, CommentViewSet, DepartmentStatisticsView,
    EmployeeSuggestionView, ImportantTasksView, TaskViewSet)


router = DefaultRouter()
router.register(r"tasks", TaskViewSet, basename="task")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "tasks/<int:task_pk>/comments/",
        CommentViewSet.as_view({"get": "list", "post": "create"}),
        name="task-comments",
    ),
    path(
        "tasks/<int:task_pk>/comments/<int:pk>/",
        CommentViewSet.as_view({"get": "retrieve", "delete": "destroy"}),
        name="task-comment-detail",
    ),

    path("employees/busy/", BusyEmployeesView.as_view(), name="busy-employees"),
    path("important-tasks/blocking/", ImportantTasksView.as_view(), name="blocking-tasks"),
    path("important-tasks/<int:task_id>/suggestions/", EmployeeSuggestionView.as_view(), name="task-suggestions"),
    path(
        "important-tasks/with-assignments/",
        BlockingTasksWithAssignmentsView.as_view(),
        name="blocking-tasks-assignments",
    ),
    path("statistics/departments/", DepartmentStatisticsView.as_view(), name="department-statistics"),
]
