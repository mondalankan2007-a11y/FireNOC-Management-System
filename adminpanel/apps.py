from django.apps import AppConfig


class AdminpanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'adminpanel'
    verbose_name = 'Admin, Database & NOC Module'

    def ready(self):
        # Registers the post_save receiver that keeps the normalized tables
        # in step with applications as they are submitted.
        from . import signals  # noqa: F401
