import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminMonitorView } from "@/components/AdminMonitorView";
import { ClientProvider } from "@/providers/ClientProvider";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => body,
  } as Response;
}

describe("AdminMonitorView", () => {
  it("shows Be Native processor and subagent runs with mode filtering", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({
        generated_at: "2026-06-04T10:00:00Z",
        workspace: "/tmp/project",
        capabilities: {
          modes: {
            benative: { subagents: ["benative_article", "vocab", "polisher", "benative_review"] },
          },
          subagents: {
            benative_review: {
              execution_modes: ["api", "agentic"],
              tools: { api: [], agentic: ["user_profile"] },
            },
          },
          processors: {
            benative_review: { output: "persona/processor/benative/review.jsonl" },
          },
        },
        triggers: [
          {
            id: "benative_review",
            name: "Be Native Review",
            mode: "benative",
            source: "mode/benative/trigger/triggers.json",
            enabled: true,
            condition: { kind: "file_line_count", count: 1 },
            subagent: "benative_review",
            processor: "benative_review",
            execution_mode: "api",
            tools: [],
            model: "deepseek-v4-flash",
            output_path: "persona/processor/benative/review.jsonl",
          },
        ],
        prompts: [],
        subagent_statuses: [],
        subagent_runs: [
          {
            timestamp: "2026-06-04T10:00:02Z",
            task_id: "task-benative",
            label: "benative_review",
            subagent: "benative_review",
            phase: "done",
            stop_reason: "completed",
            model: "deepseek-v4-flash",
            origin: {
              kind: "processor_middleware",
              mode: "benative",
              processor: "benative_review",
            },
            result: "ARTICLE article_001 review complete",
            execution_mode: "api",
            tools: [],
            input_rows: 1,
            output_rows: 1,
            duration_ms: 42,
          },
          {
            timestamp: "2026-06-04T09:59:00Z",
            task_id: "task-freechat",
            label: "vocab",
            subagent: "vocab",
            phase: "done",
            stop_reason: "completed",
            origin: { kind: "processor_middleware", mode: "freechat" },
            result: "freechat vocab complete",
            execution_mode: "api",
            tools: [],
          },
        ],
        processor_runs: [
          {
            timestamp: "2026-06-04T10:00:01Z",
            trigger_id: "benative_review",
            processor: "benative_review",
            subagent: "benative_review",
            execution_mode: "api",
            tools: [],
            mode: "benative",
            status: "completed",
            model: "deepseek-v4-flash",
            input_rows: 1,
            output_rows: 1,
            duration_ms: 40,
            output_preview: [
              {
                article_id: "article_001",
                sentence_index: 2,
                issue_type: "grammar",
              },
            ],
          },
          {
            timestamp: "2026-06-04T09:59:01Z",
            trigger_id: "freechat_vocab",
            processor: "vocab",
            subagent: "vocab",
            mode: "freechat",
            status: "completed",
            output_preview: [{ original: "good", improved: "memorable" }],
          },
        ],
        trigger_decisions: [
          {
            timestamp: "2026-06-04T10:00:00Z",
            trigger_id: "benative_review",
            mode: "benative",
            decision: "spawned",
            reason: "file_line_count_due",
            subagent: "benative_review",
          },
        ],
        recent_activity: [],
        wiki_sync_runs: [],
        cost_summary: {
          currency: "USD",
          estimated_usd: 0.001,
          prompt_tokens: 1200,
          cached_tokens: 0,
          completion_tokens: 180,
          modes: [
            {
              mode: "benative",
              prompt_tokens: 800,
              cached_tokens: 0,
              completion_tokens: 120,
              estimated_usd: 0.0007,
              runs: 2,
              budget_usd: 0.2,
              budget_used_pct: 0.35,
            },
          ],
          models: [],
        },
      })),
    );

    render(
      <ClientProvider client={{} as never} token="tok">
        <AdminMonitorView onBackToChat={() => {}} />
      </ClientProvider>,
    );

    expect(await screen.findByText("Be Native Review")).toBeInTheDocument();
    expect(screen.getAllByText("article article_001 · sentence 2 · grammar").length).toBeGreaterThan(0);
    expect(screen.getByText("按模式预算")).toBeInTheDocument();
    expect(screen.getByText("budget $0.2000")).toBeInTheDocument();
    expect(screen.getByText("0.35%")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filter monitor runs by mode"), {
      target: { value: "benative" },
    });

    await waitFor(() => {
      expect(screen.getAllByText("benative_review").length).toBeGreaterThan(0);
      expect(screen.queryByText("freechat vocab complete")).not.toBeInTheDocument();
    });
  });
});
