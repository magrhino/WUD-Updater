type NotificationStatusType = "default" | "success" | "warning" | "error";

const LABELS: Record<string, string> = {
  skipped_duplicate: "Already notified",
  skipped_cooldown: "Cooldown active",
  cooldown_ready: "Cooldown elapsed",
  manual_resend: "Manual resend",
  sent: "Notified",
  failure: "Last send failed",
};

const TYPES: Record<string, NotificationStatusType> = {
  skipped_duplicate: "success",
  sent: "success",
  failure: "error",
  skipped_cooldown: "warning",
};

export function notificationStatusLabel(status: string): string {
  return LABELS[status] ?? "Not notified";
}

export function notificationStatusType(status: string): NotificationStatusType {
  return TYPES[status] ?? "default";
}
