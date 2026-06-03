import { h, inject, provide, ref, type Component, type Ref, type VNodeChild } from "vue";
import { mount, type VueWrapper } from "@vue/test-utils";
import { createPinia, setActivePinia, type Pinia } from "pinia";
import type { Router } from "vue-router";

type MountOptions = {
  pinia?: Pinia;
  router?: Router;
};

type DataTableColumn = {
  key?: string;
  type?: string;
  render?: (row: Record<string, unknown>) => VNodeChild;
};

type TabsState = {
  activeName: Ref<string | undefined>;
};

const passthrough = (tag: string) => ({
  setup(_: unknown, { slots }: { slots: Record<string, () => unknown> }) {
    return () => h(tag, [slots.default?.()]);
  },
});

const tabsInjectionKey = Symbol("tabs");

function callUpdateValue(listener: unknown, value: string): void {
  if (typeof listener === "function") {
    listener(value);
  } else if (Array.isArray(listener)) {
    for (const handler of listener) {
      callUpdateValue(handler, value);
    }
  }
}

const nInputStub: Component = {
  props: {
    disabled: Boolean,
    inputProps: Object,
    placeholder: String,
    size: String,
    type: String,
    value: [String, Number],
  },
  emits: ["update:value"],
  setup(props, { attrs, emit }) {
    return () => {
      const { onUpdateValue, ...inputAttrs } = attrs as Record<string, unknown>;
      return h("input", {
        ...inputAttrs,
        ...(props.inputProps as Record<string, unknown> | undefined),
        disabled: props.disabled,
        placeholder: props.placeholder,
        type: props.type || "text",
        value: props.value ?? "",
        onInput: (event: Event) => {
          const value = (event.target as HTMLInputElement).value;
          emit("update:value", value);
          callUpdateValue(onUpdateValue, value);
        },
      });
    };
  },
};

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
      indeterminate: Boolean,
    },
    emits: ["update:checked"],
    setup(props, { attrs, emit, slots }) {
      return () =>
        h("label", [
          h("input", {
            ...attrs,
            type: "checkbox",
            checked: props.checked,
            disabled: props.disabled,
            indeterminate: props.indeterminate,
            "aria-checked": props.indeterminate ? "mixed" : String(props.checked),
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
      columns: Array,
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
            const record = row as Record<string, unknown> & {
              line_no: number;
              image: string;
            };
            const columns = (props.columns ?? []) as DataTableColumn[];
            const key = props.rowKey
              ? props.rowKey(record)
              : record.line_no;
            const checked = (props.checkedRowKeys ?? []).includes(key);
            return h("div", { role: "row", key }, [
              h("label", [
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
              ]),
              ...columns
                .filter((column) => column.type !== "selection")
                .map((column, index) =>
                  h(
                    "span",
                    { role: "cell", key: column.key ?? index },
                    column.render
                      ? [column.render(record)]
                      : [String(column.key ? record[column.key] ?? "" : "")],
                  ),
                ),
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
      labelProps: Object,
    },
    setup(props, { slots }) {
      return () =>
        h("label", props.labelProps as Record<string, unknown> | undefined, [
          props.label ? h("span", props.label) : null,
          slots.default?.(),
        ]);
    },
  },
  NInput: nInputStub,
  Input: nInputStub,
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
      return () => {
        const positiveButtonProps = props.positiveButtonProps as
          | { disabled?: boolean; loading?: boolean }
          | undefined;
        const positiveDisabled = Boolean(
          positiveButtonProps?.disabled || positiveButtonProps?.loading,
        );
        return props.show
          ? h("div", { role: "dialog" }, [
              props.title ? h("h2", props.title) : null,
              slots.default?.(),
              props.positiveText
                ? h(
                    "button",
                    {
                      disabled: positiveDisabled,
                      onClick: positiveDisabled
                        ? undefined
                        : () => emit("positive-click"),
                    },
                    props.positiveText,
                  )
                : null,
            ])
          : null;
      };
    },
  },
  NSelect: {
    props: {
      disabled: Boolean,
      multiple: Boolean,
      options: Array,
      value: [String, Number, Array],
    },
    emits: ["update:value"],
    setup(props, { emit }) {
      return () =>
        h(
          "select",
          {
            disabled: props.disabled,
            multiple: props.multiple,
            value: props.value ?? (props.multiple ? [] : ""),
            onChange: (event: Event) => {
              const select = event.target as HTMLSelectElement;
              emit(
                "update:value",
                props.multiple
                  ? Array.from(select.selectedOptions).map((option) => option.value)
                  : select.value,
              );
            },
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
  NTabPane: {
    props: {
      name: String,
      tab: String,
    },
    setup(props, { slots }) {
      const tabsState = inject<TabsState | null>(tabsInjectionKey, null);
      if (tabsState && !tabsState.activeName.value) {
        tabsState.activeName.value = props.name;
      }
      return () =>
        !tabsState || tabsState.activeName.value === props.name
          ? h(
              "div",
              {
                role: "tabpanel",
                "data-tab-pane": props.name,
              },
              [slots.default?.()],
            )
          : null;
    },
  },
  NTabs: {
    setup(_, { slots }) {
      const tabsState: TabsState = { activeName: ref() };
      provide(tabsInjectionKey, tabsState);
      return () => {
        const panes = slots.default?.() ?? [];
        return h("div", [
          h(
            "div",
            { role: "tablist" },
            panes.map((pane) => {
              const name = String(pane.props?.name ?? "");
              return h(
                "button",
                {
                  role: "tab",
                  type: "button",
                  "aria-selected": String(tabsState.activeName.value === name),
                  onClick: () => {
                    tabsState.activeName.value = name;
                  },
                },
                String(pane.props?.tab ?? name),
              );
            }),
          ),
          panes,
        ]);
      };
    },
  },
  NTag: passthrough("span"),
  NTooltip: {
    setup(_, { slots }) {
      return () => h("span", [slots.trigger?.(), slots.default?.()]);
    },
  },
};

Object.assign(naiveStubs, {
  Alert: naiveStubs.NAlert,
  Button: naiveStubs.NButton,
  Checkbox: naiveStubs.NCheckbox,
  ConfigProvider: naiveStubs.NConfigProvider,
  DataTable: naiveStubs.NDataTable,
  Form: naiveStubs.NForm,
  FormItem: naiveStubs.NFormItem,
  Input: naiveStubs.NInput,
  InputNumber: naiveStubs.NInputNumber,
  MessageProvider: naiveStubs.NMessageProvider,
  Modal: naiveStubs.NModal,
  Select: naiveStubs.NSelect,
  Switch: naiveStubs.NSwitch,
  TabPane: naiveStubs.NTabPane,
  Tabs: naiveStubs.NTabs,
  Tag: naiveStubs.NTag,
  Tooltip: naiveStubs.NTooltip,
});

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
