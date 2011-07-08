import logging
import sys
import traceback

from django.conf import settings
from django.core import mail
from django.views.debug import ExceptionReporter, get_exception_reporter_filter

# Make sure a NullHandler is available
# This was added in Python 2.7/3.2
try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass

# Make sure that dictConfig is available
# This was added in Python 2.7/3.2
try:
    from logging.config import dictConfig
except ImportError:
    from django.utils.dictconfig import dictConfig

getLogger = logging.getLogger

# Ensure the creation of the Django logger
# with a null handler. This ensures we don't get any
# 'No handlers could be found for logger "django"' messages
logger = getLogger('django')
if not logger.handlers:
    logger.addHandler(NullHandler())

class AdminEmailHandler(logging.Handler):
    def __init__(self, include_html=False):
        logging.Handler.__init__(self)
        self.include_html = include_html

    """An exception log handler that emails log entries to site admins.

    If the request is passed as the first argument to the log record,
    request data will be provided in the email report.
    """
    def emit(self, record):
        try:
            request = record.request
            subject = '%s (%s IP): %s' % (
                record.levelname,
                (request.META.get('REMOTE_ADDR') in settings.INTERNAL_IPS and 'internal' or 'EXTERNAL'),
                record.msg
            )
            filter = get_exception_reporter_filter(request)
            request_repr = filter.get_request_repr(request)
        except:
            subject = '%s: %s' % (
                record.levelname,
                record.msg
            )
            request = None
            request_repr = "Request repr() unavailable."

        if record.exc_info:
            exc_info = record.exc_info
            stack_trace = '\n'.join(traceback.format_exception(*record.exc_info))
        else:
            exc_info = (None, record.msg, None)
            stack_trace = 'No stack trace available'

        message = "%s\n\n%s" % (stack_trace, request_repr)
        reporter = ExceptionReporter(request, is_email=True, *exc_info)
        html_message = self.include_html and reporter.get_traceback_html() or None
        mail.mail_admins(subject, message, fail_silently=True, html_message=html_message)


class CallbackFilter(logging.Filter):
    """
    A logging filter that checks the return value of a given callable (which
    takes the record-to-be-logged as its only parameter) to decide whether to
    log a record.

    """
    def __init__(self, callback):
        self.callback = callback


    def filter(self, record):
        if self.callback(record):
            return 1
        return 0
