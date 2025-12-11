# core/urls.py

from django.urls import path
from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic.base import RedirectView
from . import views
from .views import DoctorReportListView, LabQueueListView, LabReportListView

urlpatterns = [
    # Root Redirect: Handles the empty path (/) and redirects to login
    path('', RedirectView.as_view(pattern_name='login', permanent=False), name='root_redirect'),

    # Authentication - Using Django's built-in LoginView
    path('login/', LoginView.as_view(template_name='core/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('dashboard/', views.dashboard_view, name='dashboard'), 
    
    # --- DOCTOR VIEWS ---
    # 1. Submission Form
    path('doctor/submit/', views.doctor_submit_view, name='doctor_submit'),
    
    # 2. Reports Tracking
    path('doctor/reports/', DoctorReportListView.as_view(), name='doctor_reports'),

    # --- LAB VIEWS ---
    # 1. Pending Queue (List)
    path('lab/queue/', LabQueueListView.as_view(), name='lab_queue'),
    
    # 2. Process Request (Detail/Creation)
    path('lab/process/<int:pk>/', views.lab_process_request, name='lab_process'), 
    
    # 3. Assignment system
    path('lab/assign/<int:pk>/', views.assign_case, name='assign_case'),
    
    # 4. CSV Export
    path('doctor/export-csv/', views.export_doctor_csv, name='export_doctor_csv'),
    path('lab/export-csv/', views.export_lab_csv, name='export_lab_csv'),
    
    # 5. Generate PDF Report
    path('report/pdf/<int:pk>/', views.generate_report_pdf, name='generate_report_pdf'),
    
    # 6. Download Lab Uploaded PDF
    path('report/download-pdf/<int:pk>/', views.download_lab_pdf, name='download_lab_pdf'),
    
    # 7. Lab reports (for lab users)
    path('lab/reports/', LabReportListView.as_view(), name='lab_reports'),
]
