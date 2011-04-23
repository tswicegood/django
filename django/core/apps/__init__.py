from django.core.apps.cache import AppCache
from django.core.apps.base import App, AppBase
from django.core.apps.signals import app_prepared, pre_apps_loaded, post_apps_loaded

cache = AppCache()
