import { ImageResponse } from "next/og";

export const OG_SIZE = { width: 1200, height: 630 };
export const OG_CONTENT_TYPE = "image/png";

/**
 * Shared OG image generator for all pages.
 * Renders a branded card with title, subtitle, and category label.
 */
export function generateOgImage({
  title,
  subtitle,
  label,
}: {
  title: string;
  subtitle?: string;
  label?: string;
}) {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "60px 70px",
          background: "linear-gradient(135deg, #09090b 0%, #18181b 50%, #1e1b4b 100%)",
          fontFamily: "system-ui, -apple-system, sans-serif",
        }}
      >
        {/* Top: logo + label */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
          {/* Logo mark */}
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "12px",
              background: "#6366f1",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "24px",
              fontWeight: 800,
              color: "white",
            }}
          >
            D
          </div>
          <span
            style={{
              fontSize: "22px",
              fontWeight: 700,
              color: "#e4e4e7",
              letterSpacing: "-0.3px",
            }}
          >
            Dash PM
          </span>
          {label && (
            <span
              style={{
                marginLeft: "16px",
                fontSize: "14px",
                fontWeight: 600,
                color: "#a5b4fc",
                background: "rgba(99, 102, 241, 0.15)",
                padding: "4px 14px",
                borderRadius: "20px",
              }}
            >
              {label}
            </span>
          )}
        </div>

        {/* Center: title + subtitle */}
        <div style={{ display: "flex", flexDirection: "column", gap: "16px", flex: 1, justifyContent: "center" }}>
          <h1
            style={{
              fontSize: title.length > 50 ? "44px" : "56px",
              fontWeight: 800,
              color: "#fafafa",
              lineHeight: 1.1,
              letterSpacing: "-1.5px",
              margin: 0,
              maxWidth: "900px",
            }}
          >
            {title}
          </h1>
          {subtitle && (
            <p
              style={{
                fontSize: "22px",
                color: "#a1a1aa",
                lineHeight: 1.4,
                margin: 0,
                maxWidth: "800px",
              }}
            >
              {subtitle}
            </p>
          )}
        </div>

        {/* Bottom: tagline */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span style={{ fontSize: "16px", color: "#71717a" }}>
            heydash.dev
          </span>
          <span style={{ fontSize: "16px", color: "#71717a" }}>
            Autonomous PM Agent
          </span>
        </div>
      </div>
    ),
    OG_SIZE,
  );
}
