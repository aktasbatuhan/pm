import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Link from "next/link";
import { ROLES } from "@/lib/seo-data";
import { SeoPageLayout, BulletList } from "@/components/seo-page-layout";
import { ArrowRight } from "lucide-react";

type Params = { role: string };

export function generateStaticParams(): Params[] {
  return Object.keys(ROLES).map((role) => ({ role }));
}

export async function generateMetadata({ params }: { params: Promise<Params> }): Promise<Metadata> {
  const { role } = await params;
  const data = ROLES[role as keyof typeof ROLES];
  if (!data) return {};
  return {
    title: data.title,
    description: data.description,
    alternates: { canonical: `https://heydash.dev/for/${role}` },
  };
}

export default async function RolePage({ params }: { params: Promise<Params> }) {
  const { role } = await params;
  const data = ROLES[role as keyof typeof ROLES];
  if (!data) notFound();

  return (
    <SeoPageLayout>
      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 pt-20 pb-16">
          <Link href="/" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-8">
            &larr; Back to home
          </Link>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">{data.headline}</h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground">{data.description}</p>
          <div className="mt-8">
            <Link
              href="/claim"
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
            >
              {data.cta} <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      <section className="border-b border-border/40 bg-muted/20">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-2xl font-bold tracking-tight mb-8">The problems you face</h2>
          <div className="grid gap-6 sm:grid-cols-3">
            {data.painPoints.map((p) => (
              <div key={p.title} className="rounded-xl border border-border bg-card p-6">
                <h3 className="text-base font-semibold">{p.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{p.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-b border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-16">
          <h2 className="text-2xl font-bold tracking-tight mb-8">What Dash does for you</h2>
          <BulletList items={data.features} />
        </div>
      </section>
    </SeoPageLayout>
  );
}
