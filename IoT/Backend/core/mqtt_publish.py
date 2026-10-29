import logging
import re
import threading
import unicodedata
from typing import Optional

import paho.mqtt.client as mqtt
from django.conf import settings

logger = logging.getLogger(__name__)

VALID_LEDS = range(1, 21)

_client = None
_lock = threading.Lock()


def _get_client():
    """Client dùng chung cho cả process, tự reconnect nhờ loop_start()."""
    global _client
    with _lock:
        if _client is None:
            try:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            except AttributeError:  # paho-mqtt 1.x
                c = mqtt.Client()

            user = getattr(settings, 'MQTT_USER', None)
            if user:
                c.username_pw_set(user, getattr(settings, 'MQTT_PASSWORD', None))

            c.connect(
                getattr(settings, 'MQTT_HOST', '127.0.0.1'),
                int(getattr(settings, 'MQTT_PORT', 1883)),
                keepalive=30,
            )
            c.loop_start()
            _client = c
        return _client


def publish_led_command(led_number: int, action: str) -> bool:
    """Publish ON/OFF lên iot/led/{n}. action: 'ON' | 'OFF'."""
    action = (action or '').upper()
    if action not in ('ON', 'OFF'):
        logger.warning("Invalid LED action: %r", action)
        return False

    if led_number not in VALID_LEDS:
        logger.warning("Invalid LED number: %r", led_number)
        return False

    topic = getattr(settings, f'MQTT_TOPIC_LED_{led_number}', f'iot/led/{led_number}')

    try:
        info = _get_client().publish(topic, action, qos=1)
        info.wait_for_publish(timeout=3)
        ok = info.is_published()
        logger.info("MQTT publish %s %s -> %s", topic, action, ok)
        return ok
    except Exception:
        logger.exception("MQTT publish failed (topic=%s)", topic)
        return False


def device_to_led_id(device) -> Optional[int]:
    """
    Map Device -> số LED trên ESP32 (1, 2, 3). Trả None nếu không map được.

    Thứ tự ưu tiên:
      1. Field `led_number` trên model (nếu có) - cách đúng nhất.
      2. Số trong tên thiết bị ("Đèn 3" -> 3).
      3. device.id nếu nằm trong 1..3.

    Lưu ý: KHÔNG map theo type (LIGHT/FAN) nữa, vì nhiều đèn cùng type
    sẽ bị gộp về cùng một LED (nguyên nhân lỗi đèn 3 chạy thành đèn 1).
    """
    led = getattr(device, 'led_number', None)
    if led in VALID_LEDS:
        return led

    name = unicodedata.normalize('NFC', (device.name or '')).lower()
    m = re.search(r'\d+', name)
    if m and int(m.group()) in VALID_LEDS:
        return int(m.group())

    if device.id in VALID_LEDS:
        return device.id

    return None