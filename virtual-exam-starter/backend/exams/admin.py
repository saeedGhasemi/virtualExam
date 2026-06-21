from django.contrib import admin
from .models import Exam, Question, Answer

class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at', 'updated_at')
    search_fields = ('title',)

class QuestionAdmin(admin.ModelAdmin):
    list_display = ('exam', 'text', 'created_at', 'updated_at')
    search_fields = ('text',)

class AnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'text', 'is_correct')
    search_fields = ('text',)

admin.site.register(Exam, ExamAdmin)
admin.site.register(Question, QuestionAdmin)
admin.site.register(Answer, AnswerAdmin)