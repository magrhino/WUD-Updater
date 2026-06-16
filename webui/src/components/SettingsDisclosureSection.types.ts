type TagType = "default" | "primary" | "success" | "info" | "warning" | "error";

export type SettingsDisclosureRow = {
  key: string;
  name: string;
  detail: string;
  value: string;
  valueKind: "code" | "text";
  valueClass?: string;
  tagLabel: string;
  tagType: TagType;
};
