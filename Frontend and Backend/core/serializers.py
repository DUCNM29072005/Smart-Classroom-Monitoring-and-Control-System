from rest_framework import serializers
from django.contrib.auth import authenticate
from django.utils import timezone

from .models import User, SensorReading, SensorData, Device, DeviceControlLog


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        username = attrs.get('username', '').strip()
        password = attrs.get('password', '')
        if not username or not password:
            raise serializers.ValidationError('Vui lòng nhập đầy đủ username và password')

        user = authenticate(username=username, password=password)
        if user is None:
            raise serializers.ValidationError('Tên đăng nhập hoặc mật khẩu không đúng')
        if getattr(user, 'status', 'ACTIVE') != 'ACTIVE' or not user.is_active:
            raise serializers.ValidationError('Tài khoản không hoạt động')

        attrs['user'] = user
        return attrs


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'full_name')


class SensorLatestSerializer(serializers.Serializer):
    temperature = serializers.DecimalField(max_digits=5, decimal_places=2)
    humidity = serializers.DecimalField(max_digits=5, decimal_places=2)
    light_level = serializers.DecimalField(max_digits=10, decimal_places=2)
    recorded_at = serializers.DateTimeField(allow_null=True)


class SensorDataSerializer(serializers.ModelSerializer):
    class Meta:
        model = SensorData
        fields = ('id', 'sensor_type', 'value', 'recorded_at')


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ('id', 'name', 'type', 'status', 'is_active', 'updated_at')


class DeviceControlSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['ON', 'OFF'])


class ControlLogSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source='device.name', read_only=True)
    user_name = serializers.CharField(source='user.full_name', read_only=True)

    class Meta:
        model = DeviceControlLog
        fields = (
            'id', 'device_name', 'user_name', 'action',
            'previous_status', 'new_status', 'created_at',
        )