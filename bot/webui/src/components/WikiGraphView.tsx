import { useCallback, useEffect, useRef, useState } from "react";
import ForceGraph2D, { ForceGraphMethods, NodeObject, LinkObject } from "react-force-graph-2d";
import { ZoomIn, ZoomOut, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  fetchWikiGraph,
  type WikiGraphNode,
} from "@/lib/api";
import { useClient } from "@/providers/ClientProvider";

interface GraphData {
  nodes: WikiGraphNode[];
  links: { source: string; target: string; kind: string }[];
}

export interface WikiGraphViewProps {
  /** Override filters passed in from WikiMemoryPanel */
  filterMode?: string;
  filterTopic?: string;
  filterType?: string;
  filterTags?: string;
  /** Node IDs to highlight as search results */
  highlightedNodes?: Set<string>;
  /** Callback when a page node is clicked */
  onPageClick?: (slug: string) => void;
  /** Callback when a filter node (tag/topic/mode) is clicked */
  onFilterClick?: (kind: string, value: string) => void;
  /** Whether the graph can be interacted with */
  interactive?: boolean;
  className?: string;
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
  const graphRef = useRef<ForceGraphMethods>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredNode, setHoveredNode] = useState<WikiGraphNode | null>(null);
  const [dimensions, setDimensions] = useState({ width: 600, height: 400 });

  // Measure container
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Fetch graph data
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
      setGraphData({
        nodes: data.nodes.map((n) => ({ ...n })),
        links: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          kind: e.kind,
        })),
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setIsLoading(false);
    }
  }, [token, filterMode, filterTopic, filterType, filterTags]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Recenter
  const handleRecenter = useCallback(() => {
    graphRef.current?.zoomToFit(400, 50);
  }, []);

  const handleZoomIn = useCallback(() => {
    graphRef.current?.zoom(graphRef.current.zoom() * 1.4, 300);
  }, []);

  const handleZoomOut = useCallback(() => {
    graphRef.current?.zoom(graphRef.current.zoom() / 1.4, 300);
  }, []);

  // Node click
  const handleNodeClick = useCallback(
    (node: NodeObject) => {
      const wNode = node as NodeObject & WikiGraphNode;
      if (wNode.kind === "page") {
        onPageClick?.(wNode.id);
      } else {
        // tag, topic, or mode - extract value
        let value = wNode.id;
        if (wNode.kind === "tag") value = wNode.id.replace("tag:", "");
        else if (wNode.kind === "topic") value = wNode.id.replace("topic:", "");
        else if (wNode.kind === "mode") value = wNode.id.replace("mode:", "");
        onFilterClick?.(wNode.kind, value);
      }
    },
    [onPageClick, onFilterClick],
  );

  // Node hover
  const handleNodeHover = useCallback(
    (node: NodeObject | null) => {
      if (node) {
        const wNode = node as NodeObject & WikiGraphNode;
        setHoveredNode(wNode);
      } else {
        setHoveredNode(null);
      }
    },
    [],
  );

  const getNodeLabel = useCallback((node: NodeObject): string => {
    const wNode = node as NodeObject & WikiGraphNode;
    const details = [
      wNode.label,
      `kind: ${wNode.kind}`,
      wNode.type ? `type: ${wNode.type}` : null,
      wNode.mode ? `mode: ${wNode.mode}` : null,
      wNode.tags?.length ? `tags: ${wNode.tags.join(", ")}` : null,
      wNode.topics?.length ? `topics: ${wNode.topics.join(", ")}` : null,
      wNode.updated_at ? `updated: ${new Date(wNode.updated_at).toLocaleDateString()}` : null,
      wNode.summary ? `summary: ${wNode.summary}` : null,
    ].filter(Boolean);
    return details.join("\n");
  }, []);

  // Custom node color
  const getNodeColor = useCallback(
    (node: NodeObject): string => {
      const wNode = node as NodeObject & WikiGraphNode;
      if (highlightedNodes?.has(wNode.id)) return "#f59e0b"; // amber for highlighted

      switch (wNode.kind) {
        case "page":
          return "#6366f1"; // indigo
        case "tag":
          return "#10b981"; // emerald
        case "topic":
          return "#3b82f6"; // blue
        case "mode":
          return "#8b5cf6"; // violet
        default:
          return "#6b7280"; // gray
      }
    },
    [highlightedNodes],
  );

  // Custom node size
  const getNodeSize = useCallback(
    (node: NodeObject): number => {
      const wNode = node as NodeObject & WikiGraphNode;
      const base = wNode.size ?? 1;
      const kindMultiplier = wNode.kind === "page" ? 3 : 1.5;
      return (base * kindMultiplier + 2) * 1.5;
    },
    [],
  );

  // Draw node canvas
  const drawNode = useCallback(
    (
      ctx: CanvasRenderingContext2D,
      node: NodeObject,
      x: number,
      y: number,
      size: number,
      color: string,
      isHovered: boolean,
      isSelected: boolean,
    ) => {
      const wNode = node as NodeObject & WikiGraphNode;

      // Ring for recently updated (within 24h) or highlighted
      const isHighlighted = highlightedNodes?.has(wNode.id);
      const ringColor = isHighlighted ? "#f59e0b" : isSelected ? "#6366f1" : null;

      if (ringColor) {
        ctx.beginPath();
        ctx.arc(x, y, size + 4, 0, 2 * Math.PI);
        ctx.strokeStyle = ringColor;
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Main circle
      ctx.beginPath();
      ctx.arc(x, y, size, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      if (isHovered) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label for non-page nodes
      if (wNode.kind !== "page") {
        ctx.fillStyle = "#ffffff";
        ctx.font = `${Math.max(8, size * 0.7)}px sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const label = wNode.label.length > 10 ? wNode.label.slice(0, 10) + "…" : wNode.label;
        ctx.fillText(label, x, y);
      }
    },
    [highlightedNodes],
  );

  // Paint nodes
  const paintNode = useCallback(
    (
      node: NodeObject,
      ctx: CanvasRenderingContext2D,
      _globalScale: number,
    ) => {
      const wNode = node as NodeObject & WikiGraphNode;
      const size = getNodeSize(node);
      const color = getNodeColor(node);
      const isHovered = hoveredNode?.id === wNode.id;
      const x = (node.x ?? 0);
      const y = (node.y ?? 0);
      drawNode(ctx, node, x, y, size, color, isHovered, false);
    },
    [getNodeSize, getNodeColor, hoveredNode, drawNode],
  );

  // Node canvas element
  const nodeCanvasObject = useCallback(
    (
      node: NodeObject,
      ctx: CanvasRenderingContext2D,
      _globalScale: number,
    ) => {
      paintNode(node, ctx, _globalScale);
    },
    [paintNode],
  );

  // Link color
  const getLinkColor = useCallback(
    (link: LinkObject): string => {
      const l = link as LinkObject & { kind: string };
      switch (l.kind) {
        case "link": return "rgba(107,114,128,0.4)";
        case "has_tag": return "rgba(16,185,129,0.3)";
        case "has_topic": return "rgba(59,130,246,0.3)";
        case "has_mode": return "rgba(139,92,246,0.3)";
        default: return "rgba(107,114,128,0.2)";
      }
    },
    [],
  );

  if (error) {
    return (
      <div className={cn("flex items-center justify-center text-xs text-destructive", className)}>
        {error}
      </div>
    );
  }

  return (
    <div ref={containerRef} className={cn("relative overflow-hidden", className)}>
      {/* Controls */}
      {interactive && (
        <div className="absolute right-2 top-2 z-10 flex flex-col gap-1">
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7 bg-background/80 backdrop-blur"
            onClick={handleZoomIn}
            title="Zoom in"
          >
            <ZoomIn className="h-3 w-3" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7 bg-background/80 backdrop-blur"
            onClick={handleZoomOut}
            title="Zoom out"
          >
            <ZoomOut className="h-3 w-3" />
          </Button>
          <Button
            variant="outline"
            size="icon"
            className="h-7 w-7 bg-background/80 backdrop-blur"
            onClick={handleRecenter}
            title="Fit to view"
          >
            <RotateCcw className="h-3 w-3" />
          </Button>
        </div>
      )}

      {/* Loading */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/50">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-2 left-2 z-10 flex flex-wrap gap-2 rounded-md border bg-background/80 p-1.5 text-[9px] backdrop-blur">
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-indigo-500" />
          <span className="text-muted-foreground">page</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-muted-foreground">tag</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-blue-500" />
          <span className="text-muted-foreground">topic</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-violet-500" />
          <span className="text-muted-foreground">mode</span>
        </div>
        {highlightedNodes && highlightedNodes.size > 0 && (
          <div className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            <span className="text-muted-foreground">match</span>
          </div>
        )}
      </div>

      <ForceGraph2D
        ref={graphRef}
        graphData={graphData}
        width={dimensions.width}
        height={dimensions.height}
        nodeLabel={getNodeLabel}
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={(node, color, ctx) => {
          const size = getNodeSize(node);
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x ?? 0, node.y ?? 0, size + 4, 0, 2 * Math.PI);
          ctx.fill();
        }}
        linkColor={getLinkColor}
        linkWidth={1}
        onNodeClick={interactive ? handleNodeClick : undefined}
        onNodeHover={interactive ? handleNodeHover : undefined}
        onBackgroundClick={() => setHoveredNode(null)}
        enableNodeDrag={interactive}
        enableZoomInteraction={interactive}
        enablePanInteraction={interactive}
        cooldownTicks={100}
        d3AlphaDecay={0.02}
        d3VelocityDecay={0.3}
      />
    </div>
  );
}
