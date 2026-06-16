from django.shortcuts import render
from .models import Exam


def home(request):
    upcoming_exams = Exam.objects.filter(is_active=True)[:5]
    return render(request, 'home.html', {'upcoming_exams': upcoming_exams})
