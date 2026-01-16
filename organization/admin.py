from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Department, Position


class PositionInline(admin.TabularInline):
    """Inline для отображения должностей в отделе"""

    model = Position
    extra = 0
    fields = ["name", "level_display", "employee_link", "is_active"]
    readonly_fields = ["level_display", "employee_link", "created_at", "updated_at"]
    show_change_link = True

    def level_display(self, obj):
        return obj.get_level_display()

    level_display.short_description = _("Уровень")

    def employee_link(self, obj):
        if obj.employee:
            url = f"/admin/users/user/{obj.employee.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.employee.get_full_name())
        return "Вакантно"

    employee_link.short_description = _("Сотрудник")

    def get_queryset(self, request):
        """Оптимизация запросов"""
        return super().get_queryset(request).select_related("employee", "department")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "parent_link", "level", "positions_count", "employees_count", "created_at"]
    list_filter = ["parent", "created_at"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at", "updated_at", "level_display", "full_path"]
    fieldsets = (
        (None, {"fields": ("name", "parent", "description")}),
        (_("Иерархия"), {"fields": ("full_path", "level_display"), "classes": ("collapse",)}),
        (_("Мета информация"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
    inlines = [PositionInline]  # ← УБРАЛИ DepartmentChildrenInline

    def parent_link(self, obj):
        if obj.parent:
            url = f"/admin/organization/department/{obj.parent.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.parent.name)
        return "-"

    parent_link.short_description = _("Родительский отдел")
    parent_link.admin_order_field = "parent__name"

    def level_display(self, obj):
        return obj.level

    level_display.short_description = _("Уровень вложенности")

    def full_path(self, obj):
        return obj.get_full_path()

    full_path.short_description = _("Полный путь")

    def positions_count(self, obj):
        return obj.positions.count()

    positions_count.short_description = _("Должностей")

    def employees_count(self, obj):
        return obj.positions.filter(employee__isnull=False).count()

    employees_count.short_description = _("Сотрудников")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("parent").prefetch_related("positions", "positions__employee")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ["name", "level_display", "department_link", "employee_link", "is_active", "created_at"]
    list_filter = ["level", "is_active", "department", "created_at"]
    search_fields = ["name", "department__name", "employee__email", "employee__last_name", "employee__first_name"]
    readonly_fields = ["created_at", "updated_at"]
    list_select_related = ["department", "employee"]

    fieldsets = (
        (None, {"fields": ("name", "level", "department", "employee", "is_active")}),
        (_("Мета информация"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def level_display(self, obj):
        return obj.get_level_display()  # ← ИСПРАВЛЕНО: get_level_display()

    level_display.short_description = _("Уровень")
    level_display.admin_order_field = "level"

    def department_link(self, obj):
        if obj.department:
            url = f"/admin/organization/department/{obj.department.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.department.name)
        return "-"

    department_link.short_description = _("Отдел")
    department_link.admin_order_field = "department__name"

    def employee_link(self, obj):
        if obj.employee:
            url = f"/admin/users/user/{obj.employee.id}/change/"
            return format_html('<a href="{}">{}</a>', url, obj.employee.get_full_name())
        return "Вакантно"

    employee_link.short_description = _("Сотрудник")
    employee_link.admin_order_field = "employee__last_name"

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related("department", "employee")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Фильтрация выбора сотрудника"""
        if db_field.name == "employee":
            # Показываем только активных пользователей
            kwargs["queryset"] = db_field.related_model.objects.filter(is_active=True).order_by(
                "last_name", "first_name"
            )
        elif db_field.name == "department":
            # Упорядочиваем отделы
            kwargs["queryset"] = db_field.related_model.objects.all().order_by("name")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        """
        При сохранении должности в админке гарантируем обновление пользователя.
        """
        old_employee = None
        if change and obj.pk:
            try:
                old_position = Position.objects.get(pk=obj.pk)
                old_employee = old_position.employee
            except Position.DoesNotExist:
                pass

        # Сохраняем должность (сигналы обновят пользователя)
        super().save_model(request, obj, form, change)

        # Явное обновление для надежности
        if obj.employee and obj.employee != old_employee:
            self.message_user(
                request,
                f"Сотрудник {obj.employee.email} назначен на должность. " f"Поля отдела и должности обновлены.",
            )

    actions = ["deactivate_positions", "activate_positions", "update_user_fields"]

    def deactivate_positions(self, request, queryset):
        """Деактивация выбранных должностей"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} должностей деактивировано")

    deactivate_positions.short_description = _("Деактивировать выбранные должности")

    def activate_positions(self, request, queryset):
        """Активация выбранных должностей"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} должностей активировано")

    activate_positions.short_description = _("Активировать выбранные должности")

    def update_user_fields(self, request, queryset):
        """
        Принудительное обновление полей пользователей для выбранных должностей.
        """
        updated = 0
        for position in queryset.filter(is_active=True, employee__isnull=False):
            try:
                position.employee.department = position.department.name if position.department else None
                position.employee.position = position.name
                position.employee.save(update_fields=["department", "position"])
                updated += 1
            except Exception as e:
                self.message_user(request, f"Ошибка обновления {position}: {e}", level="error")

        self.message_user(request, f"Обновлено {updated} пользователей")

    update_user_fields.short_description = _("Обновить поля пользователей")
