"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { Maximize2, Minimize2 } from "lucide-react";

/**
 * Renders a React component (JSX string) in a sandboxed iframe.
 * Pre-loads React, Recharts, and basic styling.
 * The agent generates these as ```react-chart code blocks.
 */

const SANDBOX_HTML = (code: string, theme: "light" | "dark" = "light") => `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/prop-types@15/prop-types.min.js"></script>
  <script>window.PropTypes = window.PropTypes || window.propTypes;</script>
  <script crossorigin src="https://unpkg.com/recharts@2/umd/Recharts.js"></script>
  <script crossorigin src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: transparent;
      color: ${theme === "dark" ? "#f0f0f5" : "#111827"};
      padding: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100%;
    }
    #root { width: 100%; }
    .recharts-cartesian-axis-tick-value { font-size: 12px; fill: ${theme === "dark" ? "#9ca3af" : "#6b7280"}; }
    .recharts-legend-item-text { font-size: 12px !important; }
  </style>
</head>
<body>
  <div id="root"></div>
  <script>
    window.onerror = function(msg, url, line) {
      document.getElementById('root').innerHTML = '<pre style="color:#ef4444;font-size:11px;white-space:pre-wrap">Error: ' + msg + '\\nLine: ' + line + '</pre>';
    };
  </script>
  <script type="text/babel">
    const {
      BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
      AreaChart, Area, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
      XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
      ComposedChart, Scatter, ScatterChart, Treemap, Funnel, FunnelChart,
    } = Recharts;

    const COLORS = ['#4f46e5', '#06b6d4', '#8b5cf6', '#f59e0b', '#ef4444', '#10b981', '#ec4899', '#6366f1'];

    try {
      ${code}

      const App = typeof Component !== 'undefined' ? Component : (() => React.createElement('div', null, 'No Component exported'));
      ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(App));

      // Auto-resize
      const observer = new ResizeObserver(() => {
        window.parent.postMessage({ type: 'artifact-resize', height: document.body.scrollHeight }, '*');
      });
      observer.observe(document.body);
      setTimeout(() => {
        window.parent.postMessage({ type: 'artifact-resize', height: document.body.scrollHeight }, '*');
      }, 500);
    } catch (e) {
      document.getElementById('root').innerHTML =
        '<pre style="color:#ef4444;font-size:12px;white-space:pre-wrap">' + e.message + '</pre>';
    }
  </script>
</body>
</html>`;

interface Props {
  code: string;
  title?: string;
  className?: string;
}

export function ArtifactRenderer({ code, title, className }: Props) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(320);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    function handleMessage(e: MessageEvent) {
      if (e.data?.type === "artifact-resize" && typeof e.data.height === "number") {
        setHeight(Math.max(200, Math.min(e.data.height + 32, 600)));
      }
    }
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  const srcdoc = useMemo(() => SANDBOX_HTML(code), [code]);

  return (
    <div
      className={cn(
        "my-4 overflow-hidden rounded-xl border border-border bg-card",
        expanded && "fixed inset-4 z-50 shadow-2xl",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-2">
        <span className="text-xs font-medium text-muted-foreground">
          {title || "Chart"}
        </span>
        <button
          onClick={() => setExpanded(!expanded)}
          className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          {expanded ? (
            <Minimize2 className="h-3.5 w-3.5" />
          ) : (
            <Maximize2 className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      {/* Iframe */}
      <iframe
        ref={iframeRef}
        srcDoc={srcdoc}
        sandbox="allow-scripts allow-same-origin"
        style={{ width: "100%", height: expanded ? "calc(100% - 40px)" : height, border: "none" }}
        title={title || "Chart artifact"}
      />
    </div>
  );
}
