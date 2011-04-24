import os
import sys
import time

from django.conf import Settings
from django.utils.unittest import TestCase


class InstalledAppsGlobbingTest(TestCase):
    def setUp(self):
        self.OLD_SYS_PATH = sys.path[:]
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        self.OLD_TZ = os.environ.get("TZ")

    def test_globbing(self):
        settings = Settings('test_settings')
        self.assertEqual(settings.INSTALLED_APPS, ['parent.app', 'parent.app1', 'parent.app_2'])

    def tearDown(self):
        sys.path = self.OLD_SYS_PATH
        if hasattr(time, "tzset") and self.OLD_TZ:
            os.environ["TZ"] = self.OLD_TZ
            time.tzset()
