import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export default function Image() {
  return generateOgImage({
    title: "Ship fast. Ship the right things.",
    subtitle: "Daily briefs, signal collection, report automation, team pulse — from one autonomous PM agent.",
  });
}
