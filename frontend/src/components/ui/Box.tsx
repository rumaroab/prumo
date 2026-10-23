import { forwardRef, type ComponentPropsWithoutRef } from "react";

/** Structural layout only. Use Card for a surface and SectionContainer for a page. */
export const Box = forwardRef<HTMLDivElement, ComponentPropsWithoutRef<"div">>(
  function Box(props, ref) {
    return <div {...props} ref={ref} />;
  },
);
