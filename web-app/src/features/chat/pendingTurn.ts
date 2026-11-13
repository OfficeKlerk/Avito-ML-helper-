type Turn = { key: string; text: string };

const storageKey = "ai-buddy.chat.pending";
let pending: (Turn & { userId: string }) | null = null;

export function readPendingTurn(userId: string): Turn | null {
  if (pending?.userId === userId) return pending;
  try {
    const stored = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    if (stored?.userId === userId && typeof stored.text === "string" && /^[a-f0-9]{32}$/.test(stored.key)) {
      pending = stored;
      return pending;
    }
  } catch {
    // In-memory state still works when browser storage is unavailable.
  }
  return null;
}

export function savePendingTurn(userId: string, turn: Turn) {
  pending = { ...turn, userId };
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(pending));
  } catch {
    // Keep the turn in memory until the tab is reloaded.
  }
}

export function clearPendingTurn() {
  pending = null;
  try {
    sessionStorage.removeItem(storageKey);
  } catch {
    // There is no accessible browser state to clear.
  }
}
