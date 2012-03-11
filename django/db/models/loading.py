"Utilities for loading models and the modules that contain them."
import warnings

# Imported here for backwards compatibility
from django.apps import (App, AppCache, cache,
    find_app, get_apps, get_app, get_app_errors, get_models, get_model,
    register_models, load_app, app_cache_ready)

warnings.warn(
    'The utilities in django.db.models.loading have been moved to '
    'django.apps. Please update your code accordingly.',
    PendingDeprecationWarning)
