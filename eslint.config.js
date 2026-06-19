const tsParser = require("@typescript-eslint/parser");
const tsPlugin = require("@typescript-eslint/eslint-plugin");
const vueParser = require("vue-eslint-parser");
const vuePlugin = require("eslint-plugin-vue");

const browserGlobals = {
  AbortController: "readonly",
  Blob: "readonly",
  CustomEvent: "readonly",
  Event: "readonly",
  EventSource: "readonly",
  File: "readonly",
  FormData: "readonly",
  HTMLElement: "readonly",
  KeyboardEvent: "readonly",
  MouseEvent: "readonly",
  Request: "readonly",
  Response: "readonly",
  URL: "readonly",
  URLSearchParams: "readonly",
  clearInterval: "readonly",
  clearTimeout: "readonly",
  console: "readonly",
  crypto: "readonly",
  document: "readonly",
  fetch: "readonly",
  history: "readonly",
  localStorage: "readonly",
  location: "readonly",
  navigator: "readonly",
  sessionStorage: "readonly",
  setInterval: "readonly",
  setTimeout: "readonly",
  window: "readonly",
};

const nodeGlobals = {
  AbortController: "readonly",
  Buffer: "readonly",
  URL: "readonly",
  URLSearchParams: "readonly",
  __dirname: "readonly",
  __filename: "readonly",
  clearInterval: "readonly",
  clearTimeout: "readonly",
  console: "readonly",
  fetch: "readonly",
  process: "readonly",
  setInterval: "readonly",
  setTimeout: "readonly",
};

const vitestGlobals = {
  afterAll: "readonly",
  afterEach: "readonly",
  beforeAll: "readonly",
  beforeEach: "readonly",
  describe: "readonly",
  expect: "readonly",
  it: "readonly",
  test: "readonly",
  vi: "readonly",
};

const commonRules = {
  eqeqeq: ["error", "always", { null: "ignore" }],
  "no-alert": "error",
  "no-debugger": "error",
  "no-duplicate-imports": "error",
  "no-var": "error",
  "object-shorthand": ["error", "always"],
  "prefer-const": "error",
};

const tsRules = {
  ...commonRules,
  "no-unused-vars": "off",
  "no-undef": "off",
  "@typescript-eslint/consistent-type-imports": [
    "error",
    { fixStyle: "inline-type-imports", prefer: "type-imports" },
  ],
  "@typescript-eslint/no-explicit-any": "warn",
  "@typescript-eslint/no-unused-vars": [
    "error",
    {
      argsIgnorePattern: "^_",
      caughtErrorsIgnorePattern: "^_",
      varsIgnorePattern: "^_",
    },
  ],
};

const vueUnusedVarsRule = [
  "error",
  {
    argsIgnorePattern: "^_",
    caughtErrorsIgnorePattern: "^_",
    varsIgnorePattern: "^(props|_)",
  },
];

module.exports = [
  {
    ignores: [
      "webui/coverage/**",
      "webui/dist/**",
      "webui/node_modules/**",
      "webui/test-results/**",
    ],
  },
  {
    files: ["eslint.config.js"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: nodeGlobals,
      sourceType: "commonjs",
    },
    rules: {
      ...commonRules,
      "no-undef": "error",
    },
  },
  {
    files: ["webui/scripts/**/*.mjs"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: nodeGlobals,
      sourceType: "module",
    },
    rules: {
      ...commonRules,
      "no-undef": "error",
    },
  },
  {
    files: [
      "webui/*.ts",
      "webui/src/**/*.ts",
      "webui/tests/**/*.ts",
      "webui/tests/**/*.spec.ts",
    ],
    languageOptions: {
      ecmaVersion: "latest",
      globals: browserGlobals,
      parser: tsParser,
      parserOptions: {
        sourceType: "module",
      },
      sourceType: "module",
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
    },
    rules: tsRules,
  },
  {
    files: ["webui/tests/**/*.ts", "webui/tests/**/*.spec.ts"],
    languageOptions: {
      globals: {
        ...browserGlobals,
        ...nodeGlobals,
        ...vitestGlobals,
      },
    },
    rules: {
      "@typescript-eslint/consistent-type-imports": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": "off",
    },
  },
  {
    files: ["webui/**/*.vue"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: browserGlobals,
      parser: vueParser,
      parserOptions: {
        extraFileExtensions: [".vue"],
        parser: tsParser,
        sourceType: "module",
      },
      sourceType: "module",
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      vue: vuePlugin,
    },
    rules: {
      ...tsRules,
      "@typescript-eslint/no-unused-vars": vueUnusedVarsRule,
      "vue/no-mutating-props": "error",
      "vue/no-parsing-error": "error",
      "vue/no-unused-components": "error",
      "vue/no-unused-vars": "error",
      "vue/no-v-html": "error",
      "vue/require-v-for-key": "error",
      "vue/valid-v-bind": "error",
      "vue/valid-v-for": "error",
      "vue/valid-v-on": "error",
      "vue/valid-v-slot": "error",
    },
  },
];
