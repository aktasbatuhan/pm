import { generateOgImage, OG_SIZE, OG_CONTENT_TYPE } from "@/lib/og-image";
import { GLOSSARY } from "@/lib/seo-data";

export const size = OG_SIZE;
export const contentType = OG_CONTENT_TYPE;

export function generateStaticParams() {
  return Object.keys(GLOSSARY).map((term) => ({ term }));
}

export default async function Image({ params }: { params: Promise<{ term: string }> }) {
  const { term } = await params;
  const data = GLOSSARY[term as keyof typeof GLOSSARY];
  if (!data) {
    return generateOgImage({ title: "Dash PM", label: "Glossary" });
  }
  return generateOgImage({
    title: data.headline,
    subtitle: data.definition.slice(0, 120) + "...",
    label: "Glossary",
  });
}
