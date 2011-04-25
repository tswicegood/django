import sys
import os
import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.importlib import import_module
from django.utils.module_loading import module_has_submodule

from django.apps.base import App
from django.apps.signals import app_loaded, pre_apps_loaded, post_apps_loaded


def _initialize():
    """
    Returns a dictionary to be used as the initial value of the
    shared state of the app cache.
    """
    return {
        # list of loaded app instances
        '_loaded_apps': [],

        # Mapping of app_labels to a dictionary of model names to model code.
        'unbound_models': {},

        # -- Everything below here is only used when populating the cache --
        'loaded': False,
        'handled': {},
        'postponed': [],
        'nesting_level': 0,
        '_get_models_cache': {},
        'currently_installed': settings.INSTALLED_APPS,
    }


class AppCache(object):
    """
    A cache that stores installed applications and their models. Used to
    provide reverse-relations and for app introspection (e.g. admin).
    """
    # Use the Borg pattern to share state between all instances. Details at
    # http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/66531.
    __shared_state = dict(_initialize(), write_lock=threading.RLock())

    def __init__(self):
        self.__dict__ = self.__shared_state

    @property
    def loaded_apps(self):
        if self.currently_installed != settings.INSTALLED_APPS:
            self._reload()
        return self._loaded_apps

    def _reload(self):
        """
        Reloads the cache
        """
        self.__class__.__shared_state.update(_initialize())
        self._populate()

    def _populate(self):
        """
        Fill in all the cache information. This method is threadsafe, in the
        sense that every caller will see the same state upon return, and if the
        cache is already initialised, it does no work.
        """
        if self.loaded:
            return
        self.write_lock.acquire()
        try:
            if self.loaded:
                return
            # send the pre_apps_loaded signal
            pre_apps_loaded.send(sender=self)

            for app_name in settings.INSTALLED_APPS:
                if app_name in self.handled:
                    continue
                self.load_app(app_name, True)
            if not self.nesting_level:
                for app_name in self.postponed:
                    self.load_app(app_name)
                # since the cache is still unseeded at this point
                # all models have been stored as unbound models.
                # we need to assign the models to the app instances
                for app_label, models in self.unbound_models.iteritems():
                    app = self.find_app(app_label)
                    if not app:
                        continue
                    for model in models.itervalues():
                        app._meta.models.append(model)
                # check if there is more than one app with the same
                # db_prefix attribute
                for app1 in self._loaded_apps:
                    for app2 in self._loaded_apps:
                        if (app1 != app2 and
                                app1._meta.db_prefix == app2._meta.db_prefix):
                            raise ImproperlyConfigured(
                                'The apps "%s" and "%s" have the same db_prefix "%s"'
                                % (app1, app2, app1._meta.db_prefix))
                self.loaded = True
                # send the post_apps_loaded signal
                post_apps_loaded.send(sender=self, apps=self._loaded_apps)
        finally:
            self.write_lock.release()

    def get_app_class(self, app_name):
        """
        Returns an app class for the given app name, which can be a
        dotted path to an app class or a dotted app module path.
        """
        try:
            app_path, app_attr = app_name.rsplit('.', 1)
        except ValueError:
            # First, return a new app class for the given module if
            # it's one level module path that can't be rsplit (e.g. 'myapp')
            return App.from_name(app_name)
        try:
            # Secondly, try to import the module directly,
            # because it'll fail with a class path or a bad path
            app_module = import_module(app_path)
        except ImportError, e:
            raise ImproperlyConfigured(
                "Could not import app '%s': %s" % (app_path, e))
        else:
            # Thirdly, check if there is the submodule and fall back if yes
            # If not look for the app class and do some type checks
            if not module_has_submodule(app_module, app_attr):
                try:
                    app_class = getattr(app_module, app_attr)
                except AttributeError:
                    raise ImproperlyConfigured(
                        "Could not find app '%s' in "
                        "module '%s'" % (app_attr, app_path))
                else:
                    if not issubclass(app_class, App):
                        raise ImproperlyConfigured(
                            "App '%s' must be a subclass of "
                            "'django.apps.App'" % app_name)
                    return app_class
        return App.from_name(app_name)

    def load_app(self, app_name, can_postpone=False):
        """
        Loads the app with the provided fully qualified name, and returns the
        model module.

        Keyword Arguments:
            app_name: fully qualified name (e.g. 'django.contrib.auth')
            can_postpone: If set to True and the import raises an ImportError
                the loading will be postponed and tried again when all other
                modules are loaded.
        """
        self.handled[app_name] = None
        self.nesting_level += 1

        # check if an app instance with app_name already exists, if not
        # then create one
        app = self.find_app(app_name.split('.')[-1])
        if not app:
            app_class = self.get_app_class(app_name)
            app = app_class()
            self.loaded_apps.append(app)
            # Send the signal that the app has been loaded
            app_loaded.send(sender=app_class, app=app)

        # import the app's models module and handle ImportErrors
        try:
            models = import_module(app._meta.models_path)
        except ImportError:
            self.nesting_level -= 1
            # If the app doesn't have a models module, we can just ignore the
            # ImportError and return no models for it.
            if not module_has_submodule(app._meta.module, 'models'):
                return None
            # But if the app does have a models module, we need to figure out
            # whether to suppress or propagate the error. If can_postpone is
            # True then it may be that the package is still being imported by
            # Python and the models module isn't available yet. So we add the
            # app to the postponed list and we'll try it again after all the
            # recursion has finished (in populate). If can_postpone is False
            # then it's time to raise the ImportError.
            else:
                if can_postpone:
                    self.postponed.append(app_name)
                    return None
                else:
                    raise

        self.nesting_level -= 1
        app._meta.models_module = models
        return models

    def find_app(self, app_label):
        """
        Returns the app instance that matches the given label.
        """
        for app in self.loaded_apps:
            if app._meta.label == app_label:
                return app

    def app_cache_ready(self):
        """
        Returns true if the model cache is fully populated.

        Useful for code that wants to cache the results of get_models() for
        themselves once it is safe to do so.
        """
        return self.loaded

    def get_apps(self):
        """
        Returns a list of all models modules.
        """
        self._populate()
        return [app._meta.models_module for app in self.loaded_apps
                if app._meta.models_module]

    def get_app(self, app_label, emptyOK=False):
        """
        Returns the module containing the models for the given app_label. If
        the app has no models in it and 'emptyOK' is True, returns None.
        """
        self._populate()
        app = self.find_app(app_label)
        if app:
            mod = app._meta.models_module
            if mod is None:
                if emptyOK:
                    return None
            else:
                return mod
        raise ImproperlyConfigured(
                "App with label %s could not be found" % app_label)

    def get_app_errors(self):
        """
        Returns the map of known problems with the INSTALLED_APPS.
        """
        self._populate()
        errors = {}
        for app in self.loaded_apps:
            if app._meta.errors:
                errors.update({app._meta.label: app._meta.errors})
        return errors

    def get_models(self, app_mod=None,
                   include_auto_created=False, include_deferred=False):
        """
        Given a module containing models, returns a list of the models.
        Otherwise returns a list of all installed models.

        By default, auto-created models (i.e., m2m models without an
        explicit intermediate table) are not included. However, if you
        specify include_auto_created=True, they will be.

        By default, models created to satisfy deferred attribute
        queries are *not* included in the list of models. However, if
        you specify include_deferred, they will be.
        """
        cache_key = (app_mod, include_auto_created, include_deferred)
        try:
            return self._get_models_cache[cache_key]
        except KeyError:
            pass
        self._populate()
        if app_mod:
            app_label = app_mod.__name__.split('.')[-2]
            app = self.find_app(app_label)
            if app:
                app_list = [app]
        else:
            app_list = self.loaded_apps
        model_list = []
        for app in app_list:
            model_list.extend(
                model for model in app._meta.models
                if ((not model._deferred or include_deferred) and
                    (not model._meta.auto_created or include_auto_created))
            )
        self._get_models_cache[cache_key] = model_list
        return model_list

    def get_model(self, app_label, model_name,
                  seed_cache=True, only_installed=True):
        """
        Returns the model matching the given app_label and case-insensitive
        model_name.

        Returns None if no model is found.
        """
        if seed_cache:
            self._populate()
        app = self.find_app(app_label)
        if only_installed and self.app_cache_ready() and not app:
            return
        if only_installed and self.app_cache_ready():
            for model in app._meta.models:
                if model_name.lower() == model._meta.object_name.lower():
                    return model
        else:
            return self.unbound_models.get(app_label, {}).get(
                    model_name.lower())

    def register_models(self, app_label, *models):
        """
        Register a set of models as belonging to an app.
        """
        app = self.find_app(app_label)
        for model in models:
            model_name = model._meta.object_name.lower()
            model_dict = self.unbound_models.setdefault(app_label, {})
            if model_name in model_dict:
                # The same model may be imported via different paths (e.g.
                # appname.models and project.appname.models). We use the source
                # filename as a means to detect identity.
                fname1 = os.path.abspath(sys.modules[model.__module__].__file__)
                fname2 = os.path.abspath(sys.modules[model_dict[model_name].__module__].__file__)
                # Since the filename extension could be .py the first time and
                # .pyc or .pyo the second time, ignore the extension when
                # comparing.
                if os.path.splitext(fname1)[0] == os.path.splitext(fname2)[0]:
                    continue
            if self.app_cache_ready() and app:
                app._meta.models.append(model)
            model_dict[model_name] = model
        self._get_models_cache.clear()
