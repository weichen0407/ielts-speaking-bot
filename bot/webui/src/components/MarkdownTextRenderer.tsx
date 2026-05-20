import { Children, isValidElement, useMemo } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import remarkDirective from "remark-directive";
import { visit } from "unist-util-visit";
import type { Root, Text } from "mdast";

import { CodeBlock } from "@/components/CodeBlock";
import { FileReferenceChip, isLikelyFilePath } from "@/components/FileReferenceChip";
import { cn } from "@/lib/utils";

import "katex/dist/katex.min.css";

/**
 * Remark plugin to transform ==word== text markers into highlight directive nodes.
 * This runs after remark-directive parses the directive syntax.
 */
function remarkHighlight() {
  return (tree: Root) => {
    // First pass: transform ==word== text into textDirective nodes
    visit(tree, "text", (node: Text, index, parent) => {
      if (parent == null || index == null) return;
      const text = node.value;
      if (!text.includes("==")) return;

      const parts = text.split(/(==[^=]+==)/g);
      if (parts.length <= 1) return;

      const newNodes: unknown[] = [];
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        if (!part) continue;
        if (part.startsWith("==") && part.endsWith("==")) {
          const word = part.slice(2, -2);
          // Create a textDirective node
          newNodes.push({
            type: "textDirective",
            name: "highlight",
            children: [{ type: "text", value: word }],
          });
        } else {
          newNodes.push({ type: "text", value: part } as Text);
        }
      }

      if (newNodes.length > 0) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (parent.children as any).splice(index, 1, ...newNodes);
        return index + newNodes.length;
      }
    });

    // Second pass: set hName/hProperties on directive nodes so remark-rehype converts them correctly
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    visit(tree, (node: any, index: number | null | undefined, parent: any) => {
      if (!parent || index == null) return;

      const nodeType = node.type;
      if (
        nodeType === "textDirective" ||
        nodeType === "leafDirective" ||
        nodeType === "containerDirective"
      ) {
        const data = node.data || (node.data = {});
        const name = node.name;

        if (name === "highlight") {
          // Set hName to "mark" so it renders as a <mark> element
          data.hName = "mark";
          data.hProperties = {
            class: "bg-amber-200 dark:bg-amber-700/50 text-amber-900 dark:text-amber-100 px-0.5 py-0.5 rounded-sm font-medium",
          };
        }
      }
    });
  };
}

const remarkPlugins = [remarkGfm, remarkMath, remarkDirective, remarkHighlight];

interface MarkdownTextRendererProps {
  children: string;
  className?: string;
  highlightCode?: boolean;
}

/**
 * Heavy markdown stack (GFM, math, KaTeX, syntax highlighting) kept in a
 * separate chunk so the app shell can paint sooner on refresh.
 */
export default function MarkdownTextRenderer({
  children,
  className,
  highlightCode = true,
}: MarkdownTextRendererProps) {
  const components = useMemo<Components>(
    () => ({
      code({ className: cls, children: kids, ...props }) {
        const match = /language-(\w+)/.exec(cls || "");
        if (match) {
          const code = String(kids).replace(/\n$/, "");
          return (
            <CodeBlock
              language={match[1]}
              code={code}
              className="my-3"
              highlight={highlightCode}
            />
          );
        }
        const raw = String(kids).replace(/\n$/, "");
        if (isLikelyFilePath(raw)) {
          return <FileReferenceChip path={raw} />;
        }
        const widePlainBlock = raw.includes("\n") || raw.length > 120;
        if (widePlainBlock) {
          return (
            <code
              className={cn(
                "block min-w-0 whitespace-pre bg-transparent p-0 font-mono text-[0.8125rem]",
                "leading-snug text-inherit",
                cls,
              )}
              {...props}
            >
              {kids}
            </code>
          );
        }
        return (
          <code
            className={cn(
              "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]",
              cls,
            )}
            {...props}
          >
            {kids}
          </code>
        );
      },
      pre({ children: markdownChildren }) {
        const kids = Children.toArray(markdownChildren);
        const lone = kids.length === 1 ? kids[0] : null;
        if (lone != null && isValidElement(lone) && lone.type === CodeBlock) {
          return <>{markdownChildren}</>;
        }
        return (
          <pre
            className={cn(
              "my-3 overflow-x-auto rounded-lg border border-border/60 bg-muted/35",
              "p-3 font-mono text-[0.8125rem] leading-snug text-foreground/90",
              "whitespace-pre [overflow-wrap:normal]",
            )}
          >
            {markdownChildren}
          </pre>
        );
      },
      a({ href, children: markdownChildren, ...props }) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline underline-offset-2 hover:opacity-80"
            {...props}
          >
            {markdownChildren}
          </a>
        );
      },
    }),
    [highlightCode],
  );

  return (
    <div
      className={cn(
        "markdown-content prose max-w-none dark:prose-invert",
        "prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:tracking-tight",
        "prose-h1:text-lg prose-h2:text-base prose-h3:text-sm prose-h4:text-[13px]",
        "prose-p:my-2",
        "prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5",
        "prose-blockquote:my-3 prose-blockquote:border-l-2 prose-blockquote:font-normal",
        "prose-blockquote:not-italic prose-blockquote:text-foreground/80",
        "prose-a:text-primary prose-a:underline-offset-2 hover:prose-a:opacity-80",
        "prose-hr:my-6",
        "prose-pre:my-0 prose-pre:bg-transparent prose-pre:p-0",
        "prose-code:before:content-none prose-code:after:content-none prose-code:font-normal",
        "prose-table:my-3 prose-th:text-left prose-th:font-medium",
        className,
      )}
      style={{ lineHeight: "var(--cjk-line-height)" }}
    >
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
