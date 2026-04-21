import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";
import { COMPARISONS } from "@/lib/seo-data";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export function generateStaticParams() {
  return Object.keys(COMPARISONS).map((slug) => ({ slug }));
}

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const data = COMPARISONS[slug as keyof typeof COMPARISONS];
  if (!data) {
    return generateOgImage({ title: "Dash PM", label: "Comparison" });
  }
  return generateOgImage({
    title: data.headline,
    subtitle: data.description.slice(0, 120) + "...",
    label: "Comparison",
  });
}
