import { computed, ref, watch } from "vue";

import { useSettingsStore } from "../../stores/settings";
import {
  managedOptions,
  managedSourceLabel,
  RELEASE_NOTIFICATION_DELIVERY_MODE_LABELS,
  RELEASE_NOTIFICATION_MODE_LABELS,
  RELEASE_NOTIFICATION_RESEND_POLICY_LABELS,
  RELEASE_NOTIFICATION_VERBOSITY_LABELS,
} from "./settingsDisplay";
import { useSettingsSafety } from "./useSettingsSafety";

export function useManagedNotifications() {
  const settings = useSettingsStore();
  const { preferencesDisabledReason } = useSettingsSafety();

  const settingsData = computed(() => settings.settings);
  const managedEntries = computed(() => settingsData.value?.managed ?? []);
  const releaseNotesEnabledEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "release_notes_enabled"),
  );
  const releaseNotificationDeliveryModeEntry = computed(() =>
    managedEntries.value.find(
      (entry) => entry.key === "release_notifications_delivery_mode",
    ),
  );
  const releaseNotificationModeEntry = computed(() =>
    managedEntries.value.find((entry) => entry.key === "release_notifications_mode"),
  );
  const releaseNotificationResendPolicyEntry = computed(() =>
    managedEntries.value.find(
      (entry) => entry.key === "release_notifications_resend_policy",
    ),
  );
  const releaseNotificationCooldownEntry = computed(() =>
    managedEntries.value.find(
      (entry) => entry.key === "release_notifications_cooldown_seconds",
    ),
  );
  const discordWebhookEntry = computed(() =>
    managedEntries.value.find(
      (entry) => entry.key === "release_notifications_discord_webhook",
    ),
  );
  const releaseNotificationVerbosityEntry = computed(() =>
    managedEntries.value.find(
      (entry) => entry.key === "release_notifications_verbosity",
    ),
  );

  const releaseNotesEnabledValue = ref(false);
  const releaseNotificationDeliveryModeValue = ref("on_demand");
  const releaseNotificationModeValue = ref("digest");
  const releaseNotificationResendPolicyValue = ref("remote_change");
  const releaseNotificationCooldownValue = ref("86400");
  const discordWebhookValue = ref("");
  const discordWebhookClearRequested = ref(false);
  const releaseNotificationVerbosityValue = ref("summary");
  const notificationsMessage = ref("");
  const notificationsError = ref("");
  const testWebhookDialogVisible = ref(false);

  const notificationControlsDisabled = computed(
    () => settings.loading || preferencesDisabledReason.value !== "",
  );
  const releaseNotesEnabledEditable = computed(
    () => releaseNotesEnabledEntry.value?.editable === true,
  );
  const releaseNotificationDeliveryModeEditable = computed(
    () => releaseNotificationDeliveryModeEntry.value?.editable === true,
  );
  const releaseNotificationModeEditable = computed(
    () => releaseNotificationModeEntry.value?.editable === true,
  );
  const releaseNotificationResendPolicyEditable = computed(
    () => releaseNotificationResendPolicyEntry.value?.editable === true,
  );
  const releaseNotificationCooldownEditable = computed(
    () => releaseNotificationCooldownEntry.value?.editable === true,
  );
  const discordWebhookEditable = computed(
    () => discordWebhookEntry.value?.editable === true,
  );
  const releaseNotificationVerbosityEditable = computed(
    () => releaseNotificationVerbosityEntry.value?.editable === true,
  );
  const discordWebhookConfigured = computed(
    () => discordWebhookEntry.value?.configured === true,
  );
  const discordWebhookStatus = computed(() =>
    discordWebhookConfigured.value ? "Configured" : "Not configured",
  );
  const normalizedReleaseNotificationCooldown = computed(() => {
    const cooldownValue = releaseNotificationCooldownValue.value.trim();
    return cooldownValue.replace(/^0+/, "") || "0";
  });
  const notificationsDirty = computed(
    () =>
      (releaseNotesEnabledEditable.value &&
        releaseNotesEnabledValue.value !==
          (releaseNotesEnabledEntry.value?.value === "true")) ||
      (releaseNotificationDeliveryModeEditable.value &&
        releaseNotificationDeliveryModeValue.value !==
          (releaseNotificationDeliveryModeEntry.value?.value ?? "on_demand")) ||
      (releaseNotificationModeEditable.value &&
        releaseNotificationModeValue.value !==
          (releaseNotificationModeEntry.value?.value ?? "digest")) ||
      (releaseNotificationResendPolicyEditable.value &&
        releaseNotificationResendPolicyValue.value !==
          (releaseNotificationResendPolicyEntry.value?.value ?? "remote_change")) ||
      (releaseNotificationCooldownEditable.value &&
        normalizedReleaseNotificationCooldown.value !==
          (releaseNotificationCooldownEntry.value?.value ?? "86400")) ||
      (discordWebhookEditable.value &&
        (discordWebhookValue.value.trim() !== "" ||
          discordWebhookClearRequested.value)) ||
      (releaseNotificationVerbosityEditable.value &&
        releaseNotificationVerbosityValue.value !==
          (releaseNotificationVerbosityEntry.value?.value ?? "summary")),
  );
  const notificationSaveDisabled = computed(
    () => notificationControlsDisabled.value || !notificationsDirty.value,
  );
  const testWebhookButtonDisabled = computed(
    () =>
      notificationControlsDisabled.value ||
      notificationsDirty.value ||
      !discordWebhookConfigured.value,
  );
  const releaseNotificationDeliveryModeOptions = computed(() =>
    managedOptions(
      releaseNotificationDeliveryModeEntry.value,
      RELEASE_NOTIFICATION_DELIVERY_MODE_LABELS,
    ),
  );
  const releaseNotificationModeOptions = computed(() =>
    managedOptions(
      releaseNotificationModeEntry.value,
      RELEASE_NOTIFICATION_MODE_LABELS,
    ),
  );
  const releaseNotificationResendPolicyOptions = computed(() =>
    managedOptions(
      releaseNotificationResendPolicyEntry.value,
      RELEASE_NOTIFICATION_RESEND_POLICY_LABELS,
    ),
  );
  const releaseNotificationVerbosityOptions = computed(() =>
    managedOptions(
      releaseNotificationVerbosityEntry.value,
      RELEASE_NOTIFICATION_VERBOSITY_LABELS,
    ),
  );

  function hydrateNotificationForm(): void {
    releaseNotesEnabledValue.value = releaseNotesEnabledEntry.value?.value === "true";
    releaseNotificationDeliveryModeValue.value =
      releaseNotificationDeliveryModeEntry.value?.value ?? "on_demand";
    releaseNotificationModeValue.value =
      releaseNotificationModeEntry.value?.value ?? "digest";
    releaseNotificationResendPolicyValue.value =
      releaseNotificationResendPolicyEntry.value?.value ?? "remote_change";
    releaseNotificationCooldownValue.value =
      releaseNotificationCooldownEntry.value?.value ?? "86400";
    releaseNotificationVerbosityValue.value =
      releaseNotificationVerbosityEntry.value?.value ?? "summary";
    discordWebhookValue.value = "";
    discordWebhookClearRequested.value = false;
  }

  function resetNotificationForm(): void {
    hydrateNotificationForm();
    notificationsMessage.value = "";
    notificationsError.value = "";
  }

  function clearDiscordWebhook(): void {
    if (!discordWebhookEditable.value || !discordWebhookConfigured.value) {
      return;
    }
    discordWebhookValue.value = "";
    discordWebhookClearRequested.value = true;
    notificationsMessage.value = "";
    notificationsError.value = "";
  }

  function openTestWebhookDialog(): void {
    if (testWebhookButtonDisabled.value) {
      return;
    }
    notificationsMessage.value = "";
    notificationsError.value = "";
    testWebhookDialogVisible.value = true;
  }

  async function sendTestWebhook(): Promise<void> {
    if (testWebhookButtonDisabled.value) {
      return;
    }
    notificationsMessage.value = "";
    notificationsError.value = "";
    try {
      const response = await settings.testReleaseNotificationWebhook();
      testWebhookDialogVisible.value = false;
      notificationsMessage.value = `Test webhook sent. Audit run #${response.audit_run_id}.`;
    } catch (error_) {
      notificationsError.value =
        error_ instanceof Error ? error_.message : "Test webhook could not be sent";
    }
  }

  async function saveManagedNotifications(): Promise<void> {
    if (notificationControlsDisabled.value) {
      return;
    }
    notificationsMessage.value = "";
    notificationsError.value = "";
    const values: Record<string, string> = {};
    if (
      releaseNotesEnabledEditable.value &&
      releaseNotesEnabledValue.value !==
        (releaseNotesEnabledEntry.value?.value === "true")
    ) {
      values.release_notes_enabled = releaseNotesEnabledValue.value ? "true" : "false";
    }
    if (
      releaseNotificationDeliveryModeEditable.value &&
      releaseNotificationDeliveryModeValue.value !==
        (releaseNotificationDeliveryModeEntry.value?.value ?? "on_demand")
    ) {
      values.release_notifications_delivery_mode =
        releaseNotificationDeliveryModeValue.value;
    }
    if (
      releaseNotificationModeEditable.value &&
      releaseNotificationModeValue.value !==
        (releaseNotificationModeEntry.value?.value ?? "digest")
    ) {
      values.release_notifications_mode = releaseNotificationModeValue.value;
    }
    if (
      releaseNotificationResendPolicyEditable.value &&
      releaseNotificationResendPolicyValue.value !==
        (releaseNotificationResendPolicyEntry.value?.value ?? "remote_change")
    ) {
      values.release_notifications_resend_policy =
        releaseNotificationResendPolicyValue.value;
    }
    if (
      releaseNotificationCooldownEditable.value &&
      normalizedReleaseNotificationCooldown.value !==
        (releaseNotificationCooldownEntry.value?.value ?? "86400")
    ) {
      const cooldownValue = releaseNotificationCooldownValue.value.trim();
      if (
        !/^\d+$/.test(cooldownValue) ||
        normalizedReleaseNotificationCooldown.value === "0"
      ) {
        notificationsError.value =
          "Release notification cooldown must be a positive integer.";
        return;
      }
      values.release_notifications_cooldown_seconds =
        normalizedReleaseNotificationCooldown.value;
    }
    if (discordWebhookEditable.value) {
      const webhook = discordWebhookValue.value.trim();
      if (webhook) {
        values.release_notifications_discord_webhook = webhook;
      } else if (discordWebhookClearRequested.value) {
        values.release_notifications_discord_webhook = "";
      }
    }
    if (
      releaseNotificationVerbosityEditable.value &&
      releaseNotificationVerbosityValue.value !==
        (releaseNotificationVerbosityEntry.value?.value ?? "summary")
    ) {
      values.release_notifications_verbosity = releaseNotificationVerbosityValue.value;
    }
    if (!Object.keys(values).length) {
      return;
    }

    try {
      const response = await settings.updateManagedSettings(values);
      notificationsMessage.value = `Notification settings saved. Audit run #${response.audit_run_id}.`;
      hydrateNotificationForm();
    } catch (error_) {
      notificationsError.value =
        error_ instanceof Error
          ? error_.message
          : "Notification settings could not be saved";
    }
  }

  watch(managedEntries, hydrateNotificationForm, { immediate: true });
  watch(discordWebhookValue, (value) => {
    if (value.trim()) {
      discordWebhookClearRequested.value = false;
    }
  });

  return {
    settings,
    releaseNotesEnabledEntry,
    releaseNotificationDeliveryModeEntry,
    releaseNotificationModeEntry,
    releaseNotificationResendPolicyEntry,
    releaseNotificationCooldownEntry,
    discordWebhookEntry,
    releaseNotificationVerbosityEntry,
    releaseNotesEnabledValue,
    releaseNotificationDeliveryModeValue,
    releaseNotificationModeValue,
    releaseNotificationResendPolicyValue,
    releaseNotificationCooldownValue,
    discordWebhookValue,
    discordWebhookClearRequested,
    releaseNotificationVerbosityValue,
    notificationsMessage,
    notificationsError,
    testWebhookDialogVisible,
    preferencesDisabledReason,
    notificationControlsDisabled,
    releaseNotesEnabledEditable,
    releaseNotificationDeliveryModeEditable,
    releaseNotificationModeEditable,
    releaseNotificationResendPolicyEditable,
    releaseNotificationCooldownEditable,
    discordWebhookEditable,
    discordWebhookConfigured,
    discordWebhookStatus,
    releaseNotificationVerbosityEditable,
    notificationsDirty,
    notificationSaveDisabled,
    testWebhookButtonDisabled,
    releaseNotificationDeliveryModeOptions,
    releaseNotificationModeOptions,
    releaseNotificationResendPolicyOptions,
    releaseNotificationVerbosityOptions,
    managedSourceLabel,
    resetNotificationForm,
    clearDiscordWebhook,
    openTestWebhookDialog,
    sendTestWebhook,
    saveManagedNotifications,
  };
}
