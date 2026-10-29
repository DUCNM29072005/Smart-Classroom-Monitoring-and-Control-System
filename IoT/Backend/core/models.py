from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, full_name='', email=None, **extra):
        if not username:
            raise ValueError('Username bắt buộc')
        user = self.model(
            username=username,
            full_name=full_name or username,
            email=email,
            **extra
        )
        user.set_password(password)  # lưu vào cột password_hash
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        extra.setdefault('status', 'ACTIVE')
        extra.setdefault('is_staff', True)
        extra.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=50, unique=True)
    # AbstractBaseUser.password → map sang password_hash
    password = models.CharField(max_length=255, db_column='password_hash')
    full_name = models.CharField(max_length=100)
    email = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20)  # ACTIVE / LOCKED / ...
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    last_login = models.DateTimeField(null=True, blank=True, db_column='last_login_at')

    # Cần cho Django admin (không có trong spec — có thể bỏ admin nếu không dùng)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'users'

    def save(self, *args, **kwargs):
        now = timezone.now()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now
        if not self.status:
            self.status = 'ACTIVE'
        super().save(*args, **kwargs)


class SensorReading(models.Model):
    temperature = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(-50), MaxValueValidator(100)]
    )
    humidity = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    light_level = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)]
    )

    class Meta:
        db_table = 'sensor_readings'


class Sensor(models.Model):
    code = models.CharField(
        max_length=50, unique=True,
        help_text="Mã kỹ thuật: temperature, humidity, light, wind, ..."
    )
    name = models.CharField(max_length=100, help_text="Tên hiển thị: Cảm biến gió")
    unit = models.CharField(max_length=20, blank=True, default='', help_text="m/s, °C, %...")
    measure = models.CharField(
        max_length=100, blank=True, default='',
        help_text="Đại lượng đo: tốc độ gió, nhiệt độ, ..."
    )
    is_active = models.BooleanField(default=True)
    color = models.CharField(max_length=20, blank=True, default='#3b82f6')  # màu chart
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.name} ({self.code})'

class SensorData(models.Model):
    sensor_type = models.CharField(max_length=50)  # temperature / humidity / light
    value = models.DecimalField(max_digits=10, decimal_places=2)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'sensor_data'


class Device(models.Model):
    name = models.CharField(max_length=100, unique=True)
    type = models.CharField(max_length=50)   # LIGHT / FAN / ...
    led_number = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        unique=True,
    )
    status = models.CharField(max_length=20, default='OFF')  # ON / OFF / ...
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'devices'


class DeviceControlLog(models.Model):
    device = models.ForeignKey(
        Device, on_delete=models.CASCADE,
        db_column='device_id', related_name='logs'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        db_column='user_id', related_name='control_logs'
    )
    action = models.CharField(max_length=10)           # ON / OFF
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'device_control_logs'