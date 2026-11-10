from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'Core'

    def ready(self):
        from . import account_security  # noqa: F401  (connects the login/logout session signals)
        from . import auth_guard  # noqa: F401  (sign-in / sign-out audit rows in auth_events)
        from . import checks  # noqa: F401  (deployment security checks)
