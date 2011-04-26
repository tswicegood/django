from django import apps
from django.utils.translation import ugettext_lazy as _

class AuthApp(apps.App):

    class Meta:
        verbose_name = _('auth')
