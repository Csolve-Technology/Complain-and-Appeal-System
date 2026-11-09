"use client";

import { authFetch } from "@/services/auth-http";
import { AuthPageShell } from "@/components/Auth/AuthPageShell";
import { useChiroAuth } from "@/components/ChiroAuthProvider";
import { useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import InputGroup from "@/components/FormElements/InputGroup/index";
import { Eye, EyeOff, CheckCircle2 } from "lucide-react";
import { SuccessModal } from "@/components/ui/success-modal";

function LocalSignUpPage() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL;
  const router = useRouter();
  const [form, setForm] = useState({
    firstName: "",
    lastName: "",
    email: "",
    phone: "",
    nationalId: "",
    address: "",
    password: "",
    confirmPassword: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setForm((s) => ({ ...s, [name]: value }));
    
    // Clear field error when user starts typing
    if (fieldErrors[name]) {
      setFieldErrors((prev) => {
        const newErrors = { ...prev };
        delete newErrors[name];
        return newErrors;
      });
    }
    
    // Clear general error when user starts typing
    if (error) {
      setError("");
    }
  };

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {};
    let hasErrors = false;

    // Clear previous errors
    setFieldErrors({});
    setError("");

    // First name validation
    if (!form.firstName.trim()) {
      errors.firstName = "First name is required";
      hasErrors = true;
    } else if (form.firstName.trim().length < 2) {
      errors.firstName = "First name must be at least 2 characters";
      hasErrors = true;
    }

    // Last name validation
    if (!form.lastName.trim()) {
      errors.lastName = "Last name is required";
      hasErrors = true;
    } else if (form.lastName.trim().length < 2) {
      errors.lastName = "Last name must be at least 2 characters";
      hasErrors = true;
    }

    // Phone validation
    if (!form.phone.trim()) {
      errors.phone = "Phone number is required";
      hasErrors = true;
    } else if (!/^[0-9+\-\s()]+$/.test(form.phone)) {
      errors.phone = "Please enter a valid phone number";
      hasErrors = true;
    }

    // Email validation (optional but must be valid if provided)
    if (form.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) {
      errors.email = "Please enter a valid email address";
      hasErrors = true;
    }

    // Password validation
    if (!form.password) {
      errors.password = "Password is required";
      hasErrors = true;
    } else if (form.password.length < 6) {
      errors.password = "Password must be at least 6 characters long";
      hasErrors = true;
    }

    // Confirm password validation
    if (!form.confirmPassword) {
      errors.confirmPassword = "Please confirm your password";
      hasErrors = true;
    } else if (form.password !== form.confirmPassword) {
      errors.confirmPassword = "Passwords do not match";
      hasErrors = true;
    }

    if (hasErrors) {
      setFieldErrors(errors);
      return false;
    }

    return true;
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    setFieldErrors({});

    // Validate form
    if (!validateForm()) {
      return;
    }

    if (!API_URL) {
      setError("System configuration error. Please contact support.");
      return;
    }

    try {
      setSubmitting(true);
      
      // Generate username - prefer email, fallback to phone, or generate one
      const usernameBase = form.email?.trim() || form.phone?.trim() || `${form.firstName.toLowerCase()}_${Date.now()}`;
      
      // Build payload - only include fields that exist in the API serializer
      const payload: Record<string, any> = {
        username: usernameBase,
        first_name: form.firstName.trim(),
        last_name: form.lastName.trim(),
        phone_number: form.phone.trim(),
        password: form.password,
        status: "active",
        groups: ["Citizen"], // Default role: Citizen
      };
      
      // Add optional fields only if they have values
      if (form.email?.trim()) {
        payload.email = form.email.trim();
      }
      if (form.nationalId?.trim()) {
        payload.national_id = form.nationalId.trim();
      }
      if (form.address?.trim()) {
        payload.address = form.address.trim();
      }

      console.log("Sign-up payload:", payload); // Debug log

      const res = await authFetch(`${API_URL}/users/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        let errorData: any = {};
        const responseText = await res.text();
        
        try {
          errorData = JSON.parse(responseText);
        } catch {
          errorData = { detail: responseText || res.statusText };
        }
        
        console.error("Sign-up error response:", errorData); // Debug log
        
        // Handle field-specific errors from Django REST Framework
        const newFieldErrors: Record<string, string> = {};
        
        // Helper function to extract error message
        const getErrorMessage = (fieldError: any): string => {
          if (Array.isArray(fieldError)) {
            // Return the first error message from the array
            return fieldError[0] || "Invalid value";
          }
          if (typeof fieldError === 'object' && fieldError !== null) {
            // Handle nested error objects
            if (fieldError.non_field_errors) {
              return Array.isArray(fieldError.non_field_errors) ? fieldError.non_field_errors[0] : String(fieldError.non_field_errors);
            }
            // If it's an object with a message property
            if (fieldError.message) {
              return String(fieldError.message);
            }
            // Try to stringify, but prefer a readable format
            const keys = Object.keys(fieldError);
            if (keys.length > 0) {
              return String(fieldError[keys[0]]);
            }
            return "Invalid value";
          }
          // Convert to string and make it user-friendly
          const errorStr = String(fieldError);
          // Common Django error messages
          if (errorStr.toLowerCase().includes('already exists') || errorStr.toLowerCase().includes('unique')) {
            return errorStr;
          }
          return errorStr;
        };
        
        // Map API field names to form field names
        // Check all possible field error formats from Django REST Framework
        Object.keys(errorData).forEach((key) => {
          const errorValue = errorData[key];
          
          // Skip non-field error keys
          if (key === 'detail' || key === 'message' || key === 'error' || key === 'non_field_errors') {
            return;
          }
          
          // Map API field names to form field names
          let formFieldName = '';
          switch (key) {
            case 'email':
              formFieldName = 'email';
              break;
            case 'phone_number':
              formFieldName = 'phone';
              break;
            case 'username':
              // Username errors could affect email field if email is used as username
              formFieldName = 'email';
              break;
            case 'password':
              formFieldName = 'password';
              break;
            case 'first_name':
              formFieldName = 'firstName';
              break;
            case 'last_name':
              formFieldName = 'lastName';
              break;
            case 'national_id':
              formFieldName = 'nationalId';
              break;
            case 'address':
              formFieldName = 'address';
              break;
            case 'confirm_password':
              formFieldName = 'confirmPassword';
              break;
            default:
              // For unknown fields, try to map them
              formFieldName = key;
          }
          
          if (formFieldName && errorValue) {
            const errorMsg = getErrorMessage(errorValue);
            if (errorMsg && errorMsg !== 'Invalid value') {
              newFieldErrors[formFieldName] = errorMsg;
            }
          }
        });
        
        // Set field errors if any
        if (Object.keys(newFieldErrors).length > 0) {
          setFieldErrors(newFieldErrors);
        }
        
        // Get general error message - prioritize field errors if they exist
        let errorMessage = "";
        
        if (errorData.detail) {
          errorMessage = Array.isArray(errorData.detail) ? errorData.detail[0] : String(errorData.detail);
        } else if (errorData.message) {
          errorMessage = Array.isArray(errorData.message) ? errorData.message[0] : String(errorData.message);
        } else if (errorData.error) {
          errorMessage = Array.isArray(errorData.error) ? errorData.error[0] : String(errorData.error);
        } else if (Object.keys(newFieldErrors).length > 0) {
          // If we have field errors, show a summary
          const fieldNames = Object.keys(newFieldErrors);
          if (fieldNames.length === 1) {
            errorMessage = `Please fix the error in ${fieldNames[0] === 'nationalId' ? 'National ID' : fieldNames[0] === 'phone' ? 'Phone Number' : fieldNames[0]}`;
          } else {
            errorMessage = `Please fix the errors in the form fields`;
          }
        } else {
          errorMessage = typeof errorData === 'string' ? errorData : JSON.stringify(errorData);
        }
        
        // If no error message found, use default
        if (!errorMessage) {
          errorMessage = `Registration failed (${res.status})`;
        }
        
        // Only show general error if there are no field-specific errors
        if (Object.keys(newFieldErrors).length === 0) {
          setError(errorMessage);
        } else {
          // Clear general error if we have field-specific errors
          setError("");
        }
        
        // Don't throw error if we have field-specific errors - let user see them
        if (Object.keys(newFieldErrors).length === 0) {
          throw new Error(errorMessage);
        }
        
        // If we have field errors, stop here without throwing
        setSubmitting(false);
        return;
      }

      // Show success modal
      setShowSuccessModal(true);
      
      // Clear form
      setForm({ firstName: "", lastName: "", email: "", phone: "", nationalId: "", address: "", password: "", confirmPassword: "" });
      
    } catch (err: any) {
      setError(err?.message || "Registration failed. Please check your information and try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSuccessModalClose = () => {
    setShowSuccessModal(false);
    router.push("/auth/sign-in");
  };

  return (
    <div>
      <div className="flex min-h-screen items-center justify-center bg-gray-2 p-4 dark:bg-[#020d1a]">
        <div className="w-full max-w-2xl rounded-[10px] bg-white shadow-1 dark:bg-gray-dark dark:shadow-card">
          {/* Form Section - Centered */}
          <section className="w-full p-5 sm:p-10">
            <div className="mx-auto w-full max-w-md">
                {/* Brand / heading */}
                <div className="mb-6">
                  <div className="mb-3 inline-flex items-center gap-2 rounded-lg bg-primary/10 px-3 py-1.5 text-sm font-semibold text-primary dark:bg-primary/20">
                    <CheckCircle2 className="h-4 w-4" />
                    <span>Citizen Registration</span>
                  </div>
                  <h1 className="text-2xl font-bold leading-tight text-primary">
                    Create your Citizen account
                  </h1>
                  <p className="mt-2 text-sm text-gray-600 dark:text-dark-6">
                    Register as a Citizen to submit complaints and appeals, track their progress in real time, and stay informed about your cases.
                  </p>
                </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                {/* Name fields */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <InputGroup
                      type="text"
                      label="First Name"
                      placeholder="Enter your first name"
                      name="firstName"
                      value={form.firstName}
                      onChange={handleChange}
                      required
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.firstName && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.firstName}</p>
                    )}
                  </div>
                  <div>
                    <InputGroup
                      type="text"
                      label="Last Name"
                      placeholder="Enter your last name"
                      name="lastName"
                      value={form.lastName}
                      onChange={handleChange}
                      required
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.lastName && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.lastName}</p>
                    )}
                  </div>
                </div>

                {/* Contact fields */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <InputGroup
                      type="email"
                      label="Email"
                      placeholder="Enter your email (optional)"
                      name="email"
                      value={form.email}
                      onChange={handleChange}
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.email && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.email}</p>
                    )}
                  </div>
                  <div>
                    <InputGroup
                      type="tel"
                      label="Phone Number"
                      placeholder="Enter your phone number"
                      name="phone"
                      value={form.phone}
                      onChange={handleChange}
                      required
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.phone && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.phone}</p>
                    )}
                  </div>
                </div>

                {/* Additional fields */}
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <InputGroup
                      type="text"
                      label="National ID"
                      placeholder="Enter your national ID (optional)"
                      name="nationalId"
                      value={form.nationalId}
                      onChange={handleChange}
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.nationalId && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.nationalId}</p>
                    )}
                  </div>
                  <div>
                    <InputGroup
                      type="text"
                      label="Address"
                      placeholder="Enter your address (optional)"
                      name="address"
                      value={form.address}
                      onChange={handleChange}
                      className="[&_input]:py-[15px]"
                    />
                    {fieldErrors.address && (
                      <p className="mt-1 text-xs text-red-500">{fieldErrors.address}</p>
                    )}
                  </div>
                </div>

                {/* Password fields */}
                <div>
                  <InputGroup
                    type={showPassword ? "text" : "password"}
                    label="Password"
                    placeholder="Enter your password"
                    name="password"
                    value={form.password}
                    onChange={handleChange}
                    required
                    className="[&_input]:py-[15px]"
                    endIcon={
                      <button
                        type="button"
                        onClick={() => setShowPassword((prev) => !prev)}
                        className="flex h-5 w-5 items-center justify-center text-dark-6 transition hover:text-primary focus-visible:outline-none"
                      >
                        {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                      </button>
                    }
                  />
                  {fieldErrors.password && (
                    <p className="mt-1 text-xs text-red-500">{fieldErrors.password}</p>
                  )}
                  {!fieldErrors.password && form.password && (
                    <p className="mt-1 text-xs text-gray-500 dark:text-dark-6">
                      Must be at least 6 characters
                    </p>
                  )}
                </div>

                <div>
                  <InputGroup
                    type={showConfirmPassword ? "text" : "password"}
                    label="Confirm Password"
                    placeholder="Confirm your password"
                    name="confirmPassword"
                    value={form.confirmPassword}
                    onChange={handleChange}
                    required
                    className="[&_input]:py-[15px]"
                    endIcon={
                      <button
                        type="button"
                        onClick={() => setShowConfirmPassword((prev) => !prev)}
                        className="flex h-5 w-5 items-center justify-center text-dark-6 transition hover:text-primary focus-visible:outline-none"
                      >
                        {showConfirmPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                      </button>
                    }
                  />
                  {fieldErrors.confirmPassword && (
                    <p className="mt-1 text-xs text-red-500">{fieldErrors.confirmPassword}</p>
                  )}
                </div>

                {/* General error message */}
                {error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
                    <div className="flex items-start gap-2">
                      <span className="mt-0.5 text-red-600 dark:text-red-400">⚠</span>
                      <div>
                        <p className="font-medium">Registration Error</p>
                        <p className="mt-1">{error}</p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Submit button */}
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary p-4 font-medium text-white transition hover:bg-opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {submitting ? (
                    <>
                      <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-solid border-white border-t-transparent" />
                      Creating Account...
                    </>
                  ) : (
                    "Create Account"
                  )}
                </button>

                {/* Sign in link */}
                <div className="mt-4 text-center text-sm">
                  <span className="text-gray-600 dark:text-dark-6">Already have an account? </span>
                  <Link href="/auth/sign-in" className="font-medium text-primary hover:opacity-90">
                    Sign in
                  </Link>
                </div>
              </form>
            </div>
          </section>
        </div>
      </div>
      
      {/* Success Modal */}
      <SuccessModal
        open={showSuccessModal}
        onClose={handleSuccessModalClose}
        title="Account Created Successfully!"
        message="Your Citizen account has been created. You will now be redirected to the sign-in page."
        buttonLabel="Go to Sign In"
        autoCloseMs={3000}
      />
    </div>
  );
}



export default function SignUpPage() {
  const auth = useChiroAuth();
  const [failure, setFailure] = useState<string | null>(null);
  if (auth.mode !== "keycloak") return <LocalSignUpPage />;
  return <AuthPageShell title="Sign up as an applicant" subtitle="Create your Chiro Auth account to submit complaints and appeals.">
    <div className="space-y-5">
      <p className="text-sm leading-6 text-dark-5 dark:text-dark-6">Your account lets you track your own cases, receive responses, and submit feedback.</p>
      {failure && <p role="alert" className="text-sm text-red-600">{failure}</p>}
      <button className="w-full rounded-lg bg-primary p-4 font-medium text-white" onClick={() => void auth.signUp().catch(error => setFailure(error.message))}>Create applicant account</button>
      <p className="text-sm leading-6 text-dark-5 dark:text-dark-6">{auth.requireVerifiedEmail ? "After registration, verify your email to finish setting up your account." : "After registration, sign in to start submitting and tracking your cases."} Already use another city service? You can sign in with the same Chiro Auth account.</p>
      <p className="text-sm">Already have an account? <Link href="/login" className="font-semibold text-primary underline-offset-4 hover:underline">Sign in</Link></p>
    </div>
  </AuthPageShell>;
}
