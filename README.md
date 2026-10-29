# Phòng Học IoT — Hệ thống giám sát và điều khiển phòng học thông minh

Hệ thống IoT giám sát nhiệt độ, độ ẩm, ánh sáng (và cảm biến mở rộng như CO₂), điều khiển đèn/quạt qua MQTT, giao diện Web + REST API (Django) + firmware ESP32.

**Sinh viên:** Nguyễn Minh Đức — **MSSV:** B23DCAT050

---

## Mục lục

- [Tổng quan](#tổng-quan)
- [Kiến trúc](#kiến-trúc)
- [Công nghệ](#công-nghệ)
- [Cấu trúc thư mục](#cấu-trúc-thư-mục)
- [Cơ sở dữ liệu](#cơ-sở-dữ-liệu)
- [MQTT Topics](#mqtt-topics)
- [REST API](#rest-api)
- [Cài đặt & chạy](#cài-đặt--chạy)
- [Firmware ESP32](#firmware-esp32)
- [Giao diện Web](#giao-diện-web)
- [Tính năng chính](#tính-năng-chính)
- [Giả lập cảm biến (terminal)](#giả-lập-cảm-biến-terminal)

---

## Tổng quan

Hệ thống cho phép:

1. **Đăng nhập** (JWT)
2. **Giám sát realtime** — card cảm biến, biểu đồ Chart.js, trạng thái ESP32 / MQTT
3. **Điều khiển thiết bị** — bật/tắt đèn, quạt (trạng thái LOADING trung gian)
4. **Dữ liệu cảm biến** — bảng lịch sử, lọc, tìm kiếm, phân trang
5. **Lịch sử điều khiển** — log ON/OFF/Nháy, lọc theo thiết bị / thao tác / trạng thái / thời gian
6. **Profile** — thông tin sinh viên, liên kết GitHub / Figma / Postman / báo cáo
7. **Admin Django** — thêm thiết bị, cảm biến (catalog), xem log

Luồng dữ liệu cảm biến:

```text
ESP32 (DHT11, LDR, …) → MQTT (Mosquitto) → mqtt_listener → MySQL
                                                      ↓
                                              REST API → Web (poll)
```

Luồng điều khiển:

```text
Web → PUT /api/devices/{id}/control → MQTT iot/led/{n} → ESP32 GPIO
                                         ↓
                              status iot/led/{n}/status → cập nhật DB
```

---

## Kiến trúc

```text
┌─────────────┐     MQTT      ┌──────────────┐     SQL      ┌─────────┐
│   ESP32     │◄─────────────►│  Mosquitto   │              │  MySQL  │
│  + DHT11    │  sensor/led   │   Broker     │              └────▲────┘
│  + LDR/LED  │               └──────┬───────┘                   │
└─────────────┘                      │                      Django ORM
                                     │ subscribe/publish           │
                              ┌──────▼───────┐              ┌──────┴──────┐
                              │ mqtt_listener│─────────────►│   Backend   │
                              │ (management) │              │ Django REST │
                              └──────────────┘              │    + JWT    │
                                                            └──────▲──────┘
                                                                   │ HTTP /api/*
                                                            ┌──────┴──────┐
                                                            │  Frontend   │
                                                            │ HTML/CSS/JS │
                                                            │  Chart.js   │
                                                            └─────────────┘
```

---

## Công nghệ

| Tầng | Công nghệ |
|------|-----------|
| Phần cứng | ESP32, DHT11, quang trở (LDR), LED/relay |
| Broker | Eclipse Mosquitto (MQTT) |
| Backend | Python, Django, Django REST Framework, SimpleJWT |
| Database | MySQL |
| Frontend | HTML, CSS, JavaScript (SPA), Chart.js |
| Công cụ | Postman, Django Admin, Git |

---

## Cấu trúc thư mục (gợi ý)

```text
IoT/
├── Backend/                 # Django project
│   ├── manage.py
│   ├── iot_backend/         # settings, urls
│   └── core/
│       ├── models.py
│       ├── views.py
│       ├── serializers.py
│       ├── urls.py
│       ├── admin.py
│       ├── mqtt_publish.py
│       └── management/commands/
│           └── mqtt_listener.py
├── sketch_*/                # Firmware Arduino/ESP32
├── static/ hoặc templates/  # index.html, avatar, …
├── Báo cáo.pdf
└── README.md
```

---

## Cơ sở dữ liệu

Các bảng chính:

| Bảng | Mô tả |
|------|--------|
| `users` | Tài khoản (username, password_hash, full_name, …) |
| `sensor_readings` | Bản ghi tổng hợp T/H/L (tuỳ phiên bản) |
| `sensor_data` | Từng điểm đo: `sensor_type`, `value`, `recorded_at` |
| `sensors` | Catalog cảm biến (code, name, unit, measure, color) — thêm từ Admin |
| `devices` | Thiết bị điều khiển (name, type, status, is_active) |
| `device_control_logs` | Lịch sử bật/tắt/nháy |

`sensor_type` / `sensors.code` ví dụ: `temperature`, `humidity`, `light`, `co2`, …

---

## MQTT Topics

| Topic | Hướng | Nội dung |
|-------|--------|----------|
| `iot/sensor/data` | ESP → Broker | JSON: temperature, humidity, light, co2, time |
| `iot/led/{1..n}` | Backend → ESP | `ON` / `OFF` |
| `iot/led/{n}/status` | ESP → Broker | Trạng thái thực tế |
| `iot/led/all` | Tuỳ firmware | Điều khiển tất cả |

Cấu hình broker (ví dụ):

```text
MQTT_HOST = 192.168.x.x
MQTT_PORT = 2000
MQTT_USER = iotuser
MQTT_PASSWORD = ***
```

---

## REST API

Base: `http://127.0.0.1:8000/api/`  
Auth: Header `Authorization: Bearer <access_token>` (trừ login).

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| POST | `/api/login` | Đăng nhập → JWT + user |
| GET | `/api/dashboard` (hoặc latest) | Giá trị mới nhất + `values` theo catalog |
| GET | `/api/sensors` | Danh mục cảm biến đang active |
| GET | `/api/data` | Lịch sử cảm biến (lọc, phân trang, sắp xếp) |
| GET | `/api/devices` | Danh sách thiết bị |
| PUT | `/api/devices/{id}/control` | Bật/tắt `{ "action": "ON"\|"OFF" }` |
| POST | `/api/devices/{id}/blink` | Nháy LED cảnh báo `{ "on": true\|false }` |
| GET | `/api/history` | Lịch sử điều khiển |
| GET | `/api/profile` | Thông tin user |

**Query gợi ý**

- Data: `?sensor=co2&page=1&page_size=6&sort=time&order=desc&value=...`
- History: `?device=all&action=nhay&status=ON&time=2026-10-29&page=1`

Định dạng thời gian tìm kiếm: `YYYY-MM-DD HH:MM:SS` (tìm kiểu *chứa*).

---

## Cài đặt & chạy

### Yêu cầu

- Python 3.10+
- MySQL
- Mosquitto
- (Tuỳ chọn) Arduino IDE / PlatformIO cho ESP32

### Backend

```bash
cd Backend
pip install django djangorestframework djangorestframework-simplejwt mysqlclient paho-mqtt
# chỉnh settings.py: DATABASES, MQTT_*, TIME_ZONE = 'Asia/Ho_Chi_Minh', USE_TZ = True
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Terminal khác — lắng nghe MQTT ghi DB:

```bash
python manage.py mqtt_listener
```

### Mosquitto

Chạy broker, mở port đã cấu hình (vd. 2000), user/password khớp ESP và Django.

### Frontend

Phục vụ `index.html` qua Django template/static hoặc mở cùng origin với API.  
Đăng nhập → token lưu `localStorage` → gọi `/api/*`.

### Admin

`http://127.0.0.1:8000/admin/`

- Thêm **Devices** (tên có số LED: `LED 1`, `LED 4`, …)
- Thêm **Sensors** (`code` = `temperature` / `humidity` / `light` / `co2`, …)

---

## Firmware ESP32

- Wi-Fi + PubSubClient  
- Đọc DHT11, LDR (ánh sáng: giá trị tăng khi sáng hơn)  
- Publish định kỳ lên `iot/sensor/data`  
- Subscribe `iot/led/#`, điều khiển GPIO, publish `…/status`  

Cấu hình trong sketch: `WIFI_SSID`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`.

---

## Giao diện Web

| Path (SPA) | Chức năng |
|------------|-----------|
| `/login` | Đăng nhập |
| `/dashboard` | Giám sát + điều khiển + biểu đồ |
| `/data` | Bảng dữ liệu cảm biến |
| `/history` | Lịch sử điều khiển |
| `/profile` | Thông tin & liên kết |

- Poll dashboard định kỳ để cập nhật realtime  
- Trạng thái ESP dựa trên dữ liệu cảm biến mới  
- Điều khiển: LOADING → ON/OFF; lỗi → khôi phục nút + thông báo  
- CO₂ (nếu bật): card, chart, ngưỡng an toàn, cảnh báo nháy box + nháy LED  

---

## Tính năng chính

- [x] JWT đăng nhập  
- [x] Giám sát T/H/L (và cảm biến catalog)  
- [x] Biểu đồ Chart.js  
- [x] Bật/tắt thiết bị qua MQTT  
- [x] Lịch sử điều khiển + lọc (kể cả Nháy / Dừng nháy)  
- [x] Lọc thời gian kiểu chứa `YYYY-MM-DD HH:MM:SS`  
- [x] Admin thêm thiết bị / cảm biến  
- [x] (Tuỳ chọn) Cảnh báo CO₂ + blink LED  

---

## Giả lập cảm biến (terminal)

Giả lập gói giống hardware:

```bash
mosquitto_pub -h 192.168.x.x -p 2000 -u iotuser -P iot123 \
  -t "iot/sensor/data" \
  -m "{\"temperature\":32.5,\"humidity\":57,\"light\":2500,\"co2\":80,\"time\":\"syncing\"}"
```

Điều khiển LED:

```bash
mosquitto_pub -h 192.168.x.x -p 2000 -u iotuser -P iot123 -t "iot/led/1" -m "ON"
```

---

## Bảo mật & lưu ý

- Đổi mật khẩu MQTT/DB khi deploy  
- Không commit `.env` / mật khẩu lên Git  
- Bản lab dùng HTTP + poll; production nên HTTPS, cứng hóa MQTT auth  