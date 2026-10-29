import json
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import paho.mqtt.client as mqtt

from core.models import SensorReading, SensorData, Device, DeviceControlLog, Sensor


def to_decimal(value, default=None):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def parse_recorded_at(raw):
    """Chỉ dùng khi cần; realtime nên ưu tiên timezone.now()."""
    if not raw or str(raw).strip().lower() in ('syncing', 'null', 'none', ''):
        return timezone.now()
    m = re.match(
        r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}):(\d{2}):(\d{2})',
        str(raw).strip()
    )
    if m:
        d, mo, y, h, mi, s = m.groups()
        try:
            from datetime import datetime
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone.get_current_timezone())
            return dt
        except ValueError:
            pass
    dt = parse_datetime(str(raw))
    if dt:
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    return timezone.now()


def save_extra_sensors(payload, when):
    """Lưu các cảm biến thêm từ admin (co2, wind, ...) có trong gói tin.
    Chỉ lưu code có trong bảng Sensor (đang bật). Trả về danh sách code đã lưu."""
    base = {'temperature', 'humidity', 'light'}
    codes = set(Sensor.objects.filter(is_active=True).values_list('code', flat=True)) - base
    rows = []
    for code in codes:
        if code in payload:
            value = to_decimal(payload[code])
            if value is not None:
                rows.append(SensorData(sensor_type=code, value=value, recorded_at=when))
    if rows:
        SensorData.objects.bulk_create(rows)
    return [r.sensor_type for r in rows]


class Command(BaseCommand):
    help = 'Lắng nghe MQTT: sensor + trạng thái LED → MySQL'

    def handle(self, *args, **options):
        host = getattr(settings, 'MQTT_HOST', '127.0.0.1')
        port = int(getattr(settings, 'MQTT_PORT', 1883))
        user = getattr(settings, 'MQTT_USER', None)
        password = getattr(settings, 'MQTT_PASSWORD', None)
        topic_sensor = getattr(settings, 'MQTT_TOPIC_SENSOR', 'iot/sensor/data')
        topic_status = getattr(settings, 'MQTT_TOPIC_LED_STATUS', 'iot/led/+/status')

        def on_connect(client, userdata, flags, reason_code, properties=None):
            # paho v2: reason_code; v1: rc int
            rc = reason_code if isinstance(reason_code, int) else getattr(reason_code, 'value', reason_code)
            if rc == 0:
                self.stdout.write(self.style.SUCCESS(f'MQTT connected {host}:{port}'))
                client.subscribe(topic_sensor)
                client.subscribe(topic_status)
                self.stdout.write(f'Subscribe: {topic_sensor}')
                self.stdout.write(f'Subscribe: {topic_status}')
            else:
                self.stderr.write(f'Connect failed rc={rc}')

        def on_message(client, userdata, msg):
            topic = msg.topic
            payload = msg.payload.decode('utf-8', errors='replace').strip()
            self.stdout.write(f'[{topic}] {payload[:200]}')

            try:
                if topic == topic_sensor or topic.endswith('/sensor/data'):
                    self._handle_sensor(payload)
                elif '/status' in topic and topic.startswith('iot/led/'):
                    self._handle_led_status(topic, payload)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'Error: {e}'))

        # paho-mqtt 2.x
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            client = mqtt.Client()

        if user:
            client.username_pw_set(user, password)

        client.on_connect = on_connect
        client.on_message = on_message

        self.stdout.write(f'Connecting {host}:{port} ...')
        client.connect(host, port, keepalive=60)
        client.loop_forever()

    def _handle_sensor(self, payload):
        data = json.loads(payload)
        temp = to_decimal(data.get('temperature'))
        hum = to_decimal(data.get('humidity'))
        light = to_decimal(data.get('light'))
        if temp is None or hum is None or light is None:
            self.stderr.write('Thiếu temperature/humidity/light')
            return

        # [SỬA] gán `recorded` TRƯỚC khi dùng (trước đây dùng cho co2 khi chưa có giá trị)
        recorded = timezone.now()

        reading = SensorReading.objects.create(
            temperature=temp,
            humidity=hum,
            light_level=light,
        )

        SensorData.objects.bulk_create([
            SensorData(sensor_type='temperature', value=temp, recorded_at=recorded),
            SensorData(sensor_type='humidity', value=hum, recorded_at=recorded),
            SensorData(sensor_type='light', value=light, recorded_at=recorded),
        ])

        # [MỚI] co2 và mọi cảm biến thêm từ admin, cùng thời điểm đo
        extra = save_extra_sensors(data, recorded)
        extra_txt = f' extra={extra}' if extra else ''

        self.stdout.write(self.style.SUCCESS(
            f'Saved reading id={reading.id} T={temp} H={hum} L={light}{extra_txt}'
        ))

    def _handle_led_status(self, topic, payload):
        parts = topic.split('/')

        try:
            led_num = int(parts[2])  # iot/led/4/status → 4
        except (IndexError, ValueError):
            return

        # LƯU Ý: dòng dưới là placeholder `...` nên hàm này luôn return ở bước kiểm tra ON/OFF.
        # Giữ nguyên như file gốc của bạn (xem ghi chú trong câu trả lời).
        state = ...  # Parse ON/OFF như cũ
        if state not in ('ON', 'OFF'):
            return

        # Tìm device có số LED trong tên, không có thì tạo
        name = f'LED {led_num}'
        device = None

        for d in Device.objects.filter(is_active=True):
            import re

            m = re.search(r'\d+', d.name or '')
            if m and int(m.group()) == led_num:
                device = d
                break

        if device is None:
            device, _ = Device.objects.get_or_create(
                name=name,
                defaults={
                    'type': 'LIGHT',
                    'status': 'OFF',
                    'is_active': True,
                },
            )

        old = device.status
        if old == state:
            return

        device.status = state
        device.save(update_fields=['status', 'updated_at'])

        self.stdout.write(
            self.style.SUCCESS(f'{device.name}: {old} → {state}')
        )