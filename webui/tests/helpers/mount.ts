import { h, type Component } from "vue";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import type { Router } from "vue-router";

type MountOptions = {
  pinia?: Pinia;
  router?: Router;
};

const passthrough = (tag: string) => ({
  setup(_: unknown, { slots }: { slots: Record<string, () => unknown> }) {
    return () => h(tag, [slots.default?.()]);
  },
});

export const naiveStubs: Record<string, Component> = {
  NAlert: {
    props: {
      type: String,
    },
    setup(props, { slots }) {
      return () =>
        h(
          "div",
          {
            role: props.type === "error" ? "alert" : "status",
            "data-alert-type": props.type,
          },
          [slots.default?.()],
        );
    },
  },
  NButton: {
    props: {
      attrType: String,
      disabled: Boolean,
      loading: Boolean,
      title: String,
    },
    emits: ["click"],
    setup(props, { attrs, emit, slots }) {
      return () =>
        h(
          "button",
          {
            ...attrs,
            type: props.attrType || "button",
            disabled: props.disabled || props.loading,
            title: props.title,
            onClick: (event: MouseEvent) => emit("click", event),
          },
          [slots.icon?.(), slots.default?.()],
        );
    },
  },
  NCheckbox: {
    props: {
      checked: Boolean,
      disabled: Boolean,
    },
    emits: ["update:checked"],
    setup(props, { emit, slots }) {
      return () =>
        h("label", [
          h("input", {
            type: "checkbox",
            checked: props.checked,
            disabled: props.disabled,
            onChange: (event: Event) =>
              emit("update:checked", (event.target as HTMLInputElement).checked),
          }),
          slots.default?.(),
        ]);
    },
  },
  NConfigProvider: passthrough("div"),
  NDataTable: {
    props: {
      data: Array,
      checkedRowKeys: Array,
      rowKey: Function,
    },
    emits: ["update:checked-row-keys"],
    setup(props, { emit }) {
      return () =>
        h(
          "div",
          { role: "table" },
          (props.data ?? []).map((row: unknown) => {
            const record = row as { line_no: number; image: string };
            const key = props.rowKey
              ? props.rowKey(record)
              : record.line_no;
            const checked = (props.checkedRowKeys ?? []).includes(key);
            return h("label", { role: "row", key }, [
              h("input", {
                type: "checkbox",
                checked,
                onChange: (event: Event) => {
                  const selected = new Set(props.checkedRowKeys ?? []);
                  if ((event.target as HTMLInputElement).checked) {
                    selected.add(key);
                  } else {
                    selected.delete(key);
                  }
                  emit("update:checked-row-keys", [...selected]);
                },
              }),
              h("span", record.image),
            ]);
          }),
        );
    },
  },
  NForm: {
    emits: ["submit"],
    setup(_, { emit, slots }) {
      return () =>
        h(
          "form",
          {
            onSubmit: (event: Event) => {
              event.preventDefault();
              emit("submit", event);
            },
          },
          [slots.default?.()],
        );
    },
  },
  NFormItem: {
    props: {
      label: String,
    },
    setup(props, { slots }) {
      return () =>
        h("label", [
          props.label ? h("span", props.label) : null,
          slots.default?.(),
        ]);
    },
  },
  NInput: {
    props: {
      disabled: Boolean,
      placeholder: String,
      type: String,
      value: [String, Number],
    },
    emits: ["update:value"],
    setup(props, { attrs, emit }) {
      return () =>
        h("input", {
          ...attrs,
          disabled: props.disabled,
          placeholder: props.placeholder,
          type: props.type || "text",
          value: props.value ?? "",
          onInput: (event: Event) =>
            emit("update:value", (event.target as HTMLInputElement).value),
        });
    },
  },
  NInputNumber: {
    props: {
      disabled: Boolean,
      value: Number,
    },
    emits: ["update:value"],
    setup(props, { emit }) {
      return () =>
        h("input", {
          disabled: props.disabled,
          type: "number",
          value: props.value ?? "",
          onInput: (event: Event) => {
            const value = (event.target as HTMLInputElement).value;
            emit("update:value", value ? Number(value) : null);
          },
        });
    },
  },
  NMessageProvider: passthrough("div"),
  NModal: {
    props: {
      positiveButtonProps: Object,
      positiveText: String,
      show: Boolean,
      title: String,
    },
    emits: ["positive-click", "update:show"],
    setup(props, { emit, slots }) {
      return () =>
        props.show
          ? h("div", { role: "dialog" }, [
              props.title ? h("h2", props.title) : null,
              slots.default?.(),
              h(
                "button",
                {
                  disabled: Boolean(
                    (props.positiveButtonProps as { loading?: boolean } | undefined)
                      ?.loading,
                  ),
                  onClick: () => emit("positive-click"),
                },
                props.positiveText || "Confirm",
              ),
            ])
          : null;
    },
  },
  NSelect: {
    props: {
      disabled: Boolean,
      options: Array,
      value: [String, Number],
    },
    emits: ["update:value"],
    setup(props, { emit }) {
      return () =>
        h(
          "select",
          {
            disabled: props.disabled,
            value: props.value ?? "",
            onChange: (event: Event) =>
              emit("update:value", (event.target as HTMLSelectElement).value),
          },
          (props.options as { label: string; value: string | number }[] | undefined)?.map(
            (option) =>
              h("option", { key: option.value, value: option.value }, option.label),
          ),
        );
    },
  },
  NSwitch: {
    props: {
      disabled: Boolean,
      value: Boolean,
    },
    emits: ["update:value"],
    setup(props, { emit }) {
      return () =>
        h("input", {
          role: "switch",
          type: "checkbox",
          checked: props.value,
          disabled: props.disabled,
          onChange: (event: Event) =>
            emit("update:value", (event.target as HTMLInputElement).checked),
        });
    },
  },
  NTag: passthrough("span"),
};

export function mountWithApp(component: Component, options: MountOptions = {}): VueWrapper {
  const pinia = options.pinia ?? createPinia();
  setActivePinia(pinia);

  const plugins = options.router ? [pinia, options.router] : [pinia];
  return mount(component, {
    global: {
      plugins,
      stubs: {
        ...naiveStubs,
        RouterLink: {
          props: { to: [String, Object] },
          setup(_, { slots }) {
            return () => h("a", { href: "#" }, [slots.default?.()]);
          },
        },
        RouterView: passthrough("div"),
      },
    },
  });
}
