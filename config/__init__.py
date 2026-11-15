"""
Django 6.x backward compatibility patch for CheckConstraint(check=...).
In Django 5.1, 'check' was deprecated in favor of 'condition', and in Django 6.x
it was removed from CheckConstraint.__init__. This patch maps 'check' to 'condition'
so that existing migrations and models using 'check' continue to work seamlessly.
"""
from django.db.models import CheckConstraint

_orig_check_constraint_init = CheckConstraint.__init__


def _patched_check_constraint_init(self, *args, **kwargs):
    if 'check' in kwargs and 'condition' not in kwargs:
        kwargs['condition'] = kwargs.pop('check')
    return _orig_check_constraint_init(self, *args, **kwargs)


CheckConstraint.__init__ = _patched_check_constraint_init

