import { createPinia, setActivePinia } from "pinia";
import { flushPromises } from "@vue/test-utils";
import { createMemoryHistory } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createWudRouter } from "../src/router";
import { useAuthStore } from "../src/stores/auth";
import LoginView from "../src/views/LoginView.vue";
import { authSession } from "./helpers/fixtures";
import { mountWithApp } from "./helpers/mount";

describe("LoginView", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("exposes native credential fields and submits DOM autofill values", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const auth = useAuthStore();
    auth.session = authSession({
      authenticated: false,
      setup_required: false,
      username: null,
    });
    const login = vi.spyOn(auth, "login").mockResolvedValue();
    const router = createWudRouter(createMemoryHistory());

    await router.push("/login?redirect=/pending");
    await router.isReady();
    const replace = vi.spyOn(router, "replace").mockResolvedValue(undefined);
    const wrapper = mountWithApp(LoginView, { pinia, router });
    const username = wrapper.get('input[name="username"]');
    const password = wrapper.get('input[name="password"]');

    expect(username.attributes()).toMatchObject({
      id: "login-username",
      autocomplete: "username",
      required: "",
    });
    expect(password.attributes()).toMatchObject({
      id: "login-password",
      autocomplete: "current-password",
      required: "",
    });
    expect(wrapper.get('label[for="login-username"]').exists()).toBe(true);
    expect(wrapper.get('label[for="login-password"]').exists()).toBe(true);
    expect(wrapper.get('button[type="submit"]').attributes("disabled")).toBeUndefined();

    (username.element as HTMLInputElement).value = "admin";
    (password.element as HTMLInputElement).value = "password";
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(login).toHaveBeenCalledWith("admin", "password");
    expect(replace).toHaveBeenCalledWith("/pending");
  });
});
