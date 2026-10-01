from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models
from spices_backend.validators import validate_file_size, validate_image_extension, validate_image_content


class UserManager(DjangoUserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # A superuser is made by the owner at the shell (createsuperuser), never
        # by self-registration, so its inbox needs no OTP proof — without this
        # a fresh owner account is refused by the admin login (email_not_verified).
        extra_fields.setdefault('email_verified', True)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """
    Custom User model extending Django's AbstractUser
    """
    email = models.EmailField(unique=True)
    # AP5/S1: proof of inbox ownership. Registration leaves this False until
    # the OTP is confirmed; Google sign-in sets it (Google verified the inbox).
    # Login is refused while False. See users/migrations/0010_* grandfathering.
    email_verified = models.BooleanField(default=False, db_index=True)
    name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    profile_picture = models.ImageField(
        upload_to='profiles/', 
        blank=True, 
        null=True,
        validators=[validate_file_size, validate_image_extension, validate_image_content]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        # Email is the login identifier (USERNAME_FIELD). Normalise it to a
        # canonical lower-case form on every write so that "User@x.com" and
        # "user@x.com" can never become two distinct accounts, and so login
        # (which resolves email case-insensitively) is never ambiguous.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email

    @property
    def full_address(self):
        """Returns complete formatted address"""
        parts = [self.address, self.city, self.state, self.pincode]
        return ', '.join(filter(None, parts))


class PasswordResetOTP(models.Model):
    """
    Model to store emailed 6-digit codes. The name is historical: the table
    also carries email-verification and change-email codes, told apart by
    `purpose`. Each purpose has its OWN live code and its OWN daily quota, so
    requesting one kind can neither cancel nor use up another.
    """
    MAX_FAILED_ATTEMPTS = 5
    MAX_CODES_PER_DAY = 5

    PURPOSE_RESET = 'reset'
    PURPOSE_VERIFY = 'verify'
    PURPOSE_CHANGE_EMAIL = 'change_email'
    PURPOSE_CHOICES = [
        (PURPOSE_RESET, 'Password reset'),
        (PURPOSE_VERIFY, 'Email verification'),
        (PURPOSE_CHANGE_EMAIL, 'Change email'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps')
    otp_code = models.CharField(max_length=255)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES, default=PURPOSE_RESET)
    reset_token = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    failed_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - OTP Request"
        
    def set_otp(self, raw_otp):
        from django.contrib.auth.hashers import make_password
        self.otp_code = make_password(raw_otp)

    def check_otp(self, raw_otp):
        import hmac
        from django.contrib.auth.hashers import check_password
        # Support fallback to plaintext if old record. Use a constant-time
        # comparison so the legacy path can't leak the code via response timing
        # (check_password is already constant-time for hashed records).
        if len(self.otp_code) == 6 or '$' not in self.otp_code:
            return hmac.compare_digest(str(self.otp_code), str(raw_otp))
        return check_password(raw_otp, self.otp_code)
    
    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at
    
    @property
    def is_locked(self):
        """OTP is locked after too many failed verification attempts."""
        return self.failed_attempts >= self.MAX_FAILED_ATTEMPTS

