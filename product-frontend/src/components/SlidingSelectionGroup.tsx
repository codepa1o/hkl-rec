import type { CSSProperties, ReactNode } from "react";

type SelectionIndicatorStyle = CSSProperties & {
  "--zr-selection-height": string;
  "--zr-selection-index": number;
  "--zr-selection-inset": string;
  "--zr-selection-offset": string;
};

interface Props {
  activeIndex: number;
  children: ReactNode;
  className: string;
  indicatorTestId: string;
  itemHeight: number;
  itemStep?: number;
  inset?: number;
}

export default function SlidingSelectionGroup({
  activeIndex,
  children,
  className,
  indicatorTestId,
  itemHeight,
  itemStep = itemHeight,
  inset = 0,
}: Props) {
  const indicatorStyle: SelectionIndicatorStyle = {
    "--zr-selection-height": `${itemHeight}px`,
    "--zr-selection-index": activeIndex,
    "--zr-selection-inset": `${inset}px`,
    "--zr-selection-offset": `${activeIndex * itemStep}px`,
  };

  return (
    <div className={`zr-selection-group ${className}`}>
      {activeIndex >= 0 && (
        <span
          className="zr-selection-indicator"
          data-testid={indicatorTestId}
          style={indicatorStyle}
          aria-hidden="true"
        />
      )}
      {children}
    </div>
  );
}
