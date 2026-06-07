import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockNotesState = vi.hoisted(() => ({
  value: {
    mode: "freechat",
    vocab: "",
    polisher: "",
    review: "",
  },
}));

vi.mock("@/hooks/useSessionNotes", () => ({
  useSessionNotes: () => ({
    notes: mockNotesState.value,
    loading: false,
    error: null,
  }),
}));

import { SessionNotesSheet } from "@/components/SessionNotesSheet";

describe("SessionNotesSheet", () => {
  beforeEach(() => {
    mockNotesState.value = {
      mode: "freechat",
      vocab: "",
      polisher: "",
      review: "",
    };
  });

  it("shows vocab and polisher tabs for freechat sessions", () => {
    render(
      <SessionNotesSheet
        open={true}
        onOpenChange={vi.fn()}
        sessionKey="websocket:freechat-1"
        sessionTitle="Freechat"
      />,
    );

    expect(screen.getByRole("button", { name: /vocabulary/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /grammar/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /review/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Check monitor for trigger disabled/i)).toBeInTheDocument();
  });

  it("shows only review for Be Native sessions", () => {
    mockNotesState.value = {
      mode: "benative",
      vocab: "",
      polisher: "",
      review: "",
    };

    render(
      <SessionNotesSheet
        open={true}
        onOpenChange={vi.fn()}
        sessionKey="websocket:benative-1"
        sessionTitle="Be Native"
      />,
    );

    expect(screen.getByRole("button", { name: /review/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /vocabulary/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /grammar/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Be Native review artifact has not been created yet/i)).toBeInTheDocument();
  });
});
