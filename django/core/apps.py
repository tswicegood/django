import re
import sys
import os
import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.dispatch import Signal
from django.utils.importlib import import_module
from django.utils.module_loading import module_has_submodule

def get_verbose_name(class_name):
    new = re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', ' \\1', class_name)
    return new.lower().strip()

def get_class_name(module_name):
    new = re.sub(r'_([a-z])', lambda m: (m.group(1).upper()), module_name)
    return new[0].upper() + new[1:]

DEFAULT_NAMES = ('verbose_name', 'db_prefix', 'models_path')

app_prepared = Signal(providing_args=["app"])

class AppOptions(object):
    def __init__(self, name, meta):
        self.name = name
        self.meta = meta
        self.errors = []
        self.models = []

    def contribute_to_class(self, cls, name):
        cls._meta = self
        # get the name from the path e.g. "auth" for "django.contrib.auth"
        self.label = self.name.split('.')[-1]
        self.db_prefix = self.label
        self.module = import_module(self.name)
        self.models_path = '%s.models' % self.name
        self.verbose_name = get_verbose_name(self.label)

        # Next, apply any overridden values from 'class Meta'.
        if self.meta:
            meta_attrs = self.meta.__dict__.copy()
            for name in self.meta.__dict__:
                # Ignore any private attributes that Django doesn't care about.
                if name.startswith('_'):
                    del meta_attrs[name]
            for attr_name in DEFAULT_NAMES:
                if attr_name in meta_attrs:
                    setattr(self, attr_name, meta_attrs.pop(attr_name))
                elif hasattr(self.meta, attr_name):
                    setattr(self, attr_name, getattr(self.meta, attr_name))

            # Any leftover attributes must be invalid.
            if meta_attrs != {}:
                raise TypeError("'class Meta' got invalid attribute(s): %s"
                                % ','.join(meta_attrs.keys()))
        del self.meta


class AppBase(type):
    """
    Metaclass for all apps.
    """
    def __new__(cls, name, bases, attrs):
        super_new = super(AppBase, cls).__new__
        parents = [b for b in bases if isinstance(b, AppBase)]
        if not parents:
            # If this isn't a subclass of App, don't do anything special.
            return super_new(cls, name, bases, attrs)
        module = attrs.pop('__module__', None)
        new_class = super_new(cls, name, bases, {'__module__': module})
        attr_meta = attrs.pop('Meta', None)
        if not attr_meta:
            meta = getattr(new_class, 'Meta', None)
        else:
            meta = attr_meta
        app_name = attrs.pop('_name', None)
        if app_name is None:
            # Figure out the app_name by looking one level up.
            # For 'django.contrib.sites.app', this would be 'django.contrib.sites'
            app_module = sys.modules[new_class.__module__]
            app_name = app_module.__name__.rsplit('.', 1)[0]
        new_class.add_to_class('_meta', AppOptions(app_name, meta))
        # Send the signal that the app has been loaded
        app_prepared.send(sender=cls)
        return new_class

    def add_to_class(cls, name, value):
        if hasattr(value, 'contribute_to_class'):
            value.contribute_to_class(cls, name)
        else:
            setattr(cls, name, value)


class App(object):
    """
    The base app class to be subclassed for own uses.
    """
    __metaclass__ = AppBase

    def __repr__(self):
        return '<%s: %s>' % (self.__class__.__name__, self._meta.name)

    @classmethod
    def from_name(cls, name):
        cls_name = get_class_name(name.split('.')[-1])
        return type("%sApp" % cls_name, (cls,), {'_name': name})


class AppCache(object):
    """
    A cache that stores installed applications and their models. Used to
    provide reverse-relations and for app introspection (e.g. admin).
    """
    # Use the Borg pattern to share state between all instances. Details at
    # http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/66531.
    __shared_state = dict(
        # list of loaded app instances
        app_instances = [],

        # Mapping of app_labels to a dictionary of model names to model code.
        unbound_models = {},

        # -- Everything below here is only used when populating the cache --
        loaded = False,
        handled = {},
        postponed = [],
        nesting_level = 0,
        write_lock = threading.RLock(),
        _get_models_cache = {},
    )

    def __init__(self):
        self.__dict__ = self.__shared_state

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

            # load apps listed in APP_CLASSES
            for app_name in settings.APP_CLASSES:
                if app_name in self.handled:
                    continue
                app_module, app_classname = app_name.rsplit('.', 1)
                app_module = import_module(app_module)
                app_class = getattr(app_module, app_classname)
                if not issubclass(app_class, App):
                    raise ImproperlyConfigured("'%s' must be a subclass of "
                                               "django.core.apps.App" % app_name)
                self.load_app(app_name, True, app_class)

            # load apps listed in INSTALLED_APPS
            for app_name in settings.INSTALLED_APPS:
                if app_name in self.handled:
                    continue
                self.load_app(app_name, True)

            if not self.nesting_level:
                for app_name in self.postponed:
                    self.load_app(app_name)
                # since the cache is still unseeded at this point
                # all models have been stored as unbound models
                # we need to assign the models to the app instances
                for app_label, models in self.unbound_models.iteritems():
                    app_instance = self.find_app(app_label)
                    if not app_instance:
                        raise ImproperlyConfigured(
                            'Could not find an app instance for "%s"' % app_label)
                    for model in models.itervalues():
                        app_instance._meta.models.append(model)
                # check if there is more than one app with the same
                # db_prefix attribute
                for app1 in self.app_instances:
                    for app2 in self.app_instances:
                        if (app1 != app2 and
                                app1._meta.db_prefix == app2._meta.db_prefix):
                            raise ImproperlyConfigured(
                                'The apps "%s" and "%s" have the same db_prefix "%s"'
                                % (app1, app2, app1._meta.db_prefix))
                self.loaded = True
                self.unbound_models = {}
        finally:
            self.write_lock.release()

    def load_app(self, app_name, can_postpone=False, app_class=None):
        """
        Loads the app with the provided fully qualified name, and returns the
        model module.

        Keyword Arguments:
            app_name: fully qualified name (e.g. 'django.contrib.auth')
            can_postpone: If set to True and the import raises an ImportError
                the loading will be postponed and tried again when all other
                modules are loaded.
            app_class: The app class of which an instance should be created.
        """
        self.handled[app_name] = None
        self.nesting_level += 1

        # check if an app instance with app_name already exists, if not
        # then create one
        app_instance = self.find_app(app_name.split('.')[-1])

        if not app_instance:
            if app_class:
                app_instance = app_class()
            else:
                app_instance = App.from_name(app_name)()
            self.app_instances.append(app_instance)

        try:
            models = import_module(app_instance._meta.models_path)
        except ImportError:
            self.nesting_level -= 1
            # If the app doesn't have a models module, we can just ignore the
            # ImportError and return no models for it.
            if not module_has_submodule(app_instance._meta.module, 'models'):
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
        app_instance._meta.models_module = models
        return models

    def find_app(self, label):
        """
        Returns the app instance that matches the given label.
        """
        for app in self.app_instances:
            if app._meta.label == label:
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
        return [app._meta.models_module for app in self.app_instances
                if hasattr(app._meta, 'models_module')]

    def get_app(self, app_label, emptyOK=False):
        """
        Returns the module containing the models for the given app_label. If
        the app has no models in it and 'emptyOK' is True, returns None.
        """
        self._populate()
        self.write_lock.acquire()
        try:
            for app in self.app_instances:
                if app_label == app._meta.label:
                    mod = self.load_app(app._meta.name, False)
                    if mod is None:
                        if emptyOK:
                            return None
                    else:
                        return mod
            raise ImproperlyConfigured(
                "App with label %s could not be found" % app_label)
        finally:
            self.write_lock.release()

    def get_app_errors(self):
        """
        Returns the map of known problems with the INSTALLED_APPS.
        """
        self._populate()
        errors = {}
        for app in self.app_instances:
            if app._meta.errors:
                errors.update({app._meta.label: app._meta.errors})
        return errors

    def get_models(self, app_mod=None, include_auto_created=False, include_deferred=False):
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
            app_list = self.app_instances
        model_list = []
        for app in app_list:
            model_list.extend(
                model for model in app._meta.models
                if ((not model._deferred or include_deferred)
                    and (not model._meta.auto_created or include_auto_created))
            )
        self._get_models_cache[cache_key] = model_list
        return model_list

    def get_model(self, app_label, model_name, seed_cache=True):
        """
        Returns the model matching the given app_label and case-insensitive
        model_name.

        Returns None if no model is found.
        """
        if seed_cache:
            self._populate()
        app = self.find_app(app_label)
        if self.app_cache_ready() and not app:
            return
        if cache.app_cache_ready():
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
        app_instance = self.find_app(app_label)
        if self.app_cache_ready() and not app_instance:
            raise ImproperlyConfigured(
                'Could not find an app instance with the label "%s". '
                'Please check your INSTALLED_APPS setting' % app_label)

        for model in models:
            model_name = model._meta.object_name.lower()
            if self.app_cache_ready():
                model_dict = dict([(model._meta.object_name.lower(), model)
                    for model in app_instance._meta.models])
            else:
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
            if self.app_cache_ready():
                app_instance._meta.models.append(model)
            else:
                model_dict[model_name] = model
        self._get_models_cache.clear()

cache = AppCache()
