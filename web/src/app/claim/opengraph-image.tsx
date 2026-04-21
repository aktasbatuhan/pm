import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export default function Image() {
  return generateOgImage({
    title: "Request Early Access",
    subtitle: "Get your workspace provisioned. Daily briefs running in hours, not weeks.",
    label: "Early Access",
  });
}
