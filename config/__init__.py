"""
Keep CheckConstraint usable across the Django versions the team runs.

Django 5.1 renamed CheckConstraint's `check` argument to `condition` and
removed `check` in 6.0. Members of this team are on different major versions,
so model code written against either spelling has to keep working on both.

The shim inspects the installed CheckConstraint and translates in whichever
direction that version needs. On Django 5.1 and 5.2, which accept both, it
does nothing.
"""

import inspect

from django.db.models import CheckConstraint

_PARAMETERS = inspect.signature(CheckConstraint.__init__).parameters
_ACCEPTS_CHECK = 'check' in _PARAMETERS
_ACCEPTS_CONDITION = 'condition' in _PARAMETERS

_original_init = CheckConstraint.__init__


if not _ACCEPTS_CHECK and _ACCEPTS_CONDITION:
    # Django 6.0 and later: `check` is gone.
    def _translating_init(self, *args, **kwargs):
        if 'check' in kwargs and 'condition' not in kwargs:
            kwargs['condition'] = kwargs.pop('check')
        return _original_init(self, *args, **kwargs)

    CheckConstraint.__init__ = _translating_init

elif _ACCEPTS_CHECK and not _ACCEPTS_CONDITION:
    # Django 5.0 and earlier: `condition` does not exist yet.
    def _translating_init(self, *args, **kwargs):
        if 'condition' in kwargs and 'check' not in kwargs:
            kwargs['check'] = kwargs.pop('condition')
        return _original_init(self, *args, **kwargs)

    CheckConstraint.__init__ = _translating_init
