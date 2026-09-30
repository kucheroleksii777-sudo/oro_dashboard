from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("site/", views.site, name="site"),
    path("network/", views.network, name="network"),
    path("tao/", views.tao, name="tao"),
    path("registration/", views.registration, name="registration"),
    path("neurons/", views.neurons, name="neurons"),
    path("current/", views.current, name="current"),
    path("race/", views.race, name="race"),
    path("races/", views.races, name="races"),
    path("updatedb/", views.updatedb, name="updatedb"),
    path("races/progress/", views.races_progress, name="races-progress"),
    path("races/info/", views.races_info, name="races-info"),
    path("races/<str:race_id>/", views.race_table, name="race-table"),
    path("agent-code/<str:version_id>/", views.agent_code, name="agent-code"),
    path("my-agents/", views.my_agents, name="my-agents"),
    path("my-agents/pin/", views.pin_agent, name="my-agents-pin"),
    path("auto-sub/submit/", views.auto_sub_submit, name="auto-sub-submit"),
    path("keys/", views.keys, name="keys"),
    path("keys/<int:key_id>/", views.key_detail, name="key-detail"),
]
