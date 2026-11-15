"""Application logs: one JSON object per line on stderr, with the request id.

    import logging_setup
    logging_setup.configure()          # in webApp, before the model code is imported
    logger = logging_setup.get_logger(__name__)
    logger.info('scored', extra={'fields': {'total_ms': 812}})

The app's own loggers live under the 'aipt' namespace and log from LOG_LEVEL
(default INFO). Libraries that log through the root logger log errors only:
Piper warns once for every phoneme its voice lacks, so a crafted text would
otherwise write hundreds of lines per request. transformers keeps its own
handler and level.

Logging has to be configured before the model code is imported: epitran calls
logging.basicConfig(level=CRITICAL) on import, which does nothing once the
root logger has a handler.

Never log what a user typed or said: no sentence text, no audio, no transcript.
"""
import json
import logging
import os
import sys
import time

APP_NAMESPACE = 'aipt'
# Keys every line has; extra fields never overwrite them.
_CORE_KEYS = ('t', 'level', 'logger', 'pid', 'msg', 'rid', 'exc')


def get_logger(name: str) -> logging.Logger:
    """Logger for an app module, e.g. get_logger(__name__) -> 'aipt.webApp'."""
    return logging.getLogger(f'{APP_NAMESPACE}.{name}')


class RequestIdFilter(logging.Filter):
    """Adds the id of the request being served (webApp sets flask.g.request_id)."""

    def filter(self, record):
        if getattr(record, 'request_id', None) is None:
            try:
                from flask import g, has_request_context
                if has_request_context():
                    record.request_id = g.get('request_id')
            except Exception:  # noqa: BLE001 - logging must never break a request
                pass
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per record. json.dumps escapes quotes, newlines and every
    non-ASCII character, so no value can break the line or forge another one."""

    converter = time.gmtime

    def format(self, record):
        payload = {
            't': self.formatTime(record, '%Y-%m-%dT%H:%M:%SZ'),
            'level': record.levelname.lower(),
            'logger': record.name,
            'pid': record.process,
            'msg': record.getMessage(),
        }
        request_id = getattr(record, 'request_id', None)
        if request_id:
            payload['rid'] = request_id
        fields = getattr(record, 'fields', None)
        if isinstance(fields, dict):
            payload.update({key: value for key, value in fields.items() if key not in _CORE_KEYS})
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def json_handler(stream=None) -> logging.Handler:
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    handler._aipt_json = True
    return handler


def configure():
    """Send logs to stderr as JSON lines. Safe to call more than once."""
    root = logging.getLogger()
    if not any(getattr(handler, '_aipt_json', False) for handler in root.handlers):
        root.addHandler(json_handler())
    root.setLevel(logging.ERROR)
    logging.getLogger(APP_NAMESPACE).setLevel(os.environ.get('LOG_LEVEL', 'INFO').upper())
