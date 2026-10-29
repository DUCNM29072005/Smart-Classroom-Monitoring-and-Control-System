from django.urls import path
from . import views

urlpatterns = [
    path('login', views.LoginView.as_view()),
    path('dashboard', views.SensorLatestView.as_view()),
    path('data', views.SensorListView.as_view()),
    path('history', views.ControlHistoryView.as_view()),
    path('devices', views.DeviceListView.as_view()),
    path('devices/<int:device_id>/control', views.DeviceControlView.as_view()),
    path('sensors', views.SensorCatalogView.as_view()),
    path('devices/<int:device_id>/blink', views.DeviceBlinkView.as_view()),
]