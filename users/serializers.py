from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'email_verified', 'name', 'first_name', 'last_name', 'phone',
                  'address', 'city', 'state', 'pincode', 'profile_picture', 'created_at',
                  'is_staff']
        # AP6/S3: `email` is read-only here — the login identifier changes ONLY
        # via POST /api/auth/change-email/ (current password + OTP to the new
        # address). A PATCH carrying an email is ignored by DRF, and
        # UserProfileView additionally answers 400 pointing at the endpoint.
        read_only_fields = ['id', 'created_at', 'is_staff', 'email_verified', 'email']

    def validate_email(self, value):
        # AP6: profile updates can NO LONGER change the email (read-only —
        # changes go through POST /api/auth/change-email/ with password + OTP
        # proof). This validator stays for the registration serializer's twin
        # and any admin use: same canonical, case-insensitive uniqueness rule,
        # otherwise a case variant hits the DB unique constraint and 500s.
        value = value.strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    address = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True)
    pincode = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = [
            'username', 'email', 'name', 'password', 'password2', 'first_name', 'last_name', 'phone',
            'address', 'city', 'state', 'pincode'
        ]

    def validate_email(self, value):
        # Canonicalise and reject case-insensitive duplicates up front, so a
        # clean 400 is returned instead of a DB IntegrityError, and so an
        # account can't be shadowed by a case variant of an existing email.
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords don't match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['email'] = user.email
        token['username'] = user.username
        return token


# --- Password Reset Serializers ---

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        if not User.objects.filter(email=value).exists():
            # Still return valid to prevent email enumeration, but we'll handle it in the view
            pass
        return value

class OTPVerifySerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6, min_length=6)

class PasswordResetConfirmSerializer(serializers.Serializer):
    email = serializers.EmailField()
    reset_token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({"new_password": "Passwords do not match."})
        return attrs
