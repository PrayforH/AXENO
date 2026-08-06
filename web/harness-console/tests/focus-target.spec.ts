import { describe, expect, it } from "vitest";
import { isHiddenByCollapsedDetails } from "../src/lib/focus-target";

type FakeElement = {
  tagName: string;
  open?: boolean;
  parentElement: FakeElement | null;
  children: FakeElement[];
  contains(target: unknown): boolean;
};

function element(tagName: string, parentElement: FakeElement | null = null): FakeElement {
  const node: FakeElement = {
    tagName,
    parentElement,
    children: [],
    contains(target) {
      return target === node || node.children.some((child) => child.contains(target));
    },
  };
  parentElement?.children.push(node);
  return node;
}

describe("focus target visibility", () => {
  it("excludes controls hidden inside collapsed details", () => {
    const details = element("DETAILS");
    details.open = false;
    element("SUMMARY", details);
    const hiddenButton = element("BUTTON", details);

    expect(isHiddenByCollapsedDetails(hiddenButton as unknown as HTMLElement)).toBe(true);
  });

  it("keeps the collapsed details summary reachable", () => {
    const details = element("DETAILS");
    details.open = false;
    const summary = element("SUMMARY", details);

    expect(isHiddenByCollapsedDetails(summary as unknown as HTMLElement)).toBe(false);
  });

  it("excludes nested summaries hidden by an outer collapsed details", () => {
    const outerDetails = element("DETAILS");
    outerDetails.open = false;
    element("SUMMARY", outerDetails);
    const innerDetails = element("DETAILS", outerDetails);
    innerDetails.open = false;
    const nestedSummary = element("SUMMARY", innerDetails);

    expect(isHiddenByCollapsedDetails(nestedSummary as unknown as HTMLElement)).toBe(true);
  });
});
