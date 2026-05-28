import { createRouter, createWebHashHistory } from "vue-router";

import { useAuthStore } from "../stores/auth";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/login",
      name: "login",
      component: () => import("../views/LoginView.vue"),
      meta: { requiresAuth: false },
    },
    {
      path: "/",
      name: "dashboard",
      component: () => import("../views/DashboardView.vue"),
      meta: { requiresAuth: true, title: "Dashboard" },
    },
    {
      path: "/pending",
      name: "pending",
      component: () => import("../views/PendingView.vue"),
      meta: { requiresAuth: true, title: "Pending updates" },
    },
    {
      path: "/runs",
      name: "runs",
      component: () => import("../views/RunsView.vue"),
      meta: { requiresAuth: true, title: "Run history" },
    },
    {
      path: "/runs/:id",
      name: "run-detail",
      component: () => import("../views/RunDetailView.vue"),
      meta: { requiresAuth: true, title: "Run detail" },
    },
    {
      path: "/runs/:id/log",
      name: "run-log",
      component: () => import("../views/LogView.vue"),
      meta: { requiresAuth: true, title: "Log viewer" },
    },
    {
      path: "/:pathMatch(.*)*",
      redirect: "/",
    },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (auth.session === null && !auth.loading) {
    await auth.loadSession();
  }
  if (to.meta.requiresAuth !== false && !auth.authenticated) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  if (to.name === "login" && auth.authenticated) {
    return { name: "dashboard" };
  }
  return true;
});
