from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.static import serve as serve_static

urlpatterns = [
    path('favicon.ico', serve_static, {'path': 'img/favicon.ico', 'document_root': settings.STATICFILES_DIRS[0]}),
    path('admin/', admin.site.urls),
    path('', include('apps.core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = 'apps.core.views.error_404'
handler500 = 'apps.core.views.error_500'
