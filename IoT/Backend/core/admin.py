from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, SensorReading, SensorData, Device, DeviceControlLog


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'full_name', 'email', 'status')
    ordering = ('username',)
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Thông tin', {'fields': ('full_name', 'email', 'status')}),
        ('Quyền', {'fields': ('is_staff', 'is_superuser', 'is_active')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'full_name', 'email', 'password1', 'password2', 'status'),
        }),
    )


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'type',
        'led_number',
        'status',
        'is_active',
        'updated_at',
    )

    list_filter = ('type', 'status', 'is_active')
    search_fields = ('name',)
    list_editable = ('led_number', 'status', 'is_active')
    ordering = ('id',)

    def get_changeform_initial_data(self, request):
        return {
            'status': 'OFF',
            'is_active': True,
        }

from .models import Sensor  # + các model khác

@admin.register(Sensor)
class SensorAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'measure', 'unit', 'is_active', 'color')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')
    list_editable = ('is_active',)

admin.site.register(SensorReading)
admin.site.register(SensorData)
admin.site.register(DeviceControlLog)
# KHÔNG register(Device) nữa — đã có @admin.register(Device)