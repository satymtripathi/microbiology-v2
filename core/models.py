# Create your models here.
# core/models.py

from django.db import models
from django.contrib.auth.models import AbstractUser

# ==========================================
# 1. CUSTOM USER MODEL
# ==========================================
class PortalUser(AbstractUser):
    ROLE_CHOICES = (
        ('Doctor', 'Doctor'),
        ('Lab', 'Lab Technician'),
    )
    
    # Link the custom fields
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='Doctor')
    full_name = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=4, default='0000', help_text="4-digit PIN for login")
    reading_centre_code = models.CharField(max_length=50, blank=True, null=True, help_text="Lab reading centre code")

    # Helper methods for role checking
    def is_doctor(self):
        return self.role == 'Doctor'

    def is_lab(self):
        return self.role == 'Lab'
        
    def __str__(self):
        return f"{self.full_name} ({self.role})"


# ==========================================
# 2. CORE DATA MODELS
# ==========================================
class Request(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending Analysis'),
        ('Completed', 'Report Completed'),
    )
    
    ASSIGNMENT_STATUS_CHOICES = (
        ('Unassigned', 'Unassigned'),
        ('Assigned', 'Assigned'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
    )
    
    EYE_CHOICES = (
        ('OD', 'Right Eye (OD)'),
        ('OS', 'Left Eye (OS)'),
        ('OU', 'Both Eyes (OU)'),
        ('NA', 'Not Applicable (NA)'),
    )
    
    SAMPLE_CHOICES = (
        ('Corneal Scraping', 'Corneal Scraping'),
        ('Conjunctival Swab', 'Conjunctival Swab'),
        ('Tear Film', 'Tear Film'),
        ('Contact Lens', 'Contact Lens'),
        ('Eyelid', 'Eyelid'),
        ('Other', 'Other'),
    )
    
    DURATION_UNIT_CHOICES = (
        ('Days', 'Days'),
        ('Weeks', 'Weeks'),
        ('Months', 'Months'),
        ('Years', 'Years'),
    )
    
    IMPRESSION_CHOICES = (
        ('Bacterial', 'Bacterial'),
        ('Fungal', 'Fungal'),
        ('Acanthamoeba', 'Acanthamoeba'),
        ('Pythium', 'Pythium'),
        ('Viral', 'Viral'),
        ('Others', 'Others'),
    )
    
    MED_CATEGORY_CHOICES = (
        ('Antibiotics', 'Antibiotics'),
        ('Antifungals', 'Antifungals'),
        ('Antiviral', 'Antiviral'),
        ('Steroid', 'Steroid'),
        ('Others', 'Others (Text)'),
    )
    
    # Submission Details
    timestamp = models.DateTimeField(auto_now_add=True)
    # Link to the Doctor user who submitted it
    doctor = models.ForeignKey(PortalUser, on_delete=models.PROTECT, limit_choices_to={'role': 'Doctor'})
    centre_name = models.CharField(max_length=100)
    
    # Patient & Clinical Info
    patient_id = models.CharField(max_length=50)
    eye = models.CharField(max_length=5, choices=EYE_CHOICES, default='OD')
    sample = models.CharField(max_length=50, choices=SAMPLE_CHOICES, default='Corneal Scraping')
    duration_value = models.PositiveIntegerField(default=1, help_text="Duration value")
    duration_unit = models.CharField(max_length=10, choices=DURATION_UNIT_CHOICES, default='Days')
    on_meds = models.BooleanField(default=False, help_text="Patient is on prior medications")
    meds_category = models.CharField(max_length=50, choices=MED_CATEGORY_CHOICES, blank=True, default='', help_text="Type of medication")
    meds_custom = models.CharField(max_length=250, blank=True, default='', help_text="Custom medication name (for Others category)")
    impression = models.CharField(max_length=50, choices=IMPRESSION_CHOICES, default='Bacterial')
    stain = models.CharField(max_length=150)
    
    # Technical & Status
    image = models.ImageField(upload_to='slides/%Y/%m/%d/') # Image storage
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Pending')
    
    # Assignment system
    assigned_to = models.ForeignKey(PortalUser, on_delete=models.SET_NULL, null=True, blank=True, 
                                   limit_choices_to={'role': 'Lab'}, related_name='assigned_requests')
    assignment_status = models.CharField(max_length=20, choices=ASSIGNMENT_STATUS_CHOICES, default='Unassigned')
    assigned_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Req {self.id} - {self.patient_id} ({self.status})"


class Report(models.Model):
    QUALITY_CHOICES = (
        ('Good', 'Good'), 
        ('Moderate', 'Moderate'), 
        ('Bad', 'Bad')
    )
    
    # Link (One-to-One) to the Request
    request = models.OneToOneField(Request, on_delete=models.CASCADE, primary_key=True)
    
    # Lab Findings
    rc_code = models.CharField(max_length=50)
    lab_id = models.CharField(max_length=50)
    quality = models.CharField(max_length=10, choices=QUALITY_CHOICES)
    sample_suitability = models.BooleanField(default=True)
    suitability_reason = models.TextField(blank=True, help_text="Specify reason if suitability is No")
    
    report_text = models.TextField()
    comments = models.TextField(blank=True)
    
    auth_by = models.CharField(max_length=100)
    
    # Microbiology Report PDF (optional upload by lab tech)
    microbiology_pdf = models.FileField(upload_to='reports/%Y/%m/%d/', blank=True, null=True, 
                                        help_text="Upload the microbiology report PDF")
    pdf_uploaded_date = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Report for {self.request.patient_id}"


class RequestHistory(models.Model):
    """Simple history tracking for Requests. Records actions taken, by whom, and a note."""
    request = models.ForeignKey(Request, on_delete=models.CASCADE, related_name='history_entries')
    user = models.ForeignKey(PortalUser, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=100)
    note = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        who = self.user.full_name if self.user else 'System'
        return f"{self.timestamp} - {self.action} by {who}"