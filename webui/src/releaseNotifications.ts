export const RELEASE_NOTIFICATION_DELIVERY_MODE_ON_DEMAND = "on_demand";
export const RELEASE_NOTIFICATION_DELIVERY_MODE_ON_DETECTION = "on_detection";

export const RELEASE_NOTIFICATION_DELIVERY_MODE_VALUES = [
  RELEASE_NOTIFICATION_DELIVERY_MODE_ON_DEMAND,
  RELEASE_NOTIFICATION_DELIVERY_MODE_ON_DETECTION,
] as const;

export type ReleaseNotificationDeliveryMode =
  (typeof RELEASE_NOTIFICATION_DELIVERY_MODE_VALUES)[number];

export const DEFAULT_RELEASE_NOTIFICATION_DELIVERY_MODE: ReleaseNotificationDeliveryMode =
  RELEASE_NOTIFICATION_DELIVERY_MODE_ON_DETECTION;

export const RELEASE_NOTIFICATION_DELIVERY_MODE_ERROR =
  `release_notifications_delivery_mode must be ${RELEASE_NOTIFICATION_DELIVERY_MODE_VALUES.join(" or ")}`;

export function isReleaseNotificationDeliveryMode(
  value: string | undefined,
): value is ReleaseNotificationDeliveryMode {
  return (
    value !== undefined &&
    (RELEASE_NOTIFICATION_DELIVERY_MODE_VALUES as readonly string[]).includes(value)
  );
}
