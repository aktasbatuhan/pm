import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";
import { USE_CASES } from "@/lib/seo-data";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export function generateStaticParams() {
  return Object.keys(USE_CASES).map((c) => ({ case: c }));
}

export default async function Image({ params }: { params: Promise<{ case: string }> }) {
  const { case: slug } = await params;
  const data = USE_CASES[slug as keyof typeof USE_CASES];
  if (!data) {
    return generateOgImage({ title: "Dash PM", label: "Use Case" });
  }
  return generateOgImage({
    title: data.headline,
    subtitle: data.description.slice(0, 120) + "...",
    label: "Use Case",
  });
}
