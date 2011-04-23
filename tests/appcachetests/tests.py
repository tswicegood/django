import sys
import unittest
import threading

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.apps import cache, app_loaded, pre_apps_loaded, post_apps_loaded

# remove when tests are integrated into the django testsuite
settings.configure()


class AppCacheTestCase(unittest.TestCase):
    """
    TestCase that resets the AppCache after each test.
    """

    def setUp(self):
        self.old_installed_apps = settings.INSTALLED_APPS
        settings.INSTALLED_APPS = ()
        settings.DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:'
            }
        }

    def tearDown(self):
        settings.INSTALLED_APPS = self.old_installed_apps

        # The appcache imports models modules. We need to delete the
        # imported module from sys.modules after the test has run.
        # If the module is imported again, the ModelBase.__new__ can
        # register the models with the appcache anew.
        # Some models modules import other models modules (for example
        # django.contrib.auth relies on django.contrib.contenttypes).
        # To detect which model modules have been imported, we go through
        # all loaded model classes and remove their respective module
        # from sys.modules
        for app in cache.unbound_models.itervalues():
            for name in app.itervalues():
                module = name.__module__
                if module in sys.modules:
                    del sys.modules[module]

        for app in cache.loaded_apps:
            for model in app._meta.models:
                module = model.__module__
                if module in sys.modules:
                    del sys.modules[module]

        # we cannot copy() the whole cache.__dict__ in the setUp function
        # because thread.RLock is un(deep)copyable
        cache.unbound_models = {}
        cache.loaded_apps = []

        cache.loaded = False
        cache.handled = {}
        cache.postponed = []
        cache.nesting_level = 0
        cache.write_lock = threading.RLock()
        cache._get_models_cache = {}

class AppCacheReadyTests(AppCacheTestCase):
    """
    Tests for the app_cache_ready function that indicates if the cache
    is fully populated.
    """

    def test_not_initialized(self):
        """
        Should return False if the AppCache hasn't been initialized
        """
        self.assertFalse(cache.app_cache_ready())

    def test_load_app(self):
        """
        Should return False after executing the load_app function
        """
        cache.load_app('nomodel_app')
        self.assertFalse(cache.app_cache_ready())
        cache.load_app('nomodel_app', can_postpone=True)
        self.assertFalse(cache.app_cache_ready())


class GetAppClassTests(AppCacheTestCase):
    """Tests for the get_app_class function"""

    def test_app_class(self):
        """
        Tests that the full path app class is returned
        """
        settings.INSTALLED_APPS = ('model_app.app.MyApp',)
        from model_app.app import MyApp
        app_class = cache.get_app_class(settings.INSTALLED_APPS[0])
        self.assertEquals(app_class, MyApp)

    def test_one_level_module(self):
        """
        Tests that a new app class is generated for an one level app module
        """
        settings.INSTALLED_APPS = ('model_app',)
        app_class = cache.get_app_class(settings.INSTALLED_APPS[0])
        self.assertEquals(app_class.__name__, 'ModelApp')

    def test_multi_level_module(self):
        """
        Tests that a new app class is generated for a multiple level app module
        """
        settings.INSTALLED_APPS = ('django.contrib.admin',)
        app_class = cache.get_app_class(settings.INSTALLED_APPS[0])
        self.assertEquals(app_class.__name__, 'Admin')

    def test_defunct_module(self):
        """
        Tests that a wrong module raises an ImproperlyConfigured exception
        """
        settings.INSTALLED_APPS = ('lalalala.admin',)
        self.assertRaises(ImproperlyConfigured, cache.get_app_class,
                          settings.INSTALLED_APPS[0])

    def test_missing_attribute(self):
        """
        Tests that a missing attribute raises an ImproperlyConfigured exception
        """
        settings.INSTALLED_APPS = ('nomodel_app.app.NotThereApp',)
        self.assertRaises(ImproperlyConfigured, cache.get_app_class,
                          settings.INSTALLED_APPS[0])

    def test_incorrect_subclass(self):
        """
        Tests that a class not subclassing django.core.apps.App raises an
        ImproperlyConfigured exception
        """
        settings.INSTALLED_APPS = ('nomodel_app.app.ObjectApp',)
        self.assertRaises(ImproperlyConfigured, cache.get_app_class,
                          settings.INSTALLED_APPS[0])


class GetAppsTests(AppCacheTestCase):
    """Tests for the get_apps function"""

    def test_app_classes(self):
        """
        Test that the correct models modules are returned for app classes
        installed via the INSTALLED_APPS setting
        """
        settings.INSTALLED_APPS = ('model_app.app.MyApp',)
        apps = cache.get_apps()
        self.assertTrue(cache.app_cache_ready())
        self.assertEquals(apps[0].__name__, 'model_app.othermodels')

    def test_installed_apps(self):
        """
        Test that the correct models modules are returned for apps installed
        via the INSTALLED_APPS setting
        """
        settings.INSTALLED_APPS = ('model_app',)
        apps = cache.get_apps()
        self.assertTrue(cache.app_cache_ready())
        self.assertEquals(apps[0].__name__, 'model_app.models')

    def test_same_app_in_both_settings(self):
        """
        Test that if an App is listed multiple times in INSTALLED_APPS
        only one of them is loaded
        """
        settings.INSTALLED_APPS = ('model_app.app.MyApp', 'model_app')
        apps = cache.get_apps()
        self.assertEquals(len(apps), 1)
        self.assertEquals(apps[0].__name__, 'model_app.othermodels')

    def test_empty_models(self):
        """
        Test that modules that don't contain models are not returned
        """
        settings.INSTALLED_APPS = ('nomodel_app',)
        self.assertEqual(cache.get_apps(), [])
        self.assertTrue(cache.app_cache_ready())

    def test_db_prefix_exception(self):
        """
        Test that an exception is raised if two app instances
        have the same db_prefix attribute
        """
        settings.INSTALLED_APPS = ('nomodel_app.app.MyApp',
                                   'model_app.app.MyOtherApp')
        self.assertRaises(ImproperlyConfigured, cache.get_apps)


class GetAppTests(AppCacheTestCase):
    """Tests for the get_app function"""

    def test_installed_apps(self):
        """
        Test that the correct module is returned when the app was installed
        via the INSTALLED_APPS setting
        """
        settings.INSTALLED_APPS = ('model_app',)
        mod = cache.get_app('model_app')
        self.assertTrue(cache.app_cache_ready())
        self.assertEquals(mod.__name__, 'model_app.models')

    def test_not_found_exception(self):
        """
        Test that an ImproperlyConfigured exception is raised if an app
        could not be found
        """
        self.assertRaises(ImproperlyConfigured, cache.get_app,
                          'notarealapp')
        self.assertTrue(cache.app_cache_ready())

    def test_emptyOK(self):
        """
        Test that None is returned if emptyOK is True and the module
        has no models
        """
        settings.INSTALLED_APPS = ('nomodel_app',)
        module = cache.get_app('nomodel_app', emptyOK=True)
        self.assertTrue(cache.app_cache_ready())
        self.failUnless(module is None)

    def test_exception_if_no_models(self):
        """
        Test that an ImproperlyConfigured exception is raised if the app
        has no modules and the emptyOK arg is False
        """
        settings.INSTALLED_APPS = ('nomodel_app',)
        self.assertRaises(ImproperlyConfigured, cache.get_app,
                          'nomodel_app')
        self.assertTrue(cache.app_cache_ready())


class GetAppErrorsTests(AppCacheTestCase):
    """Tests for the get_app_errors function"""

    def test_get_app_errors(self):
        """Test that the function returns an empty dict"""
        self.assertEqual(cache.get_app_errors(), {})
        self.assertTrue(cache.app_cache_ready())


class GetModelsTests(AppCacheTestCase):
    """Tests for the get_models function"""

    def test_get_models(self):
        """
        Test that only models from apps are returned that are listed in
        the INSTALLED_APPS setting
        """
        from anothermodel_app.models import Person
        from model_app.models import Person
        settings.INSTALLED_APPS = ('model_app',)
        models = cache.get_models()
        self.assertTrue(cache.app_cache_ready())
        self.assertEqual(models, [Person])

    def test_app_mod(self):
        """
        Test that the correct model classes are returned if an
        app module is specified
        """
        from model_app import models
        settings.INSTALLED_APPS = ('model_app', 'anothermodel_app',)
        models = cache.get_models(app_mod=models)
        self.assertTrue(cache.app_cache_ready())
        from model_app.models import Person
        self.assertEqual(models, [Person])

    def test_include_auto_created(self):
        """
        Test that auto created models are included
        """
        settings.INSTALLED_APPS = ('anothermodel_app',)
        models = cache.get_models(include_auto_created=True)
        self.assertTrue(cache.app_cache_ready())
        from anothermodel_app.models import Job, Person
        self.assertEqual(models[0].__name__, 'Person_jobs')
        self.assertEqual(models[1], Job)
        self.assertEqual(models[2], Person)


class GetModelTests(AppCacheTestCase):
    """Tests for the get_model function"""

    def test_seeded_only_installed_valid(self):
        """
        Test that the correct model is returned if the cache is seeded
        and only models from apps listed in INSTALLED_APPS should be returned
        """
        settings.INSTALLED_APPS = ('model_app',)
        model = cache.get_model('model_app', 'Person')
        self.assertEqual(model.__name__, 'Person')
        self.assertTrue(cache.app_cache_ready())

    def test_seeded_only_installed_invalid(self):
        """
        Test that None is returned if the cache is seeded but the model
        was not registered with the cache
        """
        model = cache.get_model('model_app', 'Person')
        self.assertEqual(model, None)
        self.assertTrue(cache.app_cache_ready())

    def test_unseeded_only_installed_valid(self):
        """
        Test that the correct model is returned if the cache is unseeded, but
        the model was registered
        """
        from model_app.models import Person
        model = cache.get_model('model_app', 'Person', seed_cache=False)
        self.assertEqual(model.__name__, 'Person')
        self.assertFalse(cache.app_cache_ready())

    def test_unseeded_only_installed_invalid(self):
        """
        Test that None is returned if the cache is unseeded and the model
        was not registered with the cache
        """
        model = cache.get_model('model_app', 'Person', seed_cache=False)
        self.assertEqual(model, None)
        self.assertFalse(cache.app_cache_ready())

    def test_seeded_all_models_valid(self):
        """
        Test that the correct model is returned if the cache is seeded and
        all models (including unbound) should be returned
        """
        cache._populate()
        from model_app.models import Person
        model = cache.get_model('model_app', 'Person', only_installed=False)
        self.assertEquals(model, Person)

    def test_seeded_all_models_invalid(self):
        """
        Test that None is returned if the cache is seeded and all models
        should be returned, but the model wasnt registered with the cache
        """
        cache._populate()
        model = cache.get_model('model_app', 'Person', only_installed=False)
        self.assertEquals(model, None)

    def test_unseeded_all_models_valid(self):
        """
        Test that the correct model is returned if the cache is unseeded and
        all models should be returned
        """
        from model_app.models import Person
        model = cache.get_model('model_app', 'Person', seed_cache=False, only_installed=False)
        self.assertEquals(model, Person)

    def test_unseeded_all_models_invalid(self):
        """
        Test that None is returned if the cache is unseeded, all models should
        be returned but the model wasn't registered with the cache
        """
        model = cache.get_model('model_app', 'Person', seed_cache=False, only_installed=False)
        self.assertEquals(model, None)

class LoadAppTests(AppCacheTestCase):
    """Tests for the load_app function"""

    def test_with_models(self):
        """
        Test that an app instance is created and the models
        module is returned
        """
        mod = cache.load_app('model_app')
        app = cache.loaded_apps[0]
        self.assertEqual(len(cache.loaded_apps), 1)
        self.assertEqual(app._meta.name, 'model_app')
        self.assertEqual(app._meta.models_module.__name__, 'model_app.models')
        self.assertEqual(mod.__name__, 'model_app.models')

    def test_with_custom_models(self):
        """
        Test that custom models are imported correctly, if the App specifies
        an models_path attribute
        """
        from model_app.app import MyApp
        mod = cache.load_app('model_app.app.MyApp', can_postpone=False)
        app = cache.loaded_apps[0]
        self.assertEqual(app._meta.models_module.__name__, 'model_app.othermodels')
        self.assertTrue(isinstance(app, MyApp))
        self.assertEqual(mod.__name__, 'model_app.othermodels')

    def test_without_models(self):
        """
        Test that an app instance is created even when there are
        no models provided
        """
        mod = cache.load_app('nomodel_app')
        app = cache.loaded_apps[0]
        self.assertEqual(len(cache.loaded_apps), 1)
        self.assertEqual(app._meta.name, 'nomodel_app')
        self.assertEqual(mod, None)

    def test_loading_the_same_app_twice(self):
        """
        Test that loading the same app twice results in only one app instance
        being created
        """
        mod = cache.load_app('model_app')
        mod2 = cache.load_app('model_app')
        self.assertEqual(len(cache.loaded_apps), 1)
        self.assertEqual(mod.__name__, 'model_app.models')
        self.assertEqual(mod2.__name__, 'model_app.models')

    def test_importerror(self):
        """
        Test that an ImportError exception is raised if a package cannot
        be imported
        """
        self.assertRaises(ImportError, cache.load_app, 'garageland')


class RegisterModelsTests(AppCacheTestCase):
    """Tests for the register_models function"""

    def test_seeded_cache(self):
        """
        Test that the models are attached to the correct app instance
        in a seeded cache
        """
        settings.INSTALLED_APPS = ('model_app',)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        app_models = cache.loaded_apps[0]._meta.models
        self.assertEqual(len(app_models), 1)
        self.assertEqual(app_models[0].__name__, 'Person')

    def test_seeded_cache_invalid_app(self):
        """
        Test that registering models with an app that doesn't have an app
        instance works
        """
        settings.INSTALLED_APPS = ('model_app',)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        from model_app.models import Person
        cache.register_models('model_app_NONEXISTENT', *(Person,))
        self.assertEquals(cache.unbound_models['model_app_NONEXISTENT']['person'], Person)

    def test_unseeded_cache(self):
        """
        Test that models can be registered with an unseeded cache
        """
        from model_app.models import Person
        self.assertFalse(cache.app_cache_ready())
        self.assertEquals(cache.unbound_models['model_app']['person'], Person)

class FindAppTests(AppCacheTestCase):
    """Tests for the find_app function"""

    def test_seeded(self):
        """
        Test that the correct app is returned when the cache is seeded
        """
        from django.core.apps import App
        settings.INSTALLED_APPS = ('model_app',)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        app = cache.find_app('model_app')
        self.assertEquals(app._meta.name, 'model_app')
        self.assertTrue(isinstance(app, App))
        self.assertEquals(app.__repr__(), '<App: model_app>')

    def test_unseeded(self):
        """
        Test that the correct app is returned when the cache is unseeded
        """
        from django.core.apps import App
        cache.load_app('model_app')
        self.assertFalse(cache.app_cache_ready())
        app = cache.find_app('model_app')
        self.assertEquals(app._meta.name, 'model_app')
        self.assertTrue(isinstance(app, App))

class SignalTests(AppCacheTestCase):
    """Tests for the signals"""

    def setUp(self):
        super(SignalTests, self).setUp()
        self.signal_fired = False

    def test_app_loaded(self):
        """
        Test the app_loaded signal
        """
        # connect the callback before the cache is initialized
        def app_loaded_callback(sender, app, **kwargs):
            self.assertEqual(app._meta.name, 'model_app')
            self.signal_fired = True
        app_loaded.connect(app_loaded_callback)

        settings.INSTALLED_APPS = ('model_app',)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        self.assertTrue(self.signal_fired)

    def test_pre_apps_loaded(self):
        """
        Test the pre_apps_loaded signal
        """
        def callback(sender, **kwargs):
            self.signal_fired = True
        pre_apps_loaded.connect(callback)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        self.assertTrue(self.signal_fired)

    def test_post_apps_loaded(self):
        """
        Test the post_apps_loaded signal
        """
        def callback(sender, **kwargs):
            self.signal_fired = True
        post_apps_loaded.connect(callback)
        cache._populate()
        self.assertTrue(cache.app_cache_ready())
        self.assertTrue(self.signal_fired)

if __name__ == '__main__':
    unittest.main()
