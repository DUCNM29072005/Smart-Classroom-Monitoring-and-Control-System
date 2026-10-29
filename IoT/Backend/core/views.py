import threading
import time
import unicodedata

from django.conf import settings
from django.db import connection
from django.db.models import Q, CharField, Value
from django.db.models.functions import (
    Cast, Concat, LPad,
    ExtractDay, ExtractMonth, ExtractYear,
    ExtractHour, ExtractMinute, ExtractSecond,
)
from django.utils import timezone
from rest_framework import status, generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken

# [SỬA] thêm Sensor vào import (trước đây thiếu -> SensorCatalogView bị NameError)
from .models import User, Sensor, SensorReading, SensorData, Device, DeviceControlLog
from .serializers import (
    LoginSerializer, UserBriefSerializer,
    SensorDataSerializer, DeviceSerializer, DeviceControlSerializer,
    ControlLogSerializer,
)
from .mqtt_publish import publish_led_command, device_to_led_id


def _norm(text):
    return unicodedata.normalize('NFC', (text or '')).strip().lower()


from django.db.models import Func, F, CharField, Value

class DateFormat(Func):
    function = 'DATE_FORMAT'
    output_field = CharField()
    arity = 2


def _time_text(field_name):
    """Một chuỗi gộp: 2026-10-22 09:28:19 (giờ VN +07)."""
    local_dt = Func(
        F(field_name),
        Value('+00:00'),
        Value('+07:00'),
        function='CONVERT_TZ',
    )
    return DateFormat(local_dt, Value('%Y-%m-%d %H:%i:%s'))


def _filter_time_contains(qs, field_name, time_q):
    time_q = (time_q or '').strip().replace('/', '-')
    # gộp khoảng trắng đôi → một space
    while '  ' in time_q:
        time_q = time_q.replace('  ', ' ')
    if not time_q:
        return qs
    return qs.annotate(_tstr=_time_text(field_name)).filter(
        _tstr__icontains=time_q
    )

def _page_params(request, default_size=8):
    try:
        page = max(1, int(request.query_params.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        size = min(50, max(1, int(request.query_params.get('page_size', default_size))))
    except (TypeError, ValueError):
        size = default_size
    return page, size


def _is_asc(request, default='desc'):
    return (request.query_params.get('order') or default).strip().lower() == 'asc'


def _bad_request(message):
    return Response(
        {'success': False, 'message': message},
        status=status.HTTP_400_BAD_REQUEST,
    )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ser = LoginSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {'success': False, 'message': ser.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = ser.validated_data['user']
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])

        token = str(AccessToken.for_user(user))
        return Response({
            'success': True,
            'message': 'Đăng nhập thành công',
            'data': {
                'access_token': token,
                'user': UserBriefSerializer(user).data,
            },
        })


class SensorCatalogView(APIView):
    """Danh sách cảm biến đang bật (do admin thêm) để frontend dựng biểu đồ / bộ lọc."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Sensor.objects.filter(is_active=True).order_by('id')
        return Response({'data': [
            {
                'id': s.id, 'code': s.code, 'name': s.name,
                'measure': s.measure, 'unit': s.unit, 'color': s.color,
            } for s in rows
        ]})


class SensorLatestView(APIView):
    """
    Giá trị mới nhất.
    - Giữ nguyên temperature / humidity / light_level (frontend cũ vẫn chạy).
    - [MỚI] 'values': giá trị mới nhất của TỪNG cảm biến trong catalog, key = code.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        reading = SensorReading.objects.order_by('-id').first()

        values = {}
        for s in Sensor.objects.filter(is_active=True).order_by('id'):
            d = (
                SensorData.objects
                .filter(sensor_type=s.code)
                .order_by('-id')
                .first()
            )
            if d:
                values[s.code] = {
                    'value': d.value,
                    'recorded_at': d.recorded_at,
                }

        if not reading and not values:
            return Response({'data': None, 'message': 'Chưa có dữ liệu cảm biến'})

        # Ưu tiên recorded_at của dòng sensor_data mới nhất
        latest_data = SensorData.objects.order_by('-id').first()
        if latest_data and latest_data.recorded_at:
            recorded_at = latest_data.recorded_at
        else:
            recorded_at = timezone.now()

        return Response({
            'data': {
                'temperature': reading.temperature if reading else None,
                'humidity': reading.humidity if reading else None,
                'light_level': reading.light_level if reading else None,
                'values': values,
                'recorded_at': recorded_at,
            }
        })


class SensorListView(APIView):
    permission_classes = [IsAuthenticated]

    SENSOR_ALIASES = {
        '': '', 'all': '', 'tất cả': '',
        'temperature': 'temperature', 'temp': 'temperature', 'nhiệt độ': 'temperature',
        'humidity': 'humidity', 'hum': 'humidity', 'độ ẩm': 'humidity',
        'light': 'light', 'bh1750': 'light', 'ánh sáng': 'light',
        'time': 'time', 'thời gian': 'time', 'thoi_gian': 'time',
        'dht': 'dht', 'dht11': 'dht',
    }

    def get(self, request):
        sensor_raw = _norm(request.query_params.get('sensor'))

        # [SỬA] ngoài alias cứng, chấp nhận mọi code cảm biến do admin thêm
        if sensor_raw in self.SENSOR_ALIASES:
            sensor = self.SENSOR_ALIASES[sensor_raw]
        else:
            s = Sensor.objects.filter(code__iexact=sensor_raw).first()
            if not s:
                return _bad_request('Loại cảm biến không hợp lệ')
            sensor = s.code

        value_q = (request.query_params.get('value') or '').strip()
        time_q = (request.query_params.get('time') or '').strip()

        qs = SensorData.objects.all()

        # --- Lọc theo loại cảm biến ---
        if sensor == 'time':
            # Chỉ tìm theo thời gian (ô value hoặc time)
            text = value_q or time_q
            if text:
                qs = _filter_time_contains(qs, 'recorded_at', text)
        else:
            if sensor in ('temperature', 'humidity', 'light'):
                qs = qs.filter(sensor_type=sensor)
            elif sensor == 'dht':
                qs = qs.filter(sensor_type__in=['temperature', 'humidity'])
            elif sensor:
                # [MỚI] cảm biến thêm từ admin (vd: wind)
                qs = qs.filter(sensor_type=sensor)
            # sensor == '' / all → không filter type

            if value_q:
                # Tìm trong giá trị HOẶC chuỗi thời gian YYYY-MM-DD HH:MM:SS
                v = value_q.replace(',', '.')
                t = value_q.replace('/', '-')
                qs = qs.annotate(
                    value_text=Cast('value', output_field=CharField()),
                    time_text=_time_text('recorded_at'),
                ).filter(
                    Q(value_text__icontains=v) | Q(time_text__icontains=t)
                )
            elif time_q:
                qs = _filter_time_contains(qs, 'recorded_at', time_q)

        # --- Sắp xếp ---
        asc = _is_asc(request)
        if (request.query_params.get('sort') or '').strip().lower() == 'id':
            qs = qs.order_by('id' if asc else '-id')
        else:
            qs = qs.order_by(
                'recorded_at' if asc else '-recorded_at',
                'id' if asc else '-id',
            )

        count = qs.count()
        page, size = _page_params(request, default_size=6)
        start = (page - 1) * size
        rows = qs[start:start + size]
        return Response({
            'data': SensorDataSerializer(rows, many=True).data,
            'count': count,
            'page': page,
            'page_size': size,
        })


class DeviceListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeviceSerializer
    queryset = Device.objects.filter(is_active=True).order_by('id')

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        ser = self.get_serializer(qs, many=True)
        return Response({'data': ser.data})


class DeviceControlView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, device_id):
        try:
            device = Device.objects.get(pk=device_id, is_active=True)
        except Device.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Thiết bị không tồn tại'},
                status=status.HTTP_404_NOT_FOUND,
            )

        ser = DeviceControlSerializer(data=request.data)
        if not ser.is_valid():
            return Response(
                {'success': False, 'message': ser.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = ser.validated_data['action']
        previous = device.status

        # --- Mạch online? (có dữ liệu cảm biến mới trong 5 giây) ---
        latest = SensorData.objects.order_by('-id').first()
        circuit_ok = False
        if latest and latest.recorded_at:
            age = (timezone.now() - latest.recorded_at).total_seconds()
            circuit_ok = age <= 5

        if not circuit_ok:
            return Response(
                {
                    'success': False,
                    'message': 'Vui lòng kết nối với mạch',
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # --- LOADING ---
        device.status = 'LOADING'
        device.save(update_fields=['status', 'updated_at'])
        DeviceControlLog.objects.create(
            device=device,
            user=request.user,
            action=action,
            previous_status=previous,
            new_status='LOADING',
        )

        led_id = device_to_led_id(device)
        ok = publish_led_command(led_id, action)

        if not ok:
            device.status = previous
            device.save(update_fields=['status', 'updated_at'])
            DeviceControlLog.objects.create(
                device=device,
                user=request.user,
                action=action,
                previous_status='LOADING',
                new_status=previous,
            )
            return Response(
                {
                    'success': False,
                    'message': 'Không gửi được lệnh MQTT / mạch không nhận',
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        device.status = action
        device.save(update_fields=['status', 'updated_at'])
        DeviceControlLog.objects.create(
            device=device,
            user=request.user,
            action=action,
            previous_status='LOADING',
            new_status=action,
        )

        return Response({
            'success': True,
            'message': 'Điều khiển thiết bị thành công',
            'data': {
                'device_id': device.id,
                'status': device.status,
                'updated_at': device.updated_at,
            },
        })


# ---------------------------------------------------------------------------
# Nháy LED cảnh báo (vd: CO2 vượt ngưỡng) — không ghi log mỗi lần đổi trạng thái
# ---------------------------------------------------------------------------
_BLINK = {}                 # device_id -> {'stop': Event, 'last': timestamp}
_BLINK_LOCK = threading.Lock()
BLINK_INTERVAL = 0.5        # giây giữa 2 lần đổi ON/OFF
BLINK_TTL = 30              # tự dừng nếu 30s không có keepalive từ frontend


def _blink_worker(device_id, led_id, state):
    on = True
    try:
        while not state['stop'].is_set() and (time.time() - state['last']) < BLINK_TTL:
            publish_led_command(led_id, 'ON' if on else 'OFF')
            on = not on
            state['stop'].wait(BLINK_INTERVAL)
    finally:
        try:
            # Trả đèn về trạng thái đang lưu trong DB
            st = Device.objects.filter(pk=device_id).values_list('status', flat=True).first()
            publish_led_command(led_id, st if st in ('ON', 'OFF') else 'OFF')
        finally:
            with _BLINK_LOCK:
                if _BLINK.get(device_id) is state:
                    _BLINK.pop(device_id, None)
            connection.close()


class DeviceBlinkView(APIView):
    """POST /devices/<id>/blink  body: {"on": true|false}
    on=true : bắt đầu nháy (hoặc gia hạn nếu đang nháy — frontend gọi lại mỗi ~10s)
    on=false: dừng nháy, đèn trở về trạng thái trước đó."""
    permission_classes = [IsAuthenticated]

    def post(self, request, device_id):
        try:
            device = Device.objects.get(pk=device_id, is_active=True)
        except Device.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Thiết bị không tồn tại'},
                status=status.HTTP_404_NOT_FOUND,
            )

        on = request.data.get('on') in (True, 'true', 'True', '1', 1)
        started = stopped = False
        with _BLINK_LOCK:
            state = _BLINK.get(device.id)
            if on:
                if state:
                    state['last'] = time.time()
                else:
                    state = {'stop': threading.Event(), 'last': time.time()}
                    _BLINK[device.id] = state
                    threading.Thread(
                        target=_blink_worker,
                        args=(device.id, device_to_led_id(device), state),
                        daemon=True,
                    ).start()
                    started = True
            elif state:
                state['stop'].set()
                stopped = True

        if started or stopped:
            DeviceControlLog.objects.create(
                device=device,
                user=request.user,
                action='BLINK_ON' if started else 'BLINK_OFF',
                previous_status=device.status,
                new_status=device.status,
            )
        return Response({'success': True, 'blinking': on})


class ControlHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    ACTION_MAP = {
        'on': 'ON', 'bật': 'ON', 'bat': 'ON',
        'off': 'OFF', 'tắt': 'OFF', 'tat': 'OFF',
        'blink_on': 'BLINK_ON', 'nháy': 'BLINK_ON', 'nhay': 'BLINK_ON', 'blink': 'BLINK_ON',
        'blink_off': 'BLINK_OFF', 'dừng nháy': 'BLINK_OFF', 'dung nhay': 'BLINK_OFF',
        'stop_blink': 'BLINK_OFF', 'stop': 'BLINK_OFF',
    }
    DEVICE_KEYWORDS = {
        'light': ('đèn', 'den', 'light', 'led'),
        'fan': ('quạt', 'quat', 'fan'),
    }

    def _device_ids(self, key):
        words = self.DEVICE_KEYWORDS[key]
        ids = []
        for d in Device.objects.all():
            text = ' '.join(
                str(getattr(d, f, '') or '') for f in ('name', 'type')
            ).lower()
            if any(w in text for w in words):
                ids.append(d.id)
        return ids

    def get(self, request):
        qs = DeviceControlLog.objects.select_related('device', 'user')
        p = request.query_params

        device_id = (p.get('device_id') or '').strip()
        device_q = (request.query_params.get('device') or '').strip()
        if device_id.isdigit():
            qs = qs.filter(device_id=int(device_id))
        elif device_q.isdigit():
            qs = qs.filter(device_id=int(device_q))
        elif device_q in self.DEVICE_KEYWORDS:
            qs = qs.filter(device_id__in=self._device_ids(device_q))
        elif device_q not in ('', 'all'):
            return _bad_request('Thiết bị không hợp lệ')

        action_q = _norm(p.get('action'))
        if action_q not in ('', 'all'):
            action = self.ACTION_MAP.get(action_q)
            if not action:
                return _bad_request('Thao tác không hợp lệ')
            qs = qs.filter(action=action)

        status_q = (p.get('status') or '').strip().upper()
        if status_q not in ('', 'ALL'):
            if status_q not in ('ON', 'OFF', 'LOADING'):
                return _bad_request('Trạng thái không hợp lệ')
            qs = qs.filter(Q(previous_status=status_q) | Q(new_status=status_q))

        time_q = (p.get('time') or '').strip()
        if time_q:
            qs = _filter_time_contains(qs, 'created_at', time_q)

        qs = qs.order_by('id' if _is_asc(request) else '-id')

        count = qs.count()
        page, size = _page_params(request, default_size=5)
        start = (page - 1) * size
        rows = qs[start:start + size]
        return Response({
            'data': ControlLogSerializer(rows, many=True).data,
            'count': count,
            'page': page,
            'page_size': size,
        })


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({
            'data': UserBriefSerializer(request.user).data
        })