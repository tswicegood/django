import re
import os

from django.utils.datastructures import SortedDict
from django.utils.importlib import import_module

DEFAULT_NAMES = ('verbose_name', 'db_prefix', 'models_path')

def get_verbose_name(class_name):
    new = re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', ' \\1', class_name)
    return new.lower().strip()

class AppOptions(object):
    def __init__(self, name, meta):
        self.name = name
        self.meta = meta
        self.errors = []
        self.models = SortedDict()

    def contribute_to_class(self, cls, name):
        cls._meta = self
        # get the name from the path e.g. "auth" for "django.contrib.auth"
        self.label = self.name.split('.')[-1]
        self.db_prefix = self.label
        self.module = import_module(self.name)
        self.models_path = '%s.models' % self.name
        self.models_module = None
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

    def get_path(self):
        return os.path.dirname(self.module.__file__)
