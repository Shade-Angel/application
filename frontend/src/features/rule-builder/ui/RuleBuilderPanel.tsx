import { useState } from "react";
import { QueryBuilder, type RuleGroupType } from "react-querybuilder";
import "react-querybuilder/dist/query-builder.css";
import { PanelTitle } from "@/shared/ui/PanelTitle";
import { useAppData } from "@/shared/context/AppDataContext";
import { api } from "@/shared/api/base";
import { operatorSets, operatorLabels } from "@/shared/lib/constants";
import { queryToDsl } from "@/shared/lib/utils";

export const RuleBuilderPanel = () => {
  const { parameters, dictionaries, refresh, setNotice } = useAppData();
  const [ruleName, setRuleName] = useState("Правило отбора");
  const [condition, setCondition] = useState(
    '{"field":"executor.vip","op":"eq","value":true}',
  );
  const [query, setQuery] = useState<RuleGroupType>({
    combinator: "and",
    rules: [{ field: "executor.vip", operator: "=", value: true }],
  });
  const [dryRun, setDryRun] = useState<
    Array<{ executor_id: number; passed: boolean }>
  >([]);

  const validate = async () => {
    try {
      const result = await api<{ valid: boolean; error?: string }>(
        "/api/rules/validate",
        {
          method: "POST",
          body: JSON.stringify({ condition: JSON.parse(condition) }),
        },
      );
      setNotice(
        result.valid ? "Условие корректно" : (result.error ?? "Ошибка"),
      );
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Неверный JSON");
    }
  };

  const runDryRun = async () => {
    try {
      setDryRun(
        await api("/api/rules/dry-run", {
          method: "POST",
          body: JSON.stringify({
            condition: JSON.parse(condition),
            order: {
              sum: 25000,
              order_type: "ORDER_1",
              subject: "subject-a",
              vip: true,
            },
          }),
        }),
      );
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Ошибка dry-run");
    }
  };

  const addRule = async () => {
    try {
      await api("/api/rules", {
        method: "POST",
        body: JSON.stringify({
          name: ruleName,
          kind: "filter",
          condition: JSON.parse(condition),
          priority: 100,
          enabled: true,
          null_policy: "pass",
        }),
      });
      await refresh();
      setNotice("Правило сохранено и применяется при новых назначениях");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ошибка правила");
    }
  };

  return (
    <section className="panel">
      <PanelTitle
        title="Конструктор условия"
        subtitle="JSON DSL · AND / OR / NOT"
      />
      <label>
        Название
        <input value={ruleName} onChange={(e) => setRuleName(e.target.value)} />
      </label>
      <div className="querybuilder">
        <QueryBuilder
          query={query}
          fields={parameters.map((p) => ({
            name: `${p.entity}.${p.key}`,
            label: `${p.label} (${p.data_type})`,
            operators: (operatorSets[p.data_type] ?? operatorSets.string).map(
              (name) => ({ name, label: operatorLabels[name] ?? name }),
            ),
            valueSources: ["value", "field"],
            ...(p.dictionary_id
              ? {
                  values: (
                    dictionaries.find((d) => d.id === p.dictionary_id)?.items ??
                    []
                  ).map((item) => ({ name: item.value, label: item.label })),
                }
              : {}),
          }))}
          onQueryChange={(next) => {
            const typed = next as RuleGroupType;
            setQuery(typed);
            setCondition(JSON.stringify(queryToDsl(typed), null, 2));
          }}
        />
      </div>
      <label>
        DSL условия<pre className="dsl-preview">{condition}</pre>
      </label>
      <div className="muted">
        Поля из каталога:{" "}
        {parameters.map((p) => `${p.entity}.${p.key}`).join(" · ") ||
          "добавьте параметры на странице «Параметры»"}
      </div>
      <div className="button-row">
        <button onClick={() => void validate()}>Проверить</button>
        <button onClick={() => void runDryRun()}>Dry-run</button>
        <button className="primary" onClick={() => void addRule()}>
          Сохранить правило
        </button>
      </div>
      {dryRun.length > 0 && (
        <p className="muted">
          Dry-run: {dryRun.filter((row) => row.passed).length} из{" "}
          {dryRun.length} исполнителей прошли условие.
        </p>
      )}
    </section>
  );
};
