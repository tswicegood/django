from django.dispatch import Signal

app_prepared = Signal(providing_args=["app"])

pre_apps_loaded = Signal()
post_apps_loaded = Signal(providing_args=["apps"])
