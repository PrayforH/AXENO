export function isHiddenByCollapsedDetails(element: HTMLElement): boolean {
  for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
    if (ancestor.tagName !== "DETAILS" || (ancestor as HTMLDetailsElement).open) continue;
    const summary = Array.from(ancestor.children).find((child) => child.tagName === "SUMMARY");
    if (!summary?.contains(element)) return true;
  }
  return false;
}
