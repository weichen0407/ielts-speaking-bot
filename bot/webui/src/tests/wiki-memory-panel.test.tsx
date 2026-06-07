import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClientProvider } from "@/providers/ClientProvider";

const graphPropsSpy = vi.hoisted(() => vi.fn());

vi.mock("@/components/WikiGraphView", () => ({
  WikiGraphView: (props: { filterMemoryStatus?: string }) => {
    graphPropsSpy(props);
    return (
      <div data-testid="wiki-graph-props">
        {props.filterMemoryStatus || "all"}
      </div>
    );
  },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    fetchWikiSearch: vi.fn().mockResolvedValue({ results: [] }),
    fetchWikiPage: vi.fn(),
    applyWikiPatch: vi.fn(),
    rebuildWikiIndex: vi.fn(),
  };
});

import { fetchWikiSearch } from "@/lib/api";
import { WikiMemoryPanel } from "@/components/WikiMemoryPanel";

describe("WikiMemoryPanel", () => {
  it("passes memory status filters into the graph view", async () => {
    render(
      <ClientProvider client={{} as never} token="tok">
        <WikiMemoryPanel
          api={{
            isOpen: true,
            open: vi.fn(),
            close: vi.fn(),
            toggle: vi.fn(),
          }}
        />
      </ClientProvider>,
    );

    await waitFor(() => expect(fetchWikiSearch).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText("Filter wiki graph by memory status"), {
      target: { value: "uncertain" },
    });
    fireEvent.click(screen.getByRole("button", { name: "graph" }));

    expect(await screen.findByTestId("wiki-graph-props")).toHaveTextContent("uncertain");
    expect(graphPropsSpy).toHaveBeenLastCalledWith(
      expect.objectContaining({ filterMemoryStatus: "uncertain" }),
    );
  });
});
