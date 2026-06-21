from django.shortcuts import render
from rest_framework import viewsets
from .models import Exam
from .serializers import ExamSerializer

class ExamViewSet(viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer

def index(request):
    return render(request, 'exams/index.html')