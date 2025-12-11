# core/views.py

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth import authenticate, login, logout
from django.urls import reverse_lazy
from django.contrib import messages
from django.views.generic import ListView
from django.views import View
from django.http import HttpResponse
from io import BytesIO
import os
import csv
from django.utils import timezone

# ReportLab PDF Imports
from reportlab.lib import colors 
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib.units import inch

from .models import Request, PortalUser, Report, RequestHistory
from .forms import DoctorRequestForm, LabReportForm


# ==========================================
# MIXINS
# ==========================================
class DoctorRequiredMixin(UserPassesTestMixin):
    """Allows access only if the user is a Doctor."""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_doctor()


class LabRequiredMixin(UserPassesTestMixin):
    """Allows access only if the user is a Lab Technician."""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_lab()


# ==========================================
# LOGIN & DASHBOARD
# ==========================================
@login_required
def dashboard_view(request):
    if request.user.is_doctor():
        return redirect('doctor_submit')
    elif request.user.is_lab():
        return redirect('lab_queue')
    return render(request, 'core/dashboard.html')


@login_required
def dashboard_view(request):
    if request.user.is_doctor():
        return redirect('doctor_submit')
    elif request.user.is_lab():
        return redirect('lab_queue')
    return render(request, 'core/dashboard.html')


# ==========================================
# DOCTOR: SUBMIT REQUEST
# ==========================================
@login_required
@user_passes_test(lambda u: u.is_doctor(), login_url='login')
def doctor_submit_view(request):
    if request.method == 'POST':
        form = DoctorRequestForm(request.POST, request.FILES)
        if form.is_valid():
            new_request = form.save(commit=False)
            new_request.doctor = request.user
            new_request.status = 'Pending'
            
            # Handle lab tech assignment
            assigned_to = form.cleaned_data.get('assigned_to')
            lab_techs = PortalUser.objects.filter(role='Lab', is_active=True)
            
            if not lab_techs.exists():
                # No lab techs available
                messages.error(request, "Cannot submit request: No lab technicians available. Please contact administrator.")
                return render(request, 'core/doctor_submit.html', {
                    'form': form,
                    'page_title': 'New Sample Submission',
                    'total_cases': Request.objects.filter(doctor=request.user).count(),
                    'pending_cases': Request.objects.filter(doctor=request.user, status='Pending').count(),
                })
            
            if assigned_to:
                # Doctor explicitly selected a lab tech
                new_request.assigned_to = assigned_to
                new_request.assignment_status = 'Assigned'
                new_request.assigned_date = timezone.now()
                assignment_msg = f"assigned to {assigned_to.full_name}"
            else:
                # Auto-assign to the least busy lab tech (fewest assigned pending cases)
                least_busy = min(
                    lab_techs,
                    key=lambda tech: tech.assigned_requests.filter(
                        status='Pending'
                    ).count()
                )
                new_request.assigned_to = least_busy
                new_request.assignment_status = 'Assigned'
                new_request.assigned_date = timezone.now()
                assignment_msg = f"auto-assigned to {least_busy.full_name} (least busy)"
            
            new_request.save()

            # Record history entry for the new submission
            try:
                assignment_note = f"Submitted by Dr. {request.user.full_name} and {assignment_msg}"
                RequestHistory.objects.create(
                    request=new_request,
                    user=request.user,
                    action='Submitted',
                    note=assignment_note
                )
            except Exception:
                pass

            messages.success(request, f"Request for Patient {new_request.patient_id} submitted successfully and {assignment_msg}!")
            return redirect('doctor_reports')
    else:
        form = DoctorRequestForm()

    # Compute summary counts for the toolbar
    total_cases = Request.objects.filter(doctor=request.user).count()
    pending_cases = Request.objects.filter(doctor=request.user, status='Pending').count()

    return render(request, 'core/doctor_submit.html', {
        'form': form,
        'page_title': 'New Sample Submission',
        'total_cases': total_cases,
        'pending_cases': pending_cases,
    })


# ==========================================
# DOCTOR: REPORT LIST
# ==========================================
class DoctorReportListView(DoctorRequiredMixin, ListView):
    model = Request
    template_name = 'core/doctor_reports.html'
    context_object_name = 'requests'

    def get_queryset(self):
        return Request.objects.filter(doctor=self.request.user).order_by('-timestamp')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for r in ctx['requests']:
            try:
                r.report_data = r.report
            except Report.DoesNotExist:
                r.report_data = None
            # Attach history entries (latest first) - don't assign to related set
            r.history_list = list(r.history_entries.all()[:20])
        return ctx


# ==========================================
# LAB: PENDING QUEUE
# ==========================================
class LabQueueListView(LabRequiredMixin, ListView):
    model = Request
    template_name = 'core/lab_queue.html'
    context_object_name = 'pending_requests'

    def get_queryset(self):
        # Show ONLY cases assigned to THIS lab tech
        return Request.objects.filter(
            status='Pending',
            assigned_to=self.request.user
        ).order_by('timestamp')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        for r in ctx['pending_requests']:
            r.history_list = list(r.history_entries.all()[:20])
        # Summary counts for header
        ctx['total_cases'] = Request.objects.filter(assigned_to=self.request.user).count()
        ctx['pending_count'] = len(ctx['pending_requests'])
        return ctx


class LabReportListView(LabRequiredMixin, ListView):
    """List of completed reports for lab users - only those assigned to them."""
    model = Request
    template_name = 'core/lab_reports.html'
    context_object_name = 'reports'

    def get_queryset(self):
        # Show ONLY completed cases assigned to THIS lab tech
        return Request.objects.filter(
            status='Completed',
            assigned_to=self.request.user
        ).order_by('-timestamp')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # attach report object where present
        for r in ctx['reports']:
            try:
                r.report_data = r.report
            except Report.DoesNotExist:
                r.report_data = None
            r.history_list = list(r.history_entries.all()[:20])
        ctx['total_reports'] = len(ctx['reports'])
        return ctx


# # ==========================================
# # LAB: PROCESS REQUEST
# # ==========================================
# @login_required
# @user_passes_test(lambda u: u.is_lab(), login_url='login')
# def lab_process_request(request, pk):
#     request_obj = get_object_or_404(Request, pk=pk, status='Pending')

#     if request.method == 'POST':
#         form = LabReportForm(request.POST)
#         if form.is_valid():
#             report = form.save(commit=False)
#             report.request = request_obj
#             report.save()

#             request_obj.status = 'Completed'
#             request_obj.save()

#             # Record history entry for completion
#             try:
#                 RequestHistory.objects.create(
#                     request=request_obj,
#                     user=request.user,
#                     action='Report Completed',
#                     note=f"Report authored by {report.auth_by}"
#                 )
#             except Exception:
#                 pass

#             messages.success(request, f"Report for {request_obj.patient_id} completed!")
#             return redirect('lab_queue')
#     else:
#         form = LabReportForm(initial={'auth_by': request.user.full_name})

#     return render(request, 'core/lab_process.html', {
#         'request_obj': request_obj,
#         'form': form,
#         'page_title': f'Process Request: {request_obj.patient_id}'
#     })
# ==========================================
# LAB: PROCESS REQUEST
# ==========================================
@login_required
@user_passes_test(lambda u: u.is_lab(), login_url='login')
@login_required
@user_passes_test(lambda u: u.is_lab(), login_url='login')
def lab_process_request(request, pk):
    request_obj = get_object_or_404(Request, pk=pk, status='Pending')

    if request.method == 'POST':
        form = LabReportForm(request.POST, request.FILES)
        if form.is_valid():
            report = form.save(commit=False)
            report.request = request_obj
            
            # Handle PDF upload
            if 'microbiology_pdf' in request.FILES:
                report.microbiology_pdf = request.FILES['microbiology_pdf']
                report.pdf_uploaded_date = timezone.now()
            
            report.save()

            request_obj.status = 'Completed'
            request_obj.assignment_status = 'Completed'
            request_obj.save()

            # Record history entry for completion
            try:
                pdf_note = ""
                if report.microbiology_pdf:
                    pdf_note = " (with PDF)"
                RequestHistory.objects.create(
                    request=request_obj,
                    user=request.user,
                    action='Report Completed',
                    note=f"Report authored by {report.auth_by}{pdf_note}"
                )
            except Exception:
                pass

            messages.success(request, f"Report for {request_obj.patient_id} completed!")
            return redirect('lab_queue')
    else:
        form = LabReportForm(initial={'auth_by': request.user.full_name})

    # ✅ FIX FOR STAIN DISPLAY (ADD THIS)
    stains = []
    if request_obj.stain:
        stains = [s.strip() for s in request_obj.stain.split(",")]

    return render(request, 'core/lab_process.html', {
        'request_obj': request_obj,
        'form': form,
        'page_title': f'Process Request: {request_obj.patient_id}',
        'stains': stains   # ✅ PASS TO TEMPLATE
    })
# ==========================================

def logout_view(request):
    """Log out the user and redirect to login. Accepts GET or POST to avoid 405 errors."""
    logout(request)
    return redirect('login')


# ==========================================
# REPORT VIEW: PDF Generation (TABLE LAYOUT)
# ==========================================
@login_required
@user_passes_test(lambda user: user.is_doctor() or user.is_lab(), login_url='login')
def generate_report_pdf(request, pk):
    """Generates a PDF report using a structured table layout."""
    
    request_obj = get_object_or_404(Request, pk=pk)
    try:
        report_obj = request_obj.report
    except Report.DoesNotExist:
        messages.error(request, "Report has not been completed yet.")
        if request.user.is_doctor():
            return redirect('doctor_reports')
        return redirect('lab_queue')

    response = HttpResponse(content_type='application/pdf')
    filename = f"Microbio_Report_{request_obj.patient_id}_{request_obj.id}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # Create PDF buffer
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, 
                            leftMargin=0.5*inch, rightMargin=0.5*inch, 
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    
    styles = getSampleStyleSheet()
    story = []
    
    def bold(text, style=styles['Normal']):
        return Paragraph(f"<b>{text}</b>", style)

    # --- 1. Title ---
    title_style = styles['Title'].clone('CustomTitle')
    title_style.alignment = 1
    title_style.fontSize = 16
    story.append(Paragraph("Ocular Microbiology Laboratory Report", title_style))
    story.append(Spacer(1, 0.25 * inch))

    # Define Column Widths for main tables
    col_widths_clinical = [1.3*inch, 2.2*inch, 1.3*inch, 1.7*inch]
    
    # --- 2. Patient & Clinical Details Table ---
    
    # Format medications properly
    meds_display = ""
    if request_obj.on_meds:
        if request_obj.meds_category == 'Others':
            meds_display = request_obj.meds_custom
        else:
            meds_display = request_obj.get_meds_category_display()
    else:
        meds_display = "No medications"

    # Format duration
    duration_display = f"{request_obj.duration_value} {request_obj.get_duration_unit_display()}"

    clinical_data_flat = [
        [bold("Patient & Clinical Details"), "", "", ""],
        [bold("Patient ID:"), request_obj.patient_id, bold("Centre:"), request_obj.centre_name],
        [bold("Eye:"), request_obj.get_eye_display(), bold("Date Submitted:"), request_obj.timestamp.strftime('%Y-%m-%d %H:%M')],
        [bold("Sample:"), request_obj.get_sample_display(), bold("Duration:"), duration_display],
        [bold("Medications:"), meds_display, bold("Stain Used:"), request_obj.stain],
        [bold("Clinical Impression:"), request_obj.get_impression_display(), "", ""], 
    ]

    clinical_table = Table(clinical_data_flat, colWidths=col_widths_clinical)
    
    clinical_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('SPAN', (0, 0), (3, 0)), 
        ('FONTNAME', (0, 0), (3, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (3, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    story.append(clinical_table)
    story.append(Spacer(1, 0.25 * inch))

    # --- 3. Laboratory Interpretation Table ---
    
    report_quality = report_obj.quality if report_obj.quality else "N/A"
    report_suitability = "Yes" if report_obj.sample_suitability else "No (Specify reason below)"
    reason_display = report_obj.suitability_reason if not report_obj.sample_suitability and report_obj.suitability_reason else "N/A"

    lab_data_flat = [
        [bold("Laboratory Interpretation"), "", "", ""],
        [bold("Lab ID:"), report_obj.lab_id, bold("RC Code:"), report_obj.rc_code],
        [bold("Sample Suitability:"), report_suitability, bold("Quality:"), report_quality],
        [bold("Suitability Reason:"), reason_display, "", ""],
    ]
    
    lab_table = Table(lab_data_flat, colWidths=col_widths_clinical)
    
    lab_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('SPAN', (0, 0), (3, 0)),
        ('FONTNAME', (0, 0), (3, 0), 'Helvetica-Bold'),
        ('BACKGROUND', (0, 0), (3, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    
    story.append(lab_table)
    story.append(Spacer(1, 0.25 * inch))

    # --- 4. Report Text and Comments Table ---
    report_data = [
        [bold("Microbiology Report:"), Paragraph(report_obj.report_text.replace('\n', '<br/>'), styles['BodyText'])],
        [bold("Additional Comments:"), Paragraph(report_obj.comments.replace('\n', '<br/>') if report_obj.comments else "None", styles['BodyText'])],
    ]
    
    report_table = Table(report_data, colWidths=[1.5*inch, 4.5*inch])
    
    report_table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('PADDING', (0, 0), (-1, 0), 6), 
        ('PADDING', (0, 1), (-1, 1), 6),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))

    story.append(report_table)
    story.append(Spacer(1, 0.25 * inch))

    # --- 5. Clinical Image Section ---
    if request_obj.image and os.path.exists(request_obj.image.path):
        try:
            story.append(bold("Clinical Image:"))
            story.append(Spacer(1, 0.1 * inch))
            img = Image(request_obj.image.path, width=5*inch, height=5*inch, kind='proportional')
            story.append(img)
            story.append(Spacer(1, 0.25 * inch))
        except Exception as e:
            story.append(Paragraph(f"<i>Note: Image could not be loaded ({str(e)})</i>", styles['Normal']))
            story.append(Spacer(1, 0.25 * inch))
    
    # --- 6. Authorization and Disclaimer ---
    story.append(Paragraph(f"<para alignment='right'><b>Authorized By:</b> {report_obj.auth_by}</para>", styles['Normal']))
    story.append(Spacer(1, 0.5 * inch))

    # Disclaimer
    disclaimer_style = styles['Normal'].clone('Disclaimer')
    disclaimer_style.fontSize = 8
    
    disclaimer_text = """
    <b>DISCLAIMER:</b> This report is generated based on the images provided by the clinician and may be subject to change on review of the entire slide at the reading centre. 
    This report acts solely as a guide to a clinician for clinical correlation. The reading centre is not responsible for any complications that may arise during the treatment of the patient.
    <br/><br/>
    <i>Generated electronically by Microbiology Portal - Ocular Microbiology Reading Centre</i>
    """
    
    story.append(Paragraph(disclaimer_text, disclaimer_style))

    # Build PDF
    doc.build(story)
    response.write(buffer.getvalue())
    buffer.close()
    
    return response

# ==========================================
# LOGOUT
# ==========================================
@login_required
def logout_user(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')


# ==========================================
# ASSIGNMENT SYSTEM
# ==========================================
@login_required
@user_passes_test(lambda u: u.is_lab(), login_url='login')
def assign_case(request, pk):
    """Assign a pending case to the current lab technician."""
    case = get_object_or_404(Request, pk=pk, status='Pending', assignment_status='Unassigned')
    
    if request.method == 'POST':
        case.assigned_to = request.user
        case.assignment_status = 'Assigned'
        case.assigned_date = timezone.now()
        case.save()
        
        # Record history
        try:
            RequestHistory.objects.create(
                request=case,
                user=request.user,
                action='Assigned',
                note=f"Assigned to {request.user.full_name}"
            )
        except Exception:
            pass
        
        messages.success(request, f"Case {case.patient_id} assigned to you.")
        return redirect('lab_queue')
    
    return render(request, 'core/confirm_assign.html', {'case': case})


# ==========================================
# CSV EXPORT
# ==========================================
@login_required
@user_passes_test(lambda u: u.is_doctor(), login_url='login')
def export_doctor_csv(request):
    """Export all cases submitted by the doctor to CSV with lab details for completed ones."""
    cases = Request.objects.filter(doctor=request.user).order_by('-timestamp')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="doctor_cases_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    # Enhanced headers with lab details
    writer.writerow([
        'Patient ID', 'Centre', 'Eye', 'Sample Type', 'Duration', 'Impression', 'Stain', 
        'Status', 'Assigned Lab Tech', 'Lab ID', 'RC Code', 'Quality', 'Suitability', 
        'Report Text', 'Authorized By', 'Submitted Date'
    ])
    
    for case in cases:
        # Get lab report if available
        try:
            report = case.report
            lab_id = report.lab_id
            rc_code = report.rc_code
            quality = report.quality
            suitability = "Yes" if report.sample_suitability else "No"
            report_text = report.report_text[:200]  # First 200 chars
            auth_by = report.auth_by
        except Report.DoesNotExist:
            lab_id = 'N/A'
            rc_code = 'N/A'
            quality = 'N/A'
            suitability = 'N/A'
            report_text = 'N/A'
            auth_by = 'N/A'
        
        assigned_tech = case.assigned_to.full_name if case.assigned_to else 'Unassigned'
        
        writer.writerow([
            case.patient_id,
            case.centre_name,
            case.get_eye_display(),
            case.get_sample_display(),
            f"{case.duration_value} {case.get_duration_unit_display()}",
            case.get_impression_display(),
            case.stain or 'N/A',
            case.status,
            assigned_tech,
            lab_id,
            rc_code,
            quality,
            suitability,
            report_text,
            auth_by,
            case.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    
    return response


@login_required
@user_passes_test(lambda u: u.is_lab(), login_url='login')
def export_lab_csv(request):
    """Export all cases assigned to the lab technician to CSV."""
    cases = Request.objects.filter(assigned_to=request.user).order_by('-timestamp')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="lab_cases_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Patient ID', 'Doctor', 'Centre', 'Eye', 'Sample Type', 'Duration', 'Impression', 'Stain', 'Status', 'Assigned Date', 'Status'])
    
    for case in cases:
        doctor_name = case.doctor.full_name if case.doctor else 'Unknown'
        writer.writerow([
            case.patient_id,
            doctor_name,
            case.centre_name,
            case.get_eye_display(),
            case.get_sample_display(),
            f"{case.duration_value} {case.get_duration_unit_display()}",
            case.get_impression_display(),
            case.stain or 'N/A',
            case.status,
            case.assigned_date.strftime('%Y-%m-%d %H:%M:%S') if case.assigned_date else 'N/A',
            case.assignment_status,
        ])
    
    return response


# ==========================================
# DOWNLOAD LAB PDF
# ==========================================
@login_required
@user_passes_test(lambda u: u.is_doctor(), login_url='login')
def download_lab_pdf(request, pk):
    """Download the microbiology report PDF uploaded by lab tech."""
    case = get_object_or_404(Request, pk=pk, doctor=request.user, status='Completed')
    
    try:
        report = case.report
    except Report.DoesNotExist:
        messages.error(request, "Report not found for this case.")
        return redirect('doctor_reports')
    
    if not report.microbiology_pdf:
        messages.error(request, "No PDF has been uploaded for this report yet.")
        return redirect('doctor_reports')
    
    # Serve the PDF file
    if os.path.exists(report.microbiology_pdf.path):
        with open(report.microbiology_pdf.path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="microbio_report_{case.patient_id}.pdf"'
            return response
    else:
        messages.error(request, "PDF file not found on server.")
        return redirect('doctor_reports')

