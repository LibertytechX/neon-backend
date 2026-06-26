from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("config", views.config),
    path("session", views.session),
    path("spin", views.spin),
    path("risk", views.risk),
    path("bank", views.bank),
    path("rotate", views.rotate),
    path("verify", views.verify),
]
