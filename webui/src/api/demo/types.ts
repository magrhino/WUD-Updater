import type {
  ApplyJobLogResponse,
  ApplyJobResponse,
  PendingGroupedItem,
  PlanResponse,
  RunDetail,
  RunLogResponse,
  RunSummary,
} from "../types";

export type DemoStackName = "data" | "home" | "media";

export type DemoStack = {
  name: DemoStackName;
  servicesLabel: string;
  services: string[];
};

export type DemoPendingItem = PendingGroupedItem & {
  stack: DemoStackName | "";
  service: string;
};

export type DemoJobRecord = {
  job: ApplyJobResponse;
  log: ApplyJobLogResponse;
  lineNumbers: number[];
  plan: PlanResponse | null;
  completed: boolean;
};

export type DemoRunFixture = {
  summary: RunSummary;
  detail: RunDetail;
  log: RunLogResponse;
};
