from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'virtual_exam.settings')

application = get_asgi_application()