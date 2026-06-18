import {
  inject,
  onBeforeUnmount,
  provide,
  shallowRef,
  type InjectionKey,
} from "vue";

export type RouteRefreshHandler = () => Promise<void> | void;

type RouteRefreshRegistry = {
  refresh: () => Promise<void>;
  register: (handler: RouteRefreshHandler) => () => void;
};

const routeRefreshKey: InjectionKey<RouteRefreshRegistry> =
  Symbol("route-refresh");

export function provideRouteRefreshRegistry(): RouteRefreshRegistry {
  const currentHandler = shallowRef<RouteRefreshHandler | null>(null);
  const registry: RouteRefreshRegistry = {
    async refresh() {
      await currentHandler.value?.();
    },
    register(handler) {
      currentHandler.value = handler;
      return () => {
        if (currentHandler.value === handler) {
          currentHandler.value = null;
        }
      };
    },
  };
  provide(routeRefreshKey, registry);
  return registry;
}

export function useRouteRefresh(handler: RouteRefreshHandler): void {
  const registry = inject(routeRefreshKey, null);
  if (!registry) {
    return;
  }
  const unregister = registry.register(handler);
  onBeforeUnmount(unregister);
}
