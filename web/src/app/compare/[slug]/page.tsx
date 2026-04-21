import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Link from "next/link";
import { COMPARISONS } from "@/lib/seo-data";
import { SeoPageLayout, BulletList } from "@/components/seo-page-layout";

type Params = { slug: string };

export function generateStaticParams(): Params[] {
  return Object.keys(COMPARISONS).map((slug) => ({ slug }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { slug } = await params;
  const data = COMPARISONS[slug as keyof typeof COMPARISONS];
  if (!data) return {};
  return {
    title: data.title,
    description: data.description,
    alternates: { canonical: `https://heydash.dev/compare/${slug}` },
  };
}

export default async function ComparePage({ params }: { params: Promise<Params> }) {
  const { slug } = await params;
  const data = COMPARISONS[slug as keyof typeof COMPARISONS];
  if (!data) notFound();

  return (
    <SeoPageLayout>
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 pt-20 pb-16">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-8">
            &larr; Back to home
          </Link>
          <p className="text-sm font-semibold text-primary mb-3">Comparison</p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">{data.headline}</h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">{data.description}</p>
        </div>
      </section>

      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-2xl font-bold tracking-tight mb-8">Where Dash excels</h2>
          <BulletList items={data.dashAdvantages} />
        </div>
      </section>

      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <div className="rounded-xl border border-border bg-card px-8 py-8">
            <p className="text-sm font-semibold text-muted-foreground mb-2">Fair play</p>
            <p className="text-base leading-relaxed">{data.theirStrength}</p>
          </div>
        </div>
      </section>
    </SeoPageLayout>
  );
}
