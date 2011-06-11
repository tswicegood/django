from django.dispatch import Signal

# Sent when an app is loaded by the app cache
app_loaded = Signal(providing_args=["app"])

# Sent when the app cache loads the apps
post_apps_loaded = Signal(providing_args=["apps"])
