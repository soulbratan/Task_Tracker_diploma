from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Comment, Task


class TaskAdminForm(forms.ModelForm):
    """Форма для админки задач"""

    class Meta:
        model = Task
        exclude = ["created_by"]  # Заполняется автоматически (исключаем из формы)


class CommentInline(admin.TabularInline):
    """Inline для комментариев"""

    model = Comment
    extra = 0
    readonly_fields = ["author", "content", "created_at"]

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request, obj=None):
        return False


class SubtaskInline(admin.TabularInline):
    """Inline для подзадач"""

    model = Task
    fk_name = "parent"
    extra = 0
    readonly_fields = ["status_display", "priority_display", "assignee_display", "owner_display", "deadline"]
    fields = ["title", "status_display", "priority_display", "assignee_display", "owner_display", "deadline"]
    show_change_link = True

    def status_display(self, obj):
        return obj.get_status_display()

    status_display.short_description = _("Статус")

    def priority_display(self, obj):
        return obj.get_priority_display()

    priority_display.short_description = _("Приоритет")

    def assignee_display(self, obj):
        """Безопасное отображение исполнителя без ссылок"""
        if obj.assignee and obj.assignee.employee:
            return obj.assignee.employee.get_full_name()
        return "-"

    assignee_display.short_description = _("Исполнитель")

    def owner_display(self, obj):
        """Безопасное отображение владельца без ссылок"""
        if obj.owner and obj.owner.employee:
            return obj.owner.employee.get_full_name()
        return "-"

    owner_display.short_description = _("Владелец")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskAdminForm
    list_display = [
        "title_short",
        "status_display",
        "priority_display",
        "owner_display",
        "assignee_display",
        "deadline",
        "is_overdue_display",
    ]
    list_filter = ["status", "priority", "created_at"]
    search_fields = ["title", "description"]
    readonly_fields = ["created_at", "updated_at", "completed_at", "created_by"]
    inlines = [CommentInline, SubtaskInline]

    def get_fieldsets(self, request, obj=None):
        """
        Динамическое формирование fieldsets:
        - При создании: не показываем created_by
        - При редактировании: показываем created_by только для чтения
        """
        if obj:  # При редактировании существующей задачи
            return (
                (None, {"fields": ("title", "description", "parent")}),
                (_("Назначение"), {"fields": ("owner", "assignee", "status", "priority")}),
                (_("Сроки"), {"fields": ("deadline", "completed_at")}),
                (
                    _("Мета информация"),
                    {"fields": ("created_at", "updated_at", "created_by"), "classes": ("collapse",)},
                ),
            )
        else:  # При создании новой задачи
            return (
                (None, {"fields": ("title", "description", "parent")}),
                (_("Назначение"), {"fields": ("owner", "assignee", "status", "priority")}),
                (_("Сроки"), {"fields": ("deadline", "completed_at")}),
            )

    def title_short(self, obj):
        if obj.title and len(obj.title) > 50:
            return obj.title[:47] + "..."
        return obj.title or "-"

    title_short.short_description = _("Название")

    def status_display(self, obj):
        return obj.get_status_display()

    status_display.short_description = _("Статус")

    def priority_display(self, obj):
        return obj.get_priority_display()

    priority_display.short_description = _("Приоритет")

    def owner_display(self, obj):
        """Безопасное отображение владельца без ссылок"""
        if obj.owner and obj.owner.employee:
            return obj.owner.employee.get_full_name()
        return "-"

    owner_display.short_description = _("Владелец")

    def assignee_display(self, obj):
        """Безопасное отображение исполнителя без ссылок"""
        if obj.assignee and obj.assignee.employee:
            return obj.assignee.employee.get_full_name()
        return "-"

    assignee_display.short_description = _("Исполнитель")

    def is_overdue_display(self, obj):
        if obj.is_overdue:
            return "⚠"
        return ""

    is_overdue_display.short_description = _("Просрочена")

    def save_model(self, request, obj, form, change):
        """
        Сохранение модели с автоматическим управлением статусом
        """
        if not change:
            # Автоматически устанавливаем создателя из текущего пользователя
            obj.created_by = request.user

        # Автоматически устанавливаем статус "Назначена" при назначении исполнителя
        if obj.assignee:
            if not change:  # При создании
                obj.status = Task.TaskStatus.ASSIGNED
            elif change and "assignee" in form.changed_data:  # При изменении
                obj.status = Task.TaskStatus.ASSIGNED
        elif not obj.assignee and obj.status == Task.TaskStatus.ASSIGNED:
            # Если сняли исполнителя и статус был "Назначена"
            obj.status = Task.TaskStatus.CREATED

        super().save_model(request, obj, form, change)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["task_title_display", "author_display", "content_preview", "created_at_display"]
    list_filter = ["task", "author", "created_at"]
    search_fields = ["content", "author__email", "task__title", "author__last_name", "author__first_name"]
    readonly_fields = ["task_link", "author_link", "content_display", "created_at_display", "updated_at_display"]
    fields = ["task_link", "author_link", "content_display", "created_at_display", "updated_at_display"]
    ordering = ["-created_at"]

    def get_list_filter(self, request):
        """Динамический список фильтров"""
        base_filters = ["created_at", "author"]

        task_count = Task.objects.count()
        if task_count <= 50:  # Если задач не более 50, добавляем фильтр
            return ["task"] + base_filters
        else:
            # Иначе добавляем поисковое поле вместо фильтра
            return base_filters

    def get_search_fields(self, request):
        """Расширенные поля поиска"""
        return [
            "content",
            "author__email",
            "author__last_name",
            "author__first_name",
            "author__middle_name",
            "task__title",
            "task__id",  # Можно искать и по ID задачи
        ]

    def get_queryset(self, request):
        """Оптимизация запросов"""
        return super().get_queryset(request).select_related("task", "author")

    def task_title_display(self, obj):
        """Отображение задачи с названием вместо номера"""
        if obj.task:
            task_title = obj.task.title
            if len(task_title) > 50:
                task_title = task_title[:47] + "..."
            return f"#{obj.task.id}: {task_title}"
        return f"#{obj.task.id}"

    task_title_display.short_description = "Задача"
    task_title_display.admin_order_field = "task__title"  # Сортировка по названию задачи

    def task_link(self, obj):
        """Ссылка на задачу в детальном просмотре"""
        if obj.task:
            url = reverse("admin:tasks_task_change", args=[obj.task.id])
            task_title = obj.task.title
            if len(task_title) > 80:
                task_title = task_title[:77] + "..."
            return format_html('<a href="{}">{}</a>', url, f"#{obj.task.id}: {task_title}")
        return "-"

    task_link.short_description = "Задача"

    def author_display(self, obj):
        """Отображение автора в списке"""
        if obj.author:
            return obj.author.get_full_name()
        return "-"

    author_display.short_description = "Автор"
    author_display.admin_order_field = "author__last_name"

    def author_link(self, obj):
        """Ссылка на автора в детальном просмотре"""
        if obj.author:
            url = reverse("admin:users_user_change", args=[obj.author.id])
            return format_html('<a href="{}">{}</a>', url, obj.author.get_full_name())
        return "-"

    author_link.short_description = "Автор"

    def content_preview(self, obj):
        """Превью комментария в списке"""
        if obj.content:
            # Убираем лишние пробелы и переносы
            content = " ".join(obj.content.split())
            if len(content) > 100:
                return content[:97] + "..."
            return content
        return "-"

    content_preview.short_description = "Комментарий"

    def content_display(self, obj):
        """Полное отображение комментария в детальном просмотре"""
        if obj.content:
            # Сохраняем форматирование с переносами строк
            return format_html(
                '<div style="white-space: pre-wrap; padding: 10px; background: #f8f8f8; border-radius: 5px;">{}</div>',
                obj.content,
            )
        return "-"

    content_display.short_description = "Текст комментария"

    def created_at_display(self, obj):
        """Форматированное отображение даты создания"""
        if obj.created_at:
            return obj.created_at.strftime("%d.%m.%Y %H:%M:%S")
        return "-"

    created_at_display.short_description = "Дата создания"

    def updated_at_display(self, obj):
        """Форматированное отображение даты обновления"""
        if obj.updated_at:
            return obj.updated_at.strftime("%d.%m.%Y %H:%M:%S")
        return "-"

    updated_at_display.short_description = "Дата обновления"

    def get_form(self, request, obj=None, **kwargs):
        """Кастомизация формы для добавления/изменения"""
        form = super().get_form(request, obj, **kwargs)

        for field_name in form.base_fields:
            form.base_fields[field_name].required = False

        return form

    def has_add_permission(self, request):
        """Запрещаем создание комментариев через админку"""
        return False

    def has_change_permission(self, request, obj=None):
        """Запрещаем редактирование комментариев через админку"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Разрешаем удаление только суперпользователям и администраторам"""
        if request.user.is_superuser:
            return True

        # Проверяем, является ли пользователь администратором через должность
        from organization.models import Position

        is_admin = Position.objects.filter(employee=request.user, level="admin", is_active=True).exists()

        return is_admin

    # Добавляем action для массового удаления (только для админов)
    actions = ["delete_selected_comments"]

    def delete_selected_comments(self, request, queryset):
        """Массовое удаление комментариев с проверкой прав"""
        # Проверяем права на удаление
        if not self.has_delete_permission(request):
            self.message_user(request, "У вас нет прав на удаление комментариев", level="error")
            return

        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"Удалено {count} комментариев")

    delete_selected_comments.short_description = "Удалить выбранные комментарии"
