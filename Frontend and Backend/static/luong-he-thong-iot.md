# Luồng hệ thống Phòng Học IoT

Tài liệu mô tả luồng dữ liệu và xử lý backend/frontend cho toàn bộ chức năng.

---

## Sơ đồ tổng quan hai chiều

```
┌─────────────────────────────────────────────────────────────────┐
│  CHIỀU THU THẬP (Cảm biến → Web)                                │
│                                                                 │
│  DHT11 / LDR / CO₂(mô phỏng) → ESP32 → MQTT iot/sensor/data     │
│       → mqtt_listener (_handle_sensor)                          │
│       → MySQL (sensor_readings, sensor_data: T/H/L/co2)         │
│       → API GET /api/dashboard | GET /api/data                  │
│       → Frontend (card, chart, bảng; CO₂ + ngưỡng + cảnh báo)   │
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
| Catalog cảm biến | `GET /api/sensors` | **SensorCatalogView** |
| Nháy LED (cảnh báo CO₂) | `POST /api/devices/{id}/blink` | **DeviceBlinkView** → **publish_led_command** |

### MQTT (không phải HTTP API)

| Việc | Hàm |
|------|-----|
| Nhận cảm biến (T/H/L/CO₂), ghi DB | `mqtt_listener` → **`_handle_sensor`** |
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

MQTT iot/sensor/data            → _handle_sensor         → sensor_readings, sensor_data (+ co2)
MQTT iot/led/{n}/status         → _handle_led_status     → devices
GET  /api/sensors               → SensorCatalogView      → sensors
POST /api/devices/{id}/blink    → DeviceBlinkView        → blink LED (+ log nếu có)
```

---

## So sánh các trang

| Trang | API | Bảng chính | Nguồn ghi | Mục đích |
|-------|-----|------------|-----------|----------|
| Giám sát | `/api/dashboard` | `sensor_readings` | ESP32 → MQTT | Realtime |
| Data cảm biến | `/api/data` | `sensor_data` | ESP32 → MQTT | Tra cứu đo |
| Điều khiển | `/api/devices/.../control` | `devices`, `device_control_logs` | User trên web | Bật/tắt |
| Lịch sử ĐK | `/api/history` | `device_control_logs` | DeviceControlView / BlinkView | Tra cứu bật/tắt/nháy |
| CO₂ giám sát | `/api/dashboard` | `sensor_data` (co2) | `_handle_sensor` | Box + chart + ngưỡng |
| CO₂ cảnh báo | `/api/devices/.../blink` | MQTT led + (log) | DeviceBlinkView | Nháy LED khi vượt ngưỡng |

---

## Models (bảng) liên quan

| Model | Bảng | Vai trò |
|-------|------|---------|
| **User** | `users` | Đăng nhập, người thao tác |
| **SensorReading** | `sensor_readings` | 1 dòng = nhiệt + ẩm + sáng (dashboard) |
| **SensorData** | `sensor_data` | Từng loại cảm biến + thời gian (bảng data) |
| **Device** | `devices` | Thiết bị và trạng thái ON/OFF/LOADING |
| **DeviceControlLog** | `device_control_logs` | Lịch sử bật/tắt / nháy (nếu log) |
| **Sensor** | `sensors` | Catalog cảm biến (code, name, unit) — Admin thêm CO₂ |

Models là cầu nối code Python ↔ MySQL: listener/view dùng ORM để INSERT/SELECT thay vì SQL thuần.

---

## 7. Luồng CO₂ (mô phỏng cảm biến + cảnh báo)

### 7.1. Thu thập & lưu CO₂

```
ESP32 (hoặc mosquitto_pub giả lập)
→ random / đo CO₂ (0–101)
→ JSON có "co2": 57 trong payload
→ publish MQTT topic: iot/sensor/data
→ mqtt_listener → _handle_sensor
→ INSERT sensor_data (sensor_type='co2', value, recorded_at)
→ (tuỳ chọn) catalog bảng sensors với code='co2' (Admin)
```

| Bước | Chi tiết |
|------|----------|
| **Nguồn** | Firmware `publishSensorData()` hoặc `mosquitto_pub -t iot/sensor/data` |
| **MQTT** | Topic `iot/sensor/data`, field JSON `co2` |
| **Nhận** | **`mqtt_listener` → `_handle_sensor`** |
| **Ghi DB** | **`sensor_data`** (`sensor_type='co2'`) |
| **Catalog** | **`sensors`** (code=`co2`, name, unit=ppm, …) — chỉ khai báo, không tạo số đo |

---

### 7.2. Đọc CO₂ ra Web (dashboard + bảng data)

```
Frontend poll GET /api/dashboard
→ SensorLatestView
→ SELECT sensor_data WHERE sensor_type='co2' ORDER BY id DESC LIMIT 1
→ (và/hoặc) data.values.co2 từ catalog
→ JSON: { ..., co2, values: { co2: { value, recorded_at } }, recorded_at }
→ Frontend: updateCo2() → box CO₂ + biểu đồ CO₂

Trang /data
→ GET /api/data?sensor=co2&page=...
→ SensorListView
→ SELECT sensor_data WHERE sensor_type='co2' …
→ Bảng lịch sử đo CO₂
```

| Bước | Chi tiết |
|------|----------|
| **Nhận request** | **SensorLatestView** (`GET /api/dashboard`) |
| **Truy vấn** | **`sensor_data`** (`sensor_type='co2'`); catalog **`sensors`** |
| **Trả về** | `{ data: { co2, values.co2, temperature, …, recorded_at } }` |
| **Ai nhận** | Frontend `loadLatestSensors` → **`updateCo2` / chart CO₂** |
| **Bảng lịch sử** | **SensorListView** + `?sensor=co2` → **`loadSensorTable`** |

---

### 7.3. Ngưỡng an toàn & cảnh báo (frontend + nháy LED)

```
updateCo2(vals, recorded_at)
→ co2Last = { v, fresh }  // fresh nếu recorded_at ≤ ~5s
→ evaluateCo2Alarm()
├─ chưa có / không fresh → không cảnh báo (hoặc “Mất dữ liệu CO₂”)
├─ v ≤ ngưỡng → An toàn → setCo2Alarm(false)
└─ v > ngưỡng và fresh → setCo2Alarm(true)
        ├─ CSS nháy box #co2Box (co2-alert)
        └─ startLedBlink()
              → findLed4() (device “Đèn 4” / LED 4)
              → POST /api/devices/{id}/blink { "on": true }
              → DeviceBlinkView → _blink_worker
              → publish_led_command ON/OFF xen kẽ → MQTT iot/led/{n}
              → ESP32 GPIO nháy
              → keepalive ~10s (gia hạn TTL server)

User lưu ngưỡng (saveCo2Threshold) → localStorage + refreshCo2Chart + evaluateCo2Alarm
Rời trang / logout → stopCo2Alarm() → stopLedBlink() → blink { on: false }
```

| Bước | Chi tiết |
|------|----------|
| **So ngưỡng** | Frontend **`evaluateCo2Alarm`** (ngưỡng: biến + `localStorage`) |
| **UI** | **`setCo2Alarm`** — class `co2-alert` trên box CO₂ |
| **API nháy** | **`POST /api/devices/{id}/blink`** → **DeviceBlinkView** |
| **MQTT ra** | **`publish_led_command`** → `iot/led/{n}` (LED cảnh báo, vd. đèn 4) |
| **Log (nếu có)** | **`device_control_logs`** action `BLINK_ON` / `BLINK_OFF` |
| **Lịch sử lọc** | **ControlHistoryView** + `?action=nhay` / `dung nhay` |

---

### 7.4. Sơ đồ riêng CO₂

```
ESP32 / mosquitto_pub
  → MQTT iot/sensor/data  ("co2": …)
  → _handle_sensor
  → sensor_data (co2)
        ↓
GET /api/dashboard → SensorLatestView
        ↓
Frontend updateCo2 → box + chart CO₂
        ↓
evaluateCo2Alarm (so ngưỡng, data còn mới?)
        ↓ có vượt
setCo2Alarm(true) → nháy box
        +
POST .../blink → DeviceBlinkView → iot/led/{n} → ESP32 LED nháy

GET /api/data?sensor=co2 → SensorListView → bảng data CO₂
```

---

### 7.5. Code / bảng liên quan CO₂

| Thành phần | Vai trò |
|------------|---------|
| **`_handle_sensor`** | Ghi `sensor_data` khi có key `co2` |
| **`Sensor` (catalog)** | Khai báo code `co2`, unit ppm |
| **`SensorLatestView`** | Trả `co2` / `values.co2` cho giám sát |
| **`SensorListView`** | Lọc lịch sử `sensor=co2` |
| **`DeviceBlinkView`** | Nháy LED khi FE báo vượt ngưỡng |
| **`publish_led_command`** | Gửi ON/OFF lên MQTT |
| **JS `updateCo2` / `evaluateCo2Alarm` / `startLedBlink`** | UI + ngưỡng + gọi blink |

**Ghi chú:** Card/chart CO₂ lấy từ **poll dashboard** (giống T/H/L). Cảnh báo **chỉ khi dữ liệu CO₂ còn mới** và **vượt ngưỡng**. Log nháy (nếu có) do **DeviceBlinkView**, không do `_handle_led_status`.

---

## Sơ đồ “ai nhận → hàm → bảng” (bổ sung CO₂)

```
GET  /api/sensors               → SensorCatalogView      → sensors
POST /api/devices/{id}/blink    → DeviceBlinkView        → (log) device_control_logs
                                → publish_led_command → MQTT iot/led/{n}

MQTT iot/sensor/data (+ field co2) → _handle_sensor → sensor_data (sensor_type='co2')
```

---

---

*Tài liệu mô tả luồng triển khai hiện tại của dự án Phòng Học IoT (Django + MySQL + MQTT + ESP32).*
