import { describe, expect, it } from "vitest";
import {
  installMarkdownControlEnhancer,
  normalizeMarkdownControls,
} from "../src/components/markdown-control-observer";

class FakeControl {
  hidden = false;
  attributes = new Map<string, string>();

  getAttribute(name: string) {
    return this.attributes.get(name) ?? null;
  }

  removeAttribute(name: string) {
    this.attributes.delete(name);
  }

  setAttribute(name: string, value: string) {
    this.attributes.set(name, value);
  }
}

class FakeRoot {
  body = {};
  copies: FakeControl[] = [];
  downloads: FakeControl[] = [];
  listener: ((event: Event) => void) | undefined;

  addEventListener(_name: string, listener: EventListenerOrEventListenerObject) {
    this.listener = listener as (event: Event) => void;
  }

  removeEventListener() {
    this.listener = undefined;
  }

  querySelectorAll(selector: string) {
    return selector.includes("download") ? this.downloads : this.copies;
  }
}

describe("Markdown code controls", () => {
  it("hides generic downloads and localizes code copy", () => {
    const root = new FakeRoot();
    const download = new FakeControl();
    const copy = new FakeControl();
    root.downloads.push(download);
    root.copies.push(copy);

    normalizeMarkdownControls(root as unknown as Document);

    expect(download.hidden).toBe(true);
    expect(download.getAttribute("aria-hidden")).toBe("true");
    expect(copy.getAttribute("aria-label")).toBe("复制代码");
    expect(copy.getAttribute("title")).toBe("复制代码");
  });

  it("enhances streamed controls, reports copied state, and cleans up", () => {
    const root = new FakeRoot();
    const callbacks: Array<() => void> = [];
    let mutationCallback: (() => void) | undefined;
    let disconnected = false;
    const observerFactory = (callback: () => void) => {
      mutationCallback = callback;
      return {
        disconnect: () => {
          disconnected = true;
        },
        observe: () => undefined,
      };
    };

    const cleanup = installMarkdownControlEnhancer(root as unknown as Document, {
      createObserver: observerFactory,
      schedule: (callback) => {
        callbacks.push(callback);
        return callbacks.length;
      },
      cancel: () => undefined,
    });

    const streamedCopy = new FakeControl();
    root.copies.push(streamedCopy);
    mutationCallback?.();
    expect(streamedCopy.getAttribute("aria-label")).toBe("复制代码");

    root.listener?.({
      target: { closest: () => streamedCopy },
    } as unknown as Event);
    expect(streamedCopy.getAttribute("data-copy-state")).toBe("copied");
    expect(streamedCopy.getAttribute("aria-label")).toBe("已复制");

    callbacks[0]?.();
    expect(streamedCopy.getAttribute("data-copy-state")).toBeNull();
    expect(streamedCopy.getAttribute("aria-label")).toBe("复制代码");

    cleanup();
    expect(disconnected).toBe(true);
    expect(root.listener).toBeUndefined();
  });
});
