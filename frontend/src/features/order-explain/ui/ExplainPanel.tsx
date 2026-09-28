import type { OrderExplain } from "@/shared/types/types";

export const ExplainPanel = ({ selected }: { selected: OrderExplain }) => (
  <section className="explain">
    <strong>Причина: {selected.rejection_reason ?? "назначено"}</strong>
    <div className="candidate-grid">
      {selected.candidates.map((candidate) => (
        <article key={candidate.executor_id}>
          <b>Исполнитель #{candidate.executor_id}</b>
          <span>
            {candidate.passed
              ? `score ${candidate.score?.toFixed(3) ?? "—"}`
              : candidate.reason}
          </span>
        </article>
      ))}
    </div>
    {selected.history.map((row, index) => (
      <p key={index}>
        #{row.executor_id ?? "—"} · {row.reason} · {row.detail}
      </p>
    ))}
  </section>
);
