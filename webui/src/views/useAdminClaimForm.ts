import { computed, onMounted, ref } from "vue";
import {
  useRoute,
  useRouter,
  type RouteLocationRaw,
} from "vue-router";

import { useAuthStore } from "../stores/auth";

type AdminClaimOperation = "reset-admin" | "setup";

export function useAdminClaimForm(options: {
  initialUsername: string;
  operation: AdminClaimOperation;
  successRoute: RouteLocationRaw;
}) {
  const auth = useAuthStore();
  const route = useRoute();
  const router = useRouter();

  const username = ref(options.initialUsername);
  const password = ref("");
  const confirmPassword = ref("");
  const submitting = ref(false);

  const claim = computed(() =>
    typeof route.query.claim === "string" ? route.query.claim : "",
  );
  const passwordMinLength = computed(
    () => auth.setupStatus?.password_min_length ?? 12,
  );
  const passwordsMatch = computed(
    () => password.value.length > 0 && password.value === confirmPassword.value,
  );
  const passwordValidationStatus = computed<"error" | undefined>(() =>
    password.value.length > 0 && password.value.length < passwordMinLength.value
      ? "error"
      : undefined,
  );
  const passwordFeedback = computed(() =>
    passwordValidationStatus.value === "error"
      ? `Use at least ${passwordMinLength.value} characters.`
      : `Minimum ${passwordMinLength.value} characters.`,
  );
  const confirmPasswordValidationStatus = computed<"error" | undefined>(() =>
    confirmPassword.value && !passwordsMatch.value ? "error" : undefined,
  );
  const confirmPasswordFeedback = computed(() =>
    confirmPasswordValidationStatus.value === "error"
      ? "Passwords do not match."
      : "Repeat the new password.",
  );
  const canSubmit = computed(
    () =>
      Boolean(claim.value) &&
      Boolean(username.value.trim()) &&
      password.value.length >= passwordMinLength.value &&
      passwordsMatch.value,
  );

  onMounted(async () => {
    await auth.loadSetupStatus();
  });

  async function submit(): Promise<void> {
    submitting.value = true;
    try {
      if (options.operation === "setup") {
        await auth.claimSetup(claim.value, username.value, password.value);
      } else {
        await auth.resetAdmin(claim.value, username.value, password.value);
      }
      await router.replace(options.successRoute);
    } finally {
      submitting.value = false;
    }
  }

  return {
    auth,
    username,
    password,
    confirmPassword,
    submitting,
    claim,
    passwordMinLength,
    passwordValidationStatus,
    passwordFeedback,
    confirmPasswordValidationStatus,
    confirmPasswordFeedback,
    canSubmit,
    submit,
  };
}
