const ACTIVE_RUN_KEY = "cogniforge_active_run_id";
const ACTIVE_TAB_KEY = "cogniforge_active_tab";

export function saveActiveRunId(runId: string): void {
  try {
    sessionStorage.setItem(ACTIVE_RUN_KEY, runId);
  } catch {
    /* private mode / quota */
  }
}

export function loadActiveRunId(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_RUN_KEY);
  } catch {
    return null;
  }
}

export function clearActiveRunId(): void {
  try {
    sessionStorage.removeItem(ACTIVE_RUN_KEY);
  } catch {
    /* ignore */
  }
}

export function saveActiveTab(tab: string): void {
  try {
    sessionStorage.setItem(ACTIVE_TAB_KEY, tab);
  } catch {
    /* ignore */
  }
}

export function loadActiveTab(): string | null {
  try {
    return sessionStorage.getItem(ACTIVE_TAB_KEY);
  } catch {
    return null;
  }
}

export function isTerminalStatus(status: string): boolean {
  return !["running"].includes(status);
}
