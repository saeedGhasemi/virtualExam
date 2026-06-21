from django.urls import path
from . import views

urlpatterns = [
    path('', views.ExamListView.as_view(), name='exam-list'),
    path('create/', views.ExamCreateView.as_view(), name='exam-create'),
    path('<int:pk>/', views.ExamDetailView.as_view(), name='exam-detail'),
    path('<int:pk>/update/', views.ExamUpdateView.as_view(), name='exam-update'),
    path('<int:pk>/delete/', views.ExamDeleteView.as_view(), name='exam-delete'),
]