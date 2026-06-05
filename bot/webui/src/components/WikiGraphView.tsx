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

type GraphKind = WikiGraphNode["kind"] | "root";
type GraphLayout = "overview" | "hierarchy";

interface GraphNode extends Omit<WikiGraphNode, "kind">, SimulationNodeDatum {
  kind: GraphKind;
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
  root: "#111827",
  page: "#2563eb",
  domain: "#0f172a",
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

function edgeColor(kind: string): string {
  if (kind === "root") return "rgba(17,24,39,0.26)";
  if (kind === "link") return "rgba(71,85,105,0.36)";
  if (kind === "has_domain") return "rgba(15,23,42,0.28)";
  if (kind === "has_topic" || kind === "contains_topic") return "rgba(15,118,110,0.30)";
  if (kind === "topic_entity" || kind === "mentions_entity") return "rgba(37,99,235,0.24)";
  if (kind === "has_subtype" || kind === "mentions_concept") return "rgba(124,58,237,0.22)";
  if (kind.startsWith("relation:")) return "rgba(219,39,119,0.32)";
  return "rgba(100,116,139,0.24)";
}

function topicAnchors(nodes: GraphNode[], width: number, height: number): Map<string, { x: number; y: number }> {
  const topics = nodes.filter((node) => node.kind === "domain" || node.kind === "topic").sort((a, b) => a.id.localeCompare(b.id));
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

function hierarchyLayer(node: GraphNode): number {
  if (node.kind === "root") return 0;
  if (node.kind === "domain") return 1;
  if (node.kind === "topic") return 2;
  if (node.kind === "entity" || node.kind === "concept") return 3;
  return 4;
}

function hierarchyTargets(nodes: GraphNode[], width: number, height: number): Map<string, { x: number; y: number }> {
  const byLayer = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const layer = hierarchyLayer(node);
    const items = byLayer.get(layer) ?? [];
    items.push(node);
    byLayer.set(layer, items);
  }

  const targets = new Map<string, { x: number; y: number }>();
  const maxLayer = Math.max(...Array.from(byLayer.keys()), 4);
  const top = 54;
  const bottom = 54;
  const usableHeight = Math.max(180, height - top - bottom);

  for (const [layer, layerNodes] of byLayer.entries()) {
    const sorted = [...layerNodes].sort((a, b) => a.label.localeCompare(b.label));
    const y = top + (usableHeight * layer) / Math.max(1, maxLayer);
    sorted.forEach((node, index) => {
      const x = (width * (index + 1)) / (sorted.length + 1);
      targets.set(node.id, { x, y });
    });
  }

  return targets;
}

function withHierarchyRoot(data: GraphData): GraphData {
  if (data.nodes.length === 0 || data.nodes.some((node) => node.kind === "root")) return data;

  const primaryChildren = data.nodes.filter((node) => node.kind === "domain");
  const fallbackChildren = primaryChildren.length > 0
    ? primaryChildren
    : data.nodes.filter((node) => node.kind === "topic");
  const rootTargets = fallbackChildren.length > 0
    ? fallbackChildren
    : data.nodes.filter((node) => node.kind === "page").slice(0, 8);

  const rootNode: GraphNode = {
    id: "__wiki_root__",
    label: "All Wiki",
    kind: "root",
    degree: rootTargets.length,
    size: 18,
    tags: [],
    topics: [],
  };

  return {
    nodes: [rootNode, ...data.nodes],
    links: [
      ...rootTargets.map((node) => ({
        source: rootNode.id,
        target: node.id,
        kind: "root",
      })),
      ...data.links,
    ],
  };
}

function topicAnchorForNode(
  node: GraphNode,
  links: GraphLink[],
  anchors: Map<string, { x: number; y: number }>,
): { x: number; y: number } | undefined {
  if (node.kind === "domain" || node.kind === "topic") return anchors.get(node.id);
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
  if ((node.kind === "domain" || node.kind === "topic") && anchor) return anchor;
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
  const hoveredNodeRef = useRef<GraphNode | null>(null);
  const selectedNodeRef = useRef<GraphNode | null>(null);
  const canvasSizeRef = useRef<{ width: number; height: number; ratio: number }>({ width: 0, height: 0, ratio: 0 });

  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [dimensions, setDimensions] = useState({ width: 640, height: 420 });
  const [layoutMode, setLayoutMode] = useState<GraphLayout>("hierarchy");
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
    if (node.kind === "root") return 30;
    if (node.kind === "domain") return Math.min(40, 22 + Math.sqrt(Math.max(node.degree, node.size ?? 1)) * 3);
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
    const nextCanvasWidth = Math.floor(dimensions.width * ratio);
    const nextCanvasHeight = Math.floor(dimensions.height * ratio);
    const currentSize = canvasSizeRef.current;
    if (currentSize.width !== nextCanvasWidth || currentSize.height !== nextCanvasHeight || currentSize.ratio !== ratio) {
      canvas.width = nextCanvasWidth;
      canvas.height = nextCanvasHeight;
      canvas.style.width = `${dimensions.width}px`;
      canvas.style.height = `${dimensions.height}px`;
      canvasSizeRef.current = { width: nextCanvasWidth, height: nextCanvasHeight, ratio };
    }

    ctx.save();
    ctx.scale(ratio, ratio);
    ctx.clearRect(0, 0, dimensions.width, dimensions.height);
    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(0, 0, dimensions.width, dimensions.height);

    const t = transformRef.current;
    const hoveredNode = hoveredNodeRef.current;
    const selectedNode = selectedNodeRef.current;
    ctx.translate(t.x, t.y);
    ctx.scale(t.k, t.k);

    for (const node of graphRef.current.nodes) {
      if ((node.kind !== "domain" && node.kind !== "topic") || typeof node.x !== "number") continue;
      const radius = getNodeRadius(node) + Math.min(90, 36 + node.degree * 8);
      ctx.beginPath();
      ctx.arc(node.x, node.y ?? 0, radius, 0, Math.PI * 2);
      ctx.fillStyle = node.kind === "domain" ? "rgba(15,23,42,0.045)" : "rgba(15,118,110,0.055)";
      ctx.fill();
      ctx.strokeStyle = node.kind === "domain" ? "rgba(15,23,42,0.14)" : "rgba(15,118,110,0.16)";
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
      ctx.strokeStyle = edgeColor(link.kind);
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
        ctx.font = `${node.kind === "domain" || node.kind === "topic" ? "600 " : ""}${Math.max(10, 11 / Math.sqrt(t.k))}px system-ui, sans-serif`;
        ctx.fillStyle = "#0f172a";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(label, x, y + radius + 4);
      }
    }

    ctx.restore();
  }, [dimensions.height, dimensions.width, getNodeColor, getNodeRadius, highlightedNodes]);

  useEffect(() => {
    selectedNodeRef.current = selectedNode;
    draw();
  }, [draw, selectedNode]);

  useEffect(() => {
    const currentGraphData = layoutMode === "hierarchy" ? withHierarchyRoot(graphData) : graphData;
    graphRef.current = currentGraphData;
    simulationRef.current?.stop();

    if (currentGraphData.nodes.length === 0) {
      draw();
      return;
    }

    const topicPositions = topicAnchors(currentGraphData.nodes, dimensions.width, dimensions.height);
    const layerPositions = layoutMode === "hierarchy"
      ? hierarchyTargets(currentGraphData.nodes, dimensions.width, dimensions.height)
      : new Map<string, { x: number; y: number }>();
    const nodes = currentGraphData.nodes.map((node, index) => ({
      ...node,
      ...(layerPositions.get(node.id)
        ?? initialNodePosition(node, index, topicPositions, dimensions.width, dimensions.height, currentGraphData.links)),
    }));
    const links = currentGraphData.links.map((link) => ({ ...link }));
    graphRef.current = { nodes, links };

    const simulation = forceSimulation<GraphNode>(nodes)
      .force(
        "link",
        forceLink<GraphNode, GraphLink>(links)
          .id((node) => node.id)
          .distance((link) => {
            if (layoutMode === "hierarchy") return link.kind === "root" ? 120 : 82;
            return link.kind === "has_domain" ? 132 : link.kind === "has_topic" || link.kind === "contains_topic" ? 118 : link.kind === "link" ? 92 : 72;
          })
          .strength((link) => {
            if (layoutMode === "hierarchy") return link.kind === "root" ? 0.26 : 0.12;
            return link.kind === "has_domain" ? 0.22 : link.kind === "has_topic" || link.kind === "contains_topic" ? 0.2 : link.kind === "link" ? 0.16 : 0.14;
          }),
      )
      .force("charge", forceManyBody<GraphNode>().strength((node) => {
        if (layoutMode === "hierarchy") return node.kind === "root" ? -180 : node.kind === "domain" || node.kind === "topic" ? -120 : -55;
        return node.kind === "domain" ? -430 : node.kind === "topic" ? -360 : node.kind === "page" ? -80 : -55;
      }))
      .force("x", forceX<GraphNode>((node) => {
        const target = layerPositions.get(node.id);
        if (target) return target.x;
        if (node.kind === "domain" || node.kind === "topic") return topicPositions.get(node.id)?.x ?? dimensions.width / 2;
        const anchor = topicAnchorForNode(node, currentGraphData.links, topicPositions);
        return anchor?.x ?? dimensions.width / 2;
      }).strength((node) => {
        if (layoutMode === "hierarchy") return node.kind === "root" ? 0.65 : 0.34;
        return node.kind === "domain" ? 0.24 : node.kind === "topic" ? 0.18 : 0.055;
      }))
      .force("y", forceY<GraphNode>((node) => {
        const target = layerPositions.get(node.id);
        if (target) return target.y;
        if (node.kind === "domain" || node.kind === "topic") return topicPositions.get(node.id)?.y ?? dimensions.height / 2;
        const anchor = topicAnchorForNode(node, currentGraphData.links, topicPositions);
        return anchor?.y ?? dimensions.height / 2;
      }).strength((node) => {
        if (layoutMode === "hierarchy") return node.kind === "root" ? 0.8 : 0.54;
        return node.kind === "domain" ? 0.24 : node.kind === "topic" ? 0.18 : 0.055;
      }))
      .force("collide", forceCollide<GraphNode>().radius((node) => getNodeRadius(node) + (layoutMode === "hierarchy" ? 18 : node.kind === "domain" ? 34 : node.kind === "topic" ? 30 : 12)))
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
  }, [dimensions.height, dimensions.width, draw, getNodeRadius, graphData, layoutMode]);

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

  const setCanvasCursor = useCallback((cursor: string) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.style.cursor = cursor;
  }, []);

  const handleNodeActivate = useCallback((node: GraphNode) => {
    selectedNodeRef.current = node;
    setSelectedNode(node);
    if (node.kind === "page" && node.id !== "__wiki_root__") {
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
      setCanvasCursor("grabbing");
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
    setCanvasCursor("grabbing");
    simulationRef.current?.alphaTarget(0.04).restart();
  }, [findNode, interactive, setCanvasCursor]);

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
    const nextHovered = findNode(event.clientX, event.clientY);
    if (hoveredNodeRef.current?.id !== nextHovered?.id) {
      hoveredNodeRef.current = nextHovered;
      setCanvasCursor(nextHovered ? "pointer" : "grab");
      draw();
    }
  }, [draw, findNode, interactive, pointToGraph, setCanvasCursor]);

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
    const nextHovered = findNode(event.clientX, event.clientY);
    hoveredNodeRef.current = nextHovered;
    setCanvasCursor(nextHovered ? "pointer" : "grab");
    const down = pointerDownRef.current;
    pointerDownRef.current = null;
    const moved = down ? Math.hypot(event.clientX - down.x, event.clientY - down.y) : 999;
    const clicked = findNode(event.clientX, event.clientY);
    if (down?.node && clicked?.id === down.node.id && moved < 5) {
      handleNodeActivate(clicked);
    }
    draw();
  }, [draw, findNode, handleNodeActivate, interactive, setCanvasCursor]);

  const handleMouseLeave = useCallback(() => {
    hoveredNodeRef.current = null;
    draggingRef.current = null;
    panningRef.current = null;
    pointerDownRef.current = null;
    setCanvasCursor("grab");
    draw();
  }, [draw, setCanvasCursor]);

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
    ...(layoutMode === "hierarchy" ? [["all", COLORS.root]] : []),
    ["domain", COLORS.domain],
    ["topic cluster", COLORS.topic],
    ["entity", COLORS.entity],
    ["concept", COLORS.concept],
    ["decision page", TYPE_COLORS.decision],
    ["gap page", TYPE_COLORS.gap],
  ], [layoutMode]);

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

      {interactive ? (
        <div className="absolute left-2 top-2 z-10 flex rounded-md border bg-background/90 p-1 shadow-sm">
          {([
            ["hierarchy", "层级"],
            ["overview", "总览"],
          ] as const).map(([value, label]) => (
            <Button
              key={value}
              variant={layoutMode === value ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setLayoutMode(value)}
            >
              {label}
            </Button>
          ))}
        </div>
      ) : null}

      <canvas
        ref={canvasRef}
        className={cn("block h-full w-full", interactive && "cursor-grab")}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
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
