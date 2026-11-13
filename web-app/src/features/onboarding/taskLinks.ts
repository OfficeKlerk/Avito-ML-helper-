const taskIdPattern = /^t_[a-z0-9_]+$/;

export const adaptationRefreshInterval = 30_000;

export function taskPath(taskId: string) {
  return `/onboarding/tasks/${encodeURIComponent(taskId)}`;
}

export function taskContext(taskId: string) {
  return `?${new URLSearchParams({ task: taskId })}`;
}

export function readTaskContext(search: string) {
  const taskId = new URLSearchParams(search).get("task");
  return taskId && taskIdPattern.test(taskId) ? taskId : null;
}
