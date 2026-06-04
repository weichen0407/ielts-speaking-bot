import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Bot,
  ChevronLeft,
  Clock3,
  Cpu,
  Database,
  DollarSign,
  FileText,
  Loader2,
  RefreshCw,
  Settings2,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  fetchAdminMonitor,
  updateAdminTrigger,
  type AdminMonitorPayload,
  type AdminProcessorRun,
  type AdminPrompt,
  type AdminSubagentRun,
  type AdminTriggerDecision,
  type AdminTrigger,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

interface AdminMonitorViewProps {
  onBackToChat: () => void;
}

function formatJson(value: unknown): string {
  if (!value || (typeof value === "object" && Object.keys(value as Record<string, unknown>).length === 0)) {
    return "-";
  }
  return JSON.stringify(value, null, 2);
}

function shortTime(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function triggerSchedule(trigger: AdminTrigger): string {
  const condition = trigger.condition ?? {};
  const kind = String(condition.kind ?? "manual");
  const count = condition.count;
  if (kind === "turn_count") return `every ${count} turns`;
  if (kind === "file_line_count") return `every ${count} new lines`;
  if (kind === "cron") return String(count ?? "cron");
  return kind;
}

function triggerKey(trigger: AdminTrigger): string {
  return `${trigger.source}:${trigger.id}`;
}

function runKey(run: AdminSubagentRun): string {
  return `${run.timestamp}:${run.task_id}`;
}

function decisionKey(decision: AdminTriggerDecision, index: number): string {
  return `${decision.timestamp}:${decision.source ?? ""}:${decision.trigger_id}:${decision.reason}:${index}`;
}

function processorRunKey(run: AdminProcessorRun): string {
  return `${run.timestamp}:${run.trigger_id}:${run.processor}`;
}

function runMode(run: AdminSubagentRun | AdminProcessorRun | AdminTriggerDecision): string {
  const direct = "mode" in run ? run.mode : undefined;
  if (typeof direct === "string" && direct.trim()) return direct;
  if ("origin" in run && run.origin && typeof run.origin === "object") {
    const originMode = (run.origin as Record<string, unknown>).mode;
    if (typeof originMode === "string" && originMode.trim()) return originMode;
  }
  return "unknown";
}

function previewValue(item: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

function processorPreviewSummary(run: AdminProcessorRun): string {
  const preview = run.output_preview ?? [];
  const first = preview.find((item) => item && typeof item === "object");
  if (!first) return "";
  const articleId = previewValue(first, ["article_id"]);
  const sentenceIndex = previewValue(first, ["sentence_index"]);
  const recordType = previewValue(first, ["record_type", "issue_type", "type", "grammar_type"]);
  const parts = [
    articleId ? `article ${articleId}` : null,
    sentenceIndex ? `sentence ${sentenceIndex}` : null,
    recordType,
  ].filter(Boolean);
  return parts.join(" · ");
}

function formatUsd(value?: number): string {
  if (!value) return "$0.0000";
  if (value < 0.0001) return `<$0.0001`;
  return `$${value.toFixed(4)}`;
}

function formatTools(tools?: string[] | null): string {
  if (!tools || tools.length === 0) return "-";
  return tools.join(", ");
}

export function AdminMonitorView({ onBackToChat }: AdminMonitorViewProps) {
  const { token } = useClient();
  const [payload, setPayload] = useState<AdminMonitorPayload | null>(null);
  const [selectedTriggerKey, setSelectedTriggerKey] = useState<string | null>(null);
  const [selectedPromptId, setSelectedPromptId] = useState<string | null>(null);
  const [selectedRunKey, setSelectedRunKey] = useState<string | null>(null);
  const [selectedProcessorRunKey, setSelectedProcessorRunKey] = useState<string | null>(null);
  const [selectedDecisionKey, setSelectedDecisionKey] = useState<string | null>(null);
  const [modeFilter, setModeFilter] = useState("all");
  const [runModeFilter, setRunModeFilter] = useState("all");
  const [countDraft, setCountDraft] = useState("");
  const [savingTrigger, setSavingTrigger] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const next = await fetchAdminMonitor(token);
      setPayload(next);
      setError(null);
      setSelectedTriggerKey((current) => current ?? (next.triggers[0] ? triggerKey(next.triggers[0]) : null));
      setSelectedPromptId((current) => current ?? next.prompts[0]?.id ?? null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const modes = useMemo(() => {
    const values = new Set(payload?.triggers.map((t) => t.mode).filter(Boolean));
    return ["all", ...Array.from(values).sort()];
  }, [payload]);

  const filteredTriggers = useMemo(() => {
    const all = payload?.triggers ?? [];
    if (modeFilter === "all") return all;
    return all.filter((trigger) => trigger.mode === modeFilter);
  }, [payload, modeFilter]);

  const selectedTrigger = useMemo(
    () => payload?.triggers.find((trigger) => triggerKey(trigger) === selectedTriggerKey) ?? filteredTriggers[0],
    [payload, selectedTriggerKey, filteredTriggers],
  );

  const promptById = useMemo(() => {
    const map = new Map<string, AdminPrompt>();
    for (const prompt of payload?.prompts ?? []) map.set(prompt.id, prompt);
    return map;
  }, [payload]);

  const selectedPrompt = useMemo(() => {
    if (selectedTrigger?.prompt_id && promptById.has(selectedTrigger.prompt_id)) {
      return promptById.get(selectedTrigger.prompt_id) ?? null;
    }
    return payload?.prompts.find((prompt) => prompt.id === selectedPromptId) ?? null;
  }, [payload, promptById, selectedPromptId, selectedTrigger]);

  useEffect(() => {
    const count = selectedTrigger?.condition?.count;
    setCountDraft(typeof count === "number" ? String(count) : "");
  }, [selectedTrigger]);

  const saveSelectedTriggerCount = useCallback(async () => {
    if (!selectedTrigger) return;
    const count = Number.parseInt(countDraft, 10);
    if (!Number.isFinite(count) || count < 1) {
      setError("触发轮数必须是大于等于 1 的整数");
      return;
    }
    setSavingTrigger(true);
    try {
      await updateAdminTrigger(token, {
        source: selectedTrigger.source,
        id: selectedTrigger.id,
        count,
      });
      await load();
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSavingTrigger(false);
    }
  }, [countDraft, load, selectedTrigger, token]);

  const activeCount = payload?.subagent_statuses.filter((s) => s.phase === "started").length ?? 0;
  const enabledCount = payload?.triggers.filter((t) => t.enabled).length ?? 0;
  const promptCount = payload?.prompts.length ?? 0;
  const activityCount = payload?.recent_activity.length ?? 0;
  const subagentRuns = payload?.subagent_runs ?? [];
  const processorRuns = payload?.processor_runs ?? [];
  const triggerDecisions = payload?.trigger_decisions ?? [];
  const wikiSyncRuns = payload?.wiki_sync_runs ?? [];
  const costSummary = payload?.cost_summary;
  const capabilitySubagents = Object.keys(payload?.capabilities?.subagents ?? {});
  const capabilityModes = Object.keys(payload?.capabilities?.modes ?? {});
  const selectedRegistrySubagent = selectedTrigger?.subagent
    ? payload?.capabilities?.subagents?.[selectedTrigger.subagent]
    : undefined;
  const selectedRegistryProcessor = selectedTrigger?.processor
    ? payload?.capabilities?.processors?.[selectedTrigger.processor]
    : undefined;

  const runModes = useMemo(() => {
    const values = new Set<string>();
    for (const run of subagentRuns) values.add(runMode(run));
    for (const run of processorRuns) values.add(runMode(run));
    for (const decision of triggerDecisions) values.add(runMode(decision));
    values.delete("unknown");
    return ["all", ...Array.from(values).sort()];
  }, [processorRuns, subagentRuns, triggerDecisions]);

  const visibleSubagentRuns = useMemo(() => {
    if (runModeFilter === "all") return subagentRuns;
    return subagentRuns.filter((run) => runMode(run) === runModeFilter);
  }, [runModeFilter, subagentRuns]);

  const visibleProcessorRuns = useMemo(() => {
    if (runModeFilter === "all") return processorRuns;
    return processorRuns.filter((run) => runMode(run) === runModeFilter);
  }, [processorRuns, runModeFilter]);

  const visibleTriggerDecisions = useMemo(() => {
    if (runModeFilter === "all") return triggerDecisions;
    return triggerDecisions.filter((decision) => runMode(decision) === runModeFilter);
  }, [runModeFilter, triggerDecisions]);

  const selectedRun = useMemo(
    () => visibleSubagentRuns.find((run) => runKey(run) === selectedRunKey) ?? visibleSubagentRuns[0] ?? null,
    [selectedRunKey, visibleSubagentRuns],
  );

  useEffect(() => {
    setSelectedRunKey((current) => {
      if (current && visibleSubagentRuns.some((run) => runKey(run) === current)) return current;
      return visibleSubagentRuns[0] ? runKey(visibleSubagentRuns[0]) : null;
    });
  }, [visibleSubagentRuns]);

  const selectedProcessorRun = useMemo(
    () => visibleProcessorRuns.find((run) => processorRunKey(run) === selectedProcessorRunKey) ?? visibleProcessorRuns[0] ?? null,
    [selectedProcessorRunKey, visibleProcessorRuns],
  );

  useEffect(() => {
    setSelectedProcessorRunKey((current) => {
      if (current && visibleProcessorRuns.some((run) => processorRunKey(run) === current)) return current;
      return visibleProcessorRuns[0] ? processorRunKey(visibleProcessorRuns[0]) : null;
    });
  }, [visibleProcessorRuns]);

  const selectedDecision = useMemo(
    () => visibleTriggerDecisions.find((decision, index) => decisionKey(decision, index) === selectedDecisionKey) ?? visibleTriggerDecisions[0] ?? null,
    [selectedDecisionKey, visibleTriggerDecisions],
  );

  useEffect(() => {
    setSelectedDecisionKey((current) => {
      if (current && visibleTriggerDecisions.some((decision, index) => decisionKey(decision, index) === current)) return current;
      return visibleTriggerDecisions[0] ? decisionKey(visibleTriggerDecisions[0], 0) : null;
    });
  }, [visibleTriggerDecisions]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="flex shrink-0 items-center justify-between border-b px-5 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBackToChat} className="h-8 w-8">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold">监控后台</h1>
            <p className="truncate text-xs text-muted-foreground">
              subagent 触发规则、prompt、工具调用和最近执行痕迹
            </p>
          </div>
        </div>
        <Button onClick={load} disabled={loading} size="sm" variant="outline" className="gap-2">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          刷新
        </Button>
      </header>

      {error ? (
        <div className="m-5 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      <div className="grid shrink-0 grid-cols-2 gap-3 px-5 py-4 lg:grid-cols-7">
        <Metric icon={Settings2} label="启用触发器" value={enabledCount} />
        <Metric icon={FileText} label="Prompt 文件" value={promptCount} />
        <Metric icon={Bot} label="运行中 subagent" value={activeCount} />
        <Metric icon={Cpu} label="Processor 调用" value={processorRuns.length} />
        <Metric icon={Database} label="Registry" value={`${capabilityModes.length}/${capabilitySubagents.length}`} />
        <Metric icon={Activity} label="触发决策" value={triggerDecisions.length} />
        <Metric icon={DollarSign} label="估算花费" value={formatUsd(costSummary?.estimated_usd)} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto px-5 pb-5 xl:grid-cols-[420px_minmax(0,1fr)] xl:overflow-hidden">
        <section className="flex min-h-0 flex-col overflow-hidden rounded-lg border bg-card">
          <div className="flex shrink-0 items-center justify-between border-b px-3 py-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <Clock3 className="h-4 w-4" />
              触发规则
            </div>
            <select
              value={modeFilter}
              onChange={(event) => setModeFilter(event.target.value)}
              className="h-8 rounded-md border bg-background px-2 text-xs"
            >
              {modes.map((mode) => (
                <option key={mode} value={mode}>{mode}</option>
              ))}
            </select>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading && !payload ? (
              <div className="flex h-32 items-center justify-center text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
              </div>
            ) : null}
            {filteredTriggers.map((trigger) => (
              <button
                key={`${trigger.source}:${trigger.id}`}
                onClick={() => {
                  setSelectedTriggerKey(triggerKey(trigger));
                  if (trigger.prompt_id) setSelectedPromptId(trigger.prompt_id);
                }}
                className={cn(
                  "mb-2 w-full rounded-md border p-3 text-left transition-colors",
                  selectedTrigger ? triggerKey(selectedTrigger) === triggerKey(trigger) : false
                    ? "border-primary/50 bg-primary/5"
                    : "border-border/60 hover:bg-muted/50",
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{trigger.name ?? trigger.id}</p>
                    <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{trigger.source}</p>
                  </div>
                  <span className={cn(
                    "rounded px-1.5 py-0.5 text-[10px] font-medium",
                    trigger.enabled ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground",
                  )}>
                    {trigger.enabled ? "enabled" : "off"}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                  <span className="rounded bg-muted px-1.5 py-0.5">{trigger.mode}</span>
                  <span className="rounded bg-muted px-1.5 py-0.5">{triggerSchedule(trigger)}</span>
                  {trigger.subagent ? <span className="rounded bg-muted px-1.5 py-0.5">{trigger.subagent}</span> : null}
                  {trigger.execution_mode ? <span className="rounded bg-muted px-1.5 py-0.5">{trigger.execution_mode}</span> : null}
                  {trigger.processor ? <span className="rounded bg-muted px-1.5 py-0.5">{trigger.processor}</span> : null}
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="grid min-h-0 grid-rows-[minmax(260px,0.95fr)_minmax(280px,0.85fr)] gap-4 overflow-visible xl:overflow-hidden">
          <div className="grid min-h-0 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[minmax(320px,0.8fr)_minmax(360px,1fr)]">
            <Panel title="调用详情" icon={Bot}>
              {selectedTrigger ? (
                <div className="space-y-3 text-sm">
                  <KeyValue label="Subagent" value={selectedTrigger.subagent || "-"} />
                  <KeyValue label="Processor" value={selectedTrigger.processor || "-"} />
                  <KeyValue label="Execution Mode" value={selectedTrigger.execution_mode || "-"} />
                  <KeyValue label="Agentic" value={selectedTrigger.agentic ? "true" : "false"} />
                  <KeyValue label="Tools" value={formatTools(selectedTrigger.tools)} />
                  <KeyValue label="Model" value={selectedTrigger.model || "default"} />
                  <KeyValue label="Prompt" value={selectedTrigger.prompt_file || "-"} />
                  <KeyValue label="Depends On" value={selectedTrigger.depends_on || "-"} />
                  <KeyValue label="Source" value={selectedTrigger.source} />
                  <div>
                    <p className="mb-1 text-xs font-medium text-muted-foreground">Registry</p>
                    <pre className="max-h-28 overflow-auto rounded-md bg-muted p-2 text-[11px]">
                      {formatJson(selectedRegistrySubagent ?? selectedRegistryProcessor ?? {
                        warning: selectedTrigger.subagent || selectedTrigger.processor
                          ? "这个 target 还没有登记在 config/capabilities.yaml"
                          : "这个 trigger 没有关联 subagent 或 processor",
                      })}
                    </pre>
                  </div>
                  {selectedTrigger.processor ? (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">Processor IO</p>
                      <pre className="max-h-32 overflow-auto rounded-md bg-muted p-2 text-[11px]">
                        {formatJson({
                          input_path: selectedTrigger.input_path,
                          input_paths: selectedTrigger.input_paths,
                          output_path: selectedTrigger.output_path,
                          batch_size: selectedTrigger.batch_size,
                          execution_mode: selectedTrigger.execution_mode,
                          tools: selectedTrigger.tools,
                        })}
                      </pre>
                    </div>
                  ) : null}
                  {selectedTrigger.condition?.kind === "turn_count" ? (
                    <div>
                      <p className="mb-1 text-xs font-medium text-muted-foreground">触发轮数</p>
                      <div className="flex gap-2">
                        <input
                          type="number"
                          min={1}
                          step={1}
                          value={countDraft}
                          onChange={(event) => setCountDraft(event.target.value)}
                          className="h-8 w-24 rounded-md border bg-background px-2 text-sm"
                        />
                        <Button size="sm" onClick={saveSelectedTriggerCount} disabled={savingTrigger}>
                          {savingTrigger ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                          保存
                        </Button>
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        保存后下一次用户回复会热加载配置；测试时可以改成 1。
                      </p>
                    </div>
                  ) : null}
                  <div>
                    <p className="mb-1 text-xs font-medium text-muted-foreground">Condition</p>
                    <pre className="max-h-32 overflow-auto rounded-md bg-muted p-2 text-[11px]">{formatJson(selectedTrigger.condition)}</pre>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium text-muted-foreground">Task Template</p>
                    <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded-md bg-muted p-2 text-[11px]">
                      {selectedTrigger.task_template || "-"}
                    </pre>
                  </div>
                </div>
              ) : (
                <EmptyText text="没有可用触发规则" />
              )}
            </Panel>

            <Panel title="Prompt 预览" icon={FileText}>
              {selectedPrompt ? (
                <div className="flex h-full min-h-0 flex-col gap-2">
                  <div className="shrink-0">
                    <p className="truncate text-sm font-medium">{selectedPrompt.path}</p>
                    {selectedPrompt.truncated ? (
                      <p className="text-xs text-amber-600">内容已截断显示</p>
                    ) : null}
                  </div>
                  <textarea
                    readOnly
                    value={selectedPrompt.content || selectedPrompt.error || ""}
                    className="min-h-0 flex-1 resize-none rounded-md border bg-muted/40 p-3 font-mono text-[11px] leading-5 outline-none"
                  />
                </div>
              ) : (
                <EmptyText text="选择一个触发规则查看 prompt" />
              )}
            </Panel>
          </div>

          <div className="grid min-h-0 grid-cols-1 gap-4 overflow-y-auto pr-1 lg:grid-cols-2 2xl:grid-cols-4">
            <div className="col-span-full flex shrink-0 items-center justify-between gap-3 rounded-lg border bg-card px-3 py-2 text-xs">
              <span className="font-medium">运行记录过滤</span>
              <select
                value={runModeFilter}
                onChange={(event) => setRunModeFilter(event.target.value)}
                className="h-8 rounded-md border bg-background px-2 text-xs"
                aria-label="Filter monitor runs by mode"
              >
                {runModes.map((mode) => (
                  <option key={mode} value={mode}>{mode}</option>
                ))}
              </select>
            </div>

            <Panel title="Subagent 调用列表" icon={Bot}>
              <div className="h-full overflow-y-auto pr-1">
                {visibleSubagentRuns.length === 0 ? <EmptyText text="还没有持久化的 subagent 回复；新运行的 subagent 会写入这里" /> : null}
                {visibleSubagentRuns.map((run) => (
                  <button
                    key={runKey(run)}
                    onClick={() => setSelectedRunKey(runKey(run))}
                    className={cn(
                      "mb-2 w-full rounded-md border p-2 text-left text-xs transition-colors",
                      selectedRun && runKey(selectedRun) === runKey(run)
                        ? "border-primary/50 bg-primary/5"
                        : "border-border/70 hover:bg-muted/50",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{run.label}</span>
                      <span className={cn(
                        "shrink-0 rounded px-1.5 py-0.5",
                        run.error || run.stop_reason === "tool_error" || run.stop_reason === "error"
                          ? "bg-red-500/10 text-red-600"
                          : "bg-emerald-500/10 text-emerald-600",
                      )}>{run.stop_reason || run.phase}</span>
                    </div>
                    <p className="mt-1 truncate text-muted-foreground">
                      {shortTime(run.timestamp)} · {run.model || "default model"}
                    </p>
                    <p className="mt-1 truncate text-muted-foreground">
                      {runMode(run)} · {run.subagent || run.label} · {run.execution_mode || "runtime"} · tools {(run.tools ?? []).length}
                    </p>
                    <p className="mt-1 line-clamp-2 whitespace-pre-wrap text-muted-foreground">
                      {run.error || run.result || "-"}
                    </p>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="Processor 调用列表" icon={Cpu}>
              <div className="h-full overflow-y-auto pr-1">
                {visibleProcessorRuns.length === 0 ? <EmptyText text="还没有 processor run log；触发后会写入 processor_runs.jsonl" /> : null}
                {visibleProcessorRuns.map((run) => (
                  <button
                    key={processorRunKey(run)}
                    onClick={() => setSelectedProcessorRunKey(processorRunKey(run))}
                    className={cn(
                      "mb-2 w-full rounded-md border p-2 text-left text-xs transition-colors",
                      selectedProcessorRun && processorRunKey(selectedProcessorRun) === processorRunKey(run)
                        ? "border-primary/50 bg-primary/5"
                        : "border-border/70 hover:bg-muted/50",
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{run.processor}</span>
                      <span className={cn(
                        "shrink-0 rounded px-1.5 py-0.5",
                        run.status === "error"
                          ? "bg-red-500/10 text-red-600"
                          : run.status === "completed"
                            ? "bg-emerald-500/10 text-emerald-600"
                            : "bg-muted text-muted-foreground",
                      )}>{run.status}</span>
                    </div>
                    <p className="mt-1 truncate text-muted-foreground">
                      {shortTime(run.timestamp)} · {run.model || "default model"}
                    </p>
                    <p className="mt-1 truncate text-muted-foreground">
                      {runMode(run)} · {run.subagent ? `${run.subagent} · ${run.execution_mode || "api"}` : "processor-only"}
                    </p>
                    <p className="mt-1 truncate text-muted-foreground">
                      in {run.input_rows ?? 0} · out {run.output_rows ?? 0} · {run.duration_ms ?? 0}ms
                    </p>
                    {processorPreviewSummary(run) ? (
                      <p className="mt-1 truncate text-muted-foreground">{processorPreviewSummary(run)}</p>
                    ) : null}
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="触发决策" icon={Clock3}>
              <div className="flex h-full min-h-0 flex-col gap-2">
                <div className="min-h-0 flex-1 overflow-y-auto pr-1">
                  {visibleTriggerDecisions.length === 0 ? <EmptyText text="还没有触发决策记录；用户回复后会写入这里" /> : null}
                  {visibleTriggerDecisions.map((decision, index) => {
                    const key = decisionKey(decision, index);
                    return (
                      <button
                        key={key}
                        onClick={() => setSelectedDecisionKey(key)}
                        className={cn(
                          "mb-2 w-full rounded-md border p-2 text-left text-xs transition-colors",
                          selectedDecision && decisionKey(selectedDecision, visibleTriggerDecisions.indexOf(selectedDecision)) === key
                            ? "border-primary/50 bg-primary/5"
                            : "border-border/70 hover:bg-muted/50",
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">{decision.name || decision.trigger_id}</span>
                          <span className={cn(
                            "shrink-0 rounded px-1.5 py-0.5",
                            decision.decision === "spawned" || decision.decision === "eligible"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : decision.decision === "failed"
                                ? "bg-red-500/10 text-red-600"
                                : "bg-muted text-muted-foreground",
                          )}>{decision.decision}</span>
                        </div>
                        <p className="mt-1 truncate text-muted-foreground">
                          {shortTime(decision.timestamp)} · {runMode(decision)} · {decision.reason}
                        </p>
                        <p className="mt-1 truncate text-muted-foreground">
                          {decision.subagent || "no subagent"}{typeof decision.turn_count === "number" ? ` · turn ${decision.turn_count}` : ""}
                        </p>
                      </button>
                    );
                  })}
                </div>
                {selectedDecision ? (
                  <div className="shrink-0 rounded-md border bg-muted/30 p-2 text-[11px]">
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{selectedDecision.reason}</span>
                      <span className="shrink-0 rounded bg-background px-1.5 py-0.5 text-muted-foreground">
                        {selectedDecision.kind || "-"}
                      </span>
                    </div>
                    <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded bg-background p-2">
                      {formatJson({
                        details: selectedDecision.details,
                        cursor_before: selectedDecision.cursor_before,
                        cursor_after: selectedDecision.cursor_after,
                        task_id: selectedDecision.subagent_task_id,
                      })}
                    </pre>
                  </div>
                ) : null}
              </div>
            </Panel>

            <Panel title="Wiki Sync" icon={Database}>
              <div className="h-full overflow-y-auto">
                {wikiSyncRuns.length === 0 ? <EmptyText text="还没有 wiki sync 记录；用户回复后会写入这里" /> : null}
                {wikiSyncRuns.map((run, index) => (
                  <div key={`${run.timestamp}:${run.session_id}:${index}`} className="mb-2 rounded-md border p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{run.session_id}</span>
                      <span className={cn(
                        "rounded px-1.5 py-0.5",
                        run.status === "error"
                          ? "bg-red-500/10 text-red-600"
                          : "bg-emerald-500/10 text-emerald-600",
                      )}>{run.status}</span>
                    </div>
                    <p className="mt-1 text-muted-foreground">{shortTime(run.timestamp)}</p>
                    <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
                      <span>messages {run.messages ?? 0}</span>
                      <span>candidates {run.candidates ?? 0}</span>
                      <span>applied {run.applied ?? 0}</span>
                      <span>lint {run.lint_findings ?? 0}</span>
                    </div>
                    {run.applied_slugs?.length ? (
                      <p className="mt-1 line-clamp-2 break-all text-muted-foreground">
                        {run.applied_slugs.join(", ")}
                      </p>
                    ) : null}
                    {run.error ? <p className="mt-1 text-red-600">{run.error}</p> : null}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Token / 花费" icon={DollarSign}>
              <div className="h-full overflow-y-auto text-xs">
                {!costSummary ? <EmptyText text="暂无 token usage 数据" /> : null}
                {costSummary ? (
                  <div className="space-y-3">
                    <div className="rounded-md border p-2">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">LLM 调用估算</span>
                        <span className="font-semibold">{formatUsd(costSummary.estimated_usd)}</span>
                      </div>
                      <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
                        <span>prompt {costSummary.prompt_tokens}</span>
                        <span>cached {costSummary.cached_tokens}</span>
                        <span>completion {costSummary.completion_tokens}</span>
                        <span>{costSummary.currency}</span>
                      </div>
                    </div>
                    {costSummary.models.map((row) => (
                      <div key={row.model} className="rounded-md border p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">{row.model}</span>
                          <span>{formatUsd(row.estimated_usd)}</span>
                        </div>
                        <div className="mt-1 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
                          <span>runs {row.runs}</span>
                          <span>known {row.known_price ? "yes" : "no"}</span>
                          <span>in {row.prompt_tokens}</span>
                          <span>out {row.completion_tokens}</span>
                        </div>
                      </div>
                    ))}
                    {costSummary.last_turn?.prompt_tokens ? (
                      <div className="rounded-md border p-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">最近主回复</span>
                          <span>{formatUsd(costSummary.last_turn.estimated_usd)}</span>
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          {costSummary.last_turn.normalized_model || costSummary.last_turn.model}
                        </p>
                      </div>
                    ) : null}
                    <p className="text-[10px] leading-4 text-muted-foreground">
                      {costSummary.note || "本地估算，官方账单为准。"}
                    </p>
                  </div>
                ) : null}
              </div>
            </Panel>

            <Panel title="Processor 详情" icon={Cpu}>
              <div className="h-full overflow-y-auto">
                {!selectedProcessorRun ? <EmptyText text="选择一次 processor 调用查看详情" /> : null}
                {selectedProcessorRun ? (
                  <div className="space-y-3 text-xs">
                    <div className="rounded-md border p-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{selectedProcessorRun.processor}</span>
                        <span className={cn(
                          "rounded px-1.5 py-0.5",
                          selectedProcessorRun.status === "error"
                            ? "bg-red-500/10 text-red-600"
                            : selectedProcessorRun.status === "completed"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : "bg-muted text-muted-foreground",
                        )}>{selectedProcessorRun.status}</span>
                      </div>
                      <p className="mt-1 text-muted-foreground">
                        {shortTime(selectedProcessorRun.timestamp)} · {selectedProcessorRun.model || "default model"}
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        {runMode(selectedProcessorRun)} · {selectedProcessorRun.subagent || "processor-only"} · {selectedProcessorRun.execution_mode || "-"} · tools {formatTools(selectedProcessorRun.tools)}
                      </p>
                      <div className="mt-2 grid grid-cols-2 gap-1 text-[11px] text-muted-foreground">
                        <span>input {selectedProcessorRun.input_rows ?? 0}</span>
                        <span>output {selectedProcessorRun.output_rows ?? 0}</span>
                        <span>{selectedProcessorRun.duration_ms ?? 0}ms</span>
                        <span>{selectedProcessorRun.cursor_kind || "-"}</span>
                      </div>
                      {processorPreviewSummary(selectedProcessorRun) ? (
                        <p className="mt-2 rounded bg-muted px-2 py-1 text-[11px] text-muted-foreground">
                          {processorPreviewSummary(selectedProcessorRun)}
                        </p>
                      ) : null}
                      {selectedProcessorRun.error ? <p className="mt-2 text-red-600">{selectedProcessorRun.error}</p> : null}
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">Input / Cursor</p>
                      <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">
                        {formatJson({
                          input_paths: selectedProcessorRun.input_paths,
                          output_path: selectedProcessorRun.output_path,
                          subagent: selectedProcessorRun.subagent,
                          execution_mode: selectedProcessorRun.execution_mode,
                          tools: selectedProcessorRun.tools,
                          cursor_before: selectedProcessorRun.cursor_before,
                          cursor_after: selectedProcessorRun.cursor_after,
                        })}
                      </pre>
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">本次输出增量</p>
                      {(selectedProcessorRun.output_preview ?? []).length === 0 ? (
                        <p className="text-muted-foreground">这次没有解析出的新增 artifact</p>
                      ) : null}
                      {(selectedProcessorRun.output_preview ?? []).map((item, index) => (
                        <pre key={index} className="mb-2 max-h-40 overflow-auto whitespace-pre-wrap rounded border bg-muted p-2">
                          {formatJson(item)}
                        </pre>
                      ))}
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">Usage</p>
                      <pre className="max-h-28 overflow-auto rounded bg-muted p-2">
                        {formatJson(selectedProcessorRun.usage)}
                      </pre>
                    </div>
                  </div>
                ) : null}
              </div>
            </Panel>

            <Panel title="本次调用详情" icon={Activity}>
              <div className="h-full overflow-y-auto">
                {!selectedRun ? <EmptyText text="选择一次 subagent 调用查看详情" /> : null}
                {selectedRun ? (
                  <div className="space-y-3 text-xs">
                    <div className="rounded-md border p-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium">{selectedRun.label}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{selectedRun.task_id}</span>
                      </div>
                      <p className="mt-1 text-muted-foreground">{shortTime(selectedRun.timestamp)} · {selectedRun.model || "default model"}</p>
                      <p className="mt-1 text-muted-foreground">
                        {runMode(selectedRun)} · {selectedRun.subagent || selectedRun.label} · {selectedRun.execution_mode || "-"} · tools {formatTools(selectedRun.tools)}
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        input {selectedRun.input_rows ?? 0} · output {selectedRun.output_rows ?? 0} · {selectedRun.duration_ms ?? 0}ms
                      </p>
                      {selectedRun.error ? <p className="mt-2 text-red-600">{selectedRun.error}</p> : null}
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">Subagent 回复</p>
                      <pre className="max-h-52 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{selectedRun.result || "-"}</pre>
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">写入文件增量</p>
                      {(selectedRun.artifacts ?? []).length === 0 ? <p className="text-muted-foreground">没有捕获到写入文件</p> : null}
                      {(selectedRun.artifacts ?? []).map((artifact) => (
                        <div key={artifact.path} className="mb-2 rounded-md border p-2">
                          <div className="mb-1 flex items-center justify-between gap-2">
                            <span className="truncate font-medium">{artifact.path}</span>
                            <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{artifact.status}</span>
                          </div>
                          {artifact.error ? <p className="text-red-600">{artifact.error}</p> : null}
                          <pre className="max-h-44 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">
                            {artifact.delta || artifact.content || "-"}
                          </pre>
                          {artifact.truncated ? <p className="mt-1 text-[11px] text-amber-600">内容已截断显示</p> : null}
                        </div>
                      ))}
                    </div>
                    <div>
                      <p className="mb-1 font-medium text-muted-foreground">Task</p>
                      <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-muted p-2">{selectedRun.task || "-"}</pre>
                    </div>
                  </div>
                ) : null}
              </div>
            </Panel>

            <Panel title="最近工具 / subagent 活动" icon={Wrench}>
              <div className="h-full overflow-y-auto">
                {(payload?.recent_activity ?? []).length === 0 ? <EmptyText text={`最近 session 里没有可展示活动；已有 ${activityCount} 条`} /> : null}
                {(payload?.recent_activity ?? []).map((item, index) => (
                  <div key={`${item.session_id}:${item.timestamp}:${index}`} className="mb-2 rounded-md border p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{item.label}</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{item.kind}</span>
                    </div>
                    <p className="mt-1 text-muted-foreground">{shortTime(item.timestamp)} · {item.session_id}</p>
                    {item.detail ? <p className="mt-1 line-clamp-3 whitespace-pre-wrap">{item.detail}</p> : null}
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number | string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Icon className="h-3.5 w-3.5" />
        {label}
      </div>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Panel({ title, icon: Icon, children }: { title: string; icon: LucideIcon; children: ReactNode }) {
  return (
    <div className="flex min-h-0 flex-col rounded-lg border bg-card">
      <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2 text-sm font-medium">
        <Icon className="h-4 w-4" />
        {title}
      </div>
      <div className="min-h-0 flex-1 overflow-hidden p-3">{children}</div>
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="mt-0.5 break-all text-sm">{value}</p>
    </div>
  );
}

function EmptyText({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">{text}</div>;
}
