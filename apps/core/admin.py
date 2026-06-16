from django.contrib import admin
from .models import Exam


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('title',)
