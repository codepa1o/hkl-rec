export class VisibleDwellAccumulator {
  private accumulatedMs = 0;
  private visibleSince: number | null;
  private sent = false;

  constructor(
    private readonly now: () => number = () => performance.now(),
    initiallyVisible = true,
  ) {
    this.visibleSince = initiallyVisible ? this.now() : null;
  }

  setVisible(visible: boolean): void {
    if (visible === (this.visibleSince !== null)) return;
    const timestamp = this.now();
    if (visible) {
      this.visibleSince = timestamp;
      return;
    }
    this.accumulatedMs += Math.max(0, timestamp - (this.visibleSince ?? timestamp));
    this.visibleSince = null;
  }

  elapsedMs(): number {
    const activeMs =
      this.visibleSince === null ? 0 : Math.max(0, this.now() - this.visibleSince);
    return Math.round(this.accumulatedMs + activeMs);
  }

  takeForSend(minimumMs: number): number | null {
    if (this.sent) return null;
    const elapsedMs = this.elapsedMs();
    if (elapsedMs < minimumMs) return null;
    this.sent = true;
    return Math.min(elapsedMs, 86_400_000);
  }
}

export function dwellEventId(
  sourceSpace: NewsSpace,
  userId: number,
  articleId: string,
  routeLoadId: string,
): string {
  return `dwell-${sourceSpace}:${userId}:${articleId}:${routeLoadId}`;
}
import type { NewsSpace } from "../api/types";
