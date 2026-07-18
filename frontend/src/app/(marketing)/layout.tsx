import { MarketingLayout } from "@/layouts/marketing-layout";

export default function MarketingGroupLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <MarketingLayout>{children}</MarketingLayout>;
}
