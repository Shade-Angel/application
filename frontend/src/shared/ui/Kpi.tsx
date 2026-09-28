import type { ReactNode } from "react";

interface KpiProps {
  title: string;
  value: ReactNode;
  note: string;
}
export const Kpi = ({ title, value, note }: KpiProps) => (
  <article>
    <small>{title}</small>
    <strong>{value}</strong>
    <span>{note}</span>
  </article>
);
