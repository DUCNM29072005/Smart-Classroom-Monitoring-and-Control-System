# Luồng hệ thống Phòng Học IoT

Tài liệu mô tả luồng dữ liệu và xử lý backend/frontend cho toàn bộ chức năng.

---

## Sơ đồ tổng quan hai chiều

```
┌─────────────────────────────────────────────────────────────────┐
│  CHIỀU THU THẬP (Cảm biến → Web)                                │
│                                                                 │
│  DHT11 / BH1750 → ESP32 → MQTT iot/sensor/data                  │
│       → mqtt_listener (_handle_sensor)                          │
│       → MySQL (sensor_readings, sensor_data)                    │
│       → API GET /api/dashboard | GET /api/data                  │
│       → Frontend (card, chart, bảng)                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  CHIỀU ĐIỀU KHIỂN (Web → Phần cứng)                             │
│                                                                 │
│  User toggle → PUT /api/devices/{id}/control                    │
│       → DeviceControlView → device_control_logs + devices       │
│       → publish_led_command → MQTT iot/led/{n}                  │
│       → ESP32 (GPIO) → MQTT iot/led/{n}/status                  │
│       → _handle_led_status → devices.status                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## API → hàm trong code

| Chức năng | API | Hàm / class |
|-----------|-----|-------------|
| Đăng nhập | `POST /api/login` | **LoginView** |
| Giám sát (mới nhất + chart) | `GET /api/dashboard` | **SensorLatestView** |
| Danh sách thiết bị | `GET /api/devices` | **DeviceListView** |
| Bật / tắt thiết bị | `PUT /api/devices/{id}/control` | **DeviceControlView** → **publish_led_command** |
| Dữ liệu cảm biến | `GET /api/data` | **SensorListView** |
| Lịch sử điều khiển | `GET /api/history` | **ControlHistoryView** |
| Profile (nếu có) | `GET /api/profile` | **ProfileView** |

### MQTT (không phải HTTP API)

| Việc | Hàm |
|------|-----|
| Nhận cảm biến, ghi DB | `mqtt_listener` → **`_handle_sensor`** |
| Nhận status đèn từ ESP32 | `mqtt_listener` → **`_handle_led_status`** |

---

## 1. Đăng nhập

```
Frontend form
    → POST /api/login  { username, password }
    → LoginView
    → Truy vấn bảng users (username, password_hash, status)
    → Cập nhật last_login_at (nếu có)
    → Trả JSON: access token + thông tin user
    → Frontend lưu localStorage → chuyển /dashboard
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **LoginView** |
| **Truy vấn** | **`users`** |
| **Trả về** | `{ access, user: { id, username, full_name, ... } }` |
| **Ai nhận** | Frontend — lưu token, vào app |

---

## 2. Giám sát phòng học (3 card + biểu đồ)

```
ESP32 đọc DHT11 + BH1750
    → publish MQTT topic: iot/sensor/data
    → mqtt_listener._handle_sensor
    → INSERT sensor_readings + sensor_data
           ↑
Frontend poll ~3s
    → GET /api/dashboard
    → SensorLatestView
    → SELECT sensor_readings ORDER BY id DESC LIMIT 1
    → JSON { temperature, humidity, light_level, recorded_at }
    → Frontend: 3 card + “Cập nhật lần cuối” + push điểm Chart.js
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **SensorLatestView** (`GET /api/dashboard`) |
| **Truy vấn** | **`sensor_readings`** (mới nhất); `recorded_at` từ **`sensor_data`** |
| **Trả về** | `{ data: { temperature, humidity, light_level, recorded_at } }` |
| **Ai nhận** | Frontend — card + chart |

**Ghi chú:** Card = giá trị hiện tại. Biểu đồ = chuỗi các lần poll trên trình duyệt (cùng API). F5 thì chart vẽ lại từ đầu.

---

## 3. Danh sách thiết bị

```
Frontend loadDevices
    → GET /api/devices
    → DeviceListView
    → SELECT devices (is_active=True)
    → JSON danh sách { id, name, type, status, updated_at }
    → Frontend vẽ card / toggle
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **DeviceListView** |
| **Truy vấn** | **`devices`** |
| **Trả về** | `{ data: [ ... ] }` |
| **Ai nhận** | Frontend `loadDevices` |

---

## 4. Bật / tắt thiết bị

```
User gạt toggle
    → PUT /api/devices/{id}/control  { "action": "ON" | "OFF" }
    → DeviceControlView
         ├─ SELECT devices theo id
         ├─ INSERT device_control_logs (previous → new, có thể qua LOADING)
         ├─ UPDATE devices.status
         └─ publish_led_command(n, action)
                → MQTT topic iot/led/{n}  payload ON/OFF
                → ESP32 bật/tắt GPIO
                → ESP32 publish iot/led/{n}/status
                → _handle_led_status
                → UPDATE devices.status (trạng thái thật)
    → JSON trả về frontend cập nhật badge
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **DeviceControlView** |
| **Truy vấn / ghi** | **`devices`**, **`device_control_logs`** |
| **MQTT ra** | **`publish_led_command`** → `iot/led/{n}` |
| **MQTT vào** | **`_handle_led_status`** → cập nhật **`devices`** (không ghi log) |
| **Trả về** | `{ data: { id, name, status, updated_at, ... } }` |
| **Ai nhận** | Frontend toggle handler |

### `_handle_led_status` làm gì?

```
topic iot/led/{n}/status + payload ON/OFF
    → tách led_num từ topic
    → parse state
    → map LED → tên device (Đèn phòng, Quạt, LED 3…)
    → get_or_create Device
    → nếu status đổi → save devices.status
```

---

## 5. Dữ liệu cảm biến (bảng lịch sử đo)

```
Frontend trang /data
    → GET /api/data?sensor=&value=&page=&page_size=&sort=&order=
    → SensorListView
    → SELECT sensor_data (filter, sort, count, slice trang)
    → JSON { data, count, page, page_size }
    → Frontend bảng + phân trang
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **SensorListView** |
| **Truy vấn** | **`sensor_data`** |
| **Trả về** | `{ data: [ { id, sensor_type, value, recorded_at } ], count, page, page_size }` |
| **Ai nhận** | Frontend `loadSensorTable` |

**Nguồn ghi:** chỉ từ `_handle_sensor` khi ESP32 gửi cảm biến — trang này chỉ đọc.

---

## 6. Lịch sử điều khiển thiết bị

```
(Trước đó) User bật/tắt → DeviceControlView INSERT device_control_logs

Frontend trang /history
    → GET /api/history?device=&action=&status=&time=&page=&page_size=&order=
    → ControlHistoryView
    → SELECT device_control_logs (+ tên từ devices, users)
    → filter / sort / phân trang
    → JSON { data, count, page, page_size }
    → Frontend bảng lịch sử + phân trang
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **ControlHistoryView** |
| **Truy vấn** | **`device_control_logs`** (+ **`devices`**, **`users`**) |
| **Trả về** | `{ data: [ { id, user_name, device_name, action, previous_status, new_status, created_at } ], count, page, page_size }` |
| **Ai nhận** | Frontend `loadHistoryTable` |
| **Ai ghi log** | **DeviceControlView** (lúc bật/tắt) — **không** phải `_handle_led_status` |

---

## Sơ đồ “ai nhận → hàm → bảng”

```
POST /api/login                 → LoginView              → users
GET  /api/dashboard             → SensorLatestView       → sensor_readings (+ sensor_data)
GET  /api/devices               → DeviceListView         → devices
PUT  /api/devices/{id}/control  → DeviceControlView      → devices + device_control_logs
                                → publish_led_command
GET  /api/data                  → SensorListView         → sensor_data
GET  /api/history               → ControlHistoryView     → device_control_logs (+ devices, users)

MQTT iot/sensor/data            → _handle_sensor         → sensor_readings, sensor_data
MQTT iot/led/{n}/status         → _handle_led_status     → devices
```

## Models (bảng) liên quan

| Model | Bảng | Vai trò |
|-------|------|---------|
| **User** | `users` | Đăng nhập, người thao tác |
| **SensorReading** | `sensor_readings` | 1 dòng = nhiệt + ẩm + sáng (dashboard) |
| **SensorData** | `sensor_data` | Từng loại cảm biến + thời gian (bảng data) |
| **Device** | `devices` | Thiết bị và trạng thái ON/OFF/LOADING |
| **DeviceControlLog** | `device_control_logs` | Lịch sử bật/tắt |

