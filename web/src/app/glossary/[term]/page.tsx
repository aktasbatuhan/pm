import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Link from "next/link";
import { GLOSSARY } from "@/lib/seo-data";
import { SeoPageLayout } from "@/components/seo-page-layout";

type Params = { term: string };

export function generateStaticParams(): Params[] {
  return Object.keys(GLOSSARY).map((term) => ({ term }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { term } = await params;
  const data = GLOSSARY[term as keyof typeof GLOSSARY];
  if (!data) return {};
  return {
    title: data.title,
    description: `${data.headline}. ${data.definition.slice(0, 120)}...`,
    alternates: { canonical: `https://heydash.dev/glossary/${term}` },
  };
}

export default async function GlossaryPage({ params }: { params: Promise<Params> }) {
  const { term } = await params;
  const data = GLOSSARY[term as keyof typeof GLOSSARY];
  if (!data) notFound();

  return (
    <SeoPageLayout>
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 pt-20 pb-16">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-8">
            &larr; Back to home
          </Link>
          <p className="text-sm font-semibold text-primary mb-3">Glossary</p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">{data.headline}</h1>
        </div>
      </section>

      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-xl font-bold tracking-tight mb-4">Definition</h2>
          <p className="text-base leading-relaxed text-muted-foreground">{data.definition}</p>
        </div>
      </section>

      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-xl font-bold tracking-tight mb-4">How Dash implements this</h2>
          <p className="text-base leading-relaxed text-muted-foreground">{data.inDash}</p>
        </div>
      </section>

      {/* Related glossary links */}
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-lg font-bold tracking-tight mb-4">Related concepts</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(GLOSSARY)
              .filter(([k]) => k !== term)
              .map(([k, v]) => (
                <Link
                  key={k}
                  href={`/glossary/${k}`}
                  className="rounded-full border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:border-primary/30 transition-colors"
                >
                  {v.title.replace("What is ", "").replace("What are ", "").replace("?", "")}
                </Link>
              ))}
          </div>
        </div>
      </section>
    </SeoPageLayout>
  );
}
