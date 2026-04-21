import Link from "next/link";
import { DashWordmark } from "@/components/dash-logo";
import { ArrowRight, ArrowLeft, CheckCircle2 } from "lucide-react";

export function SeoPageLayout({
  children,
  backLabel = "Home",
  backHref = "/",
}: {
  children: React.ReactNode;
  backLabel?: string;
  backHref?: string;
}) {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <nav className="sticky top-0 z-50 border-b border-border/40 bg-background/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-center">
            <DashWordmark height={22} className="text-foreground" />
          </Link>
          <Link
            href="/claim"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Request early access
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </nav>

      <main>{children}</main>

      {/* CTA */}
      <section className="border-t border-border/40">
        <div className="mx-auto max-w-4xl px-6 py-20 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Ready to try Dash?</h2>
          <p className="mx-auto mt-4 max-w-lg text-base leading-relaxed text-muted-foreground">
            We're onboarding a handful of teams each week. Get your workspace provisioned and running in hours.
          </p>
          <div className="mt-8">
            <Link
              href="/claim"
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90"
            >
              Request early access <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      <footer className="mx-auto max-w-6xl px-6 py-12 border-t border-border/40">
        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row">
          <DashWordmark height={20} className="text-foreground" />
          <div className="flex items-center gap-6 text-xs text-muted-foreground">
            <Link href="/for/product-managers" className="hover:text-foreground">For PMs</Link>
            <Link href="/for/founders" className="hover:text-foreground">For Founders</Link>
            <Link href="/for/engineering-leads" className="hover:text-foreground">For Eng Leads</Link>
            <Link href="/claim" className="hover:text-foreground">Early Access</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

export function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item} className="flex items-start gap-3 text-sm">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span className="text-foreground/80">{item}</span>
        </li>
      ))}
    </ul>
  );
}
