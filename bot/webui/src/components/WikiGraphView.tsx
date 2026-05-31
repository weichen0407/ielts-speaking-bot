import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceX,
  forceY,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { RotateCcw, ZoomIn, ZoomOut } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fetchWikiGraph, type WikiGraphNode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";

type GraphKind = WikiGraphNode["kind"];

interface GraphNode extends WikiGraphNode, SimulationNodeDatum {
  degree: number;
}

interface GraphLink extends SimulationLinkDatum<GraphNode> {
  source: string | GraphNode;
  target: string | GraphNode;
  kind: string;
}

interface GraphData {
  nodes: GraphNode[];
  links: GraphLink[];
}

interface Transform {
  x: number;
  y: number;
  k: number;
}

export interface WikiGraphViewProps {
  filterMode?: string;
  filterTopic?: string;
  filterType?: string;
  filterTags?: string;
  highlightedNodes?: Set<string>;
  onPageClick?: (slug: string) => void;
  onFilterClick?: (kind: string, value: string) => void;
  interactive?: boolean;
  className?: string;
}

const COLORS: Record<GraphKind, string> = {
  page: "#2563eb",
  topic: "#0f766e",
  entity: "#2563eb",
  concept: "#7c3aed",
};

const TYPE_COLORS: Record<string, string> = {
  source: "#64748b",
  entity: "#2563eb",
  concept: "#7c3aed",
  comparison: "#0891b2",
  question: "#ca8a04",
  synthesis: "#db2777",
  decision: "#dc2626",
  gap: "#ea580c",
  meta: "#475569",
};

function topicAnchors(nodes: GraphNode[], width: number, height: number): Map<string, { x: number; y: number }> {
  const topics = nodes.filter((node) => node.kind === "topic").sort((a, b) => a.id.localeCompare(b.id));
  const anchors = new Map<string, { x: number; y: number }>();
  if (topics.length === 0) return anchors;
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.max(80, Math.min(width, height) * 0.32);
  topics.forEach((topic, index) => {
    if (topics.length === 1) {
      anchors.set(topic.id, { x: cx, y: cy });
      return;
    }
    const angle = (Math.PI * 2 * index) / topics.length - Math.PI / 2;
    anchors.set(topic.id, {
      x: cx + Math.cos(angle) * radius,
      y: cy + Math.sin(angle) * radius,
    });
  });
  return anchors;
}

function topicAnchorForNode(
  node: GraphNode,
  links: GraphLink[],
  anchors: Map<string, { x: number; y: number }>,
): { x: number; y: number } | undefined {
  if (node.kind === "topic") return anchors.get(node.id);
  const link = links.find((edge) => {
    if (edge.kind !== "has_topic") return false;
    const source = typeof edge.source === "string" ? edge.source : edge.source.id;
    const target = typeof edge.target === "string" ? edge.target : edge.target.id;
    return source === node.id || target === node.id;
  });
  if (!link) return undefined;
  const source = typeof link.source === "string" ? link.source : link.source.id;
  const target = typeof link.target === "string" ? link.target : link.target.id;
  const topicId = source.startsWith("topic:") ? source : target.startsWith("topic:") ? target : "";
  return topicId ? anchors.get(topicId) : undefined;
}

function initialNodePosition(
  node: GraphNode,
  index: number,
  anchors: Map<string, { x: number; y: number }>,
  width: number,
  height: number,
  links: GraphLink[],
): { x: number; y: number } {
  const anchor = topicAnchorForNode(node, links, anchors);
  if (node.kind === "topic" && anchor) return anchor;
  const base = anchor ?? { x: width / 2, y: height / 2 };
  const angle = index * 2.399963229728653;
  const radius = node.kind === "page" ? 58 + (index % 4) * 18 : 34 + (index % 3) * 12;
  return {
    x: node.x ?? base.x + Math.cos(angle) * radius,
    y: node.y ?? base.y + Math.sin(angle) * radius,
  };
}

export function WikiGraphView({
  filterMode,
  filterTopic,
  filterType,
  filterTags,
  highlightedNodes,
  onPageClick,
  onFilterClick,
  interactive = true,
  className,
}: WikiGraphViewProps) {
  const { token } = useClient();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const simulationRef = useRef<Simulation<GraphNode, GraphLink> | null>(null);
  const graphRef = useRef<GraphData>({ nodes: [], links: [] });
  const transformRef = useRef<Transform>({ x: 0, y: 0, k: 1 });
  const draggingRef = useRef<GraphNode | null>(null);
  const panningRef = useRef<{ x: number; y: number; transform: Transform } | null>(null);
  const pointerDownRef = useRef<{ x: number; y: number; node: GraphNode | null } | null>(null);

  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [dimensions, setDimensions] = useState({ width: 640, height: 420 });
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      setDimensions({
        width: Math.max(320, rect.width),
        height: Math.max(260, rect.height),
      });
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const loadGraph = useCallback(async () => {
    if (!token) return;
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchWikiGraph(token, {
        mode: filterMode,
        topic: filterTopic,
        type: filterType,
        tags: filterTags,
      });
      const degree = new Map<string, number>();
      for (const edge of data.edges) {
        degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
        degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
      }
      setGraphData({
        nodes: data.nodes.map((node) => ({
          ...node,
          degree: degree.get(node.id) ?? 0,
        })),
        links: data.edges.map((edge) => ({ ...edge })),
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setIsLoading(false);
    }
  }, [filterMode, filterTags, filterTopic, filterType, token]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  const getNodeColor = useCallback((node: GraphNode): string => {
    if (highlightedNodes?.has(node.id)) return "#f59e0b";
    if (node.kind === "page" && node.type) return TYPE_COLORS[node.type] ?? COLORS.page;
    return COLORS[node.kind] ?? "#64748b";
  }, [highlightedNodes]);

  const getNodeRadius = useCallback((node: GraphNode): number => {
    if (node.kind === "topic") return Math.min(34, 18 + Math.sqrt(Math.max(node.degree, node.size ?? 1)) * 3);
    if (node.kind === "entity") return Math.min(22, 9 + Math.sqrt(Math.max(node.degree, node.size ?? 1)) * 2.2);
    if (node.kind === "concept") return Math.min(20, 8 + Math.sqrt(Math.max(node.degree, node.size ?? 1)) * 2);
    return Math.min(18, 7 + Math.sqrt(Math.max(node.degree, node.size ?? 1)) * 1.8);
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(dimensions.width * ratio);
    canvas.height = Math.floor(dimensions.height * ratio);
    canvas.style.width = `${dimensions.width}px`;
    canvas.style.height = `${dimensions.height}px`;

    ctx.save();
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, dimensions.width, dimensions.height);
      ctx.fillStyle = "#f8fafc";
      ctx.fillRect(0, 0, dimensions.width, dimensions.height);

    const t = transformRef.current;
    ctx.translate(t.x, t.y);
    ctx.scale(t.k, t.k);

    for (const node of graphRef.current.nodes) {
      if (node.kind !== "topic" || typeof node.x !== "number") continue;
      const radius = getNodeRadius(node) + Math.min(90, 36 + node.degree * 8);
      ctx.beginPath();
      ctx.arc(node.x, node.y ?? 0, radius, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(15,118,110,0.055)";
      ctx.fill();
      ctx.strokeStyle = "rgba(15,118,110,0.16)";
      ctx.setLineDash([6 / t.k, 6 / t.k]);
      ctx.lineWidth = 1.2 / t.k;
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const link of graphRef.current.links) {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (typeof source.x !== "number" || typeof target.x !== "number") continue;
      ctx.beginPath();
      ctx.moveTo(source.x, source.y ?? 0);
      ctx.lineTo(target.x, target.y ?? 0);
      ctx.strokeStyle = link.kind === "link"
        ? "rgba(71,85,105,0.36)"
        : link.kind === "has_topic"
          ? "rgba(15,118,110,0.30)"
          : link.kind === "mentions_entity"
            ? "rgba(37,99,235,0.24)"
            : "rgba(124,58,237,0.22)";
      ctx.lineWidth = link.kind === "link" ? 1.5 / t.k : 1 / t.k;
      ctx.stroke();
    }

    for (const node of graphRef.current.nodes) {
      if (typeof node.x !== "number") continue;
      const x = node.x;
      const y = node.y ?? 0;
      const radius = getNodeRadius(node);
      const highlighted = highlightedNodes?.has(node.id);
      const hovered = hoveredNode?.id === node.id;
      const selected = selectedNode?.id === node.id;

      if (highlighted || hovered || selected) {
        ctx.beginPath();
        ctx.arc(x, y, radius + 5, 0, Math.PI * 2);
        ctx.strokeStyle = highlighted ? "#f59e0b" : selected ? "#111827" : "#94a3b8";
        ctx.lineWidth = 2 / t.k;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = getNodeColor(node);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.95)";
      ctx.lineWidth = 1.5 / t.k;
      ctx.stroke();

      if (node.kind !== "page" || t.k > 0.82 || highlighted || hovered || selected) {
        const label = node.label.length > 22 ? `${node.label.slice(0, 21)}...` : node.label;
        ctx.font = `${node.kind === "topic" ? "600 " : ""}${Math.max(10, 11 / Math.sqrt(t.k))}px system-ui, sans-serif`;
        ctx.fillStyle = "#0f172a";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, x, y + radius + 4);
      }
    }

    ctx.restore();
  }, [dimensions.height, dimensions.width, getNodeColor, getNodeRadius, highlightedNodes, hoveredNode, selectedNode]);

  useEffect(() => {
    graphRef.current = graphData;
    simulationRef.current?.stop();

    if (graphData.nodes.length === 0) {
      draw();
      return;
    }

    const topicPositions = topicAnchors(graphData.nodes, dimensions.width, dimensions.height);
    const nodes = graphData.nodes.map((node, index) => ({
      ...node,
      ...initialNodePosition(node, index, topicPositions, dimensions.width, dimensions.height, graphData.links),
    }));
    const links = graphData.links.map((link) => ({ ...link }));
    graphRef.current = { nodes, links };

    const simulation = forceSimulation<GraphNode>(nodes)
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(links)
          .id((node) => node.id)
          .distance((link) => link.kind === "has_topic" ? 118 : link.kind === "link" ? 92 : 72)
          .strength((link) => link.kind === "has_topic" ? 0.2 : link.kind === "link" ? 0.16 : 0.14),
      )
      .force("charge", forceManyBody<GraphNode>().strength((node) => node.kind === "topic" ? -360 : node.kind === "page" ? -80 : -55))
      .force("x", forceX<GraphNode>((node) => {
        if (node.kind === "topic") return topicPositions.get(node.id)?.x ?? dimensions.width / 2;
        const anchor = topicAnchorForNode(node, graphData.links, topicPositions);
        return anchor?.x ?? dimensions.width / 2;
      }).strength((node) => node.kind === "topic" ? 0.18 : 0.055))
      .force("y", forceY<GraphNode>((node) => {
        if (node.kind === "topic") return topicPositions.get(node.id)?.y ?? dimensions.height / 2;
        const anchor = topicAnchorForNode(node, graphData.links, topicPositions);
        return anchor?.y ?? dimensions.height / 2;
      }).strength((node) => node.kind === "topic" ? 0.18 : 0.055))
      .force("collide", forceCollide<GraphNode>().radius((node) => getNodeRadius(node) + (node.kind === "topic" ? 30 : 12)))
      .alpha(0.55)
      .alphaDecay(0.055)
      .velocityDecay(0.58)
      .on("tick", () => {
        graphRef.current = { nodes, links };
        draw();
      });

    simulationRef.current = simulation;
    return () => {
      simulation.stop();
    };
  }, [dimensions.height, dimensions.width, draw, getNodeRadius, graphData]);

  useEffect(() => {
    draw();
  }, [draw]);

  const pointToGraph = useCallback((clientX: number, clientY: number) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    const t = transformRef.current;
    return {
      x: ((clientX - (rect?.left ?? 0)) - t.x) / t.k,
      y: ((clientY - (rect?.top ?? 0)) - t.y) / t.k,
    };
  }, []);

  const findNode = useCallback((clientX: number, clientY: number): GraphNode | null => {
    const p = pointToGraph(clientX, clientY);
    for (let i = graphRef.current.nodes.length - 1; i >= 0; i -= 1) {
      const node = graphRef.current.nodes[i];
      if (typeof node.x !== "number" || typeof node.y !== "number") continue;
      const radius = getNodeRadius(node) + 7;
      const dx = p.x - node.x;
      const dy = p.y - node.y;
      if (dx * dx + dy * dy <= radius * radius) return node;
    }
    return null;
  }, [getNodeRadius, pointToGraph]);

  const handleNodeActivate = useCallback((node: GraphNode) => {
    setSelectedNode(node);
    if (node.kind === "page") {
      onPageClick?.(node.id);
      return;
    }
    const value = node.id.includes(":") ? node.id.slice(node.id.indexOf(":") + 1) : node.id;
    if (node.kind === "topic") {
      onFilterClick?.(node.kind, value);
    } else {
      setSelectedNode(node);
    }
  }, [onFilterClick, onPageClick]);

  const handleMouseDown = useCallback((event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!interactive) return;
    const node = findNode(event.clientX, event.clientY);
    pointerDownRef.current = { x: event.clientX, y: event.clientY, node };
    if (!node) {
      panningRef.current = {
        x: event.clientX,
        y: event.clientY,
        transform: { ...transformRef.current },
      };
      return;
    }
    draggingRef.current = node;
    node.fx = node.x;
    node.fy = node.y;
    simulationRef.current?.alphaTarget(0.04).restart();
  }, [findNode, interactive]);

  const handleMouseMove = useCallback((event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!interactive) return;
    const dragged = draggingRef.current;
    if (dragged) {
      const p = pointToGraph(event.clientX, event.clientY);
      dragged.fx = p.x;
      dragged.fy = p.y;
      draw();
      return;
    }
    const panning = panningRef.current;
    if (panning) {
      transformRef.current = {
        ...panning.transform,
        x: panning.transform.x + event.clientX - panning.x,
        y: panning.transform.y + event.clientY - panning.y,
      };
      draw();
      return;
    }
    setHoveredNode(findNode(event.clientX, event.clientY));
  }, [draw, findNode, interactive, pointToGraph]);

  const handleMouseUp = useCallback((event: React.MouseEvent<HTMLCanvasElement>) => {
    if (!interactive) return;
    const dragged = draggingRef.current;
    if (dragged) {
      dragged.fx = dragged.x;
      dragged.fy = dragged.y;
      draggingRef.current = null;
      simulationRef.current?.alphaTarget(0);
    }
    panningRef.current = null;
    const down = pointerDownRef.current;
    pointerDownRef.current = null;
    const moved = down ? Math.hypot(event.clientX - down.x, event.clientY - down.y) : 999;
    const clicked = findNode(event.clientX, event.clientY);
    if (down?.node && clicked?.id === down.node.id && moved < 5) {
      handleNodeActivate(clicked);
    }
  }, [findNode, handleNodeActivate, interactive]);

  const handleWheel = useCallback((event: React.WheelEvent<HTMLCanvasElement>) => {
    if (!interactive) return;
    event.preventDefault();
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const t = transformRef.current;
    const scale = event.deltaY < 0 ? 1.12 : 0.9;
    const nextK = Math.max(0.35, Math.min(3.2, t.k * scale));
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    transformRef.current = {
      k: nextK,
      x: px - ((px - t.x) / t.k) * nextK,
      y: py - ((py - t.y) / t.k) * nextK,
    };
    draw();
  }, [draw, interactive]);

  const zoomBy = useCallback((factor: number) => {
    const t = transformRef.current;
    const nextK = Math.max(0.35, Math.min(3.2, t.k * factor));
    const cx = dimensions.width / 2;
    const cy = dimensions.height / 2;
    transformRef.current = {
      k: nextK,
      x: cx - ((cx - t.x) / t.k) * nextK,
      y: cy - ((cy - t.y) / t.k) * nextK,
    };
    draw();
  }, [dimensions.height, dimensions.width, draw]);

  const resetView = useCallback(() => {
    transformRef.current = { x: 0, y: 0, k: 1 };
    for (const node of graphRef.current.nodes) {
      node.fx = null;
      node.fy = null;
    }
    simulationRef.current?.alpha(0.25).restart();
    draw();
  }, [draw]);

  const legend = useMemo(() => [
    ["topic cluster", COLORS.topic],
    ["entity", COLORS.entity],
    ["concept", COLORS.concept],
    ["decision page", TYPE_COLORS.decision],
    ["gap page", TYPE_COLORS.gap],
  ], []);

  return (
    <div ref={containerRef} className={cn("relative min-h-[280px] overflow-hidden rounded-md bg-slate-50", className)}>
      {error ? (
        <div className="absolute inset-0 z-20 flex items-center justify-center p-4 text-center text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {interactive ? (
        <div className="absolute right-2 top-2 z-10 flex flex-col gap-1">
          <Button variant="outline" size="icon" className="h-7 w-7 bg-background/90" onClick={() => zoomBy(1.25)} title="Zoom in">
            <ZoomIn className="h-3 w-3" />
          </Button>
          <Button variant="outline" size="icon" className="h-7 w-7 bg-background/90" onClick={() => zoomBy(0.8)} title="Zoom out">
            <ZoomOut className="h-3 w-3" />
          </Button>
          <Button variant="outline" size="icon" className="h-7 w-7 bg-background/90" onClick={resetView} title="Reset">
            <RotateCcw className="h-3 w-3" />
          </Button>
        </div>
      ) : null}

      <canvas
        ref={canvasRef}
        className={cn("block h-full w-full", hoveredNode ? "cursor-pointer" : "cursor-grab")}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => {
          setHoveredNode(null);
          draggingRef.current = null;
          panningRef.current = null;
        }}
        onMouseUp={handleMouseUp}
        onWheel={handleWheel}
      />

      {isLoading ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/45">
          <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      ) : null}

      {graphData.nodes.length === 0 && !isLoading ? (
        <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          暂无 wiki graph 数据
        </div>
      ) : null}

      <div className="absolute bottom-2 left-2 z-10 flex max-w-[70%] flex-wrap gap-1.5 rounded-md border bg-background/90 p-2 text-[10px] shadow-sm">
        {legend.map(([label, color]) => (
          <div key={label} className="flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-muted-foreground">{label}</span>
          </div>
        ))}
      </div>

      {selectedNode ? (
        <div className="absolute bottom-2 right-2 z-10 max-w-[240px] rounded-md border bg-background/95 p-2 text-xs shadow-sm">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium">{selectedNode.label}</span>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">{selectedNode.kind}</span>
          </div>
          {selectedNode.type ? <p className="mt-1 text-muted-foreground">type: {selectedNode.type}</p> : null}
          {selectedNode.mode ? <p className="text-muted-foreground">mode: {selectedNode.mode}</p> : null}
          {selectedNode.tags?.length ? <p className="mt-1 line-clamp-2 text-muted-foreground">tags: {selectedNode.tags.join(", ")}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
