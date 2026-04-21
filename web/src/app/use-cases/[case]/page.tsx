import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Link from "next/link";
import { USE_CASES } from "@/lib/seo-data";
import { SeoPageLayout, BulletList } from "@/components/seo-page-layout";

type Params = { case: string };

export function generateStaticParams(): Params[] {
  return Object.keys(USE_CASES).map((c) => ({ case: c }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { case: slug } = await params;
  const data = USE_CASES[slug as keyof typeof USE_CASES];
  if (!data) return {};
  return {
    title: data.title,
    description: data.description,
    alternates: { canonical: `https://heydash.dev/use-cases/${slug}` },
  };
}

export default async function UseCasePage({ params }: { params: Promise<Params> }) {
  const { case: slug } = await params;
  const data = USE_CASES[slug as keyof typeof USE_CASES];
  if (!data) notFound();

  return (
    <SeoPageLayout>
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 pt-20 pb-16">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-8">
            &larr; Back to home
          </Link>
          <p className="text-sm font-semibold text-primary mb-3">Use case</p>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">{data.headline}</h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">{data.description}</p>
        </div>
      </section>

      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-2xl font-bold tracking-tight mb-8">How it works</h2>
          <BulletList items={data.howItWorks} />
        </div>
      </section>

      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <div className="rounded-xl border border-primary/20 bg-primary/5 px-8 py-8">
            <p className="text-sm font-semibold text-primary mb-2">The impact</p>
            <p className="text-lg leading-relaxed">{data.benefit}</p>
          </div>
        </div>
      </section>
    </SeoPageLayout>
  );
}
