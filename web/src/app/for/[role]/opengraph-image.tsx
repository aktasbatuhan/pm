import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";
import { ROLES } from "@/lib/seo-data";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export function generateStaticParams() {
  return Object.keys(ROLES).map((role) => ({ role }));
}

export default async function Image({ params }: { params: Promise<{ role: string }> }) {
  const { role } = await params;
  const data = ROLES[role as keyof typeof ROLES];
  if (!data) {
    return generateOgImage({ title: "Dash PM", label: "For Teams" });
  }
  return generateOgImage({
    title: data.headline,
    subtitle: data.description.slice(0, 120) + "...",
    label: "For " + data.slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
  });
}
